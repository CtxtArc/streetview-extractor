#!/usr/bin/env python3
"""
Command-line interface for street_extractor.
Installed as the `streetview-extract` console script; also runnable via
`python -m street_extractor`.
Examples:
    streetview-extract --latlon 40.689247,-74.044502 -o statue_of_liberty.jpg
    streetview-extract --address "Eiffel Tower, Paris" -o eiffel.jpg --zoom 5
    streetview-extract --address "Times Square, New York" -o times_square.jpg -q
    streetview-extract --address "Eiffel Tower, Paris" -o eiffel.jpg --html
    streetview-extract --address "Eiffel Tower, Paris" -o eiffel.jpg --html eiffel_view.html
"""
import argparse
import logging
import sys
from pathlib import Path

from .core import GeocodingError, StreetExtractor, StreetViewNotFoundError
def make_progress_printer(quiet: bool):
    if quiet:
        return None
    def _progress(done: int, total: int) -> None:
        width = 30
        filled = int(width * done / total)
        bar = "#" * filled + "-" * (width - filled)
        sys.stdout.write(f"\r[{bar}] {done}/{total} tiles")
        sys.stdout.flush()
        if done == total:
            sys.stdout.write("\n")
    return _progress
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="streetview-extract",
        description="Download and stitch a Google Street View panorama.",
    )
    loc_group = parser.add_mutually_exclusive_group(required=True)
    loc_group.add_argument("--address", type=str, help="Free-text address or place name.")
    loc_group.add_argument(
        "--latlon",
        type=str,
        metavar="LAT,LON",
        help="Coordinates as 'lat,lon', e.g. 40.6892,-74.0445",
    )
    parser.add_argument(
        "-o", "--output", type=str, default="panorama.jpg", help="Output image path."
    )
    parser.add_argument(
        "--zoom",
        type=int,
        default=4,
        choices=range(0, 6),
        help="Zoom level: 0 (tiny) .. 5 (max, ~13K px wide). Default 4 (~6.5K px).",
    )
    parser.add_argument(
        "--concurrency", type=int, default=16, help="Max simultaneous tile downloads."
    )
    parser.add_argument("--retries", type=int, default=3, help="Retries per tile on failure.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "--html",
        type=str,
        nargs="?",
        const="__AUTO__",
        default=None,
        metavar="PATH",
        help=(
            "Also generate an interactive, drag-to-look-around HTML panorama "
            "viewer (zoom + fullscreen, like Street View in Google Maps). "
            "Give a path, or omit the value to derive one from -o/--output "
            "(e.g. panorama.jpg -> panorama.html)."
        ),
    )
    parser.add_argument(
        "--html-no-embed",
        action="store_true",
        help=(
            "With --html: reference the JPG by relative filename instead of "
            "embedding it as base64 in the HTML. Produces a smaller HTML file, "
            "but the .jpg and .html must then be kept together."
        ),
    )
    return parser
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    lat = lon = None
    address = None
    if args.address:
        address = args.address
    else:
        try:
            lat_str, lon_str = args.latlon.split(",")
            lat, lon = float(lat_str.strip()), float(lon_str.strip())
        except ValueError:
            parser.error("--latlon must be formatted as 'lat,lon', e.g. 40.6892,-74.0445")

    html_output = None
    if args.html is not None:
        html_output = args.html
        if html_output == "__AUTO__":
            html_output = str(Path(args.output).with_suffix(".html"))

    extractor = StreetExtractor(
        zoom=args.zoom, concurrency=args.concurrency, max_retries=args.retries
    )
    progress = make_progress_printer(args.quiet)
    try:
        info = extractor.extract_and_save(
            output_path=args.output,
            lat=lat,
            lon=lon,
            address=address,
            on_progress=progress,
            html_output=html_output,
            embed_image_in_html=not args.html_no_embed,
        )
    except GeocodingError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except StreetViewNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    print(f"Saved: {args.output}")
    print(f"Pano ID: {info.pano_id}")
    if info.lat is not None:
        print(f"Coordinates: {info.lat}, {info.lon}")
    if info.html_path:
        print(f"3D viewer: {info.html_path}")
    return 0
if __name__ == "__main__":
    sys.exit(main())
