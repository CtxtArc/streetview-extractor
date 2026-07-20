from unittest.mock import patch

import pytest
from PIL import Image

from street_extractor import (
    GeocodingError,
    StreetExtractor,
    StreetViewNotFoundError,
)


def make_extractor(**kwargs):
    kwargs.setdefault("zoom", 1)  # 2x1 grid: fast for tests
    kwargs.setdefault("max_retries", 1)
    kwargs.setdefault("retry_backoff", 0)
    return StreetExtractor(**kwargs)


def test_invalid_zoom_raises():
    with pytest.raises(ValueError):
        StreetExtractor(zoom=99)


def test_get_image_stitches_all_tiles():
    ex = make_extractor()

    def fake_get_pano_id(self, lat, lon, radius_m=50):
        return "FAKE_PANO_ID_1234567890AB"

    async def fake_fetch_tile(self, session, sem, pano_id, x, y):
        return x, y, Image.new("RGB", (512, 512), color=(x * 50, y * 50, 100))

    with patch.object(StreetExtractor, "get_pano_id", fake_get_pano_id), patch.object(
        StreetExtractor, "_fetch_tile", fake_fetch_tile
    ):
        progress_calls = []
        img, info = ex.get_image(
            40.0, -74.0, on_progress=lambda d, t: progress_calls.append((d, t))
        )

    assert img.size == (ex.cols * 512, ex.rows * 512)
    assert info.pano_id == "FAKE_PANO_ID_1234567890AB"
    assert info.lat == 40.0 and info.lon == -74.0
    assert len(progress_calls) == ex.cols * ex.rows
    assert progress_calls[-1] == (ex.cols * ex.rows, ex.cols * ex.rows)


def test_get_image_raises_when_pano_not_found():
    ex = make_extractor()
    with patch.object(StreetExtractor, "get_pano_id", lambda self, lat, lon, radius_m=50: None):
        with pytest.raises(StreetViewNotFoundError):
            ex.get_image(0.0, 0.0)


def test_get_image_raises_when_every_tile_fails():
    ex = make_extractor()

    async def fake_fetch_tile(self, session, sem, pano_id, x, y):
        return x, y, None

    with patch.object(
        StreetExtractor, "get_pano_id", lambda self, lat, lon, radius_m=50: "PANO123"
    ), patch.object(StreetExtractor, "_fetch_tile", fake_fetch_tile):
        with pytest.raises(StreetViewNotFoundError):
            ex.get_image(0.0, 0.0)


def test_partial_tile_failure_still_produces_image():
    """A few missing tiles (edge of pano) should not fail the whole run."""
    ex = make_extractor()

    async def fake_fetch_tile(self, session, sem, pano_id, x, y):
        if x == 0 and y == 0:
            return x, y, None  # simulate one missing tile
        return x, y, Image.new("RGB", (512, 512))

    with patch.object(
        StreetExtractor, "get_pano_id", lambda self, lat, lon, radius_m=50: "PANO123"
    ), patch.object(StreetExtractor, "_fetch_tile", fake_fetch_tile):
        img, info = ex.get_image(0.0, 0.0)

    assert img.size == (ex.cols * 512, ex.rows * 512)


def test_extract_and_save_requires_location(tmp_path):
    ex = make_extractor()
    with pytest.raises(ValueError):
        ex.extract_and_save(str(tmp_path / "out.jpg"))


def test_extract_and_save_uses_geocoded_address(tmp_path):
    ex = make_extractor()

    with patch.object(StreetExtractor, "geocode", lambda self, address: (1.23, 4.56)), \
         patch.object(StreetExtractor, "get_pano_id", lambda self, lat, lon, radius_m=50: "PANO123"), \
         patch.object(
             StreetExtractor,
             "_fetch_tile",
             lambda self, session, sem, pano_id, x, y: _fake_tile(x, y),
         ):
        out = tmp_path / "out.jpg"
        info = ex.extract_and_save(str(out), address="Somewhere")

    assert out.exists()
    assert info.lat == 1.23 and info.lon == 4.56


async def _fake_tile(x, y):
    return x, y, Image.new("RGB", (512, 512))


def test_geocode_raises_on_no_results():
    ex = make_extractor()

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return []

    with patch("street_extractor.core.requests.get", return_value=FakeResp()):
        with pytest.raises(GeocodingError):
            ex.geocode("nonexistent place asdkjaskdj")
