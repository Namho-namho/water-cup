import bpy
import numpy as np
from mathutils import Vector, Quaternion

# ===== 측정기 설정 (측정 규격: SPH/FLIP 공통으로 이 값 사용) =====
GRID_N      = 32
CUP_INNER_R = 0.030
SAMPLE_R = 0.027   # 벽 인접 3mm 제외 (광선이 옆면 맞는 구간)
CUP_BASE_Z  = 0.005
RAY_START_Z = 0.30
# ================================================================

_xs = np.linspace(-CUP_INNER_R, CUP_INNER_R, GRID_N)

def extract_height_field(water_object, cup_pose):
    """씬의 임의 물 오브젝트에서 컵 좌표계 height field 추출.

    water_object : 물 메시 오브젝트 (SPH 메시든 FLIP Domain이든, 모디파이어 적용 후 평가됨)
    cup_pose     : 길이 7 배열 [x,y,z, w,qx,qy,qz] (컵 위치 + 쿼터니언)
    반환          : (GRID_N, GRID_N) 배열, 물 없는 지점은 NaN
    """
    deps = bpy.context.evaluated_depsgraph_get()
    w_eval = water_object.evaluated_get(deps)
    mw = w_eval.matrix_world
    mw_inv = mw.inverted()

    cup_pos = Vector(np.asarray(cup_pose)[:3].tolist())
    q = np.asarray(cup_pose)[3:]
    cup_quat = Quaternion((q[0], q[1], q[2], q[3]))
    d_local = mw_inv.to_3x3() @ (cup_quat @ Vector((0, 0, -1)))

    hf = np.full((GRID_N, GRID_N), np.nan)
    for i, dx in enumerate(_xs):
        for j, dy in enumerate(_xs):
            if dx*dx + dy*dy > SAMPLE_R**2:
                continue
            o_local = mw_inv @ (cup_pos + cup_quat @ Vector((dx, dy, RAY_START_Z)))
            hit, loc, _, _ = w_eval.ray_cast(o_local, d_local)
            if hit:
                hit_cup = cup_quat.inverted() @ ((mw @ loc) - cup_pos)
                h = hit_cup.z - CUP_BASE_Z
                hf[i, j] = h if h >= 0 else np.nan    # 컵 바닥 아래 교점 = 컵 밖 물 -> 무시
    return hf

print("height_field_tool loaded: extract_height_field(water_object, cup_pose)")