"""
Makes the extra sizes of the landing-page backgrounds in public/art/backgrounds/.

  portrait/<slug>.jpg  the middle strip of <slug>.jpg at full height, 3:4. An upright
                       phone or tablet shows only that strip of the picture anyway
                       (background-size: cover, centred), so it looks the same and the
                       phone decodes about a third of the pixels.
  xl/<slug>.jpg        up to 3840px wide, for screens wider than the 2200px file. Made
                       only from a press-kit original passed with --originals that is
                       at least 3000px wide (kept at its own width below 3840); nothing
                       is ever upscaled.

Same encoding as the main files: JPEG quality 72, progressive.

Usage (from the repo root):
  python frontend/scripts/make-background-sizes.py                     # portrait crops
  python frontend/scripts/make-background-sizes.py --originals DIR     # + xl from DIR/<slug>.<jpg|png|webp>
"""
import argparse
import os
import sys

from PIL import Image

# press-kit key art can be huge (Against the Void is 13500x9300)
Image.MAX_IMAGE_PIXELS = None

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'public', 'art', 'backgrounds')
PORTRAIT = 3 / 4
XL_WIDTH = 3840
XL_MIN = 3000


def save(im, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.convert('RGB').save(path, 'JPEG', quality=72, progressive=True, optimize=True)


def portrait(slug):
    im = Image.open(os.path.join(ROOT, f'{slug}.jpg'))
    w, h = im.size
    cw = min(w, round(h * PORTRAIT))
    left = (w - cw) // 2
    save(im.crop((left, 0, left + cw, h)), os.path.join(ROOT, 'portrait', f'{slug}.jpg'))
    return f'{cw}x{h}'


def xl(slug, originals):
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        src = os.path.join(originals, f'{slug}.{ext}')
        if os.path.exists(src):
            break
    else:
        return 'no original'
    im = Image.open(src)
    w, h = im.size
    if w < XL_MIN:
        return f'original only {w}px wide, skipped'
    if w > XL_WIDTH:
        im = im.resize((XL_WIDTH, round(h * XL_WIDTH / w)), Image.LANCZOS)
    save(im, os.path.join(ROOT, 'xl', f'{slug}.jpg'))
    return f'{im.size[0]}x{im.size[1]}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--originals', help='folder of full-size press-kit files named <slug>.<ext>')
    args = ap.parse_args()
    slugs = sorted(f[:-4] for f in os.listdir(ROOT) if f.endswith('.jpg'))
    if not slugs:
        sys.exit(f'no backgrounds in {ROOT}')
    for slug in slugs:
        line = f'{slug}: portrait {portrait(slug)}'
        if args.originals:
            line += f', xl {xl(slug, args.originals)}'
        print(line)


if __name__ == '__main__':
    main()
