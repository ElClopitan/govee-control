"""
Low-cost dominant screen colour sampler.

Captures the primary monitor, downscales to a tiny grid (64x36),
and computes the dominant colour using hue binning. Designed for
game mode where performance matters — no Pillow, no heavy deps.

Usage:
    from screen_color import dominant_color, grab_small
    pixels, w, h = grab_small()
    r, g, b = dominant_color(pixels, w, h)
"""

import math


def rgb_to_hsv(r, g, b):
    """Convert RGB (0-255) to HSV (h: 0-360, s: 0-1, v: 0-1)."""
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    delta = cmax - cmin

    # Hue
    if delta == 0:
        h = 0
    elif cmax == r:
        h = 60 * (((g - b) / delta) % 6)
    elif cmax == g:
        h = 60 * (((b - r) / delta) + 2)
    else:
        h = 60 * (((r - g) / delta) + 4)

    # Saturation
    if cmax == 0:
        s = 0
    else:
        s = delta / cmax

    # Value
    v = cmax

    return h, s, v


def dominant_color(pixels, width, height):
    """
    Compute the dominant colour from a small image.

    Args:
        pixels: flat list of (r, g, b) tuples, length width*height
        width: image width
        height: image height

    Returns:
        (r, g, b) tuple of the dominant colour
    """
    if not pixels:
        return (0, 0, 0)

    total = len(pixels)

    # Filter out near-black and near-grey pixels
    # Near-black: max channel < 30
    # Near-grey: max - min < 24 (low saturation)
    colored = []
    for r, g, b in pixels:
        cmax = max(r, g, b)
        cmin = min(r, g, b)
        if cmax < 30:
            continue  # near-black
        if cmax - cmin < 24:
            continue  # near-grey
        colored.append((r, g, b))

    # If fewer than 5% survive, use all pixels
    if len(colored) < total * 0.05:
        colored = pixels

    # Bucket into 12 hue bins (30 degrees each), weighted by saturation
    bins = [[] for _ in range(12)]
    for r, g, b in colored:
        h, s, v = rgb_to_hsv(r, g, b)
        bin_idx = int(h / 30) % 12
        bins[bin_idx].append((r, g, b, s))

    # Find the heaviest bin (by total saturation weight)
    best_bin = 0
    best_weight = 0
    for i, bin_pixels in enumerate(bins):
        weight = sum(s for _, _, _, s in bin_pixels)
        if weight > best_weight:
            best_weight = weight
            best_bin = i

    # Return mean colour of the heaviest bin
    bin_pixels = bins[best_bin]
    if not bin_pixels:
        # Fallback: mean of all pixels
        r_sum = sum(p[0] for p in pixels)
        g_sum = sum(p[1] for p in pixels)
        b_sum = sum(p[2] for p in pixels)
        return (
            int(r_sum / total),
            int(g_sum / total),
            int(b_sum / total),
        )

    r_sum = sum(p[0] for p in bin_pixels)
    g_sum = sum(p[1] for p in bin_pixels)
    b_sum = sum(p[2] for p in bin_pixels)
    n = len(bin_pixels)
    return (
        int(r_sum / n),
        int(g_sum / n),
        int(b_sum / n),
    )


def grab_small():
    """
    Capture the primary monitor and downscale to 64x36.

    Uses mss for capture (imported inside so the module imports without it).
    Downscales by simple striding — no Pillow resize.

    Returns:
        (pixels, width, height) where pixels is a flat list of (r, g, b) tuples
    """
    import mss

    TARGET_W = 64
    TARGET_H = 36

    with mss.mss() as sct:
        monitor = sct.monitors[0]  # primary
        img = sct.grab(monitor)

    src_w = img.width
    src_h = img.height
    src_bytes = img.bgra  # BGRA order, 4 bytes per pixel

    # Calculate stride
    x_stride = src_w / TARGET_W
    y_stride = src_h / TARGET_H

    pixels = []
    for ty in range(TARGET_H):
        sy = int(ty * y_stride)
        row_offset = sy * src_w * 4
        for tx in range(TARGET_W):
            sx = int(tx * x_stride)
            pixel_offset = row_offset + sx * 4
            # BGRA -> RGB
            b = src_bytes[pixel_offset]
            g = src_bytes[pixel_offset + 1]
            r = src_bytes[pixel_offset + 2]
            pixels.append((r, g, b))

    return (pixels, TARGET_W, TARGET_H)
