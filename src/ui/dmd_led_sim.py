#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LED pixel-simulation filter — zero UI dependencies.

Provides the fast NumPy-based grid overlay used by the DMD preview to
simulate the physical appearance of an HUB75 LED matrix panel.

Exported symbols:
  LED_SIM_SCALE  — default pixels per LED cell (int)
  LED_SIM_GAP    — default dark-border width in display pixels (int)
  LED_SIM_MAX_W  — maximum canvas width before the scale factor is clamped (int)
  apply_led_grid — the actual filter function
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as _Image

# ── Public constants ──────────────────────────────────────────────────────────
LED_SIM_SCALE: int = 4    # each DMD pixel → 4×4 display pixels
LED_SIM_GAP:   int = 1    # 1-pixel dark gap on every edge of the cell
LED_SIM_MAX_W: int = 640  # clamp canvas width to this many pixels


# ── Filter ────────────────────────────────────────────────────────────────────

def apply_led_grid(pil_img: "_Image.Image", sim_scale: int,
                   gap: int = LED_SIM_GAP) -> "_Image.Image":
    """Apply an LED pixel-grid overlay to a PIL Image.

    Each logical pixel occupies a *sim_scale × sim_scale* cell in the
    display image.  A dark border of *gap* display-pixels on every edge
    simulates the physical gap between LED emitters on an HUB75 matrix.

    The operation is fully vectorised via NumPy — no Python loops over pixels.
    Falls back to the unmodified original image if NumPy is unavailable.

    Args:
        pil_img:   RGB PIL Image already scaled to
                   ``(src_w * sim_scale, src_h * sim_scale)``.
        sim_scale: Integer pixels per logical pixel cell (>= 2).
        gap:       Width of the dark gap border in display pixels
                   (default: ``LED_SIM_GAP`` = 1).

    Returns:
        New PIL Image with the grid applied (same size as *pil_img*).
    """
    try:
        import numpy as np
    except ImportError:
        return pil_img   # NumPy unavailable: return frame unchanged

    from PIL import Image

    arr = np.array(pil_img, dtype=np.uint8)   # (H, W, 3)
    h, w = arr.shape[:2]

    xs = np.arange(w, dtype=np.int32)
    ys = np.arange(h, dtype=np.int32)

    # Position of each display pixel within its logical LED cell (0 … sim_scale-1)
    cell_x = xs % sim_scale
    cell_y = ys % sim_scale

    # True where the display pixel falls inside the dark border (bottom/right edge only)
    gap_x = (cell_x >= sim_scale - gap)                    # shape (W,)
    gap_y = (cell_y >= sim_scale - gap)                    # shape (H,)
    mask  = gap_x[np.newaxis, :] | gap_y[:, np.newaxis]    # shape (H, W)

    arr[mask] = 0   # black gap
    return Image.fromarray(arr)

