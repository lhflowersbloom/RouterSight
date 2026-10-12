# -*- coding: utf-8 -*-
'''Generate the RouterSight icon: a simple black-on-white download badge.

Monochrome by design — white rounded badge + solid black arrow and bar — so it
stays legible on both a dark and a light Windows taskbar.

Run with the DSH host python (Pillow available):
    python mod\make_icon.py
Outputs: mod\assets\logo.png (256px), mod\assets\logo.ico (16..256 multi-size)
         mod\assets\arrow_{up,down}_{dark,light}.png
'''
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'assets')
S = 1024

WHITE = (255, 255, 255, 255)
BLACK = (17, 17, 17, 255)


def _rounded_mask(size, radius):
    m = Image.new('L', (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def build(size=S):
    k = size / float(S)
    px = lambda v: max(1, int(round(v * k)))

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # white rounded badge with a hairline black edge
    edge = px(S * 0.008)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=px(S * 0.225), fill=BLACK)
    inset = edge
    d.rounded_rectangle([inset, inset, size - 1 - inset, size - 1 - inset],
                        radius=px(S * 0.225) - inset, fill=WHITE)

    # solid black download arrow: shaft + head
    w = px(S * 0.130)
    y0, y1, y2 = px(S * 0.180), px(S * 0.455), px(S * 0.700)
    h = px(S * 0.265)
    cx = size // 2
    d.polygon([(cx - w // 2, y0), (cx + w // 2, y0), (cx + w // 2, y1),
               (cx + h, y1), (cx, y2), (cx - h, y1), (cx - w // 2, y1)], fill=BLACK)

    # solid black bar under the arrow
    by0, by1 = px(S * 0.790), px(S * 0.860)
    d.rounded_rectangle([px(S * 0.255), by0, size - 1 - px(S * 0.255), by1],
                        radius=(by1 - by0) // 2, fill=BLACK)
    return img


def make_arrows():
    '''Tiny chevron PNGs for QComboBox/QSpinBox stylesheet arrows.

    Qt stylesheets cannot draw CSS border triangles, so the arrows must be
    real images (shipped next to logo.ico and referenced from the stylesheet).
    '''
    for theme, color in (('dark', (139, 147, 167)), ('light', (107, 114, 128))):
        for name, up in (('up', True), ('down', False)):
            W, H, SS = 10, 6, 6
            img = Image.new('RGBA', (W * SS, H * SS), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            if up:
                pts = [(0, H), (W // 2, 0), (W, H)]
            else:
                pts = [(0, 0), (W // 2, H), (W, 0)]
            d.polygon([(x * SS, y * SS) for x, y in pts], fill=color + (255,))
            out = os.path.join(OUT, 'arrow_%s_%s.png' % (name, theme))
            img.resize((W, H), Image.LANCZOS).save(out)
            print('arrow', out, os.path.getsize(out))


def make_sheet():
    '''Contact sheet so the small sizes can be eyeballed (not shipped).'''
    sizes = [16, 20, 24, 32, 48, 64, 128, 256]
    pad = 10
    W = sum(sizes) + pad * (len(sizes) + 1)
    H = max(sizes) + pad * 2
    sheet = Image.new('RGB', (W, H), (245, 245, 245))
    x = pad
    for s in sizes:
        sheet.paste(build(S).resize((s, s), Image.LANCZOS), (x, (H - s) // 2), build(S).resize((s, s), Image.LANCZOS))
        x += s + pad
    out = os.path.join(HERE, 'icon_sheet_new.png')
    sheet.save(out)
    print('sheet', out, os.path.getsize(out))


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    big = build(S)
    png = os.path.join(OUT, 'logo.png')
    big.resize((256, 256), Image.LANCZOS).save(png)
    ico = os.path.join(OUT, 'logo.ico')
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [big.resize((s, s), Image.LANCZOS) for s in sizes]
    frames[-1].save(ico, format='ICO', sizes=[(s, s) for s in sizes])
    print('png', png, os.path.getsize(png))
    print('ico', ico, os.path.getsize(ico))
    make_arrows()
    make_sheet()


if __name__ == '__main__':
    main()
