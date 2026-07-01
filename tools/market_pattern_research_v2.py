#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa de figuras clássicas com contexto estrutural HTF.
Leis -> figura -> nível HTF -> microconfirmação. Não publica leis.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DEFAULT_INPUT="data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_FALLBACK="data/{symbol}_{tf}.parquet"
DEFAULT_OUTPUT="data/market_chronos/{symbol}/patterns/research_v2"
TF_MINUTES={"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}

def log(m): print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}",flush=True)
def clean(v:Any)->Any:
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [clean(x) for x in v]
    if isinstance(v,(pd.Timestamp,datetime)): return v.isoformat()
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v); return None if not math.isfinite(x) else round(x,8)
    if isinstance(v,np.bool_): return bool(v)
    return v
def save_json(p,payload): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(clean(payload),ensure_ascii=False,indent=2),encoding="utf-8")
def normalize_time(df):
    o=df.copy()
    if "event_time" not in o.columns:
        c=next((x for x in ("time","datetime","timestamp","date_time","date","open_time") if x in o.columns),None)
        if c:o=o.rename(columns={c:"event_time"})
        elif isinstance(o.index,pd.DatetimeIndex): n=o.index.name or "index";o=o.reset_index().rename(columns={n:"event_time"})
        else: raise ValueError("coluna temporal não encontrada")
    o.event_time=pd.to_datetime(o.event_time,errors="coerce");return o.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)
def number(df,c): return pd.to_numeric(df[c],errors="coerce") if c in df.columns else pd.Series(np.nan,index=df.index)
def bool_series(df,c):
    if c not in df.columns:return pd.Series(False,index=df.index)
    s=df[c]
    if pd.api.types.is_bool_dtype(s):return s.fillna(False)
    if pd.api.types.is_numeric_dtype(s):return s.fillna(0).astype(int).astype(bool)
    return s.astype(str).str.lower().isin({"1","true","yes","sim"})
def finish_frame(o):
    o=o.reset_index(drop=True);tr=pd.concat([(o.high-o.low),(o.high-o.close.shift()).abs(),(o.low-o.close.shift()).abs()],axis=1).max(axis=1)
    o["atr"]=pd.to_numeric(o.atr,errors="coerce").fillna(tr.rolling(14,min_periods=5).mean());return o
def build_frame_from_mtf(raw,tf):
    p=f"{tf}_";req=[f"{p}{x}" for x in ("open","high","low","close")];miss=[x for x in req if x not in raw]
    if miss:raise ValueError("OHLC ausente: "+", ".join(miss))
    tc=next((c for c in (f"{p}event_time",f"{p}time",f"{p}datetime",f"{p}timestamp",f"{p}open_time") if c in raw),None)
    t=pd.to_datetime(raw[tc],errors="coerce") if tc else raw.event_time
    o=pd.DataFrame({"event_time":t,"open":number(raw,p+"open"),"high":number(raw,p+"high"),"low":number(raw,p+"low"),"close":number(raw,p+"close"),"atr":number(raw,p+"ATR") if p+"ATR" in raw else number(raw,p+"atr"),"vol_ratio":number(raw,p+"vol_ratio"),"breakout_up_existing":bool_series(raw,p+"breakout_up"),"breakout_down_existing":bool_series(raw,p+"breakout_down")}).dropna(subset=["event_time","open","high","low","close"])
    if tc:o=o.sort_values("event_time").drop_duplicates("event_time",keep="last")
    else:o=o.loc[o[["open","high","low","close"]].ne(o[["open","high","low","close"]].shift()).any(axis=1)]
    return finish_frame(o)
def build_frame_from_fallback(path:Path):
    r=normalize_time(pd.read_parquet(path));a={c.lower():c for c in r.columns};pick=lambda n:number(r,a[n]) if n in a else pd.Series(np.nan,index=r.index)
    o=pd.DataFrame({"event_time":r.event_time,"open":pick("open"),"high":pick("high"),"low":pick("low"),"close":pick("close"),"atr":pick("atr"),"vol_ratio":pick("vol_ratio"),"breakout_up_existing":bool_series(r,a.get("breakout_up","_")),"breakout_down_existing":bool_series(r,a.get("breakout_down","_"))}).dropna(subset=["event_time","open","high","low","close"])
    return finish_frame(o.sort_values("event_time").drop_duplicates("event_time",keep="last"))
def fit(v):
    x=np.arange(len(v),dtype=float);ok=np.isfinite(v)
    if ok.sum()<5:return np.nan,np.nan,np.nan
    s,i=np.polyfit(x[ok],v[ok],1);pred=s*x[ok]+i;ssr=np.sum((v[ok]-pred)**2);sst=np.sum((v[ok]-np.mean(v[ok]))**2)
    return float(s),float(i),float(1-ssr/sst if sst>0 else 1)
def classify(us,ls,c,w,ur,lr,a):
    if not all(np.isfinite(x) for x in (us,ls,c,w,ur,lr)) or min(ur,lr)<a.min_r2:return None
    uf,lf=abs(us)<=a.slope_flat,abs(ls)<=a.slope_flat;ud,lu=us<=-a.slope_directional,ls>=a.slope_directional
    if c>=a.min_compression:
        if ud and lu:return "TRIANGLE_SYMMETRIC"
        if uf and lu:return "TRIANGLE_ASCENDING"
        if ud and lf:return "TRIANGLE_DESCENDING"
    return "RANGE_BOX" if uf and lf and w<=a.max_range_width_atr else None
def outcomes(ev,f,hs):
    if ev.empty:return ev
    o=ev.copy();H=f.high.to_numpy(float);L=f.low.to_numpy(float);C=f.close.to_numpy(float)
    for h in hs:
        vals=[]
        for r in o.itertuples():
            i=int(r.bar_index);e=min(len(f),i+h+1);a=float(r.atr)
            if i+1>=e or not np.isfinite(a) or a<=0:vals.append((np.nan,np.nan,np.nan,False));continue
            hi,lo,last=np.nanmax(H[i+1:e]),np.nanmin(L[i+1:e]),C[e-1];entry=float(r.breakout_price)
            m,d,rr=((hi-entry)/a,(entry-lo)/a,(last-entry)/a) if r.breakout_side=="UP" else ((entry-lo)/a,(hi-entry)/a,(entry-last)/a)
            vals.append((m,d,rr,bool(m>=.5 and m>d)))
        o[[f"mfe_{h}_atr",f"mae_{h}_atr",f"return_{h}_atr",f"success_{h}"]]=pd.DataFrame(vals,index=o.index)
    return o
def detect(f,symbol,tf,a):
    E,S=[] ,[];H,L,C,A,V=[f[x].to_numpy(float) for x in ("high","low","close","atr","vol_ratio")];last=-999999
    for w in sorted(set(a.windows)):
        x=np.arange(w,dtype=float)
        for i in range(w-1,len(f)-max(a.horizons)-1):
            st=i-w+1;fa=A[st:i+1];fa=fa[np.isfinite(fa)&(fa>0)]
            if len(fa)==0:continue
            ar=float(np.median(fa));hs,ls=H[st:i+1],L[st:i+1];us,ui,ur=fit(hs);ds,di,dr=fit(ls)
            if not all(np.isfinite(z) for z in (us,ui,ds,di)):continue
            w0=ui-di;w1=(us*(w-1)+ui)-(ds*(w-1)+di)
            if w0<=0 or w1<=0:continue
            comp=1-w1/w0;pat=classify(us/ar,ds/ar,comp,w1/ar,ur,dr,a)
            if not pat:continue
            ut=np.sum(np.abs(hs-(us*x+ui))<=a.touch_tolerance_atr*ar);lt=np.sum(np.abs(ls-(ds*x+di))<=a.touch_tolerance_atr*ar)
            if min(ut,lt)<a.min_touches:continue
            n=i+1;na=A[n] if np.isfinite(A[n]) and A[n]>0 else ar;ub=us*w+ui;lb=ds*w+di;b=a.breakout_buffer_atr*na
            side="UP" if C[n]>ub+b else "DOWN" if C[n]<lb-b else None;q=float(np.clip(25*max(0,comp)+20*ur+20*dr+10*min(1,ut/4)+10*min(1,lt/4),0,100))
            base={"symbol":symbol,"timeframe":tf,"bar_index":i,"event_time":f.at[i,"event_time"],"pattern_type":pat,"window_bars":w,"compression_ratio":comp,"width_end_atr":w1/ar,"upper_slope_atr":us/ar,"lower_slope_atr":ds/ar,"upper_r2":ur,"lower_r2":dr,"upper_touches":int(ut),"lower_touches":int(lt),"quality_score":q}
            if side is None:S.append(base);continue
            if n<=last+max(2,w//5):continue
            last=n;bd=ub if side=="UP" else lb;future=C[n+1:min(len(f),n+a.false_break_horizon+1)];fb=bool(np.any(future<ub)) if side=="UP" and len(future) else bool(np.any(future>lb)) if len(future) else False
            rend=min(len(f),n+a.retest_horizon+1);tol=a.touch_tolerance_atr*na;rt=bool(np.any(np.abs(L[n+1:rend]-ub)<=tol)) if side=="UP" else bool(np.any(np.abs(H[n+1:rend]-lb)<=tol))
            E.append({**base,"pattern_id":f"{symbol}_{tf}_{pat}_{n}","bar_index":n,"formation_start_time":f.at[st,"event_time"],"formation_end_time":f.at[i,"event_time"],"breakout_time":f.at[n,"event_time"],"breakout_side":side,"breakout_price":C[n],"breakout_boundary":bd,"breakout_distance_atr":abs(C[n]-bd)/na,"breakout_volume_ratio":V[n],"atr":na,"false_breakout":fb,"retest":rt,"existing_breakout_flag":bool(f.at[n,"breakout_up_existing"] if side=="UP" else f.at[n,"breakout_down_existing"])})
    ev=pd.DataFrame(E)
    if not ev.empty:ev=outcomes(ev.sort_values(["breakout_time","quality_score"],ascending=[True,False]).drop_duplicates(["timeframe","breakout_time","breakout_side"]).reset_index(drop=True),f,sorted(set(a.horizons)))
    st=pd.DataFrame(S)
    if not st.empty:
        st=st.sort_values(["window_bars","pattern_type","bar_index"]);st["episode_id"]=st.groupby(["window_bars","pattern_type"])["bar_index"].diff().fillna(999).gt(1).groupby([st.window_bars,st.pattern_type]).cumsum();st=st.sort_values("quality_score").groupby(["window_bars","pattern_type","episode_id"],as_index=False).tail(1).sort_values("event_time").reset_index(drop=True)
    return ev,st
def swings(f,side,l,r):
    v=f.high.to_numpy(float) if side=="UP" else f.low.to_numpy(float);rows=[]
    for i in range(l,len(f)-r):
        ok=v[i]>=np.nanmax(v[i-l:i]) and v[i]>np.nanmax(v[i+1:i+r+1]) if side=="UP" else v[i]<=np.nanmin(v[i-l:i]) and v[i]<np.nanmin(v[i+1:i+r+1])
        if ok:rows.append((f.at[i,"event_time"],f.at[i+r,"event_time"],float(v[i])))
    return pd.DataFrame(rows,columns=["event_time","confirm_time","level"])
def relation(level,boundary,side,atr,tol,obs):
    d=abs(level-boundary)/atr if np.isfinite(level) and atr>0 else np.nan
    if not np.isfinite(d):return "UNAVAILABLE",d
    if d<=tol:return "ALIGNED_WITH_BREAKOUT",d
    ahead=level>boundary if side=="UP" else level<boundary
    if ahead and d<=obs:return "OBSTACLE_AHEAD",d
    return ("DISTANT_LEVEL_AHEAD" if ahead else "LEVEL_ALREADY_BEHIND"),d
def enrich(ev,frames,a):
    if ev.empty:return ev
    o=ev.copy();cache={(tf,s):swings(f,s,a.swing_left,a.swing_right) for tf,f in frames.items() for s in ("UP","DOWN")};aligned=[];obstacles=[];ptf=[];ptype=[];prel=[];pdist=[]
    for tf in ("M5","M15","H1"):
        for k in ("previous","range","swing"):o[f"{tf}_{k}_level"]=np.nan;o[f"{tf}_{k}_distance_atr"]=np.nan;o[f"{tf}_{k}_relation"]="UNAVAILABLE"
    for i,r in o.iterrows():
        cand=[];rank=TF_MINUTES.get(str(r.timeframe),0);bd=float(r.breakout_boundary);atr=float(r.atr);side=str(r.breakout_side)
        for tf in ("M5","M15","H1"):
            if tf not in frames or TF_MINUTES[tf]<=rank:continue
            f=frames[tf];eligible=f.loc[f.event_time+pd.Timedelta(minutes=TF_MINUTES[tf])<=pd.Timestamp(r.breakout_time)]
            if eligible.empty:continue
            prev=eligible.iloc[-1];recent=eligible.tail(a.higher_tf_range_bars);sw=cache[(tf,side)];sw=sw.loc[sw.confirm_time<=pd.Timestamp(r.breakout_time)] if not sw.empty else sw
            levels={"previous":float(prev.high if side=="UP" else prev.low),"range":float(recent.high.max() if side=="UP" else recent.low.min()),"swing":float(sw.iloc[-1].level) if not sw.empty else np.nan}
            for k,lvl in levels.items():
                rel,d=relation(lvl,bd,side,atr,a.higher_tf_level_tolerance_atr,a.obstacle_max_distance_atr);o.at[i,f"{tf}_{k}_level"]=lvl;o.at[i,f"{tf}_{k}_distance_atr"]=d;o.at[i,f"{tf}_{k}_relation"]=rel
                if np.isfinite(d):cand.append((tf,k,rel,d))
        al=[x for x in cand if x[2]=="ALIGNED_WITH_BREAKOUT"];ob=[x for x in cand if x[2]=="OBSTACLE_AHEAD"];aligned.append(len(al));obstacles.append(len(ob));pool=al or ob or cand
        if pool:b=min(pool,key=lambda x:x[3]);ptf.append(b[0]);ptype.append(b[1].upper());prel.append(b[2]);pdist.append(b[3])
        else:ptf.append(None);ptype.append(None);prel.append("NO_HTF_CONTEXT");pdist.append(np.nan)
    o["htf_aligned_level_count"]=aligned;o["htf_obstacle_count"]=obstacles;o["primary_htf_timeframe"]=ptf;o["primary_htf_level_type"]=ptype;o["primary_htf_relation"]=prel;o["primary_htf_distance_atr"]=pdist
    o["higher_tf_context"]=np.where(o.htf_aligned_level_count>=2,"MULTI_LEVEL_ALIGNMENT",np.where(o.htf_aligned_level_count==1,"SINGLE_LEVEL_ALIGNMENT",np.where(o.htf_obstacle_count>0,"OBSTACLE_AHEAD","NO_NEAR_HTF_LEVEL")));o["higher_tf_confluence_count"]=o.htf_aligned_level_count
    return o
def stats(ev,hs):
    if ev.empty:return pd.DataFrame()
    rows=[];keys=["timeframe","pattern_type","breakout_side","higher_tf_context","primary_htf_level_type","primary_htf_relation"]
    for vals,g in ev.groupby(keys,dropna=False):
        r=dict(zip(keys,vals));r.update(sample_size=len(g),false_breakout_rate=float(g.false_breakout.mean()),retest_rate=float(g.retest.mean()),avg_quality=float(g.quality_score.mean()),avg_breakout_atr=float(g.breakout_distance_atr.mean()),avg_volume_ratio=float(g.breakout_volume_ratio.mean()),avg_htf_aligned_count=float(g.htf_aligned_level_count.mean()),avg_htf_obstacle_count=float(g.htf_obstacle_count.mean()))
        for h in hs:r.update({f"success_rate_{h}":float(g[f"success_{h}"].mean()),f"avg_mfe_{h}_atr":float(g[f"mfe_{h}_atr"].mean()),f"avg_mae_{h}_atr":float(g[f"mae_{h}_atr"].mean()),f"avg_return_{h}_atr":float(g[f"return_{h}_atr"].mean())})
        rows.append(r)
    return pd.DataFrame(rows).sort_values(["timeframe","sample_size"],ascending=[True,False])
def parse_args():
    p=argparse.ArgumentParser();p.add_argument("--symbol",default="GOLD");p.add_argument("--anchor-tf",default="M5");p.add_argument("--input",default=DEFAULT_INPUT);p.add_argument("--fallback-template",default=DEFAULT_FALLBACK);p.add_argument("--output",default=DEFAULT_OUTPUT);p.add_argument("--timeframes",nargs="+",default=["M1","M5","M15","H1"]);p.add_argument("--windows",nargs="+",type=int,default=[12,20,30]);p.add_argument("--horizons",nargs="+",type=int,default=[3,6,12]);p.add_argument("--min-touches",type=int,default=2);p.add_argument("--touch-tolerance-atr",type=float,default=.18);p.add_argument("--breakout-buffer-atr",type=float,default=.08);p.add_argument("--false-break-horizon",type=int,default=3);p.add_argument("--retest-horizon",type=int,default=6);p.add_argument("--slope-flat",type=float,default=.025);p.add_argument("--slope-directional",type=float,default=.025);p.add_argument("--min-compression",type=float,default=.25);p.add_argument("--max-range-width-atr",type=float,default=2.5);p.add_argument("--min-r2",type=float,default=.15);p.add_argument("--higher-tf-level-tolerance-atr",type=float,default=.20);p.add_argument("--higher-tf-range-bars",type=int,default=6);p.add_argument("--swing-left",type=int,default=2);p.add_argument("--swing-right",type=int,default=2);p.add_argument("--obstacle-max-distance-atr",type=float,default=1.0);return p.parse_args()
def main():
    a=parse_args();root=Path.cwd();symbol=a.symbol.upper();anchor=a.anchor_tf.upper();inp=root/a.input.format(symbol=symbol,anchor_tf=anchor);out=root/a.output.format(symbol=symbol,anchor_tf=anchor);out.mkdir(parents=True,exist_ok=True);log(f"Lendo MTF: {inp}");raw=normalize_time(pd.read_parquet(inp));log(f"Linhas MTF: {len(raw)}")
    E,S,frames,sources,skipped,rows=[],[],{},{},{},{}
    for tf in [str(x).upper() for x in a.timeframes]:
        try:f=build_frame_from_mtf(raw,tf);src=str(inp)+" (MTF deduplicado)"
        except ValueError as e:
            fb=root/a.fallback_template.format(symbol=symbol,tf=tf,anchor_tf=anchor)
            if not fb.exists():skipped[tf]=f"{e}; fallback ausente: {fb}";continue
            f=build_frame_from_fallback(fb);src=str(fb)
        frames[tf]=f;rows[tf]=len(f);sources[tf]=src;ev,st=detect(f,symbol,tf,a);log(f"{tf}: eventos={len(ev)} | episódios={len(st)}");E.extend([ev] if not ev.empty else []);S.extend([st] if not st.empty else [])
    ev=pd.concat(E,ignore_index=True) if E else pd.DataFrame();st=pd.concat(S,ignore_index=True) if S else pd.DataFrame();ev=enrich(ev,frames,a);sm=stats(ev,sorted(set(a.horizons)))
    ev.to_parquet(out/"pattern_events.parquet",index=False);st.to_parquet(out/"pattern_active_episodes.parquet",index=False);sm.to_csv(out/"pattern_statistics.csv",index=False,encoding="utf-8-sig")
    if not ev.empty:ev[["pattern_id","timeframe","pattern_type","breakout_time","breakout_side","breakout_boundary","higher_tf_context","htf_aligned_level_count","htf_obstacle_count","primary_htf_timeframe","primary_htf_level_type","primary_htf_relation","primary_htf_distance_atr"]].to_csv(out/"pattern_breakout_context.csv",index=False,encoding="utf-8-sig")
    meta={"script":"market_pattern_research_v2.py","version":"2.2-structural-htf-context","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"rows_by_timeframe":rows,"events":len(ev),"events_with_aligned_htf_level":int((ev.htf_aligned_level_count>0).sum()) if len(ev) else 0,"events_with_multiple_aligned_levels":int((ev.htf_aligned_level_count>1).sum()) if len(ev) else 0,"events_with_obstacle_ahead":int((ev.htf_obstacle_count>0).sum()) if len(ev) else 0,"active_episodes":len(st),"statistics_rows":len(sm),"output":str(out)};save_json(out/"metadata.json",meta);print(json.dumps(clean(meta),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
