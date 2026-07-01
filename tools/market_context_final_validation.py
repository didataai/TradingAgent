#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação final 60/20/20 dos candidatos do minerador hierárquico."""
from __future__ import annotations
import argparse,json,math,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools import market_context_hierarchical_miner as miner

def clean(v:Any)->Any:
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,(pd.Timestamp,datetime)):return v.isoformat()
    if isinstance(v,np.integer):return int(v)
    if isinstance(v,(np.floating,float)):
        x=float(v);return None if not math.isfinite(x) else round(x,8)
    if isinstance(v,np.bool_):return bool(v)
    return v

def metric(g,h):
    n=len(g)
    return {"n":n,"success":float(g[f"success_{h}m"].mean()) if n else np.nan,"ret":float(g[f"return_{h}m_atr"].mean()) if n else np.nan,"median":float(g[f"return_{h}m_atr"].median()) if n else np.nan}

def parse():
    p=argparse.ArgumentParser();p.add_argument("--symbol",default="GOLD");p.add_argument("--events",default=miner.DEFAULT_EVENTS);p.add_argument("--source",default=miner.DEFAULT_SOURCE);p.add_argument("--candidates",default="data/market_chronos/{symbol}/context_hierarchical_miner/single_feature_robust.csv");p.add_argument("--output",default="data/market_chronos/{symbol}/context_final_validation");p.add_argument("--min-discovery",type=int,default=80);p.add_argument("--min-validation",type=int,default=30);p.add_argument("--min-holdout",type=int,default=30);p.add_argument("--min-success-lift",type=float,default=.03);p.add_argument("--min-return-lift",type=float,default=.05);return p.parse_args()

def main():
    a=parse();root=Path.cwd();symbol=a.symbol.upper();out=root/a.output.format(symbol=symbol);out.mkdir(parents=True,exist_ok=True)
    events=pd.read_parquet(root/a.events.format(symbol=symbol));events["event_time"]=pd.to_datetime(events.event_time,errors="coerce");events=events.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)
    cols=["time","symbol","timeframe","is_live_bar",*miner.CATEGORICAL_FEATURES,*miner.NUMERIC_FEATURES]
    candles=pd.read_parquet(root/a.source.format(symbol=symbol),columns=cols);candles=candles.loc[candles.symbol.astype(str).str.upper().eq(symbol)&candles.timeframe.astype(str).str.upper().eq("M1")].copy();candles=candles.loc[pd.to_numeric(candles.is_live_bar,errors="coerce").fillna(0).eq(0)];candles["event_time"]=pd.to_datetime(candles.time,errors="coerce");candles=candles.dropna(subset=["event_time"]).sort_values("event_time").drop_duplicates("event_time",keep="last")
    data=events.merge(candles.drop(columns=["time","symbol","timeframe","is_live_bar"],errors="ignore"),on="event_time",how="left")
    cut=int(len(data)*.60);mask=pd.Series(np.arange(len(data))<cut,index=data.index)
    for f in miner.CATEGORICAL_FEATURES:
        if f in data.columns:data[f"ctx_{f}"]=data[f].astype("string").fillna("UNKNOWN")
    for f in miner.NUMERIC_FEATURES:
        if f in data.columns:data[f"ctx_{f}_bucket"]=miner.bucket_numeric(data[f],mask)
    cand=pd.read_csv(root/a.candidates.format(symbol=symbol),encoding="utf-8-sig")
    rows=[]
    for _,r in cand.iterrows():
        feature=str(r.feature_1);side=str(r.side);h=int(r.horizon_minutes)
        if feature not in data.columns or feature not in cand.columns:continue
        value=r.get(feature)
        if pd.isna(value):continue
        base=miner.independent(data.loc[data.side.astype(str).eq(side)],h).sort_values("event_time").reset_index(drop=True)
        if base.empty:continue
        n=len(base);i1=int(n*.60);i2=int(n*.80);splits={"discovery":base.iloc[:i1],"validation":base.iloc[i1:i2],"holdout":base.iloc[i2:]}
        row={"side":side,"horizon_minutes":h,"feature":feature,"condition_value":str(value)}
        passed=True
        for name,b in splits.items():
            g=b.loc[b[feature].astype(str).eq(str(value))];bm=metric(b,h);gm=metric(g,h)
            row[f"{name}_n"]=gm["n"];row[f"{name}_success_rate"]=gm["success"];row[f"{name}_avg_return_atr"]=gm["ret"];row[f"{name}_median_return_atr"]=gm["median"];row[f"{name}_success_lift"]=gm["success"]-bm["success"] if gm["n"] else np.nan;row[f"{name}_return_lift"]=gm["ret"]-bm["ret"] if gm["n"] else np.nan
        mins=(row["discovery_n"]>=a.min_discovery and row["validation_n"]>=a.min_validation and row["holdout_n"]>=a.min_holdout)
        positive=mins and all(row[f"{s}_success_lift"]>=a.min_success_lift and row[f"{s}_return_lift"]>=a.min_return_lift and row[f"{s}_avg_return_atr"]>0 for s in splits)
        negative=mins and all(row[f"{s}_success_lift"]<=-a.min_success_lift and row[f"{s}_return_lift"]<=-a.min_return_lift and row[f"{s}_avg_return_atr"]<0 for s in splits)
        selected=base.loc[base[feature].astype(str).eq(str(value))].copy();selected["block"]=pd.qcut(selected.event_time.rank(method="first"),5,labels=False,duplicates="drop");brets=[float(g[f"return_{h}m_atr"].mean()) for _,g in selected.groupby("block") if len(g)>=10];row["valid_blocks"]=len(brets);row["positive_blocks"]=sum(x>0 for x in brets);row["negative_blocks"]=sum(x<0 for x in brets);row["status"]="FINAL_POSITIVE" if positive and row["positive_blocks"]>=4 else "FINAL_NEGATIVE" if negative and row["negative_blocks"]>=4 else "REJECTED";rows.append(row)
    res=pd.DataFrame(rows).sort_values(["status","holdout_return_lift"],ascending=[True,False]);res.to_csv(out/"final_single_candidates.csv",index=False,encoding="utf-8-sig");approved=res.loc[res.status.ne("REJECTED")];approved.to_csv(out/"approved_single_candidates.csv",index=False,encoding="utf-8-sig")
    meta={"script":"market_context_final_validation.py","version":"1.0-60-20-20-holdout","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"candidates_input":len(cand),"evaluated":len(res),"final_positive":int((res.status=="FINAL_POSITIVE").sum()),"final_negative":int((res.status=="FINAL_NEGATIVE").sum()),"output":str(out)};(out/"metadata.json").write_text(json.dumps(clean(meta),ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(clean(meta),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
