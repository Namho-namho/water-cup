#!/usr/bin/env python3
"""팀 공유용 데이터셋 샘플 비교판을 만든다.

    python3 scripts/make_sample.py <out/XXXX 폴더> <출력폴더> <프레임> [<프레임> ...]

각 프레임마다 입력 이미지 4방향과 대응 높이 필드 4장을 위아래로 붙여 짝을 보여준다.
원본 이미지(1280x720)와 npy 도 함께 복사한다.
"""
import argparse, json, os, shutil, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

CAMS = ('e', 'n', 'w', 's')
PREFIX = os.environ.get('LABEL_PREFIX', 'heightA_cup')
RAMP = np.array([[49, 54, 149], [69, 150, 220], [240, 240, 180],
                 [245, 150, 60], [165, 0, 38]], dtype=float)   # 낮음 -> 높음
NAN_RGB = (205, 205, 205)
FONTS = ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
         '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')


def font(sz, bold=False):
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p.replace('Regular', 'Bold') if bold and 'Regular' in p
                                          and os.path.exists(p.replace('Regular', 'Bold')) else p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def ramp(t):
    x = np.linspace(0, 1, len(RAMP))
    return np.stack([np.interp(t, x, RAMP[:, k]) for k in range(3)], axis=-1).astype(np.uint8)


def field_img(hf, vmin, vmax, size):
    """높이 필드 -> 색. 가로=i축, 세로=j축(위쪽이 카메라에서 먼 쪽)."""
    m = ~np.isnan(hf)
    t = np.zeros_like(hf)
    if m.any() and vmax > vmin:
        t[m] = np.clip((hf[m] - vmin) / (vmax - vmin), 0, 1)
    rgb = ramp(t)
    rgb[~m] = NAN_RGB
    im = Image.fromarray(np.transpose(rgb, (1, 0, 2))[::-1], 'RGB')
    return im.resize((size, size), Image.NEAREST)


def crop_water(path, size, zoom=0.62):
    im = Image.open(path).convert('RGB')
    a = np.asarray(im).astype(int)
    ys, xs = np.nonzero(a.sum(2) < 720)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / zoom / 2
    L, T, R, B = int(cx - half), int(cy - half), int(cx + half), int(cy + half)
    cv = Image.new('RGB', (R - L, B - T), (255, 255, 255))
    sx0, sy0, sx1, sy1 = max(L, 0), max(T, 0), min(R, im.width), min(B, im.height)
    cv.paste(im.crop((sx0, sy0, sx1, sy1)), (sx0 - L, sy0 - T))
    return cv.resize((size, size), Image.LANCZOS)


def colorbar(d, x, y, w, h, vmin, vmax, f):
    for k in range(h):
        c = tuple(int(v) for v in ramp(np.array(1 - k / (h - 1)))[()])
        d.line([(x, y + k), (x + w, y + k)], fill=c)
    d.rectangle([x, y, x + w, y + h], outline=(120, 120, 120))
    for frac, lab in ((0.0, f'{vmax*1000:.0f}'), (0.5, f'{(vmin+vmax)/2*1000:.0f}'),
                      (1.0, f'{vmin*1000:.0f}')):
        yy = y + frac * h
        d.line([(x + w, yy), (x + w + 5, yy)], fill=(120, 120, 120))
        d.text((x + w + 9, yy - 8), lab, fill=(0, 0, 0), font=f)
    d.text((x - 4, y - 24), '높이 (mm)', fill=(0, 0, 0), font=f)
    d.rectangle([x, y + h + 16, x + w, y + h + 16 + 18], fill=NAN_RGB, outline=(120, 120, 120))
    d.text((x + w + 9, y + h + 17), 'NaN', fill=(0, 0, 0), font=f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root'); ap.add_argument('out'); ap.add_argument('frames', nargs='+', type=int)
    ap.add_argument('--tags', default='')
    ap.add_argument('--kind', default=''); ap.add_argument('--water', default='')
    ap.add_argument('--name', default='')
    a = ap.parse_args()
    tags = a.tags.split(',') if a.tags else [''] * len(a.frames)
    os.makedirs(f'{a.out}/images', exist_ok=True)
    os.makedirs(f'{a.out}/labels', exist_ok=True)

    meta = None
    mp = f'{a.root}/{PREFIX}_e/label_meta.json'
    if os.path.exists(mp):
        meta = json.load(open(mp))

    CELL, PAD = 300, 14
    F, FB, FS = font(19), font(23), font(15)
    W = PAD * 2 + 4 * CELL + 3 * PAD + 96          # 96 = 컬러바 자리
    head = 132
    blockh = 34 + CELL + 22 + CELL + 26
    H = head + len(a.frames) * (blockh + PAD) + 96
    sheet = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)

    name = a.name or os.path.basename(os.path.normpath(a.root))
    d.text((PAD, 14), f'물컵 데이터셋 샘플 — traj_{name}'
           + (f'  ({a.kind}, 수위 {a.water})' if a.kind else ''), fill=(0, 0, 0), font=FB)
    spec = [
        '입력: 렌더 이미지 1280x720, 컵을 숨기고 흰 배경에 물만 (컵 밖으로 나간 물은 제거)',
        '정답: 높이 필드 32x32 float32, 단위 m, 컵 안바닥 평면 기준, 컵 축 방향 거리. 샘플 반경 27mm 안 616셀이 유효',
        'NaN: 그 자리에 물이 없거나(컵 바닥 노출) 얇은 물보라뿐인 경우. 높이가 높아서 잘리는 일은 없다',
        '격자: 컵 축에 수직인 평면. 평면 안에서 격자가 몇 도 돌지는 카메라 광축의 방위 성분이 정한다',
        '      j축(그림 세로, 위쪽 = 카메라에서 먼 쪽), i축(그림 가로) = j축과 수직. 컵 자기축 회전은 라벨에 안 들어간다',
    ]
    for k, s in enumerate(spec):
        d.text((PAD, 48 + k * 17), s, fill=(70, 70, 70), font=FS)

    y = head
    for fr, tag in zip(a.frames, tags):
        vals = np.concatenate([np.load(f'{a.root}/{PREFIX}_{c}/height_{fr:04d}.npy').ravel()
                               for c in CAMS])
        vals = vals[~np.isnan(vals)]
        vmin, vmax = float(vals.min()), float(vals.max())
        n_ok = int(np.sum(~np.isnan(np.load(f'{a.root}/height_e/height_{fr:04d}.npy'))))
        d.text((PAD, y), f'frame {fr:04d}' + (f'  · {tag}' if tag else '')
               + f'   수면 {vmin*1000:.1f}~{vmax*1000:.1f}mm (폭 {(vmax-vmin)*1000:.1f}mm) · 유효 {n_ok}셀',
               fill=(0, 0, 0), font=F)
        yy = y + 30
        for k, c in enumerate(CAMS):
            x = PAD + k * (CELL + PAD)
            img = f'{a.root}/{c}_{fr:04d}.png'
            sheet.paste(crop_water(img, CELL), (x, yy))
            d.rectangle([x, yy, x + CELL - 1, yy + CELL - 1], outline=(200, 200, 200))
            d.text((x + 6, yy + 5), f'Camera_{c}  입력', fill=(60, 60, 60), font=FS)
            hf = np.load(f'{a.root}/{PREFIX}_{c}/height_{fr:04d}.npy')
            sheet.paste(field_img(hf, vmin, vmax, CELL), (x, yy + CELL + 22))
            d.rectangle([x, yy + CELL + 22, x + CELL - 1, yy + 2 * CELL + 21], outline=(200, 200, 200))
            d.text((x + 6, yy + CELL + 3), f'↓ 같은 프레임의 정답 — 높이 필드 32x32',
                   fill=(90, 90, 90), font=FS)
            # 원본 파일 복사
            shutil.copy(img, f'{a.out}/images/{c}_{fr:04d}.png')
            np.save(f'{a.out}/labels/height_{c}_{fr:04d}.npy', hf)
        colorbar(d, PAD + 4 * (CELL + PAD) + 6, yy + CELL + 46, 26, CELL - 60, vmin, vmax, FS)
        d.text((PAD + 4 * (CELL + PAD) + 6, yy + 8), '↑ 위쪽 =', fill=(90, 90, 90), font=FS)
        d.text((PAD + 4 * (CELL + PAD) + 6, yy + 26), '카메라에서', fill=(90, 90, 90), font=FS)
        d.text((PAD + 4 * (CELL + PAD) + 6, yy + 44), '먼 쪽 (j축)', fill=(90, 90, 90), font=FS)
        y += blockh + PAD

    d.text((PAD, H - 74), '네 방향은 같은 물을 90도씩 돌려 본 것이다. 격자도 카메라를 따라 돌므로 '
           '네 높이 필드는 서로 90도 회전 관계다 (np.rot90 오차 0.00mm).', fill=(70, 70, 70), font=FS)
    d.text((PAD, H - 54), 'images/ 에 원본 1280x720 PNG, labels/ 에 npy 원본이 들어 있다.',
           fill=(70, 70, 70), font=FS)
    if meta:
        d.text((PAD, H - 34), f"라벨 설정: label_frame={meta.get('label_frame')} "
               f"grid_plane={meta.get('grid_plane')} cam_azim={meta.get('cam_azim')}",
               fill=(120, 120, 120), font=FS)
    p = f'{a.out}/sample_sheet.png'
    sheet.save(p)
    print(f'저장: {p} ({W}x{H})')


if __name__ == '__main__':
    main()
