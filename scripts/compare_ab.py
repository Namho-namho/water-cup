#!/usr/bin/env python3
"""같은 프레임을 버전 A / B 높이 필드로 나란히 그린다.

    python3 scripts/compare_ab.py <out/XXXX 폴더> <프레임> <출력.png> [--cam e]

A : 격자 = 컵 축에 수직인 평면, 높이 = 컵 안바닥 기준 (heightA_cup_*)
B : 격자 = 월드 수평면, 높이 = 바닥(z=0) 기준 절대 높이 (heightB_world_*)
두 필드를 같은 mm 축척으로 그려서 격자 범위 차이가 눈에 보이게 한다.
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

RAMP = np.array([[49, 54, 149], [69, 150, 220], [240, 240, 180],
                 [245, 150, 60], [165, 0, 38]], dtype=float)
FONTS = ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
PXMM = 4.2          # 1mm 를 몇 픽셀로 그릴지 (A와 B에 같은 축척을 쓴다)


def font(sz):
    for p in FONTS:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
    return ImageFont.load_default()


def ramp(t):
    x = np.linspace(0, 1, len(RAMP))
    return np.stack([np.interp(t, x, RAMP[:, k]) for k in range(3)], axis=-1).astype(np.uint8)


def draw_field(hf, grid_r, vmin, vmax):
    """hf 는 m 단위, vmin/vmax 는 mm 단위다."""
    v = hf * 1000.0
    m = ~np.isnan(v)
    t = np.zeros_like(v)
    if m.any() and vmax > vmin:
        t[m] = np.clip((v[m] - vmin) / (vmax - vmin), 0, 1)
    rgb = ramp(t); rgb[~m] = (215, 215, 215)
    im = Image.fromarray(np.transpose(rgb, (1, 0, 2))[::-1], 'RGB')
    px = int(round(grid_r * 2000 * PXMM))
    return im.resize((px, px), Image.NEAREST)


def colorbar(d, x, y, w, h, vmin, vmax, f, title):
    for k in range(h):
        d.line([(x, y + k), (x + w, y + k)],
               fill=tuple(int(v) for v in ramp(np.array(1 - k / (h - 1)))[()]))
    d.rectangle([x, y, x + w, y + h], outline=(120, 120, 120))
    for frac, lab in ((0.0, f'{vmax:.0f}'), (0.5, f'{(vmin+vmax)/2:.0f}'), (1.0, f'{vmin:.0f}')):
        d.text((x + w + 6, y + frac * h - 8), lab, fill=(0, 0, 0), font=f)
    d.text((x - 2, y - 20), title, fill=(0, 0, 0), font=f)


def main():
    root, fr, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    cam = 'e'
    for x in sys.argv[4:]:
        if x.startswith('--cam'): cam = x.split('=')[-1]
    F, FB, FS = font(19), font(23), font(14)
    panes = []
    for pref, name in (('heightA_cup', 'A'), ('heightB_world', 'B')):
        hf = np.load(f'{root}/{pref}_{cam}/height_{fr:04d}.npy')
        meta = json.load(open(f'{root}/{pref}_{cam}/label_meta.json'))
        v = hf[~np.isnan(hf)] * 1000
        # 색 범위는 2~98 백분위. 가장자리 얇은 물 한두 셀이 전체 범위를 잡아먹어
        # 구조가 안 보이는 것을 막는다.
        lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
        panes.append(dict(name=name, hf=hf, meta=meta, gr=meta['grid_r'],
                          vmin=lo, vmax=hi, lo=float(v.min()), hi=float(v.max()),
                          n=int(v.size)))
    W, H = 40 + sum(int(p['gr'] * 2000 * PXMM) + 165 for p in panes), 0
    imgs = [draw_field(p['hf'], p['gr'], p['vmin'], p['vmax']) for p in panes]
    H = 168 + max(i.height for i in imgs)
    sheet = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((20, 14), f'{os.path.basename(os.path.normpath(root))}  frame {fr:04d}  '
           f'Camera_{cam} — 높이 필드 버전 A / B 비교 (같은 축척, 1mm = {PXMM}px)',
           fill=(0, 0, 0), font=FB)
    x = 20
    for p, im in zip(panes, imgs):
        gr = p['gr'] * 1000
        d.text((x, 52), f"버전 {p['name']}  {p['hf'].shape[0]}x{p['hf'].shape[1]}  "
               f"격자 ±{gr:.0f}mm  유효 {p['n']}셀", fill=(0, 0, 0), font=F)
        # 설명이 옆 칸을 침범하지 않게 두 줄로 나눈다
        bs = p['meta']['basis']
        cut = bs.find(', 높이=')
        d.text((x, 74), bs[:cut] if cut > 0 else bs, fill=(80, 80, 80), font=FS)
        if cut > 0:
            d.text((x, 90), bs[cut+2:], fill=(80, 80, 80), font=FS)
        d.text((x, 106), f"값 {p['lo']:.1f}~{p['hi']:.1f}mm  (색은 2~98 백분위 "
               f"{p['vmin']:.1f}~{p['vmax']:.1f}mm)", fill=(80, 80, 80), font=FS)
        sheet.paste(im, (x, 128))
        d.rectangle([x, 128, x + im.width - 1, 128 + im.height - 1], outline=(150, 150, 150))
        # 컵 안반경 28mm 원 표시
        cx, cy = x + im.width / 2, 128 + im.height / 2
        r = 28 * PXMM
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0))
        d.text((x + 6, 128 + im.height - 20), '검은 원 = 컵 안반경 28mm',
               fill=(0, 0, 0), font=FS)
        colorbar(d, x + im.width + 22, 154, 22, im.height - 60,
                 p['vmin'], p['vmax'], FS, '높이(mm)')
        x += im.width + 165
    d.text((20, H - 24), 'A는 컵과 함께 기우는 평면에서 잰 값이라 컵 단면을 꽉 채운다. '
           'B는 위에서 수직으로 본 것이라 컵이 기울수록 물의 수평 단면이 넓게 퍼진다.',
           fill=(70, 70, 70), font=FS)
    sheet.save(out)
    print(f'저장: {out} ({W}x{H})')


if __name__ == '__main__':
    main()
