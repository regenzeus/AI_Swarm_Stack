"""App icons (build stage only): a dark tile with a radar ring and an orbiting dot. python icons.py <outdir>"""
import math, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def tile(full_bleed):
    img = Image.new("RGB", (S, S))
    px = img.load()
    for y in range(S):                          # deep navy, lighter toward the top left
        for x in range(0, S, 4):
            c = lerp((24, 30, 48), (8, 10, 18), min(1, (x + y) / (1.6 * S)))
            for k in range(4):
                px[x + k, y] = c
    d = ImageDraw.Draw(img)
    cx = cy = S // 2
    r = int(S * (0.30 if full_bleed else 0.34))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for i in range(360):                        # ring with a teal -> violet sweep
        a0, t = math.radians(i - 90), i / 360
        col = lerp((45, 212, 191), (139, 92, 246), t) + (255,)
        g.arc([cx - r, cy - r, cx + r, cy + r], i - 90, i - 89 + 1.5, fill=col, width=int(S * 0.045))
    glow_blur = glow.filter(ImageFilter.GaussianBlur(S * 0.02))
    img.paste(glow_blur, (0, 0), glow_blur)
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img)
    r2 = int(r * 0.55)
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=(148, 163, 184), width=int(S * 0.012))
    a = math.radians(-35)                        # the orbiting dot
    ox, oy = cx + r * math.cos(a), cy + r * math.sin(a)
    rd = S * 0.055
    d.ellipse([ox - rd, oy - rd, ox + rd, oy + rd], fill=(255, 255, 255))
    rc = S * 0.05
    d.ellipse([cx - rc, cy - rc, cx + rc, cy + rc], fill=(45, 212, 191))
    return img


for name, size, bleed in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                          ("maskable-512.png", 512, True), ("apple-touch-icon.png", 180, True)):
    tile(bleed).resize((size, size), Image.LANCZOS).save(out / name, optimize=True)
print("icons written")
