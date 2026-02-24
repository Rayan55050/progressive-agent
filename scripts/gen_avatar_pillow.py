"""Generate a robot face avatar for TTS video circles.

Creates a digital robot face with:
- Glowing cyan eyes
- Clear mouth area (where audio waveform will be overlaid)
- Dark futuristic background
- Circuit-pattern decorations
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def create_avatar(size: int = 384, output: str = "data/avatar.png") -> None:
    """Create a robot face avatar optimized for animated video circles.

    The mouth area (bottom third) is kept dark/clean so the FFmpeg
    showwaves filter can overlay audio visualization there.
    """
    img = Image.new("RGBA", (size, size), (5, 5, 20, 255))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2

    # === Background: radial dark gradient ===
    for r in range(size // 2, 0, -1):
        t = r / (size // 2)
        cr = int(5 + 10 * (1 - t))
        cg = int(5 + 18 * (1 - t))
        cb = int(20 + 35 * (1 - t))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(cr, cg, cb, 255))

    # === Head outline: glowing oval ===
    head_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hd = ImageDraw.Draw(head_layer)

    head_rx, head_ry = 140, 155  # slightly taller than wide
    head_cx, head_cy = cx, cy - 5

    # Outer glow
    for i in range(20, 0, -1):
        alpha = int(15 * (1 - i / 20))
        hd.ellipse(
            [head_cx - head_rx - i, head_cy - head_ry - i,
             head_cx + head_rx + i, head_cy + head_ry + i],
            outline=(0, 140, 220, alpha), width=2,
        )

    # Head fill (very dark)
    hd.ellipse(
        [head_cx - head_rx, head_cy - head_ry,
         head_cx + head_rx, head_cy + head_ry],
        fill=(8, 12, 28, 240),
    )

    # Head border
    hd.ellipse(
        [head_cx - head_rx, head_cy - head_ry,
         head_cx + head_rx, head_cy + head_ry],
        outline=(0, 180, 255, 160), width=2,
    )

    img = Image.alpha_composite(img, head_layer)

    # === Eyes: two glowing circles ===
    eye_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ed = ImageDraw.Draw(eye_layer)

    eye_y = cy - 40
    eye_spacing = 55
    eye_r = 28

    for ex in [cx - eye_spacing, cx + eye_spacing]:
        # Eye glow
        for i in range(15, 0, -1):
            alpha = int(40 * (1 - i / 15))
            ed.ellipse(
                [ex - eye_r - i, eye_y - eye_r - i,
                 ex + eye_r + i, eye_y + eye_r + i],
                fill=(0, 180, 255, alpha),
            )

        # Eye socket (dark)
        ed.ellipse(
            [ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r],
            fill=(0, 40, 80, 255),
        )

        # Pupil (bright cyan)
        pupil_r = 18
        ed.ellipse(
            [ex - pupil_r, eye_y - pupil_r, ex + pupil_r, eye_y + pupil_r],
            fill=(0, 200, 255, 220),
        )

        # Pupil inner (white highlight)
        hi_r = 6
        hi_x, hi_y = ex - 5, eye_y - 5
        ed.ellipse(
            [hi_x - hi_r, hi_y - hi_r, hi_x + hi_r, hi_y + hi_r],
            fill=(200, 240, 255, 180),
        )

    img = Image.alpha_composite(img, eye_layer)

    # === Nose: small vertical line ===
    nose_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    nd = ImageDraw.Draw(nose_layer)
    nd.line([(cx, cy + 5), (cx, cy + 25)], fill=(0, 140, 200, 60), width=2)
    nd.ellipse([cx - 3, cy + 22, cx + 3, cy + 28], fill=(0, 160, 220, 50))
    img = Image.alpha_composite(img, nose_layer)

    # === Mouth area: horizontal bar where waveform will go ===
    mouth_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    md = ImageDraw.Draw(mouth_layer)

    mouth_y = cy + 55
    mouth_w = 100
    mouth_h = 12

    # Mouth background (dark slot)
    md.rounded_rectangle(
        [cx - mouth_w, mouth_y - mouth_h, cx + mouth_w, mouth_y + mouth_h],
        radius=mouth_h,
        fill=(0, 20, 40, 200),
        outline=(0, 120, 180, 100),
        width=1,
    )

    # Subtle "resting" line in the mouth (will be covered by waveform in video)
    md.line(
        [(cx - mouth_w + 15, mouth_y), (cx + mouth_w - 15, mouth_y)],
        fill=(0, 160, 220, 80),
        width=2,
    )

    img = Image.alpha_composite(img, mouth_layer)

    # === Forehead decorations ===
    deco_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco_layer)

    # Horizontal line across forehead
    forehead_y = cy - 85
    dd.line(
        [(cx - 80, forehead_y), (cx + 80, forehead_y)],
        fill=(0, 160, 220, 50), width=1,
    )

    # Small dots
    for x_off in [-60, -30, 0, 30, 60]:
        dd.ellipse(
            [cx + x_off - 2, forehead_y - 2, cx + x_off + 2, forehead_y + 2],
            fill=(0, 200, 255, 60),
        )

    # Side lines (cheek circuits)
    for side in [-1, 1]:
        sx = cx + side * 95
        for y_off in [-20, 0, 20]:
            dd.line(
                [(sx, cy + y_off), (sx + side * 20, cy + y_off)],
                fill=(0, 140, 200, 30), width=1,
            )

    # Chin detail
    chin_y = cy + 90
    dd.line(
        [(cx - 40, chin_y), (cx + 40, chin_y)],
        fill=(0, 140, 200, 40), width=1,
    )
    dd.ellipse([cx - 3, chin_y - 3, cx + 3, chin_y + 3], fill=(0, 180, 255, 50))

    # Antenna
    ant_y = cy - head_ry - 5
    dd.line([(cx, ant_y), (cx, ant_y - 30)], fill=(0, 160, 220, 80), width=2)
    dd.ellipse(
        [cx - 5, ant_y - 35, cx + 5, ant_y - 25],
        fill=(0, 220, 255, 150),
    )
    # Antenna glow
    for r in range(12, 0, -1):
        alpha = int(25 * (1 - r / 12))
        dd.ellipse(
            [cx - r, ant_y - 35 + 5 - r, cx + r, ant_y - 25 - 5 + r],
            fill=(0, 200, 255, alpha),
        )

    img = Image.alpha_composite(img, deco_layer)

    # === Final touches: slight smoothing ===
    final = img.filter(ImageFilter.SMOOTH_MORE)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    final.convert("RGB").save(str(out), "PNG")
    print(f"Robot avatar saved: {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    create_avatar()
