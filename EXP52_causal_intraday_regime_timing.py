"""EXP52 — Causal Intraday Regime Timing Family.

Replays the exact frozen EXP49 backbone, then tests a genuinely new TRAIN-only
binary EXIT hazard family built only from causal BRT-day/session context available
at state_time. No corridor geometry timing predictor, no Dwell, no refit on OOS,
no recalibration, Exp27 untouched.
"""
from pathlib import Path
import contextlib, io, runpy, time
import numpy as np
import pandas as pd

BOOT_REPS=10000
SEED=52000
EPS=1e-12

t0=time.perf_counter()
here=Path(__file__).resolve().parent
exp49=here/'EXP49_symmetric_boundary_timing.py'
if not exp49.exists():
    raise FileNotFoundError(exp49)

buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    ns=runpy.run_path(str(exp49))

if ns.get('formal_status')!='FAIL':
    raise RuntimeError(f"EXP52 expected preserved EXP49 FAIL, got {ns.get('formal_status')}")
if not bool(ns.get('joint_identifiable',False)):
    raise RuntimeError('EXP52 expected EXP49 JOINT4 identifiability PASS')

HORIZONS=tuple(ns['HORIZONS'])
MAX_STEP=int(ns['MAX_STEP'])
JOINT_ENVS=tuple(ns['JOINT_ENVS'])
ADVANCE=int(ns['ADVANCE']); RECAPTURE=int(ns['RECAPTURE'])
fit_binary_logit=ns['fit_binary_logit']
sigmoid=ns['sigmoid']
binary_row_loss=ns['binary_row_loss']
whole_day_bootstrap=ns['whole_day_bootstrap']
auc_score=ns['auc_score']
holm_adjust=ns['holm_adjust']

# Exact frozen backbone objects from EXP49.
dyn=ns['dyn'].copy()
hazard=ns['hazard'].copy()
cells=ns['cells'].copy()
m5q=ns['m5q'].copy()
base_beta=np.asarray(ns['models']['BASE_EXIT']['beta'],float)
base_cell_pred=np.asarray(ns['cell_exit_predictions']['BASE_EXIT'],float)

print('='*132)
print('EXP52 — CAUSAL INTRADAY REGIME TIMING FAMILY')
print('='*132)
print('Frozen EXP49 replay = PASS')
print('EXP49_FORMAL_STATUS = PRESERVED_FAIL')
print('EXP49_JOINT4_IDENTIFIABILITY = PASS')
print('EXP51_FORMAL_STATUS = PRESERVED_UNDERPOWERED_WITHIN_DAY_CELL')
print('EXP47_ROBUST_MINIMAL_CORRIDOR_EQUATION_STATUS = PRESERVED_PASS')
print('EXP27 = UNTOUCHED')
print('RUNTIME_PROMOTION = NONE')

# -----------------------------------------------------------------------------
# Frozen causal BRT-day features. Every quantity uses only M5 bars at/before t.
# -----------------------------------------------------------------------------
m=m5q[['available_at_brt','open','high','low','close','ATR']].copy()
for c in ('open','high','low','close','ATR'):
    m[c]=pd.to_numeric(m[c],errors='coerce')
m['available_at_brt']=pd.to_datetime(m['available_at_brt'])
m['brt_date']=m['available_at_brt'].dt.date
minute=(m['available_at_brt'].dt.hour*60+m['available_at_brt'].dt.minute).to_numpy(float)
m['TOD_SIN']=np.sin(2*np.pi*minute/1440.0)
m['TOD_COS']=np.cos(2*np.pi*minute/1440.0)

g=m.groupby('brt_date',sort=False)
day_open=g['open'].transform('first')
cum_high=g['high'].cummax()
cum_low=g['low'].cummin()
prev_close=g['close'].shift(1)
step_path=np.where(prev_close.notna(),np.abs(m['close']-prev_close),np.abs(m['close']-m['open']))
m['DAY_PATH_PX']=pd.Series(step_path,index=m.index).groupby(m['brt_date'],sort=False).cumsum()
m['DAY_RANGE_PX']=cum_high-cum_low

atr=m['ATR'].to_numpy(float)
if (~np.isfinite(atr)).any() or (atr<=0).any():
    # Only state rows must have valid ATR; M5 history can contain warmup NaNs.
    pass
valid_atr=np.isfinite(atr)&(atr>0)
m['LOG_DAY_RANGE_ATR']=np.nan
m['LOG_DAY_PATH_ATR']=np.nan
m.loc[valid_atr,'LOG_DAY_RANGE_ATR']=np.log1p(m.loc[valid_atr,'DAY_RANGE_PX'].to_numpy(float)/atr[valid_atr])
m.loc[valid_atr,'LOG_DAY_PATH_ATR']=np.log1p(m.loc[valid_atr,'DAY_PATH_PX'].to_numpy(float)/atr[valid_atr])
path=m['DAY_PATH_PX'].to_numpy(float)
disp=np.abs(m['close'].to_numpy(float)-day_open.to_numpy(float))
eff=np.zeros(len(m),float)
pos=path>0
eff[pos]=disp[pos]/path[pos]
if np.nanmax(eff)>1.00000001 or np.nanmin(eff)<-1e-12:
    raise RuntimeError(f'DAY_EFFICIENCY invariant failed: range={np.nanmin(eff)}..{np.nanmax(eff)}')
m['DAY_EFFICIENCY']=np.clip(eff,0.0,1.0)

FEATURES=('TOD_SIN','TOD_COS','LOG_DAY_RANGE_ATR','LOG_DAY_PATH_ATR','DAY_EFFICIENCY')
fm=m[['available_at_brt',*FEATURES]].rename(columns={'available_at_brt':'state_time'})
if not fm['state_time'].is_unique:
    dup=fm.loc[fm['state_time'].duplicated(keep=False),'state_time'].head().tolist()
    raise RuntimeError(f'EXP52 M5 feature map state_time is not unique: {dup}')

dyn2=dyn.copy()
dyn2['state_id']=np.arange(len(dyn2),dtype=int)
_n_dyn_before=len(dyn2)
dyn2=dyn2.merge(fm,on='state_time',how='left',validate='many_to_one')
if len(dyn2)!=_n_dyn_before or dyn2['state_id'].nunique()!=_n_dyn_before:
    raise RuntimeError(
        f'EXP52 state mapping cardinality changed: before={_n_dyn_before} '
        f'after={len(dyn2)} unique_state_id={dyn2["state_id"].nunique()}'
    )
if dyn2[list(FEATURES)].isna().any().any() or not np.isfinite(dyn2[list(FEATURES)].to_numpy(float)).all():
    bad=dyn2.loc[dyn2[list(FEATURES)].isna().any(axis=1),['state_time',*FEATURES]].head()
    raise RuntimeError(f'EXP52 causal feature mapping failed:\n{bad}')

state_feature_map=dyn2[['state_id',*FEATURES]].copy()
hazard2=hazard.merge(state_feature_map,on='state_id',how='left',validate='many_to_one')
cells2=cells.merge(state_feature_map,on='state_id',how='left',validate='many_to_one')
if hazard2[list(FEATURES)].isna().any().any() or cells2[list(FEATURES)].isna().any().any():
    raise RuntimeError('EXP52 feature join failed')

# Preserve exact frozen joint environments from EXP49.
if 'joint_env' not in cells2:
    raise RuntimeError('EXP52 missing frozen joint_env')

MODEL_FEATURES={
    'TOD_EXIT':('TOD_SIN','TOD_COS'),
    'RANGE_EXIT':('LOG_DAY_RANGE_ATR',),
    'PATH_EXIT':('LOG_DAY_PATH_ATR',),
    'EFF_EXIT':('DAY_EFFICIENCY',),
    'JOINT5_EXIT':FEATURES,
    'DROP_TOD':('LOG_DAY_RANGE_ATR','LOG_DAY_PATH_ATR','DAY_EFFICIENCY'),
    'DROP_RANGE':('TOD_SIN','TOD_COS','LOG_DAY_PATH_ATR','DAY_EFFICIENCY'),
    'DROP_PATH':('TOD_SIN','TOD_COS','LOG_DAY_RANGE_ATR','DAY_EFFICIENCY'),
    'DROP_EFF':('TOD_SIN','TOD_COS','LOG_DAY_RANGE_ATR','LOG_DAY_PATH_ATR'),
}

def design(q,feats):
    steps=q['step'].to_numpy(int)
    d=np.eye(MAX_STEP,dtype=float)[steps-1]
    return d if not feats else np.column_stack([d,q[list(feats)].to_numpy(float)])

def predict_cumulative(states,feats,beta):
    n=len(states); surv=np.ones(n,float); out={}
    F=None if not feats else states[list(feats)].to_numpy(float)
    for step in range(1,MAX_STEP+1):
        d=np.zeros((n,MAX_STEP),float); d[:,step-1]=1.0
        X=d if F is None else np.column_stack([d,F])
        h=sigmoid(np.clip(X@beta,-35,35))
        if not np.isfinite(h).all(): raise RuntimeError('Non-finite hazard')
        surv*=1.0-h
        hm=step*5
        if hm in HORIZONS: out[hm]=(1.0-surv).copy()
    return out

def to_cells(pred_by_h):
    out=np.empty(len(cells2),float)
    for h in HORIZONS:
        mask=cells2['horizon'].eq(h).to_numpy(bool)
        ids=cells2.loc[mask,'state_id'].to_numpy(int)
        out[mask]=pred_by_h[h][ids]
    return out

print('\n'+'='*132)
print('EXP52 TRAIN-ONLY FEATURE CORRELATION / IDENTIFIABILITY DIAGNOSTIC')
print('='*132)
train_states=dyn2.loc[dyn2['period'].eq('TRAIN'),list(FEATURES)]
print(train_states.corr().to_string(float_format=lambda v:f'{v:+.6f}'))
Xf=train_states.to_numpy(float)
rank=int(np.linalg.matrix_rank(Xf))
std=Xf.std(axis=0,ddof=0)
scaled=(Xf-Xf.mean(axis=0))/np.where(std>0,std,1.0)
cond=float(np.linalg.cond(scaled))
print(f'\nTRAIN feature rank = {rank}/{len(FEATURES)}')
print(f'TRAIN standardized feature condition number = {cond:.6e}')

train_h=hazard2.loc[hazard2['period'].eq('TRAIN')].copy().reset_index(drop=True)
y_step=train_h['label'].isin([ADVANCE,RECAPTURE]).astype(int).to_numpy()
models={
    'BASE_EXIT':{
        'beta':base_beta,'converged':True,'finite':bool(np.isfinite(base_beta).all()),
        'full_rank':True,'rank':MAX_STEP,'cols':MAX_STEP,'features':()
    }
}
print('\n'+'='*132)
print('EXP52 TRAIN-ONLY BINARY EXIT HAZARD FITS')
print('='*132)
print(f"{'BASE_EXIT':<12} cols={MAX_STEP:>2} rank={MAX_STEP:>2} frozen=True")
for name,feats in MODEL_FEATURES.items():
    X=design(train_h,feats)
    r=int(np.linalg.matrix_rank(X))
    beta,it,conv=fit_binary_logit(X,y_step)
    finite=bool(np.isfinite(beta).all()); full=bool(r==X.shape[1])
    models[name]={'beta':beta,'converged':conv,'finite':finite,'full_rank':full,'rank':r,'cols':X.shape[1],'features':feats}
    print(f'{name:<12} cols={X.shape[1]:>2} rank={r:>2} iter={it:>3} converged={conv} finite={finite} full_rank={full}')

joint_identifiable=bool(models['JOINT5_EXIT']['converged'] and models['JOINT5_EXIT']['finite'] and models['JOINT5_EXIT']['full_rank'])
print('\nEXP52_JOINT5_IDENTIFIABILITY =','PASS' if joint_identifiable else 'FAIL')

# Predictions.
pred={'BASE_EXIT':base_cell_pred.copy()}
for name,info in models.items():
    if name=='BASE_EXIT': continue
    byh=predict_cumulative(dyn2,info['features'],info['beta'])
    pred[name]=to_cells(byh)

T=cells2.copy()
T['y_exit']=T['label'].isin([ADVANCE,RECAPTURE]).astype(int)
for name,p in pred.items():
    if not np.isfinite(p).all() or (p<-1e-12).any() or (p>1+1e-12).any():
        raise RuntimeError(f'Invalid probability {name}')
    T[f'p_{name.lower()}']=np.clip(p,0,1)

print('\n'+'='*132)
print('EXP52 EXIT / NO-EXIT ENVIRONMENT SCORABILITY')
print('='*132)
scorable={}; all_scorable=True
for env in JOINT_ENVS:
    q=T.loc[T['joint_env'].eq(env)]
    ne=int(q['y_exit'].sum()); nn=len(q)-ne; days=int(q['brt_date'].nunique())
    ok=bool(ne>0 and nn>0 and days>=2)
    scorable[env]=ok; all_scorable=all_scorable and ok
    print(f'{env:<31} cells={len(q):>5} EXIT={ne:>5} NO_EXIT={nn:>5} days={days:>3} SCORABLE={ok}')
print('\nEXP52_EXIT_ENVIRONMENT_STATUS =','PASS' if all_scorable else 'UNDERPOWERED_EXIT_ENVIRONMENT')

# Marginal frozen block diagnostics + Holm 64 tests.
print('\n'+'='*132)
print('EXP52 MARGINAL BLOCK DIAGNOSTICS — HOLM-AWARE, NOT FORMAL')
print('='*132)
marginals=('TOD_EXIT','RANGE_EXIT','PATH_EXIT','EFF_EXIT')
rows=[]
for mi,name in enumerate(marginals,1):
    for ei,env in enumerate(JOINT_ENVS,1):
        q=T.loc[T['joint_env'].eq(env)].copy(); y=q['y_exit'].to_numpy(int)
        qb=q['p_base_exit'].to_numpy(float); qm=q[f'p_{name.lower()}'].to_numpy(float)
        for li,loss in enumerate(('brier','logloss'),1):
            gain=binary_row_loss(y,qb,loss)-binary_row_loss(y,qm,loss)
            r=whole_day_bootstrap(q,gain,SEED+100000+mi*10000+ei*100+li)
            day=pd.DataFrame({'day':q['brt_date'].to_numpy(),'gain':gain}).groupby('day',sort=True).agg(gain_sum=('gain','sum'),n=('gain','size'))
            sums=day['gain_sum'].to_numpy(float); n=day['n'].to_numpy(float)
            rng=np.random.default_rng(SEED+200000+mi*10000+ei*100+li)
            ix=rng.integers(0,len(day),size=(BOOT_REPS,len(day)))
            boot=sums[ix].sum(1)/n[ix].sum(1)
            praw=float((1+np.sum(boot<=0))/(BOOT_REPS+1))
            rows.append({'model':name,'env':env,'loss':loss,'gain':r['point'],'lo':r['lo'],'hi':r['hi'],'p_raw':praw})
adj=holm_adjust([x['p_raw'] for x in rows])
for x,a in zip(rows,adj): x['p_holm']=float(a)
for name in marginals:
    print('\n'+name)
    for x in rows:
        if x['model']==name:
            print(f"  {x['env']:<31} {x['loss']:<7} Gain={x['gain']:+.7f} CI95=[{x['lo']:+.7f},{x['hi']:+.7f}] p_raw={x['p_raw']:.5f} p_Holm={x['p_holm']:.5f}")

print('\n'+'='*132)
print('EXP52 JOINT5 HORIZON POINT GAINS — DIAGNOSTIC ONLY')
print('='*132)
for env in JOINT_ENVS:
    print('\n'+env)
    for h in HORIZONS:
        q=T.loc[T['joint_env'].eq(env)&T['horizon'].eq(h)]
        y=q['y_exit'].to_numpy(int); qb=q['p_base_exit'].to_numpy(float); qj=q['p_joint5_exit'].to_numpy(float)
        gb=float(binary_row_loss(y,qb,'brier').mean()-binary_row_loss(y,qj,'brier').mean())
        gl=float(binary_row_loss(y,qb,'logloss').mean()-binary_row_loss(y,qj,'logloss').mean())
        print(f'  H={h:>3}m n={len(q):>5} JOINT5-BASE Brier={gb:+.6f} LL={gl:+.6f}')

print('\n'+'='*132)
print('EXP52 PRIMARY INTRADAY-REGIME TIMING FAMILY INFERENCE')
print('JOINT5_EXIT vs BASE_EXIT | EXIT_STATE_HORIZON_WEIGHTED | whole-BRT-day bootstrap')
print('='*132)
gate=bool(all_scorable and joint_identifiable)
primary={}
for ei,env in enumerate(JOINT_ENVS,1):
    q=T.loc[T['joint_env'].eq(env)].copy(); y=q['y_exit'].to_numpy(int)
    qb=q['p_base_exit'].to_numpy(float); qj=q['p_joint5_exit'].to_numpy(float)
    print('\n'+env)
    if not scorable[env]:
        gate=False; print('  UNDERPOWERED_EXIT_ENVIRONMENT'); continue
    for li,loss in enumerate(('brier','logloss'),1):
        gain=binary_row_loss(y,qb,loss)-binary_row_loss(y,qj,loss)
        r=whole_day_bootstrap(q,gain,SEED+ei*100+li)
        passed=bool(r['lo']>0)
        gate=gate and passed; primary[(env,loss)]=r
        print(f"  {loss:<7} cells={r['cells']:>5} days={r['days']:>3} Gain={r['point']:+.9f} CI95=[{r['lo']:+.9f},{r['hi']:+.9f}] P(gain>0)={r['p']*100:6.2f}% PASS={passed}")

print('\n'+'='*132)
print('EXP52 DROP-ONE FROM JOINT5 — DIAGNOSTIC ONLY')
print('='*132)
for period in ('VALIDATION','TEST'):
    print('\n'+period)
    q=T.loc[T['period'].eq(period)].copy(); y=q['y_exit'].to_numpy(int); qj=q['p_joint5_exit'].to_numpy(float)
    for di,name in enumerate(('DROP_TOD','DROP_RANGE','DROP_PATH','DROP_EFF'),1):
        qd=q[f'p_{name.lower()}'].to_numpy(float)
        for li,loss in enumerate(('brier','logloss'),1):
            gain=binary_row_loss(y,qd,loss)-binary_row_loss(y,qj,loss)
            r=whole_day_bootstrap(q,gain,SEED+300000+(1 if period=='VALIDATION' else 2)*1000+di*10+li)
            print(f"  drop={name:<10} {loss:<7} JointMinusDrop Gain={r['point']:+.8f} CI95=[{r['lo']:+.8f},{r['hi']:+.8f}]")

print('\n'+'='*132)
print('EXP52 JOINT5 EXIT AUC / CALIBRATION — DIAGNOSTIC ONLY')
print('='*132)
for env in JOINT_ENVS:
    print('\n'+env)
    for h in HORIZONS:
        q=T.loc[T['joint_env'].eq(env)&T['horizon'].eq(h)]
        y=q['y_exit'].to_numpy(int); pj=q['p_joint5_exit'].to_numpy(float)
        a=auc_score(y,pj); obs=float(y.mean()); mp=float(pj.mean())
        print(f'  H={h:>3}m AUC={a:.4f} EXIT obs/joint={obs:.4f}/{mp:.4f} cal_gap={mp-obs:+.4f}')

if not all_scorable:
    status='UNDERPOWERED_EXIT_ENVIRONMENT'; robust=False
elif not joint_identifiable:
    status='FAIL'; robust=False
else:
    robust=bool(gate); status='PASS' if robust else 'FAIL'

print('\n'+'='*132)
print('EXP52 FORMAL VERDICT')
print('='*132)
print('EXP52_EXIT_ENVIRONMENT_STATUS =','PASS' if all_scorable else 'UNDERPOWERED_EXIT_ENVIRONMENT')
print('EXP52_JOINT5_IDENTIFIABILITY =','PASS' if joint_identifiable else 'FAIL')
print('INTRADAY_REGIME_TIMING_FAMILY =',status)
print('ROBUST_INTRADAY_EXIT_CLOCK_CONTEXT =',status)
print('EXP52_FORMAL_STATUS =',status)
print('EXP51_FORMAL_STATUS = PRESERVED_UNDERPOWERED_WITHIN_DAY_CELL')
print('EXP50_FORMAL_STATUS = PRESERVED_UNDERPOWERED_RANKING_CELL')
print('EXP49_FORMAL_STATUS = PRESERVED_FAIL')
print('EXP48_POSITION_EXIT_CLOCK_STATUS = PRESERVED_FAIL')
print('EXP47_ROBUST_MINIMAL_CORRIDOR_EQUATION_STATUS = PRESERVED_PASS')
print('EXP45_ROBUST_WHICH_SIDE_LAW_STATUS = PRESERVED_PASS')
print('EXP44_ROBUST_POSITION_CORE_STATUS = PRESERVED_PASS')
print('EXP27 = UNTOUCHED')
print('RUNTIME_PROMOTION = NONE')

print('\n'+'='*132)
print('FROZEN INTERPRETATION RULES')
print('='*132)
for line in [
'1) Exp52 is a genuinely new causal intraday-regime timing family, not a geometry rescue.',
'2) Exact frozen Exp49 backbone is replayed first; any reproduction failure aborts before score.',
'3) Features use only M5 information available at or before state_time within the same BRT day.',
'4) TOD is a two-column block: sin/cos minute-of-day; range/path are ATR-normalized cumulative day statistics; efficiency is directional path efficiency.',
'5) All hazard models use the same 24 elapsed-future-step intercepts and TRAIN-only fitting.',
'6) JOINT5 numerical identifiability requires full TRAIN design rank, convergence and finite coefficients.',
'7) Marginal Holm family is 4 candidate blocks x 8 environments x 2 metrics = 64 diagnostic tests.',
'8) Formal comparison is JOINT5 vs exact BASE_EXIT on EXIT_STATE_HORIZON_WEIGHTED cells.',
'9) Formal PASS requires Brier and LogLoss CI95 lower bound >0 in all 8 environments = 16/16.',
'10) No corridor geometry timing predictor, no Dwell, no signed Position timing predictor.',
'11) No future/day-complete statistic, alternate day boundary, added feature, transform, subset, horizon/environment drop or OOS refit.',
'12) Diagnostics cannot rescue a formal failure; Exp44/45/47 remain preserved; Exp27 untouched; runtime NONE.',
]: print(line)

print(f'\nFINALIZADO em {time.perf_counter()-t0:.2f}s')
