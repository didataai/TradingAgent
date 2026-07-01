#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validação robusta dos candidatos produzidos por market_volatility_dna.py.

Aplica independência temporal por horizonte, compara cada combinação ao baseline
do mesmo lado e exige consistência em blocos cronológicos.
"""
from __future__ import annotations
import argparse,json,math
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

DEFAULT_EVENTS="data/market_chronos/{symbol}/volatility_dna/volatility_dna_events.parquet"
DEFAULT_OUTPUT="data/market_chronos/{symbol}/volatility_dna/robust_validation"
KEYS=["side","m1_previous_color","m5_color","m15_color","h1_color","m1_previous_body_bucket","m1_previous_range_bucket","directional_alignment"]

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
def independent(g,h):
    rows=[];last=None
    for idx,r in g.sort_values("event_time").iterrows():
        t=pd.Timestamp(r.event_time)
        if last is None or t>=last+pd.Timedelta(minutes=h):rows.append(idx);last=t
    return g.loc[rows].copy()
def stats(g,h):
    n=len(g)
    return {"sample_size":n,"success_rate":float(g[f"success_{h}m"].mean()) if n else np.nan,"avg_return_atr":float(g[f"return_{h}m_atr"].mean()) if n else np.nan,"avg_mfe_atr":float(g[f"mfe_{h}m_atr"].mean()) if n else np.nan,"avg_mae_atr":float(g[f"mae_{h}m_atr"].mean()) if n else np.nan}
def split_blocks(g,n_blocks):
    o=g.sort_values("event_time").reset_index(drop=True);o["validation_block"]=pd.qcut(o.index,n_blocks,labels=False,duplicates="drop") if len(o)>=n_blocks else 0;return o
def main():
    p=argparse.ArgumentParser();p.add_argument("--symbol",default="GOLD");p.add_argument("--events",default=DEFAULT_EVENTS);p.add_argument("--output",default=DEFAULT_OUTPUT);p.add_argument("--horizons-minutes",nargs="+",type=int,default=[5,15,30,60]);p.add_argument("--train-ratio",type=float,default=.7);p.add_argument("--blocks",type=int,default=5);p.add_argument("--min-train",type=int,default=100);p.add_argument("--min-test",type=int,default=40);p.add_argument("--min-block",type=int,default=20);p.add_argument("--min-success-lift",type=float,default=.03);p.add_argument("--min-return-lift",type=float,default=.05);a=p.parse_args()
    root=Path.cwd();symbol=a.symbol.upper();events_path=root/a.events.format(symbol=symbol);out=root/a.output.format(symbol=symbol);out.mkdir(parents=True,exist_ok=True)
    ev=pd.read_parquet(events_path);ev["event_time"]=pd.to_datetime(ev.event_time,errors="coerce");ev=ev.dropna(subset=["event_time"]).sort_values("event_time")
    rows=[];baseline_rows=[]
    for h in sorted(set(a.horizons_minutes)):
        base_by_side={}
        for side,sg in ev.groupby("side"):
            ind=independent(sg,h);base_by_side[side]=stats(ind,h);baseline_rows.append({"side":side,"horizon_minutes":h,**base_by_side[side]})
        for vals,g in ev.groupby(KEYS,dropna=False):
            ind=independent(g,h);n=len(ind)
            if n<2:continue
            cut=min(max(int(n*a.train_ratio),1),n-1);train=ind.iloc[:cut];test=ind.iloc[cut:]
            tr=stats(train,h);te=stats(test,h);base=base_by_side[str(vals[0])]
            blocks=split_blocks(ind,a.blocks);block_returns=[];block_success=[];valid_blocks=0
            for _,bg in blocks.groupby("validation_block"):
                if len(bg)<a.min_block:continue
                valid_blocks+=1;block_returns.append(float(bg[f"return_{h}m_atr"].mean()));block_success.append(float(bg[f"success_{h}m"].mean()))
            positive_blocks=sum(x>0 for x in block_returns);negative_blocks=sum(x<0 for x in block_returns)
            success_lift_train=tr["success_rate"]-base["success_rate"];success_lift_test=te["success_rate"]-base["success_rate"]
            return_lift_train=tr["avg_return_atr"]-base["avg_return_atr"];return_lift_test=te["avg_return_atr"]-base["avg_return_atr"]
            enough=tr["sample_size"]>=a.min_train and te["sample_size"]>=a.min_test and valid_blocks>=4
            pos=enough and tr["avg_return_atr"]>0 and te["avg_return_atr"]>0 and success_lift_train>=a.min_success_lift and success_lift_test>=a.min_success_lift and return_lift_train>=a.min_return_lift and return_lift_test>=a.min_return_lift and positive_blocks>=4
            neg=enough and tr["avg_return_atr"]<0 and te["avg_return_atr"]<0 and success_lift_train<=-a.min_success_lift and success_lift_test<=-a.min_success_lift and return_lift_train<=-a.min_return_lift and return_lift_test<=-a.min_return_lift and negative_blocks>=4
            status="ROBUST_POSITIVE" if pos else "ROBUST_NEGATIVE" if neg else "NOT_ROBUST"
            r=dict(zip(KEYS,vals));r.update(horizon_minutes=h,independent_sample_size=n,train_sample_size=tr["sample_size"],test_sample_size=te["sample_size"],baseline_success_rate=base["success_rate"],baseline_avg_return_atr=base["avg_return_atr"],train_success_rate=tr["success_rate"],test_success_rate=te["success_rate"],train_avg_return_atr=tr["avg_return_atr"],test_avg_return_atr=te["avg_return_atr"],success_lift_train=success_lift_train,success_lift_test=success_lift_test,return_lift_train=return_lift_train,return_lift_test=return_lift_test,valid_blocks=valid_blocks,positive_blocks=positive_blocks,negative_blocks=negative_blocks,min_block_return=min(block_returns) if block_returns else np.nan,max_block_return=max(block_returns) if block_returns else np.nan,robust_status=status);rows.append(r)
    result=pd.DataFrame(rows).sort_values(["robust_status","test_sample_size","train_sample_size"],ascending=[True,False,False]);baseline=pd.DataFrame(baseline_rows)
    result.to_csv(out/"volatility_dna_robust_candidates.csv",index=False,encoding="utf-8-sig");baseline.to_csv(out/"volatility_dna_independent_baseline.csv",index=False,encoding="utf-8-sig")
    meta={"script":"market_volatility_dna_validation.py","version":"1.0-independent-block-validation","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"events_input":str(events_path),"raw_events":len(ev),"horizons_minutes":sorted(set(a.horizons_minutes)),"blocks":a.blocks,"min_train":a.min_train,"min_test":a.min_test,"min_block":a.min_block,"min_success_lift":a.min_success_lift,"min_return_lift":a.min_return_lift,"robust_positive":int((result.robust_status=="ROBUST_POSITIVE").sum()),"robust_negative":int((result.robust_status=="ROBUST_NEGATIVE").sum()),"output":str(out)};save_json(out/"metadata.json",meta);print(json.dumps(clean(meta),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
