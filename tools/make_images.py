"""Makes the PNG pictures used by static/dashboard.html (icons, hero banner, shapes, logo).

Run from the project root:  python tools/make_images.py
Needs: pip install pillow numpy   (only for making images, not for running the app)
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "static" / "img"
(OUT / "ico").mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)


# ---------------- icons: drawn big, then shrunk so the edges are smooth ----------------
SCALE, BASE, FINAL = 8, 64, 64
TONES = {"white": (255, 255, 255), "teal": (10, 124, 115), "mint": (63, 193, 181)}


def icon(name, shapes):
    for tone, rgb in TONES.items():
        img = Image.new("RGBA", (BASE * SCALE, BASE * SCALE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        w = 5 * SCALE
        s = lambda pts: [(x * SCALE, y * SCALE) for x, y in pts]
        for kind, args in shapes:
            if kind == "rrect":
                x0, y0, x1, y1, r = args
                d.rounded_rectangle([x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE], r * SCALE, outline=rgb, width=w)
            elif kind == "circle":
                cx, cy, r = args
                d.ellipse([(cx - r) * SCALE, (cy - r) * SCALE, (cx + r) * SCALE, (cy + r) * SCALE], outline=rgb, width=w)
            elif kind == "dot":
                cx, cy, r = args
                d.ellipse([(cx - r) * SCALE, (cy - r) * SCALE, (cx + r) * SCALE, (cy + r) * SCALE], fill=rgb)
            elif kind == "arc":
                x0, y0, x1, y1, a0, a1 = args
                d.arc([x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE], a0, a1, fill=rgb, width=w)
            elif kind == "line":  # a polyline with round ends and round corners
                pts = s(args)
                d.line(pts, fill=rgb, width=w, joint="curve")
                for x, y in (pts[0], pts[-1]):
                    d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=rgb)
            elif kind == "poly":  # a closed outline
                pts = s(args)
                d.line(pts + [pts[0]], fill=rgb, width=w, joint="curve")
                for x, y in pts:
                    d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=rgb)
        img.resize((FINAL, FINAL), Image.LANCZOS).save(OUT / "ico" / f"{name}-{tone}.png")


icon("grid", [("rrect", (10, 10, 29, 29, 6)), ("rrect", (35, 10, 54, 29, 6)), ("rrect", (10, 35, 29, 54, 6)), ("rrect", (35, 35, 54, 54, 6))])
icon("doc", [("rrect", (14, 8, 50, 56, 7)), ("line", [(23, 24), (41, 24)]), ("line", [(23, 34), (41, 34)]), ("line", [(23, 44), (33, 44)])])
icon("scan", [("line", [(8, 20), (8, 8), (20, 8)]), ("line", [(44, 8), (56, 8), (56, 20)]), ("line", [(56, 44), (56, 56), (44, 56)]),
              ("line", [(20, 56), (8, 56), (8, 44)]), ("line", [(18, 32), (46, 32)])])
icon("code", [("line", [(24, 18), (10, 32), (24, 46)]), ("line", [(40, 18), (54, 32), (40, 46)])])
icon("people", [("circle", (24, 21, 8)), ("arc", (8, 36, 40, 68, 180, 360)), ("circle", (46, 26, 6)), ("arc", (38, 40, 56, 64, 190, 350))])
icon("clipboard", [("rrect", (14, 12, 50, 58, 7)), ("rrect", (24, 5, 40, 17, 4)), ("line", [(23, 32), (41, 32)]), ("line", [(23, 43), (35, 43)])])
icon("shield", [("poly", [(32, 7), (53, 15), (53, 32), (32, 57), (11, 32), (11, 15)]), ("line", [(23, 31), (30, 38), (42, 25)])])
icon("flag", [("line", [(15, 8), (15, 58)]), ("poly", [(15, 12), (50, 12), (42, 24), (50, 36), (15, 36)])])
icon("pulse", [("line", [(5, 34), (20, 34), (27, 14), (37, 52), (43, 34), (59, 34)])])
icon("clock", [("circle", (32, 32, 23)), ("line", [(32, 18), (32, 32), (42, 38)])])
icon("phone", [("rrect", (19, 6, 45, 58, 7)), ("line", [(28, 49), (36, 49)])])


# ---------------- hero banner: soft moving-colour mesh (the page drifts it slowly) ----------------
def mesh(w, h):
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[:] = (9, 46, 48)
    yy, xx = np.mgrid[0:h, 0:w]
    blobs = [  # centre x, centre y, radius, colour, strength
        (0.16, 0.30, 0.42, (18, 150, 140), 0.95), (0.62, 0.78, 0.40, (36, 98, 190), 0.80),
        (0.86, 0.18, 0.34, (88, 214, 186), 0.75), (0.42, 0.95, 0.22, (224, 164, 84), 0.40),
        (0.50, 0.10, 0.28, (30, 120, 150), 0.60),
    ]
    for cx, cy, r, colour, strength in blobs:
        dist = np.sqrt(((xx - cx * w) / (r * w)) ** 2 + ((yy - cy * h) / (r * w)) ** 2)
        weight = np.clip(1 - dist, 0, 1) ** 2 * strength
        base += weight[..., None] * (np.array(colour, dtype=np.float32) - base) * 0.9
    base += rng.normal(0, 2.2, (h, w, 1)).astype(np.float32)  # a little grain, so it feels printed
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


mesh(2000, 700).filter(ImageFilter.GaussianBlur(2)).save(OUT / "hero-mesh.png", optimize=True)


# ---------------- floating shapes (transparent) ----------------
def orbs(size=760):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    yy, xx = np.mgrid[0:size, 0:size]
    layers = [(0.50, 0.50, 0.34, 0.34), (0.74, 0.32, 0.16, 0.42), (0.30, 0.76, 0.12, 0.46), (0.80, 0.78, 0.07, 0.55)]
    arr = np.zeros((size, size, 4), dtype=np.float32)
    for cx, cy, r, a in layers:
        dist = np.sqrt((xx - cx * size) ** 2 + (yy - cy * size) ** 2) / (r * size)
        fill = np.clip(1 - dist, 0, 1) ** 0.6 * a                      # glassy soft body
        ring = np.exp(-(((dist - 1.0) / 0.018) ** 2)) * 0.8            # thin bright rim
        alpha = np.clip(fill + ring, 0, 1)
        tint = np.array([200, 245, 238], dtype=np.float32) * (0.7 + 0.3 * np.clip(1 - dist, 0, 1)[..., None])
        arr[..., :3] = arr[..., :3] * (1 - alpha[..., None]) + tint * alpha[..., None]
        arr[..., 3] = 1 - (1 - arr[..., 3]) * (1 - alpha)
    img = Image.fromarray((arr * np.array([1, 1, 1, 255])).clip(0, 255).astype(np.uint8), "RGBA") if False else Image.fromarray(
        np.dstack([arr[..., :3], arr[..., 3] * 255]).clip(0, 255).astype(np.uint8), "RGBA")
    return img


orbs().save(OUT / "orbs.png", optimize=True)


# ---------------- logo and favicon ----------------
def logo(path, size, fg, bg=None, pad=0.0):
    S = 8
    img = Image.new("RGBA", (size * S, size * S), bg or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if bg:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, size * S - 1, size * S - 1], size * S * 0.24, fill=bg)
    k = size * S
    m = k * (0.17 + pad)
    w = int(k * 0.075)
    d.ellipse([m, m, k - m, k - m], outline=fg, width=w)
    pts = [(0.28, 0.54), (0.40, 0.54), (0.47, 0.34), (0.57, 0.70), (0.64, 0.54), (0.74, 0.54)]
    pts = [(x * k, y * k) for x, y in pts]
    d.line(pts, fill=fg, width=w, joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=fg)
    img.resize((size, size), Image.LANCZOS).save(path, optimize=True)


logo(OUT / "logo-white.png", 128, (255, 255, 255))
logo(OUT / "favicon.png", 64, (255, 255, 255), bg=(12, 59, 58))


# ---------------- empty-state picture: a stack of cards with a tick ----------------
def empty(path, w=520, h=340):
    S = 2
    img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    cards = [(60, 70, 380, 230, (222, 238, 236, 255)), (90, 50, 410, 210, (190, 224, 220, 255)), (120, 30, 440, 190, (255, 255, 255, 255))]
    for x0, y0, x1, y1, _ in cards:
        sd.rounded_rectangle([x0 * S, (y0 + 14) * S, x1 * S, (y1 + 14) * S], 26 * S, fill=(15, 63, 70, 70))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14 * S)))
    d = ImageDraw.Draw(img)
    for x0, y0, x1, y1, c in cards:
        d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], 26 * S, fill=c, outline=(201, 218, 216, 255), width=S)
    top = cards[-1]
    for i, wd in enumerate((190, 226, 140)):
        d.rounded_rectangle([(top[0] + 84) * S, (top[1] + 42 + i * 34) * S, (top[0] + 84 + wd) * S, (top[1] + 54 + i * 34) * S], 6 * S, fill=(214, 229, 227, 255))
    cx, cy, r = (top[0] + 44) * S, (top[1] + 80) * S, 24 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(10, 124, 115, 255))
    d.line([(cx - 10 * S, cy + S), (cx - 2 * S, cy + 9 * S), (cx + 12 * S, cy - 8 * S)], fill=(255, 255, 255, 255), width=5 * S, joint="curve")
    img.resize((w, h), Image.LANCZOS).save(path, optimize=True)


empty(OUT / "empty-guidance.png")
print("done:", sorted(p.name for p in OUT.rglob("*.png"))[:6], "...", len(list(OUT.rglob('*.png'))), "files")
