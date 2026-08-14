#
# Static cup liquid simulation
# APIC + Implicit Density Projection
#
# Based on:
#   scenes/idp_apic02_3d.py
#

from manta import *
import os


# ============================================================
# Solver parameters
# ============================================================

dim = 3
particleNumber = 2

# MantaFlow coordinates:
# x = horizontal
# y = vertical
# z = horizontal
gs = vec3(152, 152, 208)

# One grid cell corresponds to this many meters
H = 0.368 / 152.0

# ============================================================
# CONFIG  (여기만 고치면 됨)
# ============================================================
TRAJ_FILE    = '~/water_cup/traj_curveG.txt'   # 컵 궤적 (x y z qw qx qy qz)
DT_REAL      = 0.008               # 궤적 프레임 간격(초) - 궤적 생성 설정과 일치해야 함
WATER_LEVEL  = 0.085               # 초기 수위 (m, 컵 안바닥 기준)
CUP_OUTER_R  = 0.035
CUP_INNER_R  = 0.028
CUP_HEIGHT   = 0.100
CUP_BOTTOM_T = 0.006
OUT_DIR      = '~/water_cup/idp_curveG'
SETTLE_T     = 200.0                # 정착 프레임 수
MARGIN       = 5.0                 # 도메인 여유 (격자)

# ---- 궤적 로드 ----
traj=[]
with open(os.path.expanduser(TRAJ_FILE)) as _f:
    for _l in _f:
        _v=[float(_x) for _x in _l.split()]
        if len(_v)>=7: traj.append(_v)
NT=len(traj)
assert NT>=4, 'trajectory too short'
TFRAME=DT_REAL/((0.01*H/9.81)**0.5)
TOTAL=int(SETTLE_T + (NT-1)*TFRAME) + 30

# ---- 궤적 이동량 (world -> grid) ----
_dx=[(p[0]-traj[0][0])/H for p in traj]      # world x -> grid x
_dy=[(p[1]-traj[0][1])/H for p in traj]      # world y -> grid z
_dz=[(p[2]-traj[0][2])/H for p in traj]      # world z(up) -> grid y

_R = CUP_OUTER_R/H + MARGIN
# 좌우 방향은 이동 구간을 도메인 중앙에 배치
_ownCenterX = gs.x*0.5 - 0.5*(min(_dx)+max(_dx))
_ownCenterZ = gs.z*0.5 - 0.5*(min(_dy)+max(_dy))
# 수직은 최저점이 바닥에서 MARGIN 위에 오도록
_ownBottom  = MARGIN + 2.0 - min(_dz)

# ---- 도메인 범위 검사 ----
def _fits(cx, cb, cz):
    """이 컵 배치로 궤적 전체가 도메인 안에 들어오는지. 안 되면 이유를 돌려준다."""
    for lo,hi,size,name in (
        (cx+min(_dx)-_R,               cx+max(_dx)+_R,                        gs.x, 'x'),
        (cz+min(_dy)-_R,               cz+max(_dy)+_R,                        gs.z, 'z(이동)'),
        (cb+min(_dz)-MARGIN,           cb+max(_dz)+CUP_HEIGHT/H+MARGIN,       gs.y, 'y(높이)')):
        if not (lo>=1.0 and hi<=size-1.0):
            return (f'{name} 방향 도메인 초과: {lo:.1f}~{hi:.1f} (도메인 0~{size:.0f})')
    return None

# ---- 정착 캐시: 컵 배치까지 맞춰야 재사용할 수 있다 ----
# 캐시에는 입자가 격자 절대 좌표로 들어 있는데 컵 배치는 궤적마다 다르다.
# 배치가 다른 캐시를 그냥 읽으면 물이 컵 밖에서 시작한다. 그래서 캐시를 쓸 때는
# 캐시를 만든 궤적의 컵 배치를 그대로 채택한다(정착 중에는 컵이 정지해 있으므로
# 평행이동만으로 정확하다). 그 배치로 궤적이 도메인을 벗어나면 캐시를 버리고
# 자기 정착을 계산한다.
# v2: 배치 정보(.json)가 함께 저장된 형식. v1 캐시는 위치를 알 수 없어 쓰지 않는다.
_SETTLE_CACHE = os.path.expanduser(
    os.path.dirname(OUT_DIR) + '/settle_cache/w%d_g%d_v2.uni' % (int(WATER_LEVEL*1000), int(gs.x)))
_SETTLE_META  = _SETTLE_CACHE.replace('.uni', '.json')

import json as _json
cupCenterX, cupBottom, cupCenterZ = _ownCenterX, _ownBottom, _ownCenterZ
_settle_skip = False        # True면 캐시를 읽어 정착 구간을 건너뛴다
_settle_write = True        # 쓸 만한 캐시가 이미 있으면 덮어쓰지 않는다
_settle_note = '캐시 없음 -> 정착 계산 후 저장'
if os.path.exists(_SETTLE_CACHE) and os.path.exists(_SETTLE_META):
    try:
        _cm = _json.load(open(_SETTLE_META))
        _cx, _cb, _cz = float(_cm['cupCenterX']), float(_cm['cupBottom']), float(_cm['cupCenterZ'])
    except Exception as _e:
        _cx = None
        _settle_note = '캐시 메타 읽기 실패(%s) -> 정착 계산 후 저장' % _e
    if _cx is not None:
        _why = _fits(_cx, _cb, _cz)
        if _why is None:
            cupCenterX, cupBottom, cupCenterZ = _cx, _cb, _cz
            _settle_skip = True
            _settle_note = '캐시 사용 (캐시의 컵 배치를 채택)'
        else:
            # 남이 잘 쓰고 있는 캐시다. 이 궤적만 자기 정착을 쓰고 캐시는 그대로 둔다.
            _settle_write = False
            _settle_note = '캐시 배치로는 %s -> 캐시 무시하고 자기 정착 계산' % _why

_shift = (((cupCenterX-_ownCenterX)**2 + (cupBottom-_ownBottom)**2
           + (cupCenterZ-_ownCenterZ)**2) ** 0.5)

# 자기 배치를 쓰는 경우에만 검사한다(캐시 배치는 위에서 이미 통과한 것만 채택).
_own_why = _fits(cupCenterX, cupBottom, cupCenterZ)
assert _own_why is None, _own_why + '. 격자를 키우거나 궤적 이동 범위를 줄이세요'

import time as _time
_t_start=_time.time()
print('--- CONFIG ---', flush=True)
print('  traj      : %s (%d frames, dt=%.4f s, 총 %.2f s)' % (TRAJ_FILE, NT, DT_REAL, (NT-1)*DT_REAL), flush=True)
print('  sim frames: %d (1 frame = %.3f ms, TFRAME=%.2f)' % (TOTAL, DT_REAL/TFRAME*1000, TFRAME), flush=True)
print('  water     : %.1f mm | cup in/out R %.1f/%.1f mm, h %.1f mm' % (
      WATER_LEVEL*1000, CUP_INNER_R*1000, CUP_OUTER_R*1000, CUP_HEIGHT*1000))
print('  cup start : x=%.1f y=%.1f z=%.1f (grid)' % (cupCenterX, cupBottom, cupCenterZ), flush=True)
print('  travel    : x %.1f~%.1f | z %.1f~%.1f | y %.1f~%.1f (grid)' % (
      min(_dx),max(_dx),min(_dy),max(_dy),min(_dz),max(_dz)))
print('  settle    : %s' % _settle_note, flush=True)
print('              cache=%s' % _SETTLE_CACHE, flush=True)
print('              자기 배치 x=%.1f y=%.1f z=%.1f -> 채택 배치 x=%.1f y=%.1f z=%.1f '
      '(이동 %.1f셀 = %.1fmm)' % (_ownCenterX, _ownBottom, _ownCenterZ,
                                  cupCenterX, cupBottom, cupCenterZ, _shift, _shift*H*1000), flush=True)
print('---------------', flush=True)


s = Solver(
    name='main',
    gridSize=gs,
    dim=dim
)

s.frameLength = 1.0
s.timestep = 1.0
s.timestepMin = 0.05
s.timestepMax = 1.0
s.cfl = 3.0


# ============================================================
# Grids
# ============================================================

flags = s.create(FlagGrid)

vel = s.create(MACGrid)
pressure = s.create(RealGrid)

# Used by extrapolateMACFromWeight
tmpVec3 = s.create(VecGrid)

# Cup and domain obstacle level set
phiObs = s.create(LevelsetGrid, name='phiObs')
obsVel = s.create(MACGrid)


# ============================================================
# Particles and APIC data
# ============================================================

pp = s.create(BasicParticleSystem)

pVel = pp.create(PdataVec3)

apic_mass = s.create(MACGrid)

apic_pCx = pp.create(PdataVec3)
apic_pCy = pp.create(PdataVec3)
apic_pCz = pp.create(PdataVec3)


# ============================================================
# Implicit Density Projection data
# ============================================================

density = s.create(RealGrid)

# Position-solver pressure p2 in the paper
Lambda = s.create(RealGrid)

deltaX = s.create(MACGrid)
flagsPos = s.create(FlagGrid)

pMass = pp.create(PdataReal)

particleMass = 1.0 / float(
    particleNumber
    * particleNumber
    * particleNumber
)


# ============================================================
# Surface reconstruction
# ============================================================

pindex = s.create(ParticleIndexSystem)
gpi = s.create(IntGrid)

phi = s.create(LevelsetGrid)
mesh = s.create(Mesh)


# ============================================================
# Static cup geometry
# ============================================================




# Leave room beneath the cup


outerRadius = CUP_OUTER_R / H
innerRadius = CUP_INNER_R / H

cupHeight = CUP_HEIGHT / H
bottomThickness = CUP_BOTTOM_T / H


# Outer solid cylinder
outerCenter = vec3(
    cupCenterX,
    cupBottom + 0.5 * cupHeight,
    cupCenterZ
)

outerCup = Cylinder(
    parent=s,
    center=outerCenter,
    radius=outerRadius,
    z=vec3(0.0, 0.5 * cupHeight, 0.0)
)

phiObs.copyFrom(
    outerCup.computeLevelset()
)


# Inner cavity
#
# The cavity extends above the outer cylinder so that
# the upper face of the cup remains open.
cavityBottom = cupBottom + bottomThickness
cavityTop = cupBottom + cupHeight + 10.0
cavityHeight = cavityTop - cavityBottom

innerCenter = vec3(
    cupCenterX,
    cavityBottom + 0.5 * cavityHeight,
    cupCenterZ
)

innerCup = Cylinder(
    parent=s,
    center=innerCenter,
    radius=innerRadius,
    z=vec3(0.0, 0.5 * cavityHeight, 0.0)
)

# Solid cup = outer cylinder minus inner cavity
phiObs.subtract(
    innerCup.computeLevelset()
)

phiCup = s.create(LevelsetGrid)
phiCup.copyFrom(phiObs)   # cup backup (initDomain wipes phiWalls!)

flags.initDomain(
    boundaryWidth=1,
    phiWalls=phiObs
)

phiObs.join(phiCup)
setObstacleFlags(flags=flags, phiObs=phiObs)


# Initialize the domain and apply cup/domain walls


# ============================================================
# Initial water volume
# ============================================================

# Keep a small gap between water and the solid cup
waterBottom = cupBottom + bottomThickness + 1.0

waterHeight = WATER_LEVEL / H
waterRadius = CUP_INNER_R / H   # 컵 안벽까지 꽉 채움 (정착 시 수면 강하 방지)

waterCenter = vec3(
    cupCenterX,
    waterBottom + 0.5 * waterHeight,
    cupCenterZ
)

water = Cylinder(
    parent=s,
    center=waterCenter,
    radius=waterRadius,
    z=vec3(0.0, 0.5 * waterHeight, 0.0)
)

phiInit = water.computeLevelset()

# Mark the initial liquid region
flags.updateFromLevelset(phiInit)

# Generate liquid particles
sampleFlagsWithParticles(
    flags=flags,
    parts=pp,
    discretization=particleNumber,
    randomness=0.5
)

# Position solver starts from the same flags
copyFlagsToFlags(
    source=flags,
    target=flagsPos
)

initialParticleCount = pp.pySize()

if GUI:
    gui = Gui()
    gui.show()
    gui.nextPdata()
    gui.nextPartDisplay()

mantaMsg(
    'Initial particle count: %d'
    % initialParticleCount
)


# ============================================================
# Output
# ============================================================

OUT = os.path.expanduser(OUT_DIR)

os.makedirs(
    OUT,
    exist_ok=True
)

import json
with open(os.path.join(OUT,'meta.json'),'w') as _mf:
    json.dump({'traj_file':TRAJ_FILE,'NT':NT,'DT_REAL':DT_REAL,'H':H,
               'TFRAME':TFRAME,'SETTLE_T':SETTLE_T,'TOTAL':TOTAL,
               'cupCenterX':cupCenterX,'cupBottom':cupBottom,'cupCenterZ':cupCenterZ,
               'cup_outer_r':CUP_OUTER_R,'cup_inner_r':CUP_INNER_R,
               'cup_height':CUP_HEIGHT,'cup_bottom_t':CUP_BOTTOM_T,
               'water_level':WATER_LEVEL,'gs':[gs.x,gs.y,gs.z],
               'settle_cache_used':bool(_settle_skip),
               'settle_cache':_SETTLE_CACHE if _settle_skip else None,
               'settle_note':_settle_note,
               'cup_placement_own':{'cupCenterX':_ownCenterX,'cupBottom':_ownBottom,
                                    'cupCenterZ':_ownCenterZ},
               'cup_placement_shift_mm':_shift*H*1000}, _mf, indent=2)
print('meta.json 저장:', os.path.join(OUT,'meta.json'), flush=True)



# ============================================================
# Main simulation loop
#
# This ordering follows idp_apic02_3d.py.
# ============================================================



def _cr(p0,p1,p2,p3,t):
    return 0.5*((2*p1) + (-p0+p2)*t + (2*p0-5*p1+4*p2-p3)*t*t + (-p0+3*p1-3*p2+p3)*t*t*t)

def _qrot(q, v):
    w,x,y,z = q
    tx = 2*(y*v[2]-z*v[1]); ty = 2*(z*v[0]-x*v[2]); tz = 2*(x*v[1]-y*v[0])
    return (v[0]+w*tx+(y*tz-z*ty), v[1]+w*ty+(z*tx-x*tz), v[2]+w*tz+(x*ty-y*tx))

def cup_axis(tt):
    ft=(tt-SETTLE_T)/TFRAME
    if ft<0.0: ft=0.0
    if ft>NT-1: ft=float(NT-1)
    i=int(ft); f=ft-i
    if i>=NT-1: i=NT-2; f=1.0
    qa=traj[i][3:7]; qb=traj[i+1][3:7]
    if sum(u*v for u,v in zip(qa,qb))<0: qb=[-u for u in qb]
    q=[qa[k]*(1-f)+qb[k]*f for k in range(4)]
    n=sum(u*u for u in q)**0.5
    q=[u/n for u in q]
    aw=_qrot(q,(0.0,0.0,1.0))
    return (aw[0], aw[2], aw[1])

def cup_pos(tt):
    ft=(tt-SETTLE_T)/TFRAME
    if ft<0.0: ft=0.0
    if ft>NT-1: ft=float(NT-1)
    i=int(ft); f=ft-i
    if i>=NT-1: i=NT-2; f=1.0
    i0=max(i-1,0); i1=i; i2=min(i+1,NT-1); i3=min(i+2,NT-1)
    px=_cr(traj[i0][0],traj[i1][0],traj[i2][0],traj[i3][0],f)
    py=_cr(traj[i0][1],traj[i1][1],traj[i2][1],traj[i3][1],f)
    pz=_cr(traj[i0][2],traj[i1][2],traj[i2][2],traj[i3][2],f)
    gx=cupCenterX+(px-traj[0][0])/H
    gy=cupBottom +(pz-traj[0][2])/H
    gz=cupCenterZ+(py-traj[0][1])/H
    return gx,gy,gz

def set_cup(tt):
    gx,gy,gz=cup_pos(tt)
    ax,ay,az=cup_axis(tt)
    hh=0.5*cupHeight
    oc=Cylinder(parent=s,center=vec3(gx+ax*hh,gy+ay*hh,gz+az*hh),radius=outerRadius,
                z=vec3(ax*hh,ay*hh,az*hh))
    phiObs.copyFrom(oc.computeLevelset())
    L=cupHeight+10.0-bottomThickness
    m=bottomThickness+0.5*L
    ic=Cylinder(parent=s,center=vec3(gx+ax*m,gy+ay*m,gz+az*m),radius=innerRadius,
                z=vec3(ax*0.5*L,ay*0.5*L,az*0.5*L))
    phiObs.subtract(ic.computeLevelset())
    phiCupNow=s.create(LevelsetGrid)
    phiCupNow.copyFrom(phiObs)
    flags.initDomain(boundaryWidth=1, phiWalls=phiObs)
    phiObs.join(phiCupNow)
    setObstacleFlags(flags=flags, phiObs=phiObs)
    markFluidCells(parts=pp, flags=flags)
    px1,py1,pz1=cup_pos(tt+0.5)
    px0,py0,pz0=cup_pos(tt-0.5)
    obsVel.setConst(vec3(px1-px0, py1-py0, pz1-pz0))
    obsVel.setBound(value=vec3(0.), boundaryWidth=2)

# 캐시 사용 여부와 컵 배치는 앞(CONFIG)에서 이미 정해졌다.
if _settle_skip:
    pp.load(_SETTLE_CACHE)
    pVel.load(_SETTLE_CACHE.replace('.uni', '_vel.uni'))
    print('[settle] 캐시 로드: %s' % _SETTLE_CACHE, flush=True)
else:
    print('[settle] %s' % _settle_note, flush=True)

for t in range(TOTAL):
    # 정착 구간: 캐시가 있으면 계산을 건너뛰고 시간만 진행
    if _settle_skip and t < SETTLE_T:
        s.step(); continue

    # Adaptive time stepping
    maxVel = vel.getMax()
    s.adaptTimestep(maxVel)

    mantaMsg(
        '\nFrame %d, time %.6f, dt %.6f, particles %d'
        % (
            s.frame,
            s.timeTotal,
            s.timestep,
            pp.pySize()
        )
    )


    # --------------------------------------------------------
    # 1. Advect particles
    # --------------------------------------------------------

    set_cup(s.timeTotal)

    pp.advectInGrid(
        flags=flags,
        vel=vel,
        integrationMode=2,
        deleteInObstacle=False,
        stopInObstacle=False
    )

    pushOutofObs(parts=pp, flags=flags, phiObs=phiObs)


    # --------------------------------------------------------
    # 2. Implicit Density Projection
    # --------------------------------------------------------

    copyFlagsToFlags(
        source=flags,
        target=flagsPos
    )

    mapMassToGrid(
        flags=flagsPos,
        density=density,
        parts=pp,
        source=pMass,
        deltaX=deltaX,
        phiObs=phiObs,
        dt=s.timestep,
        particleMass=particleMass,
        noDensityClamping=False
    )

    solvePressureSystem(
        rhs=density,
        vel=vel,
        pressure=Lambda,
        flags=flagsPos,
        cgAccuracy=1e-3
    )

    computeDeltaX(
        deltaX=deltaX,
        Lambda=Lambda,
        flags=flagsPos
    )

    mapMACToPartPositions(
        flags=flagsPos,
        deltaX=deltaX,
        parts=pp,
        dt=s.timestep
    )

    _gx,_gy,_gz = cup_pos(s.timeTotal)
    _ax,_ay,_az = cup_axis(s.timeTotal)
    clampToCupAxis(parts=pp, pvel=pVel,
                   base=vec3(_gx+_ax*bottomThickness,_gy+_ay*bottomThickness,_gz+_az*bottomThickness),
                   axis=vec3(_ax,_ay,_az), innerR=innerRadius, outerR=outerRadius,
                   height=cupHeight-bottomThickness)

    pushOutofObs(parts=pp, flags=flags, phiObs=phiObs)


    # --------------------------------------------------------
    # 3. APIC: particles to grid
    # --------------------------------------------------------

    apicMapPartsToMAC(
        flags=flags,
        vel=vel,
        parts=pp,
        partVel=pVel,
        cpx=apic_pCx,
        cpy=apic_pCy,
        cpz=apic_pCz,
        mass=apic_mass
    )

    extrapolateMACFromWeight(
        vel=vel,
        distance=2,
        weight=tmpVec3
    )


    # --------------------------------------------------------
    # 4. Reconstruct fluid flags
    # --------------------------------------------------------

    markFluidCells(
        parts=pp,
        flags=flags
    )
    # --------------------------------------------------------
    # 5. Gravity
    #
    # Same gravity magnitude as the official IDP example.
    # --------------------------------------------------------

    addGravityNoScale(
        flags=flags,
        vel=vel,
        gravity=vec3(0.0, -0.01, 0.0)
    )


    # --------------------------------------------------------
    # 6. Velocity pressure projection
    # --------------------------------------------------------

    setWallBcs(
        flags=flags,
        vel=vel,
        obvel=obsVel,
        phiObs=phiObs
    )

    solvePressure(
        flags=flags,
        vel=vel,
        pressure=pressure,
        cgAccuracy=1e-3
    )

    setWallBcs(
        flags=flags,
        vel=vel,
        obvel=obsVel,
        phiObs=phiObs
    )


    # No liquid level set is used for velocity extrapolation.
    extrapolateMACSimple(
        flags=flags,
        vel=vel,
        distance=5
    )


    # --------------------------------------------------------
    # 7. APIC: grid to particles
    # --------------------------------------------------------

    apicMapMACGridToParts(
        partVel=pVel,
        cpx=apic_pCx,
        cpy=apic_pCy,
        cpz=apic_pCz,
        parts=pp,
        vel=vel,
        flags=flags
    )


    # --------------------------------------------------------
    # 8. Reconstruct and save the liquid mesh
    # --------------------------------------------------------

    if (not _settle_skip) and _settle_write and t == int(SETTLE_T) - 1:
        # 캐시에는 반드시 이 정착을 계산한 컵 배치를 같이 남긴다.
        # 이게 없으면 배치가 다른 궤적이 읽었을 때 물이 컵 밖에서 시작한다.
        os.makedirs(os.path.dirname(_SETTLE_CACHE), exist_ok=True)
        pp.save(_SETTLE_CACHE)
        pVel.save(_SETTLE_CACHE.replace('.uni', '_vel.uni'))
        with open(_SETTLE_META, 'w') as _sf:
            _json.dump({'cupCenterX':cupCenterX, 'cupBottom':cupBottom, 'cupCenterZ':cupCenterZ,
                        'water_level':WATER_LEVEL, 'gs':[gs.x,gs.y,gs.z], 'H':H,
                        'traj_file':TRAJ_FILE}, _sf, indent=2)
        print('[settle] 캐시 저장: %s (배치 x=%.1f y=%.1f z=%.1f)'
              % (_SETTLE_CACHE, cupCenterX, cupBottom, cupCenterZ), flush=True)
    if t < SETTLE_T or (round((t-SETTLE_T)/TFRAME)*TFRAME+SETTLE_T-t)**2 > 0.30:
        s.step(); continue
    gridParticleIndex(
        parts=pp,
        indexSys=pindex,
        flags=flags,
        index=gpi
    )

    improvedParticleLevelset(
        parts=pp,
        indexSys=pindex,
        flags=flags,
        index=gpi,
        phi=phi,
        radiusFactor=2.2,
        smoothen=3,
        smoothenNeg=3
    )

    # 재구성 커널이 표면을 바깥으로 밀어내는 것을 보정 (offset_test로 0.3 결정)
    phi.createMesh(mesh)

    meshPath = os.path.join(
        OUT,
        'mesh_%04d.bobj.gz' % t
    )

    mantaMsg(
        'Writing mesh: %s'
        % meshPath
    )

    mesh.save(meshPath)
    # ---- 컵 안팎 입자 수 세기 ----
    _gx,_gy,_gz = cup_pos(s.timeTotal)
    _ax,_ay,_az = cup_axis(s.timeTotal)
    _base = vec3(_gx+_ax*bottomThickness, _gy+_ay*bottomThickness, _gz+_az*bottomThickness)
    _n_in = countParticlesInCup(parts=pp, base=_base, axis=vec3(_ax,_ay,_az),
                                innerR=innerRadius, height=cupHeight-bottomThickness)
    print('PARTCOUNT %d %d %d' % (t, _n_in, pp.pySize()), flush=True)
    pp.save(meshPath.replace('mesh_','parts_').replace('.bobj.gz','.uni'))


    # --------------------------------------------------------
    # 9. Advance solver time
    # --------------------------------------------------------

    s.step()


mantaMsg(
    'Simulation finished. Initial particles=%d, final particles=%d'
    % (
        initialParticleCount,
        pp.pySize()
    )
)

# ---- 소요 시간 기록 ----
_dt=_time.time()-_t_start
import csv as _csv, datetime as _dtm
_log=os.path.expanduser('~/water_cup/timing_log.csv')
_new=not os.path.exists(_log)
with open(_log,'a',newline='') as _f:
    _w=_csv.writer(_f)
    if _new: _w.writerow(['datetime','scenario','stage','seconds','detail'])
    _w.writerow([_dtm.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 os.path.basename(OUT).replace('idp_',''),'sim',f'{_dt:.0f}',
                 f'traj={NT}f water={WATER_LEVEL*1000:.0f}mm sim={TOTAL}f'])
print(f'[timing] sim: {_dt/60:.1f}분', flush=True)
