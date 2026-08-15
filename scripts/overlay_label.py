#!/usr/bin/env python3
"""렌더 이미지 위에 라벨 격자를 겹쳐 그린다. 이미지의 물 영역과 라벨 유효 영역이
맞는지 눈으로 확인하는 용도.

1) 카메라 정보를 한 번 뽑는다 (Blender 필요)

    blender -b water_scene_final.blend --python scripts/overlay_label.py -- \\
        --dump-cams /tmp/cams.json

2) 겹쳐 그린다 (Blender 불필요)

    python3 scripts/overlay_label.py <out/XXXX 폴더> <cams.json> <메시폴더> \\
        <프레임> [출력.png] [--cams e,n]

초록 점 = 라벨이 값을 가진 격자점(수면 위치에 찍는다)
빨강 점 = NaN 격자점(컵 테두리 높이에 찍는다. 물이 없거나 못 잡은 자리)
"""
import json
import os
import sys

import numpy as np


def dump_cams(path):
    """Blender 안에서 카메라별 view/projection 행렬을 저장한다."""
    import bpy
    sc = bpy.context.scene
    deps = bpy.context.evaluated_depsgraph_get()
    rx = int(sc.render.resolution_x * sc.render.resolution_percentage / 100)
    ry = int(sc.render.resolution_y * sc.render.resolution_percentage / 100)
    out = {'res': [rx, ry], 'cams': {}}
    for o in bpy.data.objects:
        if o.type != 'CAMERA':
            continue
        e = o.evaluated_get(deps)
        out['cams'][o.name] = {
            'view': [list(r) for r in e.matrix_world.inverted()],
            'proj': [list(r) for r in e.calc_matrix_camera(deps, x=rx, y=ry)],
        }
    json.dump(out, open(path, 'w'))
    print(f'카메라 {len(out["cams"])}개 저장: {path}')


def project(pts, cam, res):
    """월드 좌표 -> 픽셀 좌표. 카메라 뒤쪽 점은 NaN."""
    V = np.array(cam['view'], dtype=float)
    P = np.array(cam['proj'], dtype=float)
    h = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
    c = h @ V.T
    n = c @ P.T
    w = n[:, 3]
    ok = w > 1e-9
    x = np.full(len(pts), np.nan)
    y = np.full(len(pts), np.nan)
    x[ok] = (n[ok, 0] / w[ok] * 0.5 + 0.5) * res[0]
    y[ok] = (1.0 - (n[ok, 1] / w[ok] * 0.5 + 0.5)) * res[1]
    return np.stack([x, y], axis=1)


def quat_m(q):
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-w*z),   2*(x*z+w*y)],
                     [2*(x*y+w*z),   1-2*(x*x+z*z), 2*(y*z-w*x)],
                     [2*(x*z-w*y),   2*(y*z+w*x),   1-2*(x*x+y*y)]])


def grid_points(meta, pose, cam_view, hf):
    """격자점의 월드 좌표. NaN 셀은 컵 테두리 높이에 둔다."""
    R = quat_m(pose[3:7])
    up = R @ np.array([0.0, 0.0, 1.0])
    base = np.array(pose[:3]) + up * meta['cup_bottom_t']
    # 격자 j축 = 카메라 광축의 방위 성분을 컵 평면에 투영 (height_field_tool과 동일)
    fwd = np.array(cam_view)[:3, :3].T @ np.array([0.0, 0.0, -1.0])
    v = np.array([fwd[0], fwd[1], 0.0])
    e_j = v - up * v.dot(up)
    e_j /= np.linalg.norm(e_j)
    e_i = np.cross(e_j, up)
    n = hf.shape[0]
    xs = np.linspace(-0.030, 0.030, n)
    di, dj = np.meshgrid(xs, xs, indexing='ij')
    h = np.where(np.isnan(hf), meta['cup_height'] - meta['cup_bottom_t'], hf)
    p = (base + di[..., None] * e_i + dj[..., None] * e_j + h[..., None] * up)
    inside = (di*di + dj*dj) <= 0.027**2      # 샘플 반경 밖은 애초에 안 재는 자리
    return (p.reshape(-1, 3)[inside.reshape(-1)],
            (~np.isnan(hf)).reshape(-1)[inside.reshape(-1)])


def main():
    if '--dump-cams' in sys.argv:
        dump_cams(sys.argv[sys.argv.index('--dump-cams') + 1])
        return
    from PIL import Image, ImageDraw

    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(a) < 4:
        sys.exit(__doc__)
    root, cams_json, mesh_dir, frame = a[0], a[1], a[2], int(a[3])
    out_png = a[4] if len(a) > 4 else os.path.join(root, f'overlay_{frame:04d}.png')
    want = 'e,n,w,s'
    for x in sys.argv[1:]:
        if x.startswith('--cams'):
            want = x.split('=', 1)[1] if '=' in x else want
    cams = [c for c in want.split(',') if os.path.exists(
        os.path.join(root, f'{c}_{frame:04d}.png'))]

    C = json.load(open(cams_json))
    meta = json.load(open(os.path.join(os.path.expanduser(mesh_dir), 'meta.json')))
    traj = np.loadtxt(os.path.expanduser(meta['traj_file']))
    pose = traj[frame][:7]

    tiles = []
    for c in cams:
        img = Image.open(os.path.join(root, f'{c}_{frame:04d}.png')).convert('RGB')
        hf = np.load(os.path.join(root, f'height_{c}', f'height_{frame:04d}.npy'))
        cam = C['cams'][f'Camera_{c}']
        pts, valid = grid_points(meta, pose, cam['view'], hf)
        px = project(pts, cam, C['res'])
        d = ImageDraw.Draw(img)
        for (x, y), v in zip(px, valid):
            if not np.isfinite(x):
                continue
            r = 3
            col = (0, 230, 0) if v else (255, 0, 0)
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        # 물이 있는 부분만 잘라 키운다
        arr = np.asarray(img).astype(int)
        ink = arr.sum(2) < 720
        ys, xs = np.nonzero(ink)
        cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
        half = max(xs.max() - xs.min(), ys.max() - ys.min()) * 0.65 + 20
        L, T, R, B = int(cx - half), int(cy - half), int(cx + half), int(cy + half)
        canvas = Image.new('RGB', (R - L, B - T), (255, 255, 255))
        sx0, sy0 = max(L, 0), max(T, 0)
        sx1, sy1 = min(R, img.width), min(B, img.height)
        canvas.paste(img.crop((sx0, sy0, sx1, sy1)), (sx0 - L, sy0 - T))
        tiles.append(canvas.resize((420, 420), Image.LANCZOS))

    sheet = Image.new('RGB', (420 * len(tiles) + 10 * (len(tiles) - 1), 440), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for k, (t, c) in enumerate(zip(tiles, cams)):
        sheet.paste(t, (k * 430, 20))
        d.text((k * 430 + 4, 4), f'Camera_{c}  frame {frame}', fill=(0, 0, 0))
    sheet.save(out_png)
    n_ok = int(sum(1 for v in valid if v))
    print(f'저장: {out_png}  (초록 {n_ok} / 빨강 {len(valid)-n_ok})')


if __name__ == '__main__':
    main()
