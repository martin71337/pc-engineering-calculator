"""Draws the app icon (calculator/assets/calculator.ico and .png).  Run:  py -3.14 tools/make_icon.py"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "calculator", "assets")
S = 1024  # draw large, then downsample for crisp small sizes

BODY = (31, 59, 99)        # navy
BODY_EDGE = (20, 40, 70)
SCREEN = (214, 236, 214)   # LCD green
SCREEN_TEXT = (24, 60, 40)
KEY = (232, 238, 246)
KEY_DARK = (122, 146, 178)
ACCENT = (240, 140, 30)    # orange "=" key


def font(size, bold=True):
    for name in (("consolab.ttf", "seguisb.ttf", "arialbd.ttf") if bold else ("consola.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(simple: bool = False) -> Image.Image:
    """simple=True leaves out the text, which turns to noise at 16-48 px."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 70
    # Shadow, body
    d.rounded_rectangle((m + 18, m + 26, S - m + 18, S - m + 26), radius=120, fill=(0, 0, 0, 70))
    d.rounded_rectangle((m, m, S - m, S - m), radius=120, fill=BODY, outline=BODY_EDGE, width=14)
    # Display
    sx0, sy0, sx1, sy1 = m + 70, m + 80, S - m - 70, m + 330
    d.rounded_rectangle((sx0, sy0, sx1, sy1), radius=40, fill=SCREEN, outline=(150, 180, 150), width=8)
    f = font(170)
    text = "" if simple else "x=?"
    tw = d.textlength(text, font=f)
    d.text((sx1 - 40 - tw, (sy0 + sy1) / 2), text, font=f, fill=SCREEN_TEXT, anchor="lm")
    # Keys: 3 x 3 grid, bottom-right key is the orange "="
    labels = [["7", "8", "÷"], ["4", "5", "×"], ["√", "x²", "="]]
    gx0, gy0, gx1, gy1 = m + 70, m + 390, S - m - 70, S - m - 70
    gap = 34
    kw = (gx1 - gx0 - 2 * gap) / 3
    kh = (gy1 - gy0 - 2 * gap) / 3
    kf = font(120)
    for r in range(3):
        for c in range(3):
            x0 = gx0 + c * (kw + gap)
            y0 = gy0 + r * (kh + gap)
            is_eq = labels[r][c] == "="
            fill = ACCENT if is_eq else (KEY if c < 2 else KEY_DARK)
            d.rounded_rectangle((x0, y0, x0 + kw, y0 + kh), radius=30, fill=fill)
            color = (255, 255, 255) if is_eq or c == 2 else BODY
            if not simple:
                d.text((x0 + kw / 2, y0 + kh / 2), labels[r][c], font=kf, fill=color, anchor="mm")
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "calculator.png"))
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    small = draw(simple=True)
    frames = [(small if w <= 48 else big).resize((w, h), Image.LANCZOS) for w, h in sizes]
    frames[-1].save(os.path.join(OUT, "calculator.ico"), sizes=sizes, append_images=frames[:-1])
    print("wrote", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
