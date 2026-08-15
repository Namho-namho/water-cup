#!/usr/bin/env python3
"""궤적 일괄 생성기.

인덱스를 받아 유형과 파라미터를 무작위로 정하고, traj_curveG.py를 템플릿 삼아
이동 구간만 교체한 스크립트를 만들어 실행합니다.

사용:
    python gen_traj_batch.py <인덱스> [출력루트]
    python gen_traj_batch.py --params-only 1000    # params.csv만 미리 생성
"""
import os, sys, math, random, subprocess, csv

ROOT = os.path.expanduser(os.environ.get('TRAJ_ROOT', '~/water_cup/batch'))
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'traj_curveG.py')
WATER_LEVELS = [0.055, 0.065, 0.075, 0.085]
KINDS = ['static', 'curve', 'stop', 'shake', 'zigzag', 'tilt']

# ---- 가속도 예산 ----------------------------------------------------------
# 이동 구간은 200스텝 = 100프레임 = 0.80초로 고정이다(step은 조각 길이만 바꾸고
# 총 시간은 안 바뀐다). 따라서 가속도는 진폭과 주기 수로만 조절한다.
#
#   흔들림 가속도 a ~= K * 진폭 * 주기수^2      (실제 생성한 궤적에서 맞춘 계수)
#     zigzag K=27, shake K=30 (실측 23~29. 예산을 조금 보수적으로 잡는 쪽)
#     curve  K=80             (실측 57~78. 최댓값 쪽에 맞춰야 5를 안 넘는다)
#     tilt   a ~= deg * (0.061*주기수^2 + 0.108)   (실측 0.155~0.367 /deg)
#
# 물을 넘치게 하는 건 가속도 자체보다 공진이다. 안반경 28mm 원통의 1차 슬로싱은
# 4.04Hz = 0.8초에 3.23주기(수위 55~85mm 모두 같다). 그래서 주기 수를 공진 근처로
# 두고 진폭을 가속도 예산에서 역산한다. 같은 출렁임을 훨씬 낮은 가속도로 얻는다.
ACC_MAX = float(os.environ.get('ACC_MAX', 5.0))    # 목표 최대 가속도 (m/s^2)
ACC_MIN = float(os.environ.get('ACC_MIN', 2.0))
K_ZIG, K_SHAKE, K_CURVE = 27.0, 30.0, 80.0
T_MOVE = 0.80                                       # 이동 구간 길이(초)
RESONANCE = 3.23                                    # 0.8초 동안의 슬로싱 주기 수

MARK = '    frame["save_on"] = True'
END  = '    settle(20)'   # 이동 구간 끝. 이후(내려놓기)는 저장 안 함


def params(idx):
    """인덱스로 결정되는 파라미터 (재현 가능)."""
    r = random.Random(20260812 + idx)
    k = KINDS[idx % len(KINDS)]
    p = {
        'idx': idx,
        'kind': k,
        'water': WATER_LEVELS[(idx // len(KINDS)) % len(WATER_LEVELS)],
        'dist': round(r.uniform(0.24, 0.40), 4),      # 이동 거리(m)
        'step': r.randint(5, 8),                       # 조각당 스텝(속도)
        'seg':  0,                                     # 아래에서 결정
    }
    _target = 300 if idx <= 11 else 400   # 1~11: 150프레임, 12~25: 200프레임
    p['seg'] = max(12, int(round(_target / float(p['step']))))
    # 이동 자체(거리 dist를 u^2로 가속)에서 나오는 바닥 가속도
    a_base = 2.0 * p['dist'] / (T_MOVE ** 2)
    a_t = r.uniform(ACC_MIN, ACC_MAX)                  # 이 궤적의 목표 최대 가속도
    if k == 'curve':
        p['amp'] = round(min(0.18, a_t / K_CURVE), 4)  # 곡선 세기 (가속도 예산에서 역산)
        p['amp0'] = round(r.uniform(0.02, 0.08), 4)    # 곡률 없는 초기 옆이동
        a_drive = K_CURVE * p['amp']
    elif k == 'stop':
        p['accel'] = r.choice([2, 3])                  # u^2 / u^3
        a_drive = a_base * (1.0 if p['accel'] == 2 else 2.2)
    elif k == 'shake':
        p['sh_cyc'] = round(r.uniform(2.4, 3.6), 2)    # 공진(3.23) 근처
        p['sh_amp'] = round(min(0.05, a_t / (K_SHAKE * p['sh_cyc'] ** 2)), 4)
        p['sh_axis'] = r.choice(['y', 'x'])            # y=좌우, x=앞뒤
        a_drive = K_SHAKE * p['sh_amp'] * p['sh_cyc'] ** 2
    elif k == 'static':
        p['nudge'] = round(r.uniform(0.0, 0.02), 4)      # 아주 작은 흔들림(m)
        a_drive = 0.0
    elif k == 'zigzag':
        p['zz_cyc'] = round(r.uniform(2.2, 3.4), 2)    # 공진 근처
        p['zz_amp'] = round(min(0.09, a_t / (K_ZIG * p['zz_cyc'] ** 2)), 4)
        a_drive = K_ZIG * p['zz_amp'] * p['zz_cyc'] ** 2
    elif k == 'tilt':
        p['tilt_cyc'] = round(r.choice([0.0, 1.0, 2.0]), 1)  # 0=단조증가, >0=흔들림
        # 기울임도 컵 중심을 흔들어 가속도를 만든다
        _kt = 0.061 * max(p['tilt_cyc'], 0.5) ** 2 + 0.108
        _cap = (ACC_MAX - a_base) / _kt
        p['tilt_deg'] = round(min(r.uniform(6.0, 14.0), _cap), 2)   # 최종 기울기(도)
        a_drive = _kt * p['tilt_deg']
    else:
        a_drive = 0.0
    p['acc_pred'] = round((a_base ** 2 + a_drive ** 2) ** 0.5, 2)   # 예상 최대 가속도
    return p


def body(p):
    """이동 구간 코드 생성."""
    k = p['kind']
    p['seg'] = max(12, int(round(200.0 / p['step'])))   # 총 ~200스텝 = 100프레임
    if k == 'curve':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u * _u
        _y = {p['dist']} * _q
        _amp = {p['amp0']} + {p['amp']} * _q
        _x = GRASP_X + _amp * _m.sin(_m.pi * _q)
        move_lin((_x, _y, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'stop':
        e = p['accel']
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u ** {e}
        move_lin((GRASP_X, {p['dist']} * _q, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'shake':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _d = {p['sh_amp']} * _m.sin(2.0 * _m.pi * {p['sh_cyc']} * _u)
        _px = GRASP_X + (_d if '{p['sh_axis']}' == 'x' else 0.0)
        _py = _d if '{p['sh_axis']}' == 'y' else 0.0
        move_lin((_px, _py, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'static':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _y = {p['nudge']} * _m.sin(2.0 * _m.pi * 1.0 * _u)
        move_lin((GRASP_X, _y, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'tilt':
        cyc = p['tilt_cyc']
        expr = (f"{p['tilt_deg']} * _m.sin(2.0 * _m.pi * {cyc} * _u)" if cyc > 0
                else f"{p['tilt_deg']} * (_u * _u * (3.0 - 2.0 * _u))")
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u * _u
        _tl = {expr}
        move_lin((GRASP_X, {p['dist']} * _q, Z_LIFT), side_quat(_tl), {p['step']}, FINGER_GRASP)"""
    if k == 'vert':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u * _u
        _sm = _u * _u * (3.0 - 2.0 * _u)
        _z = Z_LIFT + {p['vz_amp']} * _m.sin(2.0 * _m.pi * {p['vz_cyc']} * _u)
        _tl = {p['tilt_deg']} * _sm
        move_lin((GRASP_X, {p['dist']} * _q, _z), side_quat(_tl), {p['step']}, FINGER_GRASP)"""
    # zigzag
    return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _y = {p['dist']} * (_u * _u)
        _x = GRASP_X + {p['zz_amp']} * _m.sin(2.0 * _m.pi * {p['zz_cyc']} * _u)
        move_lin((_x, _y, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""


def make(idx, root=ROOT):
    p = params(idx)
    src = open(TEMPLATE).read()
    i = src.index(MARK) + len(MARK)
    j = src.index(END, i)
    out_name = f'traj_{idx:04d}'
    s = src[:i] + '\n' + body(p) + '\n    frame["save_on"] = False\n' + src[j:]
    s = s.replace('traj_curveG_only', f'{out_name}_only')
    compile(s, 'x', 'exec')
    os.makedirs(root, exist_ok=True)
    py = os.path.join(root, f'{out_name}.py')
    open(py, 'w').write(s)
    return p, py, out_name


if __name__ == '__main__':
    if sys.argv[1] == '--params-only':
        n = int(sys.argv[2])
        os.makedirs(ROOT, exist_ok=True)
        with open(os.path.join(ROOT, 'params.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=[
                'idx','kind','water','dist','step','seg','acc_pred',
                'amp','amp0','accel','sh_amp','sh_cyc','zz_amp','zz_cyc',
                'tilt_deg','tilt_cyc','sh_axis','nudge'])
            w.writeheader()
            for i in range(1, n + 1):
                w.writerow(params(i))
        print(f'params.csv 생성: {n}개')
        sys.exit(0)

    idx = int(sys.argv[1])
    root = sys.argv[2] if len(sys.argv) > 2 else ROOT
    p, py, name = make(idx, root)
    print(f'[{idx}] {p["kind"]} water={p["water"]} dist={p["dist"]} -> {py}', flush=True)
    subprocess.run([sys.executable, py], check=True, cwd=os.path.dirname(py))
    # npy -> txt
    conv = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'make_traj.py')
    subprocess.run([sys.executable, conv,
                    os.path.expanduser(f'~/water_cup/{name}_only'),
                    os.path.join(root, f'{name}.txt')], check=True)
    print(f'[{idx}] 완료', flush=True)
