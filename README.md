# streetview-extractor

Download and stitch full Google Street View panoramas from either GPS
coordinates or a plain-text address — no Google Maps API key required.

> **Private/internal project.** No license is granted for reuse or
> redistribution; this repo is for internal use only.

## Install

```bash
git clone https://github.com/<your-username>/streetview-extractor.git
cd streetview-extractor
pip install -e .
```

For development (tests, linting):

```bash
pip install -e ".[dev]"
```

## CLI usage

Once installed, the `streetview-extract` command is on your PATH:

```bash
# By address (geocoded automatically via OpenStreetMap Nominatim)
streetview-extract --address "Eiffel Tower, Paris" -o eiffel.jpg

# By coordinates
streetview-extract --latlon 40.689247,-74.044502 -o statue.jpg

# Higher resolution (zoom 0-5, default 4 ≈ 6.5K px wide, 5 ≈ 13K px wide)
streetview-extract --address "Times Square, New York" -o times_square.jpg --zoom 5

# Quiet mode (no progress bar), useful for scripting
streetview-extract --latlon 48.8584,2.2945 -o out.jpg -q
```

Or without installing the entry point:

```bash
python -m street_extractor --address "Golden Gate Bridge" -o gg.jpg
```

Run `streetview-extract --help` for all options (concurrency, retries,
verbose logging).

## Library usage

```python
from street_extractor import StreetExtractor, StreetViewNotFoundError

extractor = StreetExtractor(zoom=4)

# By address
info = extractor.extract_and_save("out.jpg", address="Golden Gate Bridge")

# By coordinates, with a progress callback
def progress(done, total):
    print(f"{done}/{total} tiles")

try:
    info = extractor.extract_and_save(
        "out.jpg", lat=37.8199, lon=-122.4783, on_progress=progress
    )
    print(info.pano_id, info.lat, info.lon)
except StreetViewNotFoundError:
    print("No panorama here.")
```

Or work with the image in memory without saving:

```python
img, info = extractor.get_image(37.8199, -122.4783)  # PIL.Image
```

## Testing

```bash
pip install -e ".[dev]"
pytest -v
```

Tests mock all network calls, so they run offline and don't hit Google's
servers. CI (`.github/workflows/ci.yml`) runs the suite against Python 3.9,
3.11, and 3.12 on every push/PR to `main`.

## Notes

- **Zoom levels**: 0 (tiny) through 5 (full ~13K×6.5K px). Higher zoom = more
  tiles = slower and heavier on Google's servers, so don't go higher than you
  need.
- **Reliability**: this uses the same undocumented endpoints the Street View
  web viewer calls in your browser. There's no official support contract for
  them, so Google can change the response format or rate-limit requests at
  any time. Tile downloads retry automatically on transient failures; a
  missing tile just leaves a black gap in the stitched image rather than
  failing the whole run.
- **Terms of use**: review Google's Street View / Maps Platform terms before
  using downloaded imagery beyond personal or exploratory use — this tool
  doesn't grant any additional rights to the imagery itself.
- **Geocoding**: addresses are resolved via OpenStreetMap's free Nominatim
  service. It's rate-limited and meant for light use; for heavy/production
  use, swap in a paid geocoder (e.g. Google Geocoding API) in
  `StreetExtractor.geocode()`.

## Project layout

```
streetview-extractor/
├── src/street_extractor/
│   ├── __init__.py     # public API exports
│   ├── core.py         # StreetExtractor, geocoding, tile download/stitch
│   ├── cli.py           # streetview-extract command
│   └── __main__.py     # enables `python -m street_extractor`
├── tests/
│   ├── test_core.py
│   └── test_cli.py
├── .github/workflows/ci.yml
├── pyproject.toml
└── README.md
```
