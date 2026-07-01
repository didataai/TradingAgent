#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa de figuras clássicas na base consolidada de candles.

Detecta TRIANGLE_SYMMETRIC, TRIANGLE_ASCENDING, TRIANGLE_DESCENDING e RANGE_BOX
em M5, M15 e H1. Usa candles nativos H1/H4 como contexto, mede rompimentos,
MFE/MAE/retorno e gera validação cronológica por blocos.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DEFAULT_SOURCE="data/market_chronos/candle_base/consolidated/{symbol}_candle_research.parquet"
DEFAULT_OUTPUT="data/market_chronos/{symbol}/patterns/consolidated_research"
TF_MINUTES={"M5":5,"M15":15,"H1":60,"H4":240}

def log(m):print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}",flush=True)
def clean(v:Any)->Any:
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,(pd.Timestamp,datetime)):return v.isoformat()
    if isinstance(v,np.integer):return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v);return None if not math.isfinite(x) else round(x,8)
    if isinstance(v,np.bool_):return bool(v)
    return v
def save_json(p,payload):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(clean(payload),ensure_ascii=False,indent=2),encoding="utf-8")
def fit(v):
    x=np.arange(len(v),dtype=float);ok=np.isfinite(v)
    if ok.sum()<5:return np.nan,np.nan,np.nan
    s,i=np.polyfit(x[ok],v[ok],1);pred=s*x[ok]+i;ssr=np.sum((v[ok]-pred)**2);sst=np.sum((v[ok]-np.mean(v[ok]))**2)
    return float(s),float(i),float(1-ssr/sst if sst>0 else 1)
def load_frames(path,symbol,timeframes):
    cols=["time","open","high","low","close","tick_volume","symbol","timeframe","is_live_bar","ATR"]
    raw=pd.read_parquet(path,columns=cols)
    raw=raw.loc[raw.symbol.astype(str).str.upper().eq(symbol)]
    if "is_live_bar" in raw.columns:raw=raw.loc[pd.to_numeric(raw.is_live_bar,errors="coerce").fillna(0).eq(0)]
    raw["time"]=pd.to_datetime(raw.time,errors="coerce");raw=raw.dropna(subset=["time"])
    frames={}
    for tf in timeframes:
        x=raw.loc[raw.timeframe.astype(str).str.upper().eq(tf),["time","open","high","low","close","tick_volume","ATR"]].copy()
        x=x.rename(columns={"time":"event_time","tick_volume":"volume","ATR":"atr"}).sort_values("event_time").drop_duplicates("event_time",keep="last").reset_index(drop=True)
        for c in ("open","high","low","close","volume","atr"):x[c]=pd.to_numeric(x[c],errors="coerce")
        x=x.dropna(subset=["open","high","low","close"])
        tr=pd.concat([(x.high-x.low),(x.high-x.close.shift()).abs(),(x.low-x.close.shift()).abs()],axis=1).max(axis=1)
        x["atr"]=x.atr.fillna(tr.rolling(14,min_periods=5).mean());frames[tf]=x.reset_index(drop=True)
    return frames
def classify(us,ls,compression,width_atr,ur,lr,a):
    if min(ur,lr)<a.min_r2:return None
    uf,lf=abs(us)<=a.slope_flat,abs(ls)<=a.slope_flat;ud,lu=us<=-a.slope_directional,ls>=a.slope_directional
    if compression>=a.min_compression:
        if ud and lu:return "TRIANGLE_SYMMETRIC"
        if uf and lu:return "TRIANGLE_ASCENDING"
        if ud and lf:return "TRIANGLE_DESCENDING"
    return "RANGE_BOX" if uf and lf and width_atr<=a.max_range_width_atr else None
def context_for_event(event,frames):
    t=pd.Timestamp(event["breakout_time"]);side=event["breakout_side"];price=float(event["breakout_price"]);atr=float(event["atr"])
    rows=[]
    for tf in ("H1","H4"):
        f=frames.get(tf)
        if f is None or f.empty:continue
        delay=pd.Timedelta(minutes=TF_MINUTES[tf]);eligible=f.loc[f.event_time+delay<=t]
        if eligible.empty:continue
        b=eligible.iloc[-1];color="GREEN" if b.close>b.open else "RED" if b.close<b.open else "DOJI"
        ahead=float(b.high-price) if side=="UP" else float(price-b.low)
        rows.append((tf,color,ahead/atr if atr>0 else np.nan))
    event["h1_color"]=next((c for tf,c,d in rows if tf=="H1"),"UNKNOWN")
    event["h4_color"]=next((c for tf,c,d in rows if tf=="H4"),"UNKNOWN")
    dists=[d for _,_,d in rows if np.isfinite(d) and d>=0]
    event["nearest_htf_obstacle_atr"]=min(dists) if dists else np.nan
    event["htf_alignment"]="FULL" if all((side=="UP" and c=="GREEN") or (side=="DOWN" and c=="RED") for _,c,_ in rows) and rows else "PARTIAL_OR_NONE"
    return event
def outcomes(event,frame,horizons):
    i=int(event["bar_index"]);side=event["breakout_side"];entry=float(event["breakout_price"]);atr=float(event["atr"])
    for h in horizons:
        bars=max(1,int(round(h/TF_MINUTES[event["timeframe"]])));future=frame.iloc[i+1:min(len(frame),i+bars+1)]
        if future.empty:
            event[f"success_{h}m"]=pd.NA;continue
        if side=="UP":mfe=(future.high.max()-entry)/atr;mae=(entry-future.low.min())/atr;ret=(future.iloc[-1].close-entry)/atr
        else:mfe=(entry-future.low.min())/atr;mae=(future.high.max()-entry)/atr;ret=(entry-future.iloc[-1].close)/atr
        event[f"mfe_{h}m_atr"]=float(mfe);event[f"mae_{h}m_atr"]=float(mae);event[f"return_{h}m_atr"]=float(ret);event[f"success_{h}m"]=bool(mfe>=.5 and mfe>mae)
    return event
def detect(frame,symbol,tf,a,horizons):
    H,L,C,A=[frame[c].to_numpy(float) for c in ("high","low","close","atr")];events=[];last=-999999
    max_future=max(1,int(round(max(horizons)/TF_MINUTES[tf])))
    for w in sorted(set(a.windows)):
        x=np.arange(w,dtype=float)
        for i in range(w-1,len(frame)-max_future-2):
            st=i-w+1;fa=A[st:i+1];fa=fa[np.isfinite(fa)&(fa>0)]
            if len(fa)<5:continue
            atr=float(np.median(fa));hs,ls=H[st:i+1],L[st:i+1];us,ui,ur=fit(hs);ds,di,dr=fit(ls)
            if not all(np.isfinite(z) for z in (us,ui,ds,di)):continue
            w0=ui-di;w1=(us*(w-1)+ui)-(ds*(w-1)+di)
            if w0<=0 or w1<=0:continue
            comp=1-w1/w0;pat=classify(us/atr,ds/atr,comp,w1/atr,ur,dr,a)
            if not pat:continue
            ut=np.sum(np.abs(hs-(us*x+ui))<=a.touch_tolerance_atr*atr);lt=np.sum(np.abs(ls-(ds*x+di))<=a.touch_tolerance_atr*atr)
            if min(ut,lt)<a.min_touches:continue
            n=i+1;na=A[n] if np.isfinite(A[n]) and A[n]>0 else atr;ub=us*w+ui;lb=ds*w+di;b=a.breakout_buffer_atr*na
            side="UP" if C[n]>ub+b else "DOWN" if C[n]<lb-b else None
            if side is None or n<=last+max(2,w//5):continue
            last=n;bd=ub if side=="UP" else lb
            e={"pattern_id":f"{symbol}_{tf}_{pat}_{n}","symbol":symbol,"timeframe":tf,"pattern_type":pat,"window_bars":w,"formation_start_time":frame.at[st,"event_time"],"formation_end_time":frame.at[i,"event_time"],"breakout_time":frame.at[n,"event_time"],"bar_index":n,"breakout_side":side,"breakout_price":float(C[n]),"breakout_boundary":float(bd),"breakout_distance_atr":abs(float(C[n])-float(bd))/na,"atr":float(na),"compression_ratio":float(comp),"width_end_atr":float(w1/atr),"upper_r2":float(ur),"lower_r2":float(dr),"upper_touches":int(ut),"lower_touches":int(lt)}
            events.append(outcomes(e,frame,horizons))
    return pd.DataFrame(events)
def aggregate(events,horizons,min_sample):
    rows=[];keys=["timeframe","pattern_type","breakout_side","h1_color","h4_color","htf_alignment"]
    for vals,g in events.groupby(keys,dropna=False):
        if not isinstance(vals,tuple):vals=(vals,)
        base=dict(zip(keys,vals))
        for h in horizons:
            v=g.loc[g[f"success_{h}m"].notna()];n=len(v);r=dict(base);r.update(horizon_minutes=h,sample_size=n,sample_status="ADEQUATE" if n>=min_sample else "INSUFFICIENT_SAMPLE",success_rate=float(v[f"success_{h}m"].mean()) if n else np.nan,avg_return_atr=float(v[f"return_{h}m_atr"].mean()) if n else np.nan,avg_mfe_atr=float(v[f"mfe_{h}m_atr"].mean()) if n else np.nan,avg_mae_atr=float(v[f"mae_{h}m_atr"].mean()) if n else np.nan,avg_nearest_htf_obstacle_atr=float(v.nearest_htf_obstacle_atr.mean()) if n else np.nan);rows.append(r)
    return pd.DataFrame(rows)
def validate_blocks(events,horizons,blocks,min_block):
    rows=[];keys=["timeframe","pattern_type","breakout_side","h1_color","h4_color","htf_alignment"]
    ordered=events.sort_values("breakout_time").reset_index(drop=True);ordered["block"]=pd.qcut(ordered.index,blocks,labels=False,duplicates="drop")
    for vals,g in ordered.groupby(keys,dropna=False):
        if not isinstance(vals,tuple):vals=(vals,)
        for h in horizons:
            block_returns=[];block_success=[]
            for _,bg in g.groupby("block"):
                if len(bg)<min_block:continue
                block_returns.append(float(bg[f"return_{h}m_atr"].mean()));block_success.append(float(bg[f"success_{h}m"].mean()))
            r=dict(zip(keys,vals));r.update(horizon_minutes=h,valid_blocks=len(block_returns),positive_blocks=sum(x>0 for x in block_returns),negative_blocks=sum(x<0 for x in block_returns),avg_block_return=float(np.mean(block_returns)) if block_returns else np.nan,min_block_return=float(np.min(block_returns)) if block_returns else np.nan,max_block_return=float(np.max(block_returns)) if block_returns else np.nan,avg_block_success=float(np.mean(block_success)) if block_success else np.nan)
            r["robust_status"]="ROBUST_POSITIVE" if len(block_returns)>=4 and r["positive_blocks"]>=4 else "ROBUST_NEGATIVE" if len(block_returns)>=4 and r["negative_blocks"]>=4 else "NOT_ROBUST";rows.append(r)
    return pd.DataFrame(rows)
def parse_args():
    p=argparse.ArgumentParser();p.add_argument("--symbol",default="GOLD");p.add_argument("--source",default=DEFAULT_SOURCE);p.add_argument("--output",default=DEFAULT_OUTPUT);p.add_argument("--timeframes",nargs="+",default=["M5","M15","H1"]);p.add_argument("--windows",nargs="+",type=int,default=[12,20,30,40]);p.add_argument("--horizons-minutes",nargs="+",type=int,default=[15,30,60,180]);p.add_argument("--min-r2",type=float,default=.55);p.add_argument("--min-compression",type=float,default=.18);p.add_argument("--slope-flat",type=float,default=.03);p.add_argument("--slope-directional",type=float,default=.015);p.add_argument("--max-range-width-atr",type=float,default=3.0);p.add_argument("--touch-tolerance-atr",type=float,default=.18);p.add_argument("--min-touches",type=int,default=2);p.add_argument("--breakout-buffer-atr",type=float,default=.08);p.add_argument("--min-sample",type=int,default=20);p.add_argument("--blocks",type=int,default=5);p.add_argument("--min-block",type=int,default=5);return p.parse_args()
def main():
    a=parse_args();root=Path.cwd();symbol=a.symbol.upper();source=root/a.source.format(symbol=symbol);out=root/a.output.format(symbol=symbol);out.mkdir(parents=True,exist_ok=True)
    needed=sorted(set([x.upper() for x in a.timeframes]+["H1","H4"]),key=lambda x:TF_MINUTES[x]);log(f"Lendo base consolidada: {source}");frames=load_frames(source,symbol,needed)
    all_events=[];horizons=sorted(set(a.horizons_minutes))
    for tf in [x.upper() for x in a.timeframes]:
        log(f"Detectando {tf}: candles={len(frames[tf])}");ev=detect(frames[tf],symbol,tf,a,horizons)
        if not ev.empty:ev=pd.DataFrame([context_for_event(r,frames) for r in ev.to_dict("records")]);all_events.append(ev)
    events=pd.concat(all_events,ignore_index=True) if all_events else pd.DataFrame()
    if events.empty:raise ValueError("nenhum rompimento de figura detectado")
    summary=aggregate(events,horizons,a.min_sample);robust=validate_blocks(events,horizons,a.blocks,a.min_block)
    events.to_parquet(out/"pattern_events.parquet",index=False);summary.to_csv(out/"pattern_summary.csv",index=False,encoding="utf-8-sig");robust.to_csv(out/"pattern_robust_validation.csv",index=False,encoding="utf-8-sig")
    meta={"script":"market_pattern_research_consolidated.py","version":"1.0-consolidated-native-timeframes","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"source":str(source),"timeframes":[x.upper() for x in a.timeframes],"frame_rows":{tf:len(frames[tf]) for tf in frames},"events":len(events),"events_by_timeframe":events.timeframe.value_counts().to_dict(),"events_by_pattern":events.pattern_type.value_counts().to_dict(),"robust_positive":int((robust.robust_status=="ROBUST_POSITIVE").sum()),"robust_negative":int((robust.robust_status=="ROBUST_NEGATIVE").sum()),"output":str(out)};save_json(out/"metadata.json",meta);log("OK");print(json.dumps(clean(meta),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
