"""Draw the Hype Toolkit app icon (dark rounded square, a white bold "H" and a gold full stop, like the website's
"Title." headings) -> assets/icon.ico (16-256 px) + assets/icon.png (512 px). Needs Pillow:  python tools/make_icon.py"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'assets')
FONTS = [r'C:\Windows\Fonts\segoeuib.ttf', r'C:\Windows\Fonts\arialbd.ttf', '/System/Library/Fonts/Helvetica.ttc',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']


def draw(size):
    s = size * 4                                       # draw big, scale down for smooth edges
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(s * 0.225)
    top, bottom = (40, 42, 50), (14, 15, 18)
    for y in range(s):                                 # soft vertical gradient
        t = y / s
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,)
        d.line([(0, y), (s, y)], fill=c)
    mask = Image.new('L', (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], r, fill=255)
    im.putalpha(mask)
    font = ImageFont.truetype(next(f for f in FONTS if os.path.exists(f)), int(s * 0.62))
    box = d.textbbox((0, 0), 'H', font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    dot = int(s * 0.115)
    x = (s - w - dot * 1.25) / 2 - box[0]
    y = (s - h) / 2 - box[1]
    d.text((x, y), 'H', font=font, fill=(245, 245, 247, 255))
    dx, dy = x + box[2] + dot * 0.25, y + box[3] - dot
    d.ellipse([dx, dy, dx + dot, dy + dot], fill=(245, 185, 66, 255))
    return im.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    big = draw(512)
    big.save(os.path.join(OUT, 'icon.png'))
    draw(256).save(os.path.join(OUT, 'icon.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('assets/icon.ico + icon.png')
