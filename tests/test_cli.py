import pytest

from street_extractor.cli import build_parser, main


def test_requires_address_or_latlon_or_from_image():
    # Argparse itself no longer enforces this (it can't, since --from-image
    # needs to join the same mutual-exclusion without being required on its
    # own) -- main() checks for "at least one mode selected" and exits via
    # parser.error(), which raises SystemExit just the same.
    with pytest.raises(SystemExit):
        main([])


def test_address_and_latlon_are_mutually_exclusive():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--address", "Paris", "--latlon", "1,2"])


def test_from_image_is_mutually_exclusive_with_address():
    with pytest.raises(SystemExit):
        main(["--address", "Paris", "--from-image", "pano.jpg"])


def test_parses_address():
    parser = build_parser()
    args = parser.parse_args(["--address", "Eiffel Tower"])
    assert args.address == "Eiffel Tower"
    assert args.zoom == 4
    assert args.output == "panorama.jpg"


def test_parses_latlon_and_options():
    parser = build_parser()
    args = parser.parse_args(
        ["--latlon", "40.6892,-74.0445", "-o", "out.jpg", "--zoom", "5", "-q"]
    )
    assert args.latlon == "40.6892,-74.0445"
    assert args.output == "out.jpg"
    assert args.zoom == 5
    assert args.quiet is True


def test_parses_from_image():
    parser = build_parser()
    args = parser.parse_args(["--from-image", "pano.jpg", "--html", "pano.html"])
    assert args.from_image == "pano.jpg"
    assert args.html == "pano.html"
    assert args.address is None
    assert args.latlon is None


def test_rejects_invalid_zoom():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--address", "Paris", "--zoom", "99"])


def test_from_image_converts_without_network(tmp_path):
    """--from-image should generate the viewer directly, with no geocoding
    or download involved -- exercised against a real tiny JPG on disk."""
    from PIL import Image

    jpg_path = tmp_path / "pano.jpg"
    Image.new("RGB", (8, 4), color=(10, 20, 30)).save(jpg_path, quality=90)
    html_path = tmp_path / "pano.html"

    rc = main(["--from-image", str(jpg_path), "--html", str(html_path)])

    assert rc == 0
    assert html_path.is_file()


def test_from_image_auto_derives_html_path(tmp_path, monkeypatch):
    """Omitting --html entirely should derive <name>.html from --from-image,
    the same way -o/--output does for the download path."""
    from PIL import Image

    jpg_path = tmp_path / "pano.jpg"
    Image.new("RGB", (8, 4), color=(10, 20, 30)).save(jpg_path, quality=90)
    monkeypatch.chdir(tmp_path)

    rc = main(["--from-image", str(jpg_path)])

    assert rc == 0
    assert (tmp_path / "pano.html").is_file()


def test_from_image_missing_file_returns_error(tmp_path):
    missing = tmp_path / "does_not_exist.jpg"
    rc = main(["--from-image", str(missing)])
    assert rc == 1
