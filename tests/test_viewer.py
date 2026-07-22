"""
Tests for street_extractor.viewer.generate_html_viewer.

These are all pure filesystem tests -- no network calls are made by
this module, so nothing needs mocking (unlike test_core.py, which mocks
requests/aiohttp).
"""
import base64
import os

import pytest
from PIL import Image

from street_extractor.viewer import generate_html_viewer


@pytest.fixture
def sample_jpg(tmp_path):
    """A tiny valid JPG on disk to exercise the viewer generator against."""
    path = tmp_path / "pano.jpg"
    Image.new("RGB", (8, 4), color=(120, 180, 220)).save(path, quality=90)
    return str(path)


def test_raises_if_image_missing(tmp_path):
    missing = str(tmp_path / "does_not_exist.jpg")
    out = str(tmp_path / "out.html")
    with pytest.raises(FileNotFoundError):
        generate_html_viewer(missing, out)


def test_creates_html_file(sample_jpg, tmp_path):
    out = str(tmp_path / "out.html")
    result = generate_html_viewer(sample_jpg, out)
    assert result == out
    assert os.path.isfile(out)


def test_embedded_image_is_base64_data_uri(sample_jpg, tmp_path):
    out = str(tmp_path / "out.html")
    generate_html_viewer(sample_jpg, out, embed_image=True)
    html = open(out, encoding="utf-8").read()

    assert 'var IMAGE_SRC = "data:image/jpeg;base64,' in html

    # The embedded bytes should round-trip back to the original file bytes.
    with open(sample_jpg, "rb") as f:
        expected_b64 = base64.b64encode(f.read()).decode("ascii")
    assert expected_b64 in html

    # Note: "pano.jpg" (bare filename) legitimately appears elsewhere on the
    # page regardless of embed_image, since it's also the default caption
    # text (<div id="caption">pano.jpg</div>). So we can't assert the
    # substring is absent from the whole page -- only that IMAGE_SRC itself
    # isn't the bare relative-path form.
    assert 'var IMAGE_SRC = "pano.jpg"' not in html


def test_non_embedded_image_uses_relative_path(sample_jpg, tmp_path):
    out = str(tmp_path / "out.html")
    generate_html_viewer(sample_jpg, out, embed_image=False)
    html = open(out, encoding="utf-8").read()

    assert 'var IMAGE_SRC = "pano.jpg";' in html
    # Must NOT have inlined the image data when embed_image=False.
    assert "base64," not in html


def test_non_embedded_relative_path_from_nested_output_dir(sample_jpg, tmp_path):
    """If the html file lives in a subdirectory, the relative path to the
    image (which is one level up) should be computed correctly."""
    nested_dir = tmp_path / "viewers"
    nested_dir.mkdir()
    out = str(nested_dir / "out.html")

    generate_html_viewer(sample_jpg, out, embed_image=False)
    html = open(out, encoding="utf-8").read()

    expected_rel = os.path.relpath(sample_jpg, start=str(nested_dir))
    assert f'var IMAGE_SRC = "{expected_rel}";' in html


def test_default_title_and_caption_from_filename(sample_jpg, tmp_path):
    out = str(tmp_path / "out.html")
    generate_html_viewer(sample_jpg, out)
    html = open(out, encoding="utf-8").read()

    assert "<title>pano</title>" in html          # stem, no extension
    assert '<div id="caption">pano.jpg</div>' in html  # full filename


def test_custom_title_and_caption(sample_jpg, tmp_path):
    out = str(tmp_path / "out.html")
    generate_html_viewer(
        sample_jpg, out, title="My Panorama", caption="48.87407, 2.293991"
    )
    html = open(out, encoding="utf-8").read()

    assert "<title>My Panorama</title>" in html
    assert '<div id="caption">48.87407, 2.293991</div>' in html


def test_empty_string_caption_is_respected_not_defaulted(sample_jpg, tmp_path):
    """caption='' should render as an empty caption, not fall back to the
    filename -- confirms the function distinguishes None from ''."""
    out = str(tmp_path / "out.html")
    generate_html_viewer(sample_jpg, out, caption="")
    html = open(out, encoding="utf-8").read()

    assert '<div id="caption"></div>' in html


def test_no_external_network_dependencies(sample_jpg, tmp_path):
    """The whole point of the WebGL rewrite: no CDN, no external requests
    of any kind -- the page must work fully offline."""
    out = str(tmp_path / "out.html")
    generate_html_viewer(sample_jpg, out)
    html = open(out, encoding="utf-8").read()

    assert "cdn.pannellum" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_viewer_config_includes_expected_controls(sample_jpg, tmp_path):
    out = str(tmp_path / "out.html")
    generate_html_viewer(sample_jpg, out)
    html = open(out, encoding="utf-8").read()

    # WebGL context + sphere/shader setup is present.
    assert "getContext('webgl')" in html
    assert "createShader" in html

    # UI controls matching the old Pannellum feature set are present.
    assert 'id="pano-zoom-in"' in html
    assert 'id="pano-zoom-out"' in html
    assert 'id="pano-fullscreen"' in html

    # Same fov defaults as before.
    assert "HFOV = 100, MIN_HFOV = 30, MAX_HFOV = 120" in html


def test_output_path_is_returned(sample_jpg, tmp_path):
    out = str(tmp_path / "sub" / "out.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    assert generate_html_viewer(sample_jpg, out) == out
