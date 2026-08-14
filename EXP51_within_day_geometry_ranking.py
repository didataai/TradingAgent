"""EXP51 — Within-Day Exit-Risk Geometry Transport."""
from pathlib import Path
import contextlib, io, runpy, time
import numpy as np
import pandas as pd

BOOT_REPS=10000; MIN_VALID_BOOT=9500; AUC_NULL=.5; SEED=51000
EXPECTED={
('VALIDATION_EARLY__FULL_UP',15):.789923,('VALIDATION_EARLY__FULL_UP',30):.774640,('VALIDATION_EARLY__FULL_UP',60):.774083,('VALIDATION_EARLY__FULL_UP',120):.802855,
('VALIDATION_EARLY__FULL_DOWN',15):.800206,('VALIDATION_EARLY__FULL_DOWN',30):.784846,('VALIDATION_EARLY__FULL_DOWN',60):.748538,('VALIDATION_EARLY__FULL_DOWN',120):.794166,
('VALIDATION_LATE__FULL_UP',15):.880961,('VALIDATION_LATE__FULL_UP',30):.850086,('VALIDATION_LATE__FULL_UP',60):.818551,('VALIDATION_LATE__FULL_UP',120):.804540,
('VALIDATION_LATE__FULL_DOWN',15):.734634,('VALIDATION_LATE__FULL_DOWN',30):.749896,('VALIDATION_LATE__FULL_DOWN',60):.849280,('VALIDATION_LATE__FULL_DOWN',120):.940767,
('TEST_EARLY__FULL_UP',15):.876404,('TEST_EARLY__FULL_UP',30):.910551,('TEST_EARLY__FULL_UP',60):.957189,('TEST_EARLY__FULL_UP',120):.982553,
('TEST_EARLY__FULL_DOWN',15):.881788,('TEST_EARLY__FULL_DOWN',30):.874239,('TEST_EARLY__FULL_DOWN',60):.891534,('TEST_EARLY__FULL_DOWN',120):.885324,
('TEST_LATE__FULL_UP',15):.750796,('TEST_LATE__FULL_UP',30):.714628,('TEST_LATE__FULL_UP',60):.696966,('TEST_LATE__FULL_UP',120):.822139,
('TEST_LATE__FULL_DOWN',15):.811529,('TEST_LATE__FULL_DOWN',30):.791016,('TEST_LATE__FULL_DOWN',60):.768327,('TEST_LATE__FULL_DOWN',120):.817401,
}
t0=time.perf_counter(); here=Path(__file__).resolve().parent; p=here/'EXP50_geometry_exit_ranking.py'
if not p.exists(): raise FileNotFoundError(p)
b=io.StringIO()
try:
    with contextlib.redirect_stdout(b): ctx=runpy.run_path(str(p),run_name='__exp50_replay__')
except Exception:
    print('\n'.join(b.getvalue().splitlines()[-100:])); raise
for k in ('timing','JOINT_ENVS','HORIZONS','results','n_pass','all_boot_scorable','all_cells_scorable','ranking_status','ctx'):
    if k not in ctx: raise RuntimeError(f'EXP51 missing Exp50 object {k}')
if int(ctx['n_pass'])!=22 or bool(ctx['ranking_status']) or bool(ctx['all_boot_scorable']):
    raise RuntimeError('EXP51 ABORT: frozen EXP50 status did not reproduce')
if not bool(ctx['ctx']['joint_identifiable']): raise RuntimeError('EXP49 identifiability replay failed')
timing=ctx['timing'].copy(); ENVS=tuple(ctx['JOINT_ENVS']); HS=tuple(ctx['HORIZONS']); r50=ctx['results'].copy()
if len(ENVS)!=8 or HS!=(15,30,60,120): raise RuntimeError('environment/horizon reproduction failed')
for x in r50.itertuples(index=False):
    exp=EXPECTED[(x.env,int(x.horizon))]
    if abs(float(x.point)-exp)>5e-7: raise RuntimeError(f'EXP50 point AUC mismatch {x.env} H={x.horizon}')
print('='*132); print('EXP51 — WITHIN-DAY EXIT-RISK GEOMETRY TRANSPORT'); print('='*132)
print('Frozen EXP50 replay = PASS'); print('EXP50_FORMAL_STATUS = PRESERVED_UNDERPOWERED_RANKING_CELL'); print('EXP49_FORMAL_STATUS = PRESERVED_FAIL'); print('EXP49_JOINT4_IDENTIFIABILITY = PASS'); print('EXP27 = UNTOUCHED'); print('RUNTIME_PROMOTION = NONE')

def auc(y,s):
    y=np.asarray(y,int); s=np.asarray(s,float); n1=(y==1).sum(); n0=(y==0).sum()
    if n1==0 or n0==0:return np.nan
    o=np.argsort(s,kind='mergesort'); y=y[o]; s=s[o]; u=0.; nb=0.; i=0
    while i<len(y):
        j=i+1
        while j<len(y) and s[j]==s[i]: j+=1
        p=(y[i:j]==1).sum(); n=(y[i:j]==0).sum(); u+=p*(nb+.5*n); nb+=n; i=j
    return float(u/(n1*n0))

def daystats(q):
    z=[]
    for d,g in q.groupby('brt_date',sort=True):
        y=g.y_exit.to_numpy(int); s=g.p_joint4_exit.to_numpy(float); n1=(y==1).sum(); n0=(y==0).sum(); pairs=float(n1*n0)
        a=auc(y,s) if pairs else np.nan
        z.append((d,pairs,0. if not pairs else a*pairs,a,float(s.mean()),float(y.mean())))
    return pd.DataFrame(z,columns=['day','pairs','u','day_auc','mean_score','exit_rate'])

def boot(ds,seed):
    u=ds.u.to_numpy(float); pairs=ds.pairs.to_numpy(float); nd=len(ds); den=pairs.sum(); point=float(ds.u.sum()/den) if den>0 else np.nan
    rng=np.random.default_rng(seed); vals=[]; probs=np.full(nd,1/nd)
    for start in range(0,BOOT_REPS,1000):
        n=min(1000,BOOT_REPS-start); m=rng.multinomial(nd,probs,size=n).astype(float); bd=m@pairs; ok=bd>0
        if ok.any(): vals.append((m@u)[ok]/bd[ok])
    vv=np.concatenate(vals) if vals else np.empty(0)
    return point,(float(np.quantile(vv,.025)) if len(vv) else np.nan),(float(np.quantile(vv,.975)) if len(vv) else np.nan),len(vv)

print(); print('='*132); print('EXP51 CELL STRUCTURE / PRIMARY INFERENCE'); print('='*132)
rows=[]; pre=True; ep=0
for ei,e in enumerate(ENVS,1):
    for hi,h in enumerate(HS,1):
        q=timing.loc[timing.joint_env.eq(e)&timing.horizon.eq(h)].copy(); ds=daystats(q); mixed=int((ds.pairs>0).sum()); days=len(ds); y=q.y_exit.to_numpy(int)
        pooled=auc(y,q.p_joint4_exit.to_numpy(float)); preok=bool((y==1).any() and (y==0).any() and days>=2 and mixed>=2); pre=pre and preok
        if preok: point,lo,hi95,valid=boot(ds,SEED+ei*1000+hi)
        else: point=lo=hi95=np.nan; valid=0
        bsc=valid>=MIN_VALID_BOOT; passed=bool(preok and bsc and np.isfinite(lo) and lo>AUC_NULL); ep+=int(passed)
        dayeq=float(ds.loc[ds.pairs>0,'day_auc'].mean()) if mixed else np.nan
        corr=float(np.corrcoef(ds.mean_score,ds.exit_rate)[0,1]) if days>=2 and ds.mean_score.std()>0 and ds.exit_rate.std()>0 else np.nan
        print(f'{e:<31} H={h:>3}m WITHIN_AUC={point:.6f} CI95=[{lo:.6f},{hi95:.6f}] mixed_days={mixed:>3}/{days:<3} valid_boot={valid:>5}/{BOOT_REPS} pooledAUC={pooled:.6f} dayEqAUC={dayeq:.6f} dayRegimeR={corr:+.4f} PASS={passed}')
        rows.append((e,h,days,mixed,pooled,point,lo,hi95,valid,passed))
R=pd.DataFrame(rows,columns=['env','horizon','days','mixed_days','pooled_auc','within_auc','lo','hi','valid','pass'])
allboot=bool((R.valid>=MIN_VALID_BOOT).all()); full=bool(pre and allboot and ep==32)
status='PASS' if full else ('UNDERPOWERED_WITHIN_DAY_CELL' if (not pre or not allboot) else 'FAIL')
print(); print('='*132); print('EXP51 FORMAL VERDICT'); print('='*132)
print('EXP51_WITHIN_DAY_CELL_STATUS =', 'PASS' if pre and allboot else 'UNDERPOWERED_WITHIN_DAY_CELL')
print(f'EXP51_FORMAL_CELLS_PASS = {ep}/32')
print('WITHIN_DAY_GEOMETRY_RANKING_TRANSPORT =', status)
print('ROBUST_WITHIN_DAY_EXIT_URGENCY_ORDERING =', status)
print('EXP51_FORMAL_STATUS =', status)
print('EXP50_FORMAL_STATUS = PRESERVED_UNDERPOWERED_RANKING_CELL'); print('EXP49_TIMING_GEOMETRY_FAMILY_STATUS = PRESERVED_FAIL'); print('EXP47_ROBUST_MINIMAL_CORRIDOR_EQUATION_STATUS = PRESERVED_PASS'); print('EXP45_ROBUST_WHICH_SIDE_LAW_STATUS = PRESERVED_PASS'); print('EXP44_ROBUST_POSITION_CORE_STATUS = PRESERVED_PASS'); print('EXP27 = UNTOUCHED'); print('RUNTIME_PROMOTION = NONE')
print(); print('='*132); print('FROZEN INTERPRETATION RULES'); print('='*132)
for x in [
'1) Same original TRAIN-fitted JOINT4_EXIT; no refit/recalibration/new feature.',
'2) Only same-BRT-day EXIT-vs-NO_EXIT pairs enter the formal concordance numerator/denominator.',
'3) Days with one class contribute zero pairs but remain in the whole-day bootstrap universe.',
'4) Cell requires both classes overall, >=2 days, >=2 mixed-class days, >=9500 valid bootstraps.',
'5) Formal PASS requires CI95 lower bound >0.5 in all 32 environment×horizon cells.',
'6) Pooled AUC, day-equal AUC and day-regime correlation are diagnostic only.',
'7) PASS would establish same-day urgency ordering only; it cannot reverse Exp49/Exp50.',
'8) No dropped day/horizon/environment, alternate AUC, feature subset/transform, threshold or Validation/TEST refit.',
'9) Exp27 untouched; historical OOS exploratory; runtime promotion NONE.'
]: print(x)
print(); print(f'FINALIZADO em {time.perf_counter()-t0:.2f}s')