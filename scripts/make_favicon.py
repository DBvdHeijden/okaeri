# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=10"]
# ///
"""Generate okaeri's favicons from the Lorenz attractor used on the homepage.

    uv run scripts/make_favicon.py

Writes app/static/favicon.svg (adapts to light/dark tabs), favicon-32.png
and apple-touch-icon.png. Line thickness follows the hidden depth axis, as on
the page.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"

SIGMA, RHO, BETA = 10.0, 28.0, 8.0 / 3.0
DT = 0.005
TRANSIENT = 2000
STEPS = 1500  # how much of the trajectory to draw; more = denser wings
SEARCH = 20000  # look this far ahead for a window that visits both wings evenly
ANGLE = 0.0  # view rotation around z; 0 is the classic x–z butterfly

LIGHT, DARK = "#22221F", "#D4D4CF"  # --text in light / dark theme
BG = "#FBFBFA"  # apple-touch-icon background (iOS doesn't do transparency)
WIDTH_LEVELS = 4


def lorenz_points() -> list[tuple[float, float, float]]:
    def deriv(x, y, z):
        return SIGMA * (y - x), x * (RHO - z) - y, x * y - BETA * z

    x, y, z = 0.1, 0.0, 0.0
    points = []
    for n in range(TRANSIENT + SEARCH + STEPS):
        k1 = deriv(x, y, z)
        k2 = deriv(x + k1[0] * DT / 2, y + k1[1] * DT / 2, z + k1[2] * DT / 2)
        k3 = deriv(x + k2[0] * DT / 2, y + k2[1] * DT / 2, z + k2[2] * DT / 2)
        k4 = deriv(x + k3[0] * DT, y + k3[1] * DT, z + k3[2] * DT)
        x += (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]) * DT / 6
        y += (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]) * DT / 6
        z += (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2]) * DT / 6
        if n >= TRANSIENT:
            points.append((x, y, z))

    # Pick the window whose time is split most evenly between the two wings (x < 0, x > 0).
    right = [0]
    for px, _, _ in points:
        right.append(right[-1] + (px > 0))
    best = min(range(0, SEARCH, 50), key=lambda a: abs((right[a + STEPS] - right[a]) / STEPS - 0.5))
    return points[best : best + STEPS]


def project(points, size: float, pad: float):
    """Screen (u, v) in a size×size box, plus nearness in 0..1 (the hidden axis)."""
    c, s = math.cos(ANGLE), math.sin(ANGLE)
    uv = [(x * c - y * s, z) for x, y, z in points]
    depth = [x * s + y * c for x, y, _ in points]
    us, vs = [p[0] for p in uv], [p[1] for p in uv]
    span = max(max(us) - min(us), max(vs) - min(vs))
    scale = (size - 2 * pad) / span
    ou = (size - (max(us) - min(us)) * scale) / 2 - min(us) * scale
    ov = (size - (max(vs) - min(vs)) * scale) / 2 + max(vs) * scale
    lo, hi = min(depth), max(depth)
    return [
        (ou + u * scale, ov - v * scale, (d - lo) / (hi - lo))
        for (u, v), d in zip(uv, depth)
    ]


def line_width(level: int) -> float:
    """Stroke width in a 32-unit box: far side thin, near side thicker."""
    return 0.55 + 0.75 * level / (WIDTH_LEVELS - 1)


def runs(projected, levels: int):
    """Split the polyline into runs of equal width level."""
    out, current, level = [], [], None
    for i, (x, y, near) in enumerate(projected):
        lvl = min(levels - 1, int(near * levels))
        if lvl != level and current:
            current.append((x, y))  # overlap one point so runs join up
            out.append((level, current))
            current = []
        level = lvl
        current.append((x, y))
    if len(current) > 1:
        out.append((level, current))
    return out


def simplify(points, eps: float):
    """Ramer–Douglas–Peucker, iterative."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-9
        far, far_d = None, eps
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > far_d:
                far, far_d = i, d
        if far is not None:
            keep[far] = True
            stack += [(a, far), (far, b)]
    return [p for p, k in zip(points, keep) if k]


def svg(points) -> str:
    size = 32
    projected = project(points, size, pad=1.5)
    paths = []
    for level, run in runs(projected, WIDTH_LEVELS):
        width = line_width(level)
        d = "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in simplify(run, 0.04))
        paths.append(f'<path d="{d}" stroke-width="{width:.2f}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
        f"<style>g{{stroke:{LIGHT}}}@media (prefers-color-scheme:dark){{g{{stroke:{DARK}}}}}</style>"
        '<g fill="none" stroke-linecap="round" stroke-linejoin="round">'
        + "".join(paths)
        + "</g></svg>\n"
    )


def png(points, size: int, background: str | None, pad_frac: float) -> Image.Image:
    ss = 8  # supersample, then downscale for clean anti-aliasing
    big = size * ss
    img = Image.new("RGBA", (big, big), background or (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    projected = project(points, big, pad=big * pad_frac)
    for level, run in runs(projected, WIDTH_LEVELS):
        width = line_width(level) * big / 32
        draw.line(run, fill=LIGHT, width=max(1, round(width)), joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    points = lorenz_points()
    (STATIC / "favicon.svg").write_text(svg(points))
    png(points, 32, None, 0.05).save(STATIC / "favicon-32.png")
    png(points, 180, BG, 0.16).save(STATIC / "apple-touch-icon.png")
    for name in ("favicon.svg", "favicon-32.png", "apple-touch-icon.png"):
        print(f"{name}: {(STATIC / name).stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
