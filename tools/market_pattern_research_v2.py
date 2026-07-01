#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pesquisa canônica de padrões clássicos e contexto multi-timeframe.

Detecta triângulos e ranges, preserva episódios ativos e enriquece cada
rompimento de figura com a proximidade das máximas/mínimas dos últimos candles
fechados de timeframes superiores.

Hierarquia:
leis -> figura clássica -> nível superior -> microconfirmação.
Não publica leis nem altera registries operacionais.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_INPUT = "data/market_chronos/{symbol}/lab/{symbol}_{anchor_tf}_mtf_research_base.parquet"
DEFAULT_FALLBACK = "data/{symbol}_{tf}.parquet"
DEFAULT_OUTPUT = "data/market_chronos/{symbol}/patterns/research_v2"
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def clean(v: Any) -> Any:
    if isinstance(v, dict): return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [clean(x) for x in v]
    if isinstance(v, (pd.Timestamp, datetime)): return v.isoformat()
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v); return None if not math.isfinite(x) else round(x, 8)
    if isinstance(v, np.bool_): return bool(v)
    return v


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_time(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "event_time" not in out.columns:
        candidate = next((c for c in ("time", "datetime", "timestamp", "date_time", "date", "open_time") if c in out.columns), None)
        if candidate: out = out.rename(columns={candidate: "event_time"})
        elif isinstance(out.index, pd.DatetimeIndex):
            name = out.index.name or "index"; out = out.reset_index().rename(columns={name: "event_time"})
        else: raise ValueError("coluna temporal não encontrada")
    out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    return out.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)


def number(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(np.nan, index=df.index)


def bool_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns: return pd.Series(False, index=df.index)
    s = df[col]
    if pd.api.types.is_bool_dtype(s): return s.fillna(False)
    if pd.api.types.is_numeric_dtype(s): return s.fillna(0).astype(int).astype(bool)
    return s.astype(str).str.lower().isin({"1", "true", "yes", "sim"})


def finish_frame(out: pd.DataFrame) -> pd.DataFrame:
    out = out.reset_index(drop=True)
    tr = pd.concat([(out.high-out.low), (out.high-out.close.shift()).abs(), (out.low-out.close.shift()).abs()], axis=1).max(axis=1)
    out["atr"] = pd.to_numeric(out["atr"], errors="coerce").fillna(tr.rolling(14, min_periods=5).mean())
    return out


def build_frame_from_mtf(raw: pd.DataFrame, tf: str) -> pd.DataFrame:
    p = f"{tf}_"; required = [f"{p}open", f"{p}high", f"{p}low", f"{p}close"]
    missing = [c for c in required if c not in raw.columns]
    if missing: raise ValueError("OHLC ausente: " + ", ".join(missing))
    time_col = next((c for c in (f"{p}event_time", f"{p}time", f"{p}datetime", f"{p}timestamp", f"{p}open_time") if c in raw.columns), None)
    event_time = pd.to_datetime(raw[time_col], errors="coerce") if time_col else raw["event_time"]
    out = pd.DataFrame({
        "event_time": event_time,
        "open": number(raw, f"{p}open"), "high": number(raw, f"{p}high"),
        "low": number(raw, f"{p}low"), "close": number(raw, f"{p}close"),
        "atr": number(raw, f"{p}ATR") if f"{p}ATR" in raw.columns else number(raw, f"{p}atr"),
        "vol_ratio": number(raw, f"{p}vol_ratio"),
        "breakout_up_existing": bool_series(raw, f"{p}breakout_up"),
        "breakout_down_existing": bool_series(raw, f"{p}breakout_down"),
        "false_up_existing": bool_series(raw, f"{p}false_breakout_up"),
        "false_down_existing": bool_series(raw, f"{p}false_breakout_down"),
        "sweep_high_existing": bool_series(raw, f"{p}sweep_high"),
        "sweep_low_existing": bool_series(raw, f"{p}sweep_low"),
    }).dropna(subset=["event_time", "open", "high", "low", "close"])
    if time_col:
        out = out.sort_values("event_time").drop_duplicates("event_time", keep="last")
    else:
        changed = out[["open", "high", "low", "close"]].ne(out[["open", "high", "low", "close"]].shift()).any(axis=1)
        out = out.loc[changed]
    return finish_frame(out)


def build_frame_from_fallback(path: Path) -> pd.DataFrame:
    raw = normalize_time(pd.read_parquet(path)); aliases = {c.lower(): c for c in raw.columns}
    def pick(name: str):
        col = aliases.get(name); return number(raw, col) if col else pd.Series(np.nan, index=raw.index)
    out = pd.DataFrame({
        "event_time": raw.event_time, "open": pick("open"), "high": pick("high"),
        "low": pick("low"), "close": pick("close"), "atr": pick("atr"), "vol_ratio": pick("vol_ratio"),
        "breakout_up_existing": bool_series(raw, aliases.get("breakout_up", "__missing")),
        "breakout_down_existing": bool_series(raw, aliases.get("breakout_down", "__missing")),
        "false_up_existing": bool_series(raw, aliases.get("false_breakout_up", "__missing")),
        "false_down_existing": bool_series(raw, aliases.get("false_breakout_down", "__missing")),
        "sweep_high_existing": bool_series(raw, aliases.get("sweep_high", "__missing")),
        "sweep_low_existing": bool_series(raw, aliases.get("sweep_low", "__missing")),
    }).dropna(subset=["event_time", "open", "high", "low", "close"])
    return finish_frame(out.sort_values("event_time").drop_duplicates("event_time", keep="last"))


def fit(values: np.ndarray) -> tuple[float, float, float]:
    x = np.arange(len(values), dtype=float); valid = np.isfinite(values)
    if valid.sum() < 5: return np.nan, np.nan, np.nan
    slope, intercept = np.polyfit(x[valid], values[valid], 1); pred = slope*x[valid]+intercept
    ssr = float(np.sum((values[valid]-pred)**2)); sst = float(np.sum((values[valid]-np.mean(values[valid]))**2))
    return float(slope), float(intercept), float(1-ssr/sst if sst > 0 else 1)


def classify(us, ls, compression, width_atr, ur2, lr2, a):
    if not all(np.isfinite(v) for v in (us,ls,compression,width_atr,ur2,lr2)) or min(ur2,lr2) < a.min_r2: return None
    uf, lf = abs(us) <= a.slope_flat, abs(ls) <= a.slope_flat
    ud, lu = us <= -a.slope_directional, ls >= a.slope_directional
    if compression >= a.min_compression:
        if ud and lu: return "TRIANGLE_SYMMETRIC"
        if uf and lu: return "TRIANGLE_ASCENDING"
        if ud and lf: return "TRIANGLE_DESCENDING"
    if uf and lf and width_atr <= a.max_range_width_atr: return "RANGE_BOX"
    return None


def outcomes(events: pd.DataFrame, frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if events.empty: return events
    out = events.copy(); highs=frame.high.to_numpy(float); lows=frame.low.to_numpy(float); closes=frame.close.to_numpy(float)
    for h in horizons:
        mfe=[]; mae=[]; ret=[]; success=[]
        for r in out.itertuples():
            i=int(r.bar_index); end=min(len(frame),i+h+1); atr=float(r.atr)
            if i+1>=end or not np.isfinite(atr) or atr<=0:
                mfe.append(np.nan); mae.append(np.nan); ret.append(np.nan); success.append(False); continue
            hi=float(np.nanmax(highs[i+1:end])); lo=float(np.nanmin(lows[i+1:end])); last=float(closes[end-1]); entry=float(r.breakout_price)
            if r.breakout_side=="UP": m=(hi-entry)/atr; d=(entry-lo)/atr; rr=(last-entry)/atr
            else: m=(entry-lo)/atr; d=(hi-entry)/atr; rr=(entry-last)/atr
            mfe.append(m); mae.append(d); ret.append(rr); success.append(bool(m>=0.5 and m>d))
        out[f"mfe_{h}_atr"]=mfe; out[f"mae_{h}_atr"]=mae; out[f"return_{h}_atr"]=ret; out[f"success_{h}"]=success
    return out


def detect(frame: pd.DataFrame, symbol: str, tf: str, a) -> tuple[pd.DataFrame,pd.DataFrame]:
    events=[]; states=[]; high=frame.high.to_numpy(float); low=frame.low.to_numpy(float); close=frame.close.to_numpy(float); atr=frame.atr.to_numpy(float); vol=frame.vol_ratio.to_numpy(float)
    last_break=-999999
    for window in sorted(set(a.windows)):
        x=np.arange(window,dtype=float)
        for idx in range(window-1,len(frame)-max(a.horizons)-1):
            start=idx-window+1; finite=atr[start:idx+1][np.isfinite(atr[start:idx+1]) & (atr[start:idx+1]>0)]
            if len(finite)==0: continue
            ar=float(np.median(finite)); hs=high[start:idx+1]; ls_=low[start:idx+1]
            us,ui,ur2=fit(hs); ls,li,lr2=fit(ls_)
            if not all(np.isfinite(v) for v in (us,ui,ls,li)): continue
            w0=ui-li; w1=(us*(window-1)+ui)-(ls*(window-1)+li)
            if w0<=0 or w1<=0: continue
            comp=1-w1/w0; pattern=classify(us/ar,ls/ar,comp,w1/ar,ur2,lr2,a)
            if not pattern: continue
            up_line=us*x+ui; low_line=ls*x+li
            ut=int(np.sum(np.abs(hs-up_line)<=a.touch_tolerance_atr*ar)); lt=int(np.sum(np.abs(ls_-low_line)<=a.touch_tolerance_atr*ar))
            if min(ut,lt)<a.min_touches: continue
            nxt=idx+1; na=atr[nxt] if np.isfinite(atr[nxt]) and atr[nxt]>0 else ar; ub=us*window+ui; lb=ls*window+li; buffer=a.breakout_buffer_atr*na
            side="UP" if close[nxt]>ub+buffer else "DOWN" if close[nxt]<lb-buffer else None
            quality=float(np.clip(25*max(0,comp)+20*ur2+20*lr2+10*min(1,ut/4)+10*min(1,lt/4),0,100))
            base={"symbol":symbol,"timeframe":tf,"bar_index":idx,"event_time":frame.at[idx,"event_time"],"pattern_type":pattern,"window_bars":window,"compression_ratio":comp,"width_end_atr":w1/ar,"upper_slope_atr":us/ar,"lower_slope_atr":ls/ar,"upper_r2":ur2,"lower_r2":lr2,"upper_touches":ut,"lower_touches":lt,"quality_score":quality}
            if side is None: states.append(base); continue
            if nxt<=last_break+max(2,window//5): continue
            last_break=nxt; boundary=ub if side=="UP" else lb; future=close[nxt+1:min(len(frame),nxt+a.false_break_horizon+1)]
            false_break=bool(np.any(future<ub)) if side=="UP" and len(future) else bool(np.any(future>lb)) if len(future) else False
            rend=min(len(frame),nxt+a.retest_horizon+1); tol=a.touch_tolerance_atr*na
            retest=bool(np.any(np.abs(low[nxt+1:rend]-ub)<=tol)) if side=="UP" else bool(np.any(np.abs(high[nxt+1:rend]-lb)<=tol))
            events.append({**base,"pattern_id":f"{symbol}_{tf}_{pattern}_{nxt}","bar_index":nxt,"formation_start_time":frame.at[start,"event_time"],"formation_end_time":frame.at[idx,"event_time"],"breakout_time":frame.at[nxt,"event_time"],"breakout_side":side,"breakout_price":close[nxt],"breakout_boundary":boundary,"breakout_distance_atr":abs(close[nxt]-boundary)/na,"breakout_volume_ratio":vol[nxt],"atr":na,"false_breakout":false_break,"retest":retest,"existing_breakout_flag":bool(frame.at[nxt,"breakout_up_existing"] if side=="UP" else frame.at[nxt,"breakout_down_existing"])})
    ev=pd.DataFrame(events)
    if not ev.empty:
        ev=ev.sort_values(["breakout_time","quality_score"],ascending=[True,False]).drop_duplicates(["timeframe","breakout_time","breakout_side"],keep="first").reset_index(drop=True)
        ev=outcomes(ev,frame,sorted(set(a.horizons)))
    st=pd.DataFrame(states)
    if not st.empty:
        st=st.sort_values(["window_bars","pattern_type","bar_index"])
        st["episode_break"]=(st.groupby(["window_bars","pattern_type"])["bar_index"].diff().fillna(999)>1)
        st["episode_id"]=st.groupby(["window_bars","pattern_type"])["episode_break"].cumsum()
        st=st.sort_values("quality_score").groupby(["window_bars","pattern_type","episode_id"],as_index=False).tail(1).drop(columns="episode_break").sort_values("event_time").reset_index(drop=True)
    return ev,st


def enrich_higher_tf_context(events: pd.DataFrame, frames: dict[str,pd.DataFrame], tolerance_atr: float) -> pd.DataFrame:
    if events.empty: return events
    out=events.copy(); ordered=sorted(TF_MINUTES, key=TF_MINUTES.get)
    for tf in ("M5","M15","H1"):
        out[f"{tf}_level"] = np.nan
        out[f"{tf}_level_distance_atr"] = np.nan
        out[f"near_{tf}_level"] = False
        out[f"{tf}_candle_open_time"] = pd.NaT
    counts=[]; nearest_tf=[]; nearest_dist=[]; labels=[]
    for idx,row in out.iterrows():
        pattern_rank=TF_MINUTES.get(str(row.timeframe),0); boundary=float(row.breakout_boundary); atr=float(row.atr)
        found=[]
        for tf in ("M5","M15","H1"):
            if tf not in frames or TF_MINUTES[tf] <= pattern_rank: continue
            frame=frames[tf]; close_times=frame.event_time + pd.Timedelta(minutes=TF_MINUTES[tf])
            eligible=frame.loc[close_times <= pd.Timestamp(row.breakout_time)]
            if eligible.empty: continue
            candle=eligible.iloc[-1]; level=float(candle.high if row.breakout_side=="UP" else candle.low)
            distance=abs(boundary-level)/atr if np.isfinite(atr) and atr>0 else np.nan
            near=bool(np.isfinite(distance) and distance <= tolerance_atr)
            out.at[idx,f"{tf}_level"]=level; out.at[idx,f"{tf}_level_distance_atr"]=distance
            out.at[idx,f"near_{tf}_level"]=near; out.at[idx,f"{tf}_candle_open_time"]=candle.event_time
            found.append((tf,distance,near))
        near_items=[x for x in found if x[2]]
        counts.append(len(near_items))
        valid=[x for x in found if np.isfinite(x[1])]
        if valid:
            best=min(valid,key=lambda x:x[1]); nearest_tf.append(best[0]); nearest_dist.append(best[1])
        else:
            nearest_tf.append(None); nearest_dist.append(np.nan)
        labels.append("MULTI_TF_CONFLUENCE" if len(near_items)>=2 else "SINGLE_HTF_CONFLUENCE" if len(near_items)==1 else "NO_HTF_CONFLUENCE")
    out["higher_tf_confluence_count"]=counts
    out["nearest_higher_tf"]=nearest_tf
    out["nearest_higher_tf_distance_atr"]=nearest_dist
    out["higher_tf_context"]=labels
    return out


def stats(events: pd.DataFrame,horizons:list[int])->pd.DataFrame:
    if events.empty:return pd.DataFrame()
    rows=[]
    keys=["timeframe","pattern_type","breakout_side","higher_tf_context"]
    for vals,g in events.groupby(keys,dropna=False):
        row=dict(zip(keys,vals)); row.update({"sample_size":len(g),"false_breakout_rate":float(g.false_breakout.mean()),"retest_rate":float(g.retest.mean()),"avg_quality":float(g.quality_score.mean()),"avg_breakout_atr":float(g.breakout_distance_atr.mean()),"avg_volume_ratio":float(g.breakout_volume_ratio.mean()),"avg_htf_confluence_count":float(g.higher_tf_confluence_count.mean())})
        for h in horizons: row.update({f"success_rate_{h}":float(g[f"success_{h}"].mean()),f"avg_mfe_{h}_atr":float(g[f"mfe_{h}_atr"].mean()),f"avg_mae_{h}_atr":float(g[f"mae_{h}_atr"].mean()),f"avg_return_{h}_atr":float(g[f"return_{h}_atr"].mean())})
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["timeframe","sample_size"],ascending=[True,False])


def parse_args():
    p=argparse.ArgumentParser(description="Classical pattern research with higher-TF level context")
    p.add_argument("--symbol",default="GOLD");p.add_argument("--anchor-tf",default="M5");p.add_argument("--input",default=DEFAULT_INPUT);p.add_argument("--fallback-template",default=DEFAULT_FALLBACK);p.add_argument("--output",default=DEFAULT_OUTPUT)
    p.add_argument("--timeframes",nargs="+",default=["M1","M5","M15","H1"]);p.add_argument("--windows",nargs="+",type=int,default=[12,20,30]);p.add_argument("--horizons",nargs="+",type=int,default=[3,6,12])
    p.add_argument("--min-touches",type=int,default=2);p.add_argument("--touch-tolerance-atr",type=float,default=.18);p.add_argument("--breakout-buffer-atr",type=float,default=.08);p.add_argument("--false-break-horizon",type=int,default=3);p.add_argument("--retest-horizon",type=int,default=6)
    p.add_argument("--slope-flat",type=float,default=.025);p.add_argument("--slope-directional",type=float,default=.025);p.add_argument("--min-compression",type=float,default=.25);p.add_argument("--max-range-width-atr",type=float,default=2.5);p.add_argument("--min-r2",type=float,default=.15)
    p.add_argument("--higher-tf-level-tolerance-atr",type=float,default=.20)
    return p.parse_args()


def main():
    a=parse_args();root=Path.cwd();symbol=a.symbol.upper();anchor=a.anchor_tf.upper();input_path=root/a.input.format(symbol=symbol,anchor_tf=anchor);out=root/a.output.format(symbol=symbol,anchor_tf=anchor);out.mkdir(parents=True,exist_ok=True)
    log(f"Lendo MTF: {input_path}");raw=normalize_time(pd.read_parquet(input_path));log(f"Linhas MTF: {len(raw)}")
    all_ev=[];all_st=[];frames={};sources={};skipped={};rows_by_tf={}
    for tf in [str(x).upper() for x in a.timeframes]:
        try:
            frame=build_frame_from_mtf(raw,tf);source=str(input_path)+" (MTF deduplicado)"
        except ValueError as exc:
            fallback=root/a.fallback_template.format(symbol=symbol,tf=tf,anchor_tf=anchor)
            if not fallback.exists(): skipped[tf]=f"{exc}; fallback ausente: {fallback}";log(f"{tf}: ignorado — {skipped[tf]}");continue
            frame=build_frame_from_fallback(fallback);source=str(fallback)
        frames[tf]=frame;rows_by_tf[tf]=len(frame);sources[tf]=source;log(f"{tf}: candles únicos={len(frame)} | fonte={source}")
        ev,st=detect(frame,symbol,tf,a);log(f"{tf}: eventos={len(ev)} | episódios ativos={len(st)}")
        if not ev.empty:all_ev.append(ev)
        if not st.empty:all_st.append(st)
    ev=pd.concat(all_ev,ignore_index=True) if all_ev else pd.DataFrame();st=pd.concat(all_st,ignore_index=True) if all_st else pd.DataFrame()
    ev=enrich_higher_tf_context(ev,frames,a.higher_tf_level_tolerance_atr)
    summary=stats(ev,sorted(set(a.horizons)))
    ev.to_parquet(out/"pattern_events.parquet",index=False);st.to_parquet(out/"pattern_active_episodes.parquet",index=False);summary.to_csv(out/"pattern_statistics.csv",index=False,encoding="utf-8-sig")
    if not ev.empty:
        ev[["pattern_id","timeframe","pattern_type","breakout_time","breakout_side","breakout_boundary","higher_tf_context","higher_tf_confluence_count","nearest_higher_tf","nearest_higher_tf_distance_atr"]].to_csv(out/"pattern_breakout_context.csv",index=False,encoding="utf-8-sig")
    current=[]
    if not st.empty:
        for tf,g in st.groupby("timeframe"): current.extend(g.sort_values("event_time").tail(3).sort_values("quality_score",ascending=False).to_dict("records"))
    save_json(out/"pattern_current_state.json",{"schema_version":"2.1","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"patterns":current})
    meta={"script":"market_pattern_research_v2.py","version":"2.1-htf-context","generated_at_utc":datetime.now(timezone.utc).isoformat(),"symbol":symbol,"anchor_tf":anchor,"rows_mtf":len(raw),"rows_by_timeframe":rows_by_tf,"sources":sources,"skipped":skipped,"events":len(ev),"events_with_htf_confluence":int((ev.higher_tf_confluence_count>0).sum()) if len(ev) else 0,"events_with_multi_htf_confluence":int((ev.higher_tf_confluence_count>1).sum()) if len(ev) else 0,"active_episodes":len(st),"statistics_rows":len(summary),"higher_tf_level_tolerance_atr":a.higher_tf_level_tolerance_atr,"output":str(out)}
    save_json(out/"metadata.json",meta);log("OK");print(json.dumps(clean(meta),ensure_ascii=False,indent=2))


if __name__=="__main__":main()
