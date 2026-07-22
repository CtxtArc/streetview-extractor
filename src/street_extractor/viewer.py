"""
viewer.py

Generates a standalone HTML page that displays a stitched Street View
panorama (equirectangular JPG) as an interactive, drag-to-look-around
viewer with zoom and fullscreen controls -- similar to the panorama
viewer used in Google Maps' Street View.

Implementation notes
---------------------
This is a hand-rolled WebGL viewer (no external libraries, no CDN).
The panorama is projected onto the inside of a sphere; dragging rotates
the "camera" (yaw/pitch), scrolling/pinching adjusts field of view.

The generated HTML is fully self-contained: the viewer JS is inlined
directly into the page, and (by default) the panorama image is embedded
as a base64 data URI. The result works completely offline -- no network
access is required at any point, either to generate it or to view it.
"""

import base64
import os
from pathlib import Path
from string import Template
from typing import Optional

# Kept for backwards compatibility with anything that imported these;
# no longer used internally since the viewer no longer depends on a CDN.
PANNELLUM_CSS = None
PANNELLUM_JS = None


_HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #000; overflow: hidden; }
  #pano-container { position: relative; width: 100%; height: 100%; }
  #pano-canvas { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
  #pano-canvas:active { cursor: grabbing; }
  #caption {
    position: absolute; bottom: 10px; left: 10px; z-index: 10;
    color: #eee; font: 13px/1.4 -apple-system, "Segoe UI", sans-serif;
    background: rgba(0,0,0,0.45); padding: 6px 10px; border-radius: 4px;
    pointer-events: none;
  }
  #pano-controls {
    position: absolute; bottom: 10px; right: 10px; z-index: 10;
    display: flex; gap: 6px;
  }
  .pano-btn {
    width: 32px; height: 32px; border: none; border-radius: 4px;
    background: rgba(0,0,0,0.45); color: #eee; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.15s;
  }
  .pano-btn:hover { background: rgba(0,0,0,0.7); }
  .pano-btn svg { width: 16px; height: 16px; fill: none; stroke: #eee; stroke-width: 2; }
  #pano-loading {
    position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%);
    color: #888; font: 13px -apple-system, sans-serif; z-index: 5;
  }
</style>
</head>
<body>
<div id="pano-container">
  <canvas id="pano-canvas"></canvas>
  <div id="pano-loading">Loading panorama...</div>
  <div id="caption">$caption</div>
  <div id="pano-controls">
    <button class="pano-btn" id="pano-zoom-in" title="Zoom in" aria-label="Zoom in">
      <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
    </button>
    <button class="pano-btn" id="pano-zoom-out" title="Zoom out" aria-label="Zoom out">
      <svg viewBox="0 0 24 24"><line x1="5" y1="12" x2="19" y2="12"/></svg>
    </button>
    <button class="pano-btn" id="pano-fullscreen" title="Fullscreen" aria-label="Fullscreen">
      <svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>
    </button>
  </div>
</div>
<script>
$viewer_js
</script>
</body>
</html>
""")


def _image_to_data_uri(image_path: str) -> str:
    ext = Path(image_path).suffix.lower().lstrip(".") or "jpg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def _build_viewer_js(image_src: str, hfov: int = 100, min_hfov: int = 30,
                      max_hfov: int = 120, autorotate_deg_per_frame: float = -0.02) -> str:
    """Build the self-contained WebGL panorama viewer script.

    No external dependencies, no network requests -- everything the
    viewer needs (shaders, sphere geometry, controls) lives in this
    string. The image is loaded from `image_src`, which is either a
    data: URI (embedded) or a relative path (non-embedded).
    """
    js = r"""
(function () {
  var IMAGE_SRC = "__IMAGE_SRC__";
  var HFOV = __HFOV__, MIN_HFOV = __MIN_HFOV__, MAX_HFOV = __MAX_HFOV__;
  var AUTOROTATE_DEG_PER_FRAME = __AUTOROTATE__;

  var canvas = document.getElementById('pano-canvas');
  var loadingEl = document.getElementById('pano-loading');
  var gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
  if (!gl) {
    loadingEl.textContent = 'WebGL is not supported in this browser.';
    return;
  }

  // ---- shaders ----
  var vsSource = [
    'attribute vec3 aPosition;',
    'attribute vec2 aTexCoord;',
    'uniform mat4 uProjection;',
    'uniform mat4 uPitch;',
    'uniform mat4 uYaw;',
    'varying vec2 vTexCoord;',
    'void main(void) {',
    '  gl_Position = uProjection * uPitch * uYaw * vec4(aPosition, 1.0);',
    '  vTexCoord = aTexCoord;',
    '}'
  ].join('\n');

  var fsSource = [
    'precision mediump float;',
    'varying vec2 vTexCoord;',
    'uniform sampler2D uSampler;',
    'void main(void) {',
    '  gl_FragColor = texture2D(uSampler, vTexCoord);',
    '}'
  ].join('\n');

  function compileShader(type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(shader));
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  var vs = compileShader(gl.VERTEX_SHADER, vsSource);
  var fs = compileShader(gl.FRAGMENT_SHADER, fsSource);
  var program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(gl.getProgramInfoLog(program));
  }
  gl.useProgram(program);

  var aPosition = gl.getAttribLocation(program, 'aPosition');
  var aTexCoord = gl.getAttribLocation(program, 'aTexCoord');
  var uProjection = gl.getUniformLocation(program, 'uProjection');
  var uPitch = gl.getUniformLocation(program, 'uPitch');
  var uYaw = gl.getUniformLocation(program, 'uYaw');
  var uSampler = gl.getUniformLocation(program, 'uSampler');

  // ---- build sphere geometry (camera sits at the center, looking out) ----
  var LAT_BANDS = 40, LON_BANDS = 40, RADIUS = 100;
  var positions = [], texCoords = [], indices = [];
  for (var lat = 0; lat <= LAT_BANDS; lat++) {
    var theta = lat * Math.PI / LAT_BANDS;
    var sinTheta = Math.sin(theta), cosTheta = Math.cos(theta);
    for (var lon = 0; lon <= LON_BANDS; lon++) {
      var phi = lon * 2 * Math.PI / LON_BANDS;
      var sinPhi = Math.sin(phi), cosPhi = Math.cos(phi);
      var x = cosPhi * sinTheta;
      var y = cosTheta;
      var z = sinPhi * sinTheta;
      positions.push(RADIUS * x, RADIUS * y, RADIUS * z);
      texCoords.push(1.0 - (lon / LON_BANDS), lat / LAT_BANDS);
    }
  }
  for (lat = 0; lat < LAT_BANDS; lat++) {
    for (lon = 0; lon < LON_BANDS; lon++) {
      var first = lat * (LON_BANDS + 1) + lon;
      var second = first + LON_BANDS + 1;
      indices.push(first, second, first + 1);
      indices.push(second, second + 1, first + 1);
    }
  }

  var positionBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);

  var texCoordBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, texCoordBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(texCoords), gl.STATIC_DRAW);

  var indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);

  gl.disable(gl.CULL_FACE); // camera is inside the sphere; skip winding-order concerns
  gl.enable(gl.DEPTH_TEST);

  // ---- texture (placeholder pixel until the image loads) ----
  var texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([20, 20, 20, 255]));

  var ready = false;
  var image = new Image();
  image.onload = function () {
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    if (isPowerOf2(image.width) && isPowerOf2(image.height)) {
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    } else {
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    }
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    loadingEl.style.display = 'none';
    ready = true;
  };
  image.onerror = function () {
    loadingEl.textContent = 'Failed to load panorama image.';
  };
  image.src = IMAGE_SRC;

  function isPowerOf2(v) { return (v & (v - 1)) === 0; }

  // ---- matrix helpers (column-major, WebGL convention) ----
  function mat4Perspective(fovyRad, aspect, near, far) {
    var f = 1.0 / Math.tan(fovyRad / 2);
    var out = new Float32Array(16);
    out[0] = f / aspect; out[5] = f;
    out[10] = (far + near) / (near - far); out[11] = -1;
    out[14] = (2 * far * near) / (near - far);
    return out;
  }
  function mat4RotateX(rad) {
    var c = Math.cos(rad), s = Math.sin(rad);
    return new Float32Array([1, 0, 0, 0,  0, c, s, 0,  0, -s, c, 0,  0, 0, 0, 1]);
  }
  function mat4RotateY(rad) {
    var c = Math.cos(rad), s = Math.sin(rad);
    return new Float32Array([c, 0, -s, 0,  0, 1, 0, 0,  s, 0, c, 0,  0, 0, 0, 1]);
  }

  // ---- interaction state ----
  var yaw = 0, pitch = 0, hfov = HFOV;
  var dragging = false, lastX = 0, lastY = 0;
  var userInteracted = false;
  var pinchStartDist = null, pinchStartHfov = null;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function onPointerDown(x, y) {
    dragging = true; lastX = x; lastY = y; userInteracted = true;
    canvas.style.cursor = 'grabbing';
  }
  function onPointerMove(x, y) {
    if (!dragging) return;
    var dx = x - lastX, dy = y - lastY;
    lastX = x; lastY = y;
    yaw += dx * 0.15;
    pitch = clamp(pitch - dy * 0.15, -85, 85);
  }
  function onPointerUp() { dragging = false; canvas.style.cursor = 'grab'; }

  canvas.addEventListener('mousedown', function (e) { onPointerDown(e.clientX, e.clientY); });
  window.addEventListener('mousemove', function (e) { onPointerMove(e.clientX, e.clientY); });
  window.addEventListener('mouseup', onPointerUp);

  canvas.addEventListener('touchstart', function (e) {
    userInteracted = true;
    if (e.touches.length === 1) {
      onPointerDown(e.touches[0].clientX, e.touches[0].clientY);
    } else if (e.touches.length === 2) {
      dragging = false;
      pinchStartDist = touchDist(e.touches);
      pinchStartHfov = hfov;
    }
    e.preventDefault();
  }, { passive: false });

  canvas.addEventListener('touchmove', function (e) {
    if (e.touches.length === 1 && dragging) {
      onPointerMove(e.touches[0].clientX, e.touches[0].clientY);
    } else if (e.touches.length === 2 && pinchStartDist) {
      var d = touchDist(e.touches);
      hfov = clamp(pinchStartHfov * (pinchStartDist / d), MIN_HFOV, MAX_HFOV);
    }
    e.preventDefault();
  }, { passive: false });

  canvas.addEventListener('touchend', function () {
    onPointerUp();
    pinchStartDist = null;
  });

  function touchDist(touches) {
    var dx = touches[0].clientX - touches[1].clientX;
    var dy = touches[0].clientY - touches[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  canvas.addEventListener('wheel', function (e) {
    e.preventDefault();
    userInteracted = true;
    hfov = clamp(hfov + e.deltaY * 0.05, MIN_HFOV, MAX_HFOV);
  }, { passive: false });

  document.getElementById('pano-zoom-in').addEventListener('click', function () {
    userInteracted = true;
    hfov = clamp(hfov - 10, MIN_HFOV, MAX_HFOV);
  });
  document.getElementById('pano-zoom-out').addEventListener('click', function () {
    userInteracted = true;
    hfov = clamp(hfov + 10, MIN_HFOV, MAX_HFOV);
  });
  document.getElementById('pano-fullscreen').addEventListener('click', function () {
    var container = document.getElementById('pano-container');
    if (!document.fullscreenElement) {
      (container.requestFullscreen || container.webkitRequestFullscreen || function () {}).call(container);
    } else {
      (document.exitFullscreen || document.webkitExitFullscreen || function () {}).call(document);
    }
  });

  // ---- render loop ----
  function resize() {
    var dpr = window.devicePixelRatio || 1;
    var w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w; canvas.height = h;
    }
  }

  function render() {
    resize();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    if (ready && canvas.width > 0 && canvas.height > 0) {
      if (!userInteracted) yaw += AUTOROTATE_DEG_PER_FRAME;

      var aspect = canvas.width / canvas.height;
      var hfovRad = hfov * Math.PI / 180;
      var vfovRad = 2 * Math.atan(Math.tan(hfovRad / 2) / aspect);
      var projection = mat4Perspective(vfovRad, aspect, 0.1, 1000);

      // view = Rx(-pitch) * Ry(-yaw), i.e. the inverse of the camera's
      // world-space orientation Ry(yaw) * Rx(pitch)
      var pitchMat = mat4RotateX(-pitch * Math.PI / 180);
      var yawMat = mat4RotateY(-yaw * Math.PI / 180);

      gl.useProgram(program);
      gl.uniformMatrix4fv(uProjection, false, projection);
      gl.uniformMatrix4fv(uPitch, false, pitchMat);
      gl.uniformMatrix4fv(uYaw, false, yawMat);

      gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
      gl.enableVertexAttribArray(aPosition);
      gl.vertexAttribPointer(aPosition, 3, gl.FLOAT, false, 0, 0);

      gl.bindBuffer(gl.ARRAY_BUFFER, texCoordBuffer);
      gl.enableVertexAttribArray(aTexCoord);
      gl.vertexAttribPointer(aTexCoord, 2, gl.FLOAT, false, 0, 0);

      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(uSampler, 0);

      gl.drawElements(gl.TRIANGLES, indices.length, gl.UNSIGNED_SHORT, 0);
    }

    requestAnimationFrame(render);
  }
  requestAnimationFrame(render);
})();
"""
    js = js.replace("__IMAGE_SRC__", image_src.replace("\\", "\\\\").replace('"', '\\"'))
    js = js.replace("__HFOV__", str(hfov))
    js = js.replace("__MIN_HFOV__", str(min_hfov))
    js = js.replace("__MAX_HFOV__", str(max_hfov))
    js = js.replace("__AUTOROTATE__", str(autorotate_deg_per_frame))
    return js


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

    The viewer is a self-contained WebGL implementation with no external
    dependencies or network requests -- the resulting HTML file works
    fully offline.

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

    viewer_js = _build_viewer_js(image_src)

    html = _HTML_TEMPLATE.substitute(
        title=title,
        caption=caption,
        viewer_js=viewer_js,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
