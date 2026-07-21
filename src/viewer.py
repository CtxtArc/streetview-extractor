"""
viewer.py

Generates a standalone HTML page that displays a stitched Street View
panorama (equirectangular JPG) as an interactive, drag-to-look-around
viewer with zoom and fullscreen controls -- similar to the panorama
viewer used in Google Maps' Street View.

Implementation notes
---------------------
Uses Pannellum (https://pannellum.org/, MIT licensed), a small
open-source panorama viewer, loaded from its public CDN. Generating
the HTML requires no network access at all; the CDN request only
happens later, in the *viewer's* browser, when the page is opened.

The panorama image itself is embedded directly in the HTML as a
base64 data URI by default, so the resulting .html file is fully
self-contained and can be moved, emailed, or hosted on its own
without needing to keep the .jpg alongside it. Pass
``embed_image=False`` to instead reference the image by relative
path (keeps the HTML small, but the two files must stay together).
"""

import base64
import os
from pathlib import Path
from typing import Optional

PANNELLUM_CSS = "https://cdn.pannellum.org/2.5/pannellum.css"
PANNELLUM_JS = "https://cdn.pannellum.org/2.5/pannellum.js"

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{css}">
<script src="{js}"></script>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #000; }}
  #panorama {{ width: 100%; height: 100%; }}
  #caption {{
    position: absolute; bottom: 10px; left: 10px; z-index: 10;
    color: #eee; font: 13px/1.4 -apple-system, Segoe UI, sans-serif;
    background: rgba(0,0,0,0.45); padding: 6px 10px; border-radius: 4px;
    pointer-events: none;
  }}
</style>
</head>
<body>
<div id="panorama"></div>
<div id="caption">{caption}</div>
<script>
  pannellum.viewer('panorama', {{
    "type": "equirectangular",
    "panorama": "{image_src}",
    "autoLoad": true,
    "autoRotate": -2,
    "compass": false,
    "showZoomCtrl": true,
    "showFullscreenCtrl": true,
    "hfov": 100,
    "minHfov": 30,
    "maxHfov": 120
  }});
</script>
</body>
</html>
"""


def _image_to_data_uri(image_path: str) -> str:
    ext = Path(image_path).suffix.lower().lstrip(".") or "jpg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def generate_html_viewer(
    image_path: str,
    output_path: str,
    title: Optional[str] = None,
    caption: Optional[str] = None,
    embed_image: bool = True,
) -> str:
    """
    Generate a standalone HTML page with an interactive panorama viewer
    (drag/scroll to look around, pinch/scroll to zoom, fullscreen button)
    from a stitched equirectangular panorama image.

    :param image_path: Path to the stitched equirectangular JPG (e.g. the
        output of ``StreetExtractor.extract_and_save``).
    :param output_path: Where to write the .html file.
    :param title: Page <title>. Defaults to the image filename.
    :param caption: Small overlay caption text. Defaults to the image filename.
    :param embed_image: If True (default), the image is base64-embedded
        directly in the HTML so the page is fully self-contained. If
        False, the HTML references the image by relative filename
        instead (smaller HTML file, but keep both files together).
    :returns: output_path
    :raises FileNotFoundError: if image_path doesn't exist.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Panorama image not found: {image_path}")

    title = title or Path(image_path).stem
    caption = caption if caption is not None else Path(image_path).name

    if embed_image:
        image_src = _image_to_data_uri(image_path)
    else:
        out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
        image_src = os.path.relpath(os.path.abspath(image_path), start=out_dir)

    html = _HTML_TEMPLATE.format(
        title=title,
        css=PANNELLUM_CSS,
        js=PANNELLUM_JS,
        caption=caption,
        image_src=image_src,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
