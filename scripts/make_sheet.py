#!/usr/bin/env python3
"""프레임별로 4방향 이미지와 대응 높이 필드를 한 장으로 합친다.

    python3 scripts/make_sheet.py <out/XXXX 폴더> <출력.png> [프레임 ...]

프레임을 안 주면 잔잔한 프레임 / 수면이 가장 기운 프레임 / 물이 가장 튄 프레임을
라벨에서 자동으로 고른다.

폴더 구조는 배치 잡 결과 그대로다.
    <폴더>/{e,n,w,s}_XXXX.png
    <폴더>/height_{e,n,w,s}/height_XXXX.npy
"""
import glob
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CAMS = ('e', 'n', 'w', 's')
# 라벨 폴더 접두어. heightA_cup=버전 A, heightB_world=버전 B, height=예전 데이터
PREFIX = os.environ.get('LABEL_PREFIX', 'heightA_cup')
CELL = 320          # 한 칸 크기(px)
PAD = 8
LABEL_H = 30

_FONTS = ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
          '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
          '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')


def font(size):
    """한글이 나오는 글꼴을 찾는다. 없으면 기본 글꼴."""
    for p in _FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


F_BIG, F_SMALL = font(20), font(14)


def load_labels(root, cam):
    out = {}
    for f in sorted(glob.glob(os.path.join(root, f'{PREFIX}_{cam}', 'height_*.npy'))):
        out[int(os.path.basename(f)[7:11])] = f
    return out


def pick_frames(root):
    """잔잔 / 크게 기움 / 튐 프레임을 라벨 통계로 고른다."""
    lab = load_labels(root, 'e')
    idx = sorted(lab)
    spread, valid = {}, {}
    for i in idx:
        a = np.load(lab[i])
        v = a[~np.isnan(a)]
        spread[i] = (v.max() - v.min()) if v.size else 0.0
        valid[i] = v.size
    calm = min(idx, key=lambda i: spread[i])
    tilt = max(idx, key=lambda i: spread[i])
    # 물이 튄 프레임: 유효 셀이 가장 적은(=광선이 수면을 못 찾은) 프레임.
    # 다 616이면 기울기 폭 2등을 쓴다.
    splash = min(idx, key=lambda i: (valid[i], -spread[i]))
    tag = '튐 (유효셀 최소)'
    if valid[splash] == max(valid.values()):
        # 유효셀이 다 차 있으면 튄 프레임이 없는 궤적이다. 기울기 2등을 대신 쓴다
        splash = sorted(idx, key=lambda i: -spread[i])[1]
        tag = '기움 2위 (튄 프레임 없음)'
    return [(calm, '잔잔'), (tilt, '크게 기움'), (splash, tag)]


# 낮음 -> 높음 (RdYlBu 뒤집기). 파랑=낮음, 빨강=높음
_RAMP = np.array([[49, 54, 149], [69, 150, 220], [240, 240, 180],
                  [245, 150, 60], [165, 0, 38]], dtype=float)


def field_image(path, vmin, vmax, size=CELL):
    """높이 필드를 색으로. NaN은 회색."""
    a = np.load(path)
    m = ~np.isnan(a)
    t = np.zeros_like(a)
    if m.any() and vmax > vmin:
        t[m] = np.clip((a[m] - vmin) / (vmax - vmin), 0, 1)
    x = np.linspace(0, 1, len(_RAMP))
    rgb = np.stack([np.interp(t, x, _RAMP[:, k]) for k in range(3)], axis=-1)
    rgb = rgb.astype(np.uint8)
    rgb[~m] = (205, 205, 205)
    # 각 카메라에서 내려다본 방향으로 눕힌다: 가로=i축, 세로=j축(위쪽이 카메라에서 먼 쪽)
    im = Image.fromarray(np.transpose(rgb, (1, 0, 2))[::-1], 'RGB')
    return im.resize((size, size), Image.NEAREST)


def crop_water(path, size=CELL):
    """물이 있는 부분만 정사각형으로 잘라 키운다. 화면 밖은 흰색으로 채운다."""
    im = Image.open(path).convert('RGB')
    a = np.asarray(im).astype(int)
    ink = a.sum(2) < 720                      # 흰 배경이 아닌 픽셀
    ys, xs = np.nonzero(ink)
    if len(ys) < 10:
        s = min(im.size)
        return im.crop((0, 0, s, s)).resize((size, size), Image.LANCZOS)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) * 0.75 + 20
    L, T = int(cx - half), int(cy - half)
    R, B = int(cx + half), int(cy + half)
    canvas = Image.new('RGB', (R - L, B - T), (255, 255, 255))
    sx0, sy0 = max(L, 0), max(T, 0)
    sx1, sy1 = min(R, im.width), min(B, im.height)
    if sx1 > sx0 and sy1 > sy0:
        canvas.paste(im.crop((sx0, sy0, sx1, sy1)), (sx0 - L, sy0 - T))
    return canvas.resize((size, size), Image.LANCZOS)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    root, out_path = sys.argv[1], sys.argv[2]
    frames = ([(int(x), '') for x in sys.argv[3:]] if len(sys.argv) > 3
              else pick_frames(root))

    cams = [c for c in CAMS if os.path.isdir(os.path.join(root, f'{PREFIX}_{c}'))]
    # 색 기준은 프레임마다 그 프레임의 최소~최대로 잡는다. 네 방향은 같은 기준을 쓰므로
    # 방향끼리는 그대로 비교되고, 잔잔한 프레임에서도 구조가 보인다.
    rng = {}
    for i, _ in frames:
        vals = []
        for c in cams:
            a = np.load(os.path.join(root, f'{PREFIX}_{c}', f'height_{i:04d}.npy'))
            vals.append(a[~np.isnan(a)])
        vals = np.concatenate([v for v in vals if v.size])
        rng[i] = (float(vals.min()), float(vals.max()))

    ncol = len(cams)
    W = PAD + ncol * (CELL + PAD)
    rowh = LABEL_H + 2 * CELL + PAD
    H = PAD + len(frames) * (rowh + PAD) + 24
    sheet = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)

    y = PAD
    for i, tag in frames:
        vmin, vmax = rng[i]
        d.text((PAD, y + 6),
               f'frame {i:04d}  {tag}   색 범위 {vmin*1000:.1f}~{vmax*1000:.1f}mm',
               fill=(0, 0, 0), font=F_BIG)
        y += LABEL_H
        for k, c in enumerate(cams):
            x = PAD + k * (CELL + PAD)
            img = os.path.join(root, f'{c}_{i:04d}.png')
            if os.path.exists(img):
                sheet.paste(crop_water(img), (x, y))
            d.text((x + 4, y + 4), f'Camera_{c}', fill=(90, 90, 90), font=F_SMALL)
            hf = os.path.join(root, f'{PREFIX}_{c}', f'height_{i:04d}.npy')
            if os.path.exists(hf):
                sheet.paste(field_image(hf, vmin, vmax), (x, y + CELL))
                a = np.load(hf)
                v = a[~np.isnan(a)]
                s = (f'유효 {v.size}  평균 {v.mean()*1000:.1f}  '
                     f'폭 {(v.max()-v.min())*1000:.1f}mm' if v.size else '유효 0')
                d.text((x + 4, y + 2 * CELL - 18), s, fill=(255, 255, 255), font=F_SMALL)
        y += 2 * CELL + PAD * 2
    d.text((PAD, H - 18),
           '위=WATER_ONLY 렌더, 아래=높이 필드(파랑 낮음 -> 빨강 높음, 회색=NaN). '
           '색 범위는 프레임마다 그 프레임의 최소~최대. '
           '필드는 각 카메라에서 내려다본 방향으로 그렸다: 위쪽=카메라에서 먼 쪽(j축), 가로=i축',
           fill=(0, 0, 0), font=F_SMALL)
    sheet.save(out_path)
    print(f'저장: {out_path}  ({W}x{H})  프레임 {[i for i,_ in frames]}')


if __name__ == '__main__':
    main()
