import bpy
import os
import numpy as np
from mathutils import Vector, Quaternion

# ===== 측정기 설정 (측정 규격: SPH/FLIP 공통으로 이 값 사용) =====
GRID_N      = 32
CUP_INNER_R = 0.030
SAMPLE_R = 0.027   # 벽 인접 3mm 제외 (광선이 옆면 맞는 구간)
CUP_BASE_Z  = 0.005
RAY_START_Z = 0.30
RIM_MAX     = 0.104   # 컵 테두리(94mm) + 여유 4mm. 이보다 높은 교점은 물방울로 간주

# ===== 격자 좌표계 =====
# 기본(camera / cup / view): 격자 평면은 컵 축에 수직인 평면(컵 로컬 xy), 광선은 컵 축
# 반대 방향, 높이는 컵 안바닥에서 교점까지 컵 축 방향 거리. 이 평면 안에서 격자를 몇 도
# 돌릴지만 카메라 광축이 정한다. 컵이 기울어도 광선이 단면을 그대로 덮어 616셀이 유지되고,
# 컵의 자기축 회전은 라벨에 들어가지 않아 마커 없이도 이미지로 복원할 수 있다.
#
# LABEL_FRAME  camera(기본) : 격자 방위각을 카메라 기준으로 잡는다
#              cup          : 예전 방식. 격자 축까지 컵 로컬 xy 를 그대로 쓴다
# GRID_PLANE   cup(기본)    : 격자 평면 = 컵 바닥면, 광선 = 컵 축 -z, 높이 = 컵 축 방향 거리
#              world        : 격자 평면 = 월드 수평면, 광선 = 월드 -z, 높이 = z 차이.
#                            컵이 기울면 수직 광선이 단면을 벗어나 자유수면 대신 물-벽
#                            접촉선을 재는 셀이 생긴다 (8.9도에서 616셀 중 169개)
# CAM_AZIM     view(기본)   : 방위각 = 카메라 광축의 투영. 컵 위치와 무관해 프레임마다
#                            흔들리지 않고 e/n/w/s 가 정확히 90도씩 벌어진다
#              position     : 방위각 = 카메라 위치에서 컵으로 향하는 방향의 투영
LABEL_FRAME = os.environ.get("LABEL_FRAME", "camera").strip().lower()
GRID_PLANE  = os.environ.get("GRID_PLANE", "cup").strip().lower()
CAM_AZIM    = os.environ.get("CAM_AZIM", "view").strip().lower()
CAM_NAME    = os.environ.get("CAM_NAME", "").strip()
for _k, _v, _ok in (("LABEL_FRAME", LABEL_FRAME, ("camera", "cup")),
                    ("GRID_PLANE", GRID_PLANE, ("world", "cup")),
                    ("CAM_AZIM", CAM_AZIM, ("position", "view"))):
    if _v not in _ok:
        raise RuntimeError(f"{_k} 값이 이상하다: {_v!r} ({' / '.join(_ok)} 중 하나)")
# ================================================================

_xs = np.linspace(-CUP_INNER_R, CUP_INNER_R, GRID_N)


def _find_camera():
    """CAM_NAME > 씬 카메라 > 씬에 하나뿐인 카메라 순으로 찾는다.

    이름을 하드코딩하지 않으므로 Camera_e/_n/_w/_s 말고 다른 카메라도 그대로 쓴다.
    """
    obj = bpy.data.objects.get(CAM_NAME) if CAM_NAME else None
    if CAM_NAME and obj is None:
        raise RuntimeError(f"CAM_NAME={CAM_NAME!r} 카메라가 blend에 없다")
    if obj is None:
        obj = bpy.context.scene.camera
    if obj is None:
        cams = [o for o in bpy.context.scene.objects if o.type == 'CAMERA']
        if len(cams) == 1:
            obj = cams[0]
    if obj is None or obj.type != 'CAMERA':
        raise RuntimeError("카메라를 정하지 못했다. CAM_NAME 환경변수로 지정하라 "
                           "(LABEL_FRAME=cup 이면 카메라가 필요 없다)")
    return obj


_CAM = None if LABEL_FRAME == "cup" else _find_camera()


def _cam_dir(center_world):
    """격자 방향의 근거가 되는 카메라 벡터. 카메라 위치·자세는 blend에서 읽는다.

    이름을 하드코딩하지 않고 오브젝트에서 읽으므로 다른 카메라를 써도 그대로 동작한다.
    """
    deps = bpy.context.evaluated_depsgraph_get()
    m = _CAM.evaluated_get(deps).matrix_world     # 제약(Track To)까지 반영된 자세
    # 부감각(내려다보는 각)은 떨군 방위 성분만 쓴다. 광축을 통째로 컵 평면에 투영하면
    # 45도 부감이 기울어진 평면에서 크게 꺾여, 네 방향이 90도씩 벌어지지 않는다
    # (기울기 8.9도 궤적에서 최대 5.4도 어긋남. 방위 성분만 쓰면 0.1도 이내).
    if CAM_AZIM == "position":
        p = m.translation                          # 카메라 -> 컵
        return Vector((center_world.x - p.x, center_world.y - p.y, 0.0))
    fwd = m.to_3x3() @ Vector((0.0, 0.0, -1.0))    # 카메라 광축
    return Vector((fwd.x, fwd.y, 0.0))


def grid_frame(cup_pose):
    """이 프레임의 격자 좌표계: (원점, i축, j축, 위쪽 방향).

    원점 = 컵 안바닥 중심(월드). 높이 0 기준점이기도 하다.
    광선 방향은 항상 -위쪽, 높이는 위쪽 성분으로 잰다. i x j = 위쪽 (오른손).
    """
    cup_pos = Vector(np.asarray(cup_pose)[:3].tolist())
    q = np.asarray(cup_pose)[3:]
    cup_quat = Quaternion((q[0], q[1], q[2], q[3]))
    cup_up = cup_quat @ Vector((0.0, 0.0, 1.0))
    base = cup_pos + cup_up * CUP_BASE_Z

    if LABEL_FRAME == "cup":
        return (base, cup_quat @ Vector((1.0, 0.0, 0.0)),
                cup_quat @ Vector((0.0, 1.0, 0.0)), cup_up)

    up = Vector((0.0, 0.0, 1.0)) if GRID_PLANE == "world" else cup_up
    v = _cam_dir(base)
    e_j = v - up * v.dot(up)               # 카메라 벡터를 격자 평면에 투영
    if e_j.length < 1e-6:
        raise RuntimeError("카메라 방향이 격자 평면에 수직이라 격자 방향을 정할 수 없다")
    e_j.normalize()
    return base, e_j.cross(up), e_j, up


def grid_azimuth_deg(cup_pose):
    """격자 j축의 월드 방위각(도). 사람이 읽는 기록용."""
    _, _, e_j, _ = grid_frame(cup_pose)
    return float(np.degrees(np.arctan2(e_j.y, e_j.x)) % 360.0)


def grid_angle_deg(cup_pose):
    """격자 평면 안에서 j축이 돌아간 각도(도).

    같은 프레임의 두 라벨은 이 각도 차이만큼 정확히 돌아가 있다. 검증용.
    기준축은 격자 평면과 함께 간다: 컵 평면이면 컵 로컬 x/y, 월드 평면이면 월드 x/y.
    """
    q = np.asarray(cup_pose)[3:]
    cup_quat = Quaternion((q[0], q[1], q[2], q[3]))
    _, _, e_j, _ = grid_frame(cup_pose)
    if LABEL_FRAME != "cup" and GRID_PLANE == "world":
        rx, ry = Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0))
    else:
        rx, ry = cup_quat @ Vector((1.0, 0.0, 0.0)), cup_quat @ Vector((0.0, 1.0, 0.0))
    return float(np.degrees(np.arctan2(e_j.dot(ry), e_j.dot(rx))) % 360.0)


def extract_height_field(water_object, cup_pose):
    """씬의 임의 물 오브젝트에서 height field 추출.

    water_object : 물 메시 오브젝트 (SPH 메시든 FLIP Domain이든, 모디파이어 적용 후 평가됨)
    cup_pose     : 길이 7 배열 [x,y,z, w,qx,qy,qz] (컵 위치 + 쿼터니언)
    반환          : (GRID_N, GRID_N) 배열, [i축, j축] 순서. 물 없는 지점은 NaN
    """
    deps = bpy.context.evaluated_depsgraph_get()
    w_eval = water_object.evaluated_get(deps)
    mw = w_eval.matrix_world
    mw_inv = mw.inverted()

    base, e_i, e_j, up = grid_frame(cup_pose)
    q = np.asarray(cup_pose)[3:]
    # 물방울·바닥 판정은 항상 컵 축 기준으로 한다. 테두리(RIM_MAX)와 안바닥은
    # 컵에 붙어 있는 기준선이라, 격자가 월드 수평이어도 판정선은 같이 기울어야 한다.
    cup_up = Quaternion((q[0], q[1], q[2], q[3])) @ Vector((0.0, 0.0, 1.0))

    d_local = mw_inv.to_3x3() @ (-up)
    hf = np.full((GRID_N, GRID_N), np.nan)
    for a, di in enumerate(_xs):
        for b, dj in enumerate(_xs):
            if di*di + dj*dj > SAMPLE_R**2:
                continue
            o_local = mw_inv @ (base + e_i*di + e_j*dj + up*RAY_START_Z)
            # 공중의 물방울을 건너뛰고 컵 안 수면을 찾는다.
            # 광선을 위에서 아래로 쏘며 교점을 차례로 받아, RIM_MAX 아래 첫 교점을 채택.
            o = o_local.copy()
            h = None
            for _ in range(8):
                hit, loc, _, _ = w_eval.ray_cast(o, d_local)
                if not hit:
                    break
                rel = (mw @ loc) - base
                if rel.dot(cup_up) <= RIM_MAX:
                    h = rel.dot(up) if rel.dot(cup_up) >= 0 else None
                    break
                o = loc + d_local * 1e-4      # 그 교점 바로 아래에서 다시 발사
            hf[a, b] = h if h is not None else np.nan
    return hf


print(f"height_field_tool loaded: LABEL_FRAME={LABEL_FRAME}"
      + (f" GRID_PLANE={GRID_PLANE} CAM_AZIM={CAM_AZIM} camera={_CAM.name}"
         if _CAM is not None else ""))
