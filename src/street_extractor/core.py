"""
street_extractor.py

A Google Street View panorama downloader. Given GPS coordinates (or a
plain-text address), it locates the nearest panorama, downloads all of
its tiles concurrently, stitches them into a single equirectangular
image, and saves it to disk.

Note: this relies on the same undocumented endpoints the Street View
web viewer itself calls in the browser (no official API key needed for
the tile/pano-id lookups). Because it's undocumented, Google can change
or rate-limit it at any time -- treat this as a best-effort tool, not
something to hammer at scale, and review Google's Terms of Service /
Street View usage policies before using downloaded imagery for
anything beyond personal/exploratory use.
"""

import asyncio
import io
import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import aiohttp
import requests
from PIL import Image

from .viewer import generate_html_viewer

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# zoom -> (columns, rows) of 512x512 tiles that make up the full panorama
ZOOM_GRIDS = {
    0: (1, 1),
    1: (2, 1),
    2: (4, 2),
    3: (7, 4),
    4: (13, 7),
    5: (26, 13),
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class StreetViewNotFoundError(Exception):
    """Raised when no panorama could be found near the requested location."""


class GeocodingError(Exception):
    """Raised when an address could not be resolved to coordinates."""


@dataclass
class PanoInfo:
    pano_id: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    html_path: Optional[str] = None


class StreetExtractor:
    """Downloads and stitches Google Street View panoramas."""

    def __init__(
        self,
        zoom: int = 4,
        max_retries: int = 3,
        retry_backoff: float = 0.75,
        concurrency: int = 16,
        timeout: float = 15.0,
    ):
        """
        :param zoom: Zoom level (0=lowest .. 5=highest, ~13K px wide). Default 4 (~6.5K wide).
        :param max_retries: Retries per tile before giving up on it.
        :param retry_backoff: Base seconds for exponential backoff between tile retries.
        :param concurrency: Max simultaneous tile downloads.
        :param timeout: Per-request timeout in seconds.
        """
        if zoom not in ZOOM_GRIDS:
            raise ValueError(f"zoom must be one of {sorted(ZOOM_GRIDS)}, got {zoom}")
        self.zoom = zoom
        self.tile_size = 512
        self.cols, self.rows = ZOOM_GRIDS[zoom]
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.concurrency = concurrency
        self.timeout = timeout
        self.headers = {"User-Agent": USER_AGENT}

    # ------------------------------------------------------------------ #
    # Lookup helpers
    # ------------------------------------------------------------------ #

    def geocode(self, address: str) -> Tuple[float, float]:
        """Resolve a free-text address to (lat, lon) using OSM Nominatim
        (no API key required). For heavier use, swap in a paid geocoder."""
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1}
        resp = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        results = resp.json()
        if not results:
            raise GeocodingError(f"Could not geocode address: {address!r}")
        return float(results[0]["lat"]), float(results[0]["lon"])

    def get_pano_id(self, lat: float, lon: float, radius_m: int = 50) -> Optional[str]:
        """Fetches the panorama ID nearest a given GPS coordinate."""
        pb = (
            f"!1m5!1sapiv3!5sUS!11m2!1m1!1b0!2m4!1m2!3d{lat}!4d{lon}!2d{radius_m}"
            "!3m10!2m2!1sen!2sUS!9m1!1e2!11m4!1m3!1e2!2b1!3e2!4m10!1e1!1e2!1e3!1e4"
            "!1e8!1e6!5m1!1e2!6m1!1e2"
        )
        url = (
            "https://maps.googleapis.com/maps/api/js/GeoPhotoService.SingleImageSearch"
            f"?pb={pb}&callback=callback"
        )

        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            text = resp.text

            if "[" not in text:
                return None

            clean_json = text[text.find("[") : text.rfind("]") + 1]
            while ",," in clean_json:
                clean_json = clean_json.replace(",,", ",null,")
            clean_json = clean_json.replace("[,", "[null,").replace(",]", ",null]")

            data = json.loads(clean_json)

            def find_id(obj):
                if isinstance(obj, str):
                    if len(obj) == 22 or obj.startswith("AF1Q") or obj.startswith("CAoS"):
                        return obj
                elif isinstance(obj, list):
                    for item in obj:
                        result = find_id(item)
                        if result:
                            return result
                return None

            return find_id(data)
        except requests.RequestException as e:
            logger.error(f"Network error fetching pano ID: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to parse pano ID response: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Tile download / stitch
    # ------------------------------------------------------------------ #

    async def _fetch_tile(
        self,
        session: aiohttp.ClientSession,
        sem: asyncio.Semaphore,
        pano_id: str,
        x: int,
        y: int,
    ) -> Tuple[int, int, Optional[Image.Image]]:
        """Downloads a single map tile, with retries on transient failures."""
        url = (
            "https://streetviewpixels-pa.googleapis.com/v1/tile"
            f"?cb_client=maps_sv.tactile&panoid={pano_id}&x={x}&y={y}&zoom={self.zoom}"
        )

        async with sem:
            for attempt in range(1, self.max_retries + 1):
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            return x, y, Image.open(io.BytesIO(data)).convert("RGB")
                        elif resp.status == 404:
                            # Tile genuinely doesn't exist (edge of pano) -- not an error.
                            return x, y, None
                        else:
                            logger.debug(
                                f"Tile ({x},{y}) attempt {attempt}: HTTP {resp.status}"
                            )
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug(f"Tile ({x},{y}) attempt {attempt} error: {e}")

                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_backoff * attempt)

            logger.warning(f"Giving up on tile ({x},{y}) after {self.max_retries} attempts.")
            return x, y, None

    async def get_image_async(
        self, lat: float, lon: float, on_progress=None
    ) -> Tuple[Image.Image, PanoInfo]:
        """Asynchronously downloads and stitches the panorama.

        :param on_progress: optional callback(done, total) called after each tile.
        :returns: (stitched PIL Image, PanoInfo)
        :raises StreetViewNotFoundError: if no panorama exists nearby.
        """
        logger.info(f"Looking up panorama near {lat}, {lon}...")
        pano_id = self.get_pano_id(lat, lon)

        if not pano_id:
            raise StreetViewNotFoundError(
                f"No Google Street View panorama found near ({lat}, {lon})."
            )

        logger.info(f"Found pano {pano_id}. Downloading {self.cols * self.rows} tiles...")

        sem = asyncio.Semaphore(self.concurrency)
        total = self.cols * self.rows
        done = 0

        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = [
                asyncio.create_task(self._fetch_tile(session, sem, pano_id, x, y))
                for x in range(self.cols)
                for y in range(self.rows)
            ]
            results = []
            for coro in asyncio.as_completed(tasks):
                result = await coro
                results.append(result)
                done += 1
                if on_progress:
                    on_progress(done, total)

        canvas = Image.new("RGB", (self.cols * self.tile_size, self.rows * self.tile_size))
        valid_tiles = 0
        for x, y, img in results:
            if img:
                canvas.paste(img, (x * self.tile_size, y * self.tile_size))
                valid_tiles += 1

        if valid_tiles == 0:
            raise StreetViewNotFoundError(
                f"Panorama {pano_id} found but every tile failed to download."
            )

        logger.info(f"Stitched {valid_tiles}/{total} tiles successfully.")
        return canvas, PanoInfo(pano_id=pano_id, lat=lat, lon=lon)

    # ------------------------------------------------------------------ #
    # Sync convenience wrappers
    # ------------------------------------------------------------------ #

    def get_image(self, lat: float, lon: float, on_progress=None) -> Tuple[Image.Image, PanoInfo]:
        """Synchronous wrapper around get_image_async."""
        return asyncio.run(self.get_image_async(lat, lon, on_progress=on_progress))

    def save_html_viewer(
        self,
        image_path: str,
        output_path: str,
        title: Optional[str] = None,
        caption: Optional[str] = None,
        embed_image: bool = True,
    ) -> str:
        """
        Generate a standalone HTML page with an interactive, drag-to-look-around
        panorama viewer (zoom + fullscreen controls) from an already-saved
        panorama JPG -- similar to the 3D Street View viewer in Google Maps.

        This is independent of extract_and_save: you can call it any time
        on any equirectangular panorama JPG you already have on disk.

        :param image_path: Path to the stitched equirectangular JPG.
        :param output_path: Where to write the .html file.
        :param title: Page title. Defaults to the image filename.
        :param caption: Overlay caption. Defaults to the image filename.
        :param embed_image: Embed the image as base64 (self-contained HTML,
            default) vs. reference it by relative path (smaller HTML).
        :returns: output_path
        """
        return generate_html_viewer(
            image_path,
            output_path,
            title=title,
            caption=caption,
            embed_image=embed_image,
        )

    def extract_and_save(
        self,
        output_path: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        address: Optional[str] = None,
        on_progress=None,
        html_output: Optional[str] = None,
        embed_image_in_html: bool = True,
    ) -> PanoInfo:
        """
        Fetch a panorama (by lat/lon or address) and save it to disk.

        Exactly one of (lat and lon) or address must be provided.
        Returns PanoInfo on success. Raises GeocodingError or
        StreetViewNotFoundError on failure.

        :param html_output: Optional path. If given, also generates an
            interactive 3D-style HTML panorama viewer (like Google Maps'
            Street View) alongside the saved JPG. Leave as None (default)
            to skip this -- all prior behavior is unchanged.
        :param embed_image_in_html: If True (default) and html_output is
            given, the JPG is base64-embedded in the HTML so it's a single
            self-contained file. If False, the HTML references the JPG by
            relative path instead.
        """
        if address is not None:
            lat, lon = self.geocode(address)
            logger.info(f"Geocoded {address!r} -> ({lat}, {lon})")
        elif lat is None or lon is None:
            raise ValueError("Provide either an address, or both lat and lon.")

        img, info = self.get_image(lat, lon, on_progress=on_progress)
        img.save(output_path, quality=100)
        logger.info(f"Saved panorama to {output_path}")

        if html_output:
            self.save_html_viewer(
                output_path,
                html_output,
                title=f"Street View \u2014 {lat:.5f}, {lon:.5f}",
                caption=f"{lat:.5f}, {lon:.5f}  \u00b7  pano {info.pano_id}",
                embed_image=embed_image_in_html,
            )
            info.html_path = html_output
            logger.info(f"Saved 3D viewer to {html_output}")

        return info
