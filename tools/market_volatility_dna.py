#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa do DNA de volatilidade em rompimentos de barras M1.

M5, M15 e H1 são reconstruídos diretamente do M1 para garantir sincronismo,
candles realmente fechados e ausência de lookahead.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DEFAULT_M1="data/{symbol}_M1.parquet"
DEFAULT_OUTPUT="data/market_chronos/{symbol}/volatility_dna"
TF_RULES={"M5":"5min","M15":"15min","H1":"60min"}
TF_MINUTES={"M5":5,"M15":15,"H1":60}

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
        elif isinstance(o.index,pd.DatetimeIndex):n=o.index.name or "index";o=o.reset_index().rename(columns={n:"event_time"})
        else:raise ValueError("coluna temporal não encontrada")
    o.event_time=pd.to_datetime(o.event_time,errors="coerce");return o.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)
def number(df,c):return pd.to_numeric(df[c],errors="coerce") if c in df.columns else pd.Series(np.nan,index=df.index)
def anatomy(o):
    out=o.copy();r=(out.high-out.low).replace(0,np.nan);body=(out.close-out.open).abs()
    out["color"]=np.where(out.close>out.open,"GREEN",np.where(out.close<out.open,"RED","DOJI"));out["body_ratio"]=body/r
    out["upper_wick_ratio"]=(out.high-out[["open","close"]].max(axis=1))/r;out["lower_wick_ratio"]=(out[["open","close"]].min(axis=1)-out.low)/r
    out["close_location"]=(out.close-out.low)/r;out["range_atr"]=r/out.atr;return out
def load_m1(path):
    raw=normalize_time(pd.read_parquet(path));a={c.lower():c for c in raw.columns};missing=[x for x in ("open","high","low","close") if x not in a]
    if missing:raise ValueError("OHLC ausente: "+", ".join(missing))
    vol=a.get("tick_volume",a.get("volume"))
    o=pd.DataFrame({"event_time":raw.event_time,"open":number(raw,a["open"]),"high":number(raw,a["high"]),"low":number(raw,a["low"]),"close":number(raw,a["close"]),"volume":number(raw,vol) if vol else np.nan}).dropna(subset=["event_time","open","high","low","close"])
    o=o.sort_values("event_time").drop_duplicates("event_time",keep="last").reset_index(drop=True)
    tr=pd.concat([(o.high-o.low),(o.high-o.close.shift()).abs(),(o.low-o.close.shift()).abs()],axis=1).max(axis=1);o["atr"]=tr.rolling(14,min_periods=5).mean();o["volume_ratio"]=o.volume/o.volume.rolling(20,min_periods=5).mean()
    return anatomy(o)
def resample_context(m1,tf):
    rule=TF_RULES[tf];x=m1.set_index("event_time")
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    o=x.resample(rule,label="left",closed="left").agg(agg).dropna(subset=["open","high","low","close"]).reset_index()
    o["closed_time"]=o.event_time+pd.Timedelta(minutes=TF_MINUTES[tf])
    tr=pd.concat([(o.high-o.low),(o.high-o.close.shift()).abs(),(o.low-o.close.shift()).abs()],axis=1).max(axis=1);o["atr"]=tr.rolling(14,min_periods=5).mean();o["volume_ratio"]=o.volume/o.volume.rolling(20,min_periods=5).mean()
    return anatomy(o)
def body_bucket(v):return "UNKNOWN" if not np.isfinite(v) else "SMALL_BODY" if v<.35 else "MEDIUM_BODY" if v<.65 else "STRONG_BODY"
def range_bucket(v):return "UNKNOWN" if not np.isfinite(v) else "LOW_RANGE" if v<.75 else "NORMAL_RANGE" if v<1.25 else "EXPANSION_RANGE"
def volume_bucket(v):return "UNKNOWN" if not np.isfinite(v) else "LOW_VOLUME" if v<.8 else "NORMAL_VOLUME" if v<1.5 else "HIGH_VOLUME"
def last_closed(frame,event_time):
    e=frame.loc[frame.closed_time<=event_time];return None if e.empty else e.iloc[-1]
def detect(m1,contexts,horizons):
    rows=[]
    for i in range(1,len(m1)-max(horizons)-1):
        p=m1.iloc[i-1];c=m1.iloc[i]
        if not np.isfinite(c.atr) or c.atr<=0:continue
        up=c.high>p.high;down=c.low<p.low
        for side in (["UP"] if up and not down else ["DOWN"] if down and not up else ["UP","DOWN"] if up and down else []):
            t=pd.Timestamp(c.event_time);entry=float(p.high if side=="UP" else p.low)
            e={"event_id":f"M1_{i}_{side}","event_time":t,"side":side,"entry_price":entry,"atr":float(c.atr),"m1_double_break":bool(up and down),
               "m1_previous_color":p.color,"m1_previous_body_bucket":body_bucket(float(p.body_ratio)),"m1_previous_range_bucket":range_bucket(float(p.range_atr)),"m1_previous_volume_bucket":volume_bucket(float(p.volume_ratio)),
               "m1_previous_body_ratio":p.body_ratio,"m1_previous_range_atr":p.range_atr,"m1_previous_volume_ratio":p.volume_ratio,"m1_current_color":c.color,"m1_current_body_ratio":c.body_ratio,"m1_current_range_atr":c.range_atr,"m1_current_volume_ratio":c.volume_ratio,"m1_break_distance_atr":abs(float(c.close)-entry)/float(c.atr)}
            aligned=0;known=0
            for tf,f in contexts.items():
                b=last_closed(f,t);q=tf.lower()
                if b is None:
                    for k in ("color","body_bucket","range_bucket","volume_bucket"):e[f"{q}_{k}"]="UNKNOWN"
                    continue
                known+=1;e[f"{q}_color"]=b.color;e[f"{q}_body_bucket"]=body_bucket(float(b.body_ratio));e[f"{q}_range_bucket"]=range_bucket(float(b.range_atr));e[f"{q}_volume_bucket"]=volume_bucket(float(b.volume_ratio));e[f"{q}_body_ratio"]=b.body_ratio;e[f"{q}_range_atr"]=b.range_atr;e[f"{q}_volume_ratio"]=b.volume_ratio
                if (side=="UP" and b.color=="GREEN") or (side=="DOWN" and b.color=="RED"):aligned+=1
            e["htf_known_count"]=known;e["htf_aligned_count"]=aligned;e["directional_alignment"]="UNKNOWN_CONTEXT" if known<3 else "FULL_ALIGNMENT" if aligned==3 else "PARTIAL_ALIGNMENT" if aligned>0 else "NO_ALIGNMENT"
            for h in horizons:
                future=m1.iloc[i+1:min(len(m1),i+h+1)]
                if side=="UP":mfe=(future.high.max()-entry)/c.atr;mae=(entry-future.low.min())/c.atr;ret=(future.iloc[-1].close-entry)/c.atr
                else:mfe=(entry-future.low.min())/c.atr;mae=(future.high.max()-entry)/c.atr;ret=(entry-future.iloc[-1].close)/c.atr
                e[f"mfe_{h}m_atr"]=float(mfe);e[f"mae_{h}m_atr"]=float(mae);e[f"return_{h}m_atr"]=float(ret);e[f"success_{h}m"]=bool(mfe>=.5 and mfe>mae)
            rows.append(e)
    return pd.DataFrame(rows)
def split(events,ratio):
    o=events.sort_values("event_time").reset_index(drop=True);cut=min(max(int(len(o)*ratio),1),len(o)-1);o["temporal_split"]=np.where(o.index<cut,"TRAIN","TEST");return o
def aggregate(events,keys,horizons,min_sample):
    rows=[]
    for vals,g in events.groupby(keys,dropna=False):
        if not isinstance(vals,tuple):vals=(vals,)
        base=dict(zip(keys,vals))
        for h in horizons:
            n=len(g);r=dict(base);r.update(horizon_minutes=h,sample_size=n,sample_status="ADEQUATE" if n>=min_sample else "INSUFFICIENT_SAMPLE",success_rate=float(g[f"success_{h}m"].mean()),avg_mfe_atr=float(g[f"mfe_{h}m_atr"].mean()),avg_mae_atr=float(g[f"mae_{h}m_atr"].mean()),avg_return_atr=float(g[f"return_{h}m_atr"].mean()),median_return_atr=float(g[f"return_{h}m_atr"].median()));rows.append(r)
    return pd.DataFrame(rows).sort_values(["horizon_minutes","sample_size"],ascending=[True,False])
def candidates(train,test,keys,horizons,min_train,min_test):
    a=aggregate(train,keys,horizons,min_train);b=aggregate(test,keys,horizons,min_test);k=keys+["horizon_minutes"];m=a.merge(b,on=k,how="outer",suffixes=("_train","_test"))
    enough=(m.sample_size_train>=min_train)&(m.sample_size_test>=min_test)
    pos=enough&(m.success_rate_train>=.55)&(m.success_rate_test>=.55)&(m.avg_return_atr_train>0)&(m.avg_return_atr_test>0)
    neg=enough&(m.success_rate_train<.45)&(m.success_rate_test<.45)&(m.avg_return_atr_train<0)&(m.avg_return_atr_test<0)
    m["candidate_status"]=np.where(pos,"STABLE_POSITIVE",np.where(neg,"STABLE_NEGATIVE","NOT_STABLE"));return m.sort_values(["candidate_status","sample_size_test","sample_size_train"],ascending=[True,False,False])
def parse_args():
    p=argparse.ArgumentParser();p.add_argument("--symbol",default="GOLD");p.add_argument("--m1",default=DEFAULT_M1);p.add_argument("--output",default=DEFAULT_OUTPUT);p.add_argument("--horizons-minutes",nargs="+",type=int,default=[5,15,30,60]);p.add_argument("--train-ratio",type=float,default=.7);p.add_argument("--min-sample",type=int,default=30);p.add_argument("--min-train",type=int,default=20);p.add_argument("--min-test",type=int,default=10);return p.parse_args()
def main():
    a=parse_args();root=Path.cwd();symbol=a.symbol.upper();m1_path=root/a.m1.format(symbol=symbol);out=root/a.output.format(symbol=symbol);out.mkdir(parents=True,exist_ok=True)
    log(f"Lendo M1: {m1_path}");m1=load_m1(m1_path);contexts={tf:resample_context(m1,tf) for tf in TF_RULES};log(f"Candles M1: {len(m1)} | M5={len(contexts['M5'])} | M15={len(contexts['M15'])} | H1={len(contexts['H1'])}")
    hs=sorted(set(a.horizons_minutes));ev=split(detect(m1,contexts,hs),a.train_ratio);train=ev[ev.temporal_split=="TRAIN"];test=ev[ev.temporal_split=="TEST"]
    align=aggregate(ev,["side","directional_alignment"],hs,a.min_sample);colors=aggregate(ev,["side","m1_previous_color","m5_color","m15_color","h1_color"],hs,a.min_sample);anat=aggregate(ev,["side","m1_previous_body_bucket","m1_previous_range_bucket","m1_previous_volume_bucket","directional_alignment"],hs,a.min_sample)
    keys=["side","m1_previous_color","m5_color","m15_color","h1_color","m1_previous_body_bucket","m1_previous_range_bucket","directional_alignment"];cand=candidates(train,test,keys,hs,a.min_train,a.min_test)
    ev.to_parquet(out/"volatility_dna_events.parquet",index=False);align.to_csv(out/"volatility_dna_alignment_summary.csv",index=False,encoding="utf-8-sig");colors.to_csv(out/"volatility_dna_color_summary.csv",index=False,encoding="utf-8-sig");anat.to_csv(out/"volatility_dna_anatomy_summary.csv",index=False,encoding="utf-8-sig");cand.to_csv(out/"volatility_dna_candidates.csv",index=False,encoding="utf-8-sig")
    color_distribution={tf:contexts[tf].color.value_counts().to_dict() for tf in contexts};meta={"script":"market_volatility_dna.py","version":"1.1-resampled-htf-context","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"m1_candles":len(m1),"context_candles":{tf:len(f) for tf,f in contexts.items()},"context_color_distribution":color_distribution,"events":len(ev),"train_events":len(train),"test_events":len(test),"horizons_minutes":hs,"stable_positive_candidates":int((cand.candidate_status=="STABLE_POSITIVE").sum()),"stable_negative_candidates":int((cand.candidate_status=="STABLE_NEGATIVE").sum()),"output":str(out)};save_json(out/"metadata.json",meta);log("OK");print(json.dumps(clean(meta),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
