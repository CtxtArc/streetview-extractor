import pytest

from street_extractor.cli import build_parser


def test_requires_address_or_latlon():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_address_and_latlon_are_mutually_exclusive():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--address", "Paris", "--latlon", "1,2"])


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


def test_rejects_invalid_zoom():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--address", "Paris", "--zoom", "99"])
