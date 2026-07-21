# streetview-extractor

Download and stitch full Google Street View panoramas from either GPS
coordinates or a plain-text address — no Google Maps API key required.
Optionally also generate an interactive, drag-to-look-around 3D-style HTML
viewer, like the one in Google Maps.

## Example image

```bash
streetview-extract --latlon 48.87407,2.293991 --zoom 5 -o arc_triomphe.jpg
13:21:48 INFO Looking up panorama near 48.87407, 2.293991...

13:21:48 INFO Found pano HpkevTEl6q-UE_uDqVlndg. Downloading 338 tiles...
[##############################] 338/338 tiles
13:21:49 INFO Stitched 338/338 tiles successfully.
13:21:50 INFO Saved panorama to arc_triomphe.jpg
Saved: arc_triomphe.jpg
Pano ID: HpkevTEl6q-UE_uDqVlndg
Coordinates: 48.87407, 2.293991
```
![arc](./assets/arc_triomphe.jpg)

## Install

```bash
git clone https://github.com/CtxtArc/streetview-extractor.git
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

### Interactive 3D viewer

Pass `--html` to also generate a standalone HTML page with a
drag-to-look-around, zoom, and fullscreen panorama viewer — the same
interaction model as Street View in Google Maps. It's powered by
[Pannellum](https://pannellum.org/) (MIT-licensed), loaded from its CDN
at view-time; no extra install step or API key needed.

```bash
# auto-derives eiffel.html from -o eiffel.jpg
streetview-extract --address "Eiffel Tower, Paris" -o eiffel.jpg --html

# custom html output path
streetview-extract --latlon 48.8584,2.2945 -o out.jpg --html tour.html

# smaller HTML that references the jpg by relative path instead of
# embedding it as base64 (keep the .jpg and .html together if you use this)
streetview-extract --address "Times Square, New York" -o ts.jpg --html --html-no-embed
```

By default the panorama JPG is base64-embedded directly in the HTML, so
the generated file is fully self-contained — you can move, email, or host
it on its own.

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

Generate the interactive HTML viewer in the same call:

```python
info = extractor.extract_and_save(
    "out.jpg", address="Golden Gate Bridge", html_output="out.html"
)
print(info.html_path)  # -> "out.html"
```

Or generate a viewer from a panorama JPG you already have on disk, any time:

```python
extractor.save_html_viewer("out.jpg", "out.html")
```

Or use the standalone function directly, without a `StreetExtractor` instance:

```python
from street_extractor import generate_html_viewer

generate_html_viewer("out.jpg", "out.html", embed_image=False)
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
- **3D viewer**: `--html` generates the page locally and needs no network
  access to build; the viewer's browser fetches Pannellum's small JS/CSS
  from its CDN the first time the page is opened, so an internet connection
  is needed to *view* the page (not to generate it).

## Project layout

```
streetview-extractor/
├── src/street_extractor/
│   ├── __init__.py     # public API exports
│   ├── core.py         # StreetExtractor, geocoding, tile download/stitch
│   ├── viewer.py        # interactive 3D-style HTML panorama viewer generator
│   ├── cli.py           # streetview-extract command
│   └── __main__.py     # enables `python -m street_extractor`
├── tests/
│   ├── test_core.py
│   ├── test_cli.py
│   └── test_viewer.py
├── .github/workflows/ci.yml
├── pyproject.toml
└── README.md
```
