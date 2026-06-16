#!/usr/bin/env python3
"""
TradingAgent - Agente Intraday

FINALIDADE
    Orquestrar análises intraday em modo single ou ensemble usando LangGraph.

ENTRADAS
    - tradingagent.json
    - data/payload/{symbol}_intraday_payload.json
    - prompts/promptIntraday.md
    - memória anterior opcional em data/state/{symbol}_intraday_state.json

PROCESSAMENTO
    - single: executa apenas um analista configurado; não chama crítico ou árbitro.
    - ensemble: executa analistas independentes, calcula consenso, chama crítico e árbitro.
    - usa asyncio, timeout e semáforo por provider.

SAÍDAS
    - data/state/{symbol}_intraday_state.json
    - data/agent_results/{symbol}_intraday_latest.json
    - data/agent_runs/{symbol}_intraday_runs.jsonl

OBSERVAÇÕES
    - O payload deve permanecer factual e sem viés decisório.
    - No modo single, promptCritic.md e promptArbiter.md não são necessários.
    - A avaliação da tese anterior, a ação imediata e a nova tese são campos
      separados para evitar ambiguidade entre memória e decisão atual.
    - A memória operacional usa schema 1.1 e é sobrescrita a cada ciclo.
    - Estados antigos no schema 1.0 continuam sendo aceitos como entrada.
    - BUY/SELL passam por validação determinística de integridade:
      exigem gatilho/entrada, stop e target_1; incoerências rebaixam a ação
      imediata para WAIT sem apagar a análise original.
    - O primeiro provider implementado é Ollama; outros já podem existir no JSON,
      mas precisam de implementação antes do uso.

EXEMPLOS
    python agent/intraday_agent.py --symbol GOLD
    python agent/intraday_agent.py --symbol GOLD --mode single --analyst analyst_1
    python agent/intraday_agent.py --symbol GOLD --mode ensemble
"""
from __future__ import annotations

import argparse, asyncio, json, re, sys, time, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

import httpx
from langgraph.graph import START, END, StateGraph

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'tradingagent.json'
ACTIONS = {'BUY','SELL','WAIT'}
STATUSES = {'CONFIRMED','PARTIALLY_CONFIRMED','STILL_DEVELOPING','INVALIDATED','EXPIRED','REPLACED','NO_PREVIOUS_THESIS'}

def log(message: str) -> None:
    stamp = datetime.now().strftime('%H:%M:%S')
    print(f'[{stamp}] {message}', flush=True)

async def await_with_heartbeat(task, label: str, heartbeat_seconds: int):
    started = time.perf_counter()
    while True:
        done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
        if done:
            return await task
        elapsed = round(time.perf_counter() - started)
        log(f'{label} ainda em execução | elapsed={elapsed}s')

class S(TypedDict, total=False):
    run_id:str; symbol:str; mode:str; selected_analyst:str|None
    config:dict[str,Any]; payload:dict[str,Any]; memory:dict[str,Any]|None
    analyst_results:list[dict[str,Any]]; consensus:dict[str,Any]|None
    critic_result:dict[str,Any]|None; arbiter_result:dict[str,Any]|None
    final_result:dict[str,Any]|None; errors:list[dict[str,Any]]
    started_perf:float

def now(): return datetime.now(timezone.utc).isoformat()
def read_json(p:Path): return json.loads(p.read_text(encoding='utf-8'))
def write_json(p:Path,d:dict):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+'.tmp')
    t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(p)
def append_jsonl(p:Path,d:dict):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a',encoding='utf-8') as f: f.write(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n')
def path_tpl(t:str,symbol:str): return ROOT / t.format(symbol=symbol)
def norm_action(v):
    x=str(v or '').upper().strip(); return x if x in ACTIONS else 'WAIT'
def norm_status(v):
    x=str(v or '').upper().strip(); return x if x in STATUSES else 'NO_PREVIOUS_THESIS'
def extract_json(txt:str):
    txt=txt.strip()
    try:
        v=json.loads(txt); assert isinstance(v,dict); return v
    except Exception: pass
    m=re.search(r'```(?:json)?\s*(\{.*?\})\s*```',txt,re.S|re.I)
    if m: return json.loads(m.group(1))
    a,b=txt.find('{'),txt.rfind('}')
    if a>=0 and b>a: return json.loads(txt[a:b+1])
    raise ValueError('Resposta não contém JSON válido')
def mode_from(cfg,cli):
    if cli: return cli
    m=cfg['agent']['execution_modes']; enabled=[k for k in ('single','ensemble') if bool(m.get(k))]
    if len(enabled)!=1: raise ValueError("Exatamente um modo deve estar True em agent.execution_modes")
    return enabled[0]
def role_by_id(cfg,rid):
    for r in cfg['llm']['roles']['analysts']:
        if r['id']==rid and r.get('enabled',True): return r
    raise ValueError(f'Analista inválido/desabilitado: {rid}')
def enabled_roles(cfg): return [r for r in cfg['llm']['roles']['analysts'] if r.get('enabled',True)]
def load_prompt(rel):
    p=ROOT/rel
    if not p.exists(): raise FileNotFoundError(f'Prompt não encontrado: {p}')
    return p.read_text(encoding='utf-8')

def compact_payload(p):
    out={'payload_schema_version':p.get('payload_schema_version'),'symbol':p.get('symbol'),'current_price':p.get('current_price'),'market_status':p.get('market_status'),'generated_at_utc':p.get('generated_at_utc'),'timeframes':{}}
    for tf,b in p.get('timeframes',{}).items():
        out['timeframes'][tf]={k:b.get(k) for k in ('current_bar','previous_closed_bar','indicators_exact','derived_metrics_exact','algorithmic_annotations','nearby_level_zones','pattern_geometry','recent_bars')}
    return out

ANALYST_SCHEMA='''
Responda SOMENTE com JSON válido, sem Markdown:
{
  "action": "BUY|SELL|WAIT",
  "confidence": "LOW|MODERATE|HIGH",
  "summary": "interpretação da ação imediata",
  "previous_thesis_evaluation": {
    "status": "CONFIRMED|PARTIALLY_CONFIRMED|STILL_DEVELOPING|INVALIDATED|EXPIRED|REPLACED|NO_PREVIOUS_THESIS",
    "reason": "explique objetivamente o que aconteceu com a tese anterior"
  },
  "timeframes": {"H1":"...","M15":"...","M5":"...","M1":"somente timing"},
  "patterns": [],
  "trade_plan": {
    "action_now": "BUY|SELL|WAIT",
    "conditional_bias": "BUY|SELL|NEUTRAL",
    "trigger": null,
    "entry_min": null,
    "entry_max": null,
    "stop": null,
    "target_1": null,
    "target_2": null
  },
  "confirmation_conditions": [],
  "invalidation_conditions": [],
  "risk_flags": [],
  "current_thesis": {
    "scenario": "identificador curto",
    "action_now": "BUY|SELL|WAIT",
    "conditional_bias": "BUY|SELL|NEUTRAL",
    "summary": "nova tese da rodada atual",
    "trigger": null,
    "invalidation": null,
    "expiry_minutes": 15
  }
}
Regras adicionais:
- previous_thesis_evaluation descreve somente a tese recebida na memória.
- current_thesis descreve somente a nova tese criada nesta rodada.
- action é a ação imediata e deve ser igual a trade_plan.action_now.
- Se action=WAIT, conditional_bias pode ser BUY, SELL ou NEUTRAL.
- Não use o termo invalidation sem deixar claro se é invalidação da nova tese.
- Não reutilize a tese anterior como nova tese sem explicar por que ela continua válida.
- Não invente níveis, probabilidades ou fatos ausentes.
- A memória serve para testar a tese anterior, não para defendê-la.
'''
CRITIC='''Você é o crítico do TradingAgent. Compare os analistas com os fatos e a memória. Detecte invenções. Não decida por maioria simples. Responda SOMENTE JSON:
{"recommended_action":"BUY|SELL|WAIT","previous_thesis_status":"CONFIRMED|PARTIALLY_CONFIRMED|STILL_DEVELOPING|INVALIDATED|EXPIRED|REPLACED|NO_PREVIOUS_THESIS","agreement_level":"UNANIMOUS|PARTIAL|CONFLICTED|INSUFFICIENT","requires_arbiter":true,"summary":"...","model_evaluations":[],"key_agreements":[],"key_disagreements":[],"hallucination_flags":[],"recommended_levels":{"trigger":null,"invalidation":null,"target_1":null,"target_2":null}}'''
ARBITER='''Você é o árbitro final. Use os fatos como fonte primária, não apenas a maioria. Se o setup estiver incompleto, WAIT. Responda SOMENTE JSON:
{"final_action":"BUY|SELL|WAIT","confidence":"LOW|MODERATE|HIGH","previous_thesis_status":"CONFIRMED|PARTIALLY_CONFIRMED|STILL_DEVELOPING|INVALIDATED|EXPIRED|REPLACED|NO_PREVIOUS_THESIS","summary":"...","decision_basis":{"majority_action":"BUY|SELL|WAIT","critic_action":"BUY|SELL|WAIT","selected_action":"BUY|SELL|WAIT","reason":"..."},"levels":{"trigger":null,"entry_min":null,"entry_max":null,"invalidation":null,"target_1":null,"target_2":null},"confirmation_conditions":[],"invalidation_conditions":[],"risk_flags":[],"current_thesis":{"scenario":"...","summary":"...","expiry_minutes":15}}'''

class Runtime:
    def __init__(self,cfg):
        self.cfg=cfg
        self.global_sem=asyncio.Semaphore(int(cfg['agent']['concurrency']['global_max_parallel_llm_requests']))
        self.provider_sems={n:asyncio.Semaphore(max(1,int(p.get('max_parallel_requests',1)))) for n,p in cfg['llm']['providers'].items()}
    async def call(self,model_ref,prompt,role_id):
        mc=self.cfg['llm']['models'][model_ref]; pn=mc['provider']; pc=self.cfg['llm']['providers'][pn]
        if pc['type']!='ollama': raise NotImplementedError(f'Provider ainda não implementado: {pn}')
        body={'model':mc['model'],'prompt':prompt,'stream':False,'format':'json','keep_alive':pc.get('keep_alive','10m'),'options':{'temperature':mc.get('temperature',0),'num_ctx':mc.get('num_ctx',32768),'num_predict':mc.get('max_output_tokens',1400)}}
        started=time.perf_counter(); last=None
        async with self.global_sem,self.provider_sems[pn]:
            for attempt in range(int(pc.get('max_retries',1))+1):
                try:
                    timeout_seconds = float(pc.get('timeout_seconds', 300))
                    heartbeat_seconds = int(self.cfg['agent']['execution'].get('heartbeat_seconds', 30))
                    log(
                        f'LLM início | role={role_id} | model={mc["model"]} '
                        f'| provider={pn} | prompt_chars={len(prompt)} | timeout={timeout_seconds}s'
                    )
                    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                        request_task = asyncio.create_task(
                            client.post(pc['base_url'].rstrip('/') + '/api/generate', json=body)
                        )
                        r = await await_with_heartbeat(
                            request_task,
                            f'LLM role={role_id}',
                            heartbeat_seconds,
                        )
                        r.raise_for_status()
                        raw = r.json()
                    log(
                        f'LLM fim | role={role_id} | prompt_tokens={raw.get("prompt_eval_count")} '
                        f'| output_tokens={raw.get("eval_count")}'
                    )
                    return {'success':True,'role_id':role_id,'model_ref':model_ref,'requested_model':mc['model'],'actual_model':raw.get('model'),'provider':pn,'latency_ms':round((time.perf_counter()-started)*1000),'usage':{'prompt_tokens':raw.get('prompt_eval_count'),'output_tokens':raw.get('eval_count'),'total_duration_ns':raw.get('total_duration')},'format_valid':True,'content':extract_json(str(raw.get('response',''))),'error':None}
                except Exception as e:
                    last=e
                    if attempt<int(pc.get('max_retries',1)): await asyncio.sleep(1.5*(attempt+1))
        return {'success':False,'role_id':role_id,'model_ref':model_ref,'requested_model':mc['model'],'actual_model':None,'provider':pn,'latency_ms':round((time.perf_counter()-started)*1000),'usage':{},'format_valid':False,'content':None,'error':f'{type(last).__name__}: {last}'}

def validate_analyst(c, rid):
    c['role'] = 'analyst'
    c['analyst_id'] = rid
    c['action'] = norm_action(c.get('action'))
    c.setdefault('confidence', 'LOW')
    c.setdefault('summary', '')
    c.setdefault('timeframes', {})
    c.setdefault('patterns', [])
    c.setdefault('confirmation_conditions', [])
    c.setdefault('invalidation_conditions', [])
    c.setdefault('risk_flags', [])

    previous_eval = c.get('previous_thesis_evaluation')
    if not isinstance(previous_eval, dict):
        previous_eval = {
            'status': norm_status(c.get('previous_thesis_status')),
            'reason': '',
        }
    previous_eval['status'] = norm_status(previous_eval.get('status'))
    previous_eval.setdefault('reason', '')
    c['previous_thesis_evaluation'] = previous_eval
    c['previous_thesis_status'] = previous_eval['status']

    trade_plan = c.get('trade_plan')
    if not isinstance(trade_plan, dict):
        old_levels = c.get('levels') if isinstance(c.get('levels'), dict) else {}
        trade_plan = {
            'action_now': c['action'],
            'conditional_bias': 'NEUTRAL',
            'trigger': old_levels.get('trigger'),
            'entry_min': old_levels.get('entry_min'),
            'entry_max': old_levels.get('entry_max'),
            'stop': old_levels.get('invalidation'),
            'target_1': old_levels.get('target_1'),
            'target_2': old_levels.get('target_2'),
        }
    trade_plan['action_now'] = c['action']
    bias = str(trade_plan.get('conditional_bias') or 'NEUTRAL').upper()
    trade_plan['conditional_bias'] = bias if bias in {'BUY', 'SELL', 'NEUTRAL'} else 'NEUTRAL'
    for field in ('trigger', 'entry_min', 'entry_max', 'stop', 'target_1', 'target_2'):
        trade_plan.setdefault(field, None)
    c['trade_plan'] = trade_plan
    c['levels'] = {
        'trigger': trade_plan.get('trigger'),
        'entry_min': trade_plan.get('entry_min'),
        'entry_max': trade_plan.get('entry_max'),
        'invalidation': trade_plan.get('stop'),
        'target_1': trade_plan.get('target_1'),
        'target_2': trade_plan.get('target_2'),
    }

    thesis = c.get('current_thesis')
    if not isinstance(thesis, dict):
        thesis = {}
    thesis.setdefault('scenario', '')
    thesis['action_now'] = c['action']
    thesis_bias = str(thesis.get('conditional_bias') or trade_plan.get('conditional_bias') or 'NEUTRAL').upper()
    thesis['conditional_bias'] = thesis_bias if thesis_bias in {'BUY', 'SELL', 'NEUTRAL'} else 'NEUTRAL'
    thesis.setdefault('summary', '')
    thesis.setdefault('trigger', trade_plan.get('trigger'))
    thesis.setdefault('invalidation', trade_plan.get('stop'))
    thesis.setdefault('expiry_minutes', 15)
    c['current_thesis'] = thesis
    return c

async def prepare(s:S): return {}
async def analysts(s:S):
    cfg=s['config']; rt=Runtime(cfg); roles=[role_by_id(cfg,s['selected_analyst'] or 'analyst_1')] if s['mode']=='single' else enabled_roles(cfg)
    async def one(r):
        mc=cfg['llm']['models'][r['model_ref']]
        prompt=load_prompt(r['prompt_path']).replace('{{MARKET_DATA}}',json.dumps(s['payload'],ensure_ascii=False,separators=(',',':')))
        prompt+='\n\nMEMÓRIA:\n'+json.dumps(s.get('memory') or {},ensure_ascii=False,separators=(',',':'))
        prompt+=f"\n\nVocê é {r['id']}. Propósito: {mc.get('purpose','')}. Foco: {mc.get('focus',[])}."+ANALYST_SCHEMA
        x=await rt.call(r['model_ref'],prompt,r['id'])
        if x['success']: x['content']=validate_analyst(x['content'],r['id'])
        return x
    log(f'Analistas selecionados: {[r["id"] for r in roles]} | modo={s["mode"]}')
    results=await asyncio.gather(*(one(r) for r in roles))
    errs=[{'stage':'analyst','role_id':x['role_id'],'error':x['error']} for x in results if not x['success']]
    return {'analyst_results':results,'errors':s.get('errors',[])+errs}
async def consensus(s:S):
    ok=[x for x in s.get('analyst_results',[]) if x.get('success')]; votes=Counter(norm_action(x['content'].get('action')) for x in ok); total=len(ok)
    maj=votes.most_common(1)[0][0] if total else 'WAIT'
    return {'consensus':{'successful_analysts':total,'failed_analysts':len(s.get('analyst_results',[]))-total,'votes':{a:votes.get(a,0) for a in ('BUY','SELL','WAIT')},'majority_action':maj,'unanimous':total>0 and len(votes)==1,'agreement_ratio':round(max(votes.values())/total,4) if total else 0.0}}
async def critic(s:S):
    if s['mode']=='single' or not s['config']['agent']['ensemble_mode'].get('call_critic',True):
        log('Crítico ignorado neste modo.')
        return {'critic_result':None}
    cfg=s['config']; role=cfg['llm']['roles']['critic']; p=ROOT/role.get('prompt_path',''); base=p.read_text(encoding='utf-8') if p.exists() else CRITIC
    body={'market_context':compact_payload(s['payload']),'previous_memory':s.get('memory'),'analyst_results':s.get('analyst_results',[]),'consensus':s.get('consensus'),'errors':s.get('errors',[])}
    x=await Runtime(cfg).call(role['model_ref'],base+'\nINPUT:\n'+json.dumps(body,ensure_ascii=False,separators=(',',':')),'critic')
    if x['success']:
        x['content']['recommended_action']=norm_action(x['content'].get('recommended_action')); x['content']['previous_thesis_status']=norm_status(x['content'].get('previous_thesis_status'))
    return {'critic_result':x}
async def arbiter(s:S):
    if s['mode']=='single' or not s['config']['agent']['ensemble_mode'].get('call_arbiter',True):
        log('Árbitro ignorado neste modo.')
        return {'arbiter_result':None}
    cfg=s['config']; role=cfg['llm']['roles']['arbiter']; mode=cfg['agent']['ensemble_mode'].get('arbiter_call_mode','always')
    cc=((s.get('critic_result') or {}).get('content') or {})
    if mode=='on_disagreement' and not cc.get('requires_arbiter',False): return {'arbiter_result':None}
    p=ROOT/role.get('prompt_path',''); base=p.read_text(encoding='utf-8') if p.exists() else ARBITER
    body={'market_context':compact_payload(s['payload']),'previous_memory':s.get('memory'),'analyst_results':s.get('analyst_results',[]),'consensus':s.get('consensus'),'critic_result':s.get('critic_result'),'errors':s.get('errors',[])}
    x=await Runtime(cfg).call(role['model_ref'],base+'\nINPUT:\n'+json.dumps(body,ensure_ascii=False,separators=(',',':')),'arbiter')
    if x['success']:
        x['content']['final_action']=norm_action(x['content'].get('final_action')); x['content']['previous_thesis_status']=norm_status(x['content'].get('previous_thesis_status'))
    return {'arbiter_result':x}


def _number_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_decision_integrity(final: dict[str, Any], current_price: Any) -> dict[str, Any]:
    """
    Valida a executabilidade da decisão final.

    BUY/SELL somente permanecem acionáveis quando existe:
    - gatilho ou zona de entrada;
    - stop técnico;
    - target_1;
    - relações de preço coerentes com a direção.

    Em caso de inconsistência, a análise é preservada, mas a ação imediata
    é rebaixada para WAIT.
    """
    original_action = norm_action(final.get("action"))
    trade_plan = final.get("trade_plan")
    if not isinstance(trade_plan, dict):
        trade_plan = {}

    trade_plan["action_now"] = original_action
    trade_plan.setdefault("conditional_bias", "NEUTRAL")
    for field in ("trigger", "entry_min", "entry_max", "stop", "target_1", "target_2"):
        trade_plan.setdefault(field, None)

    issues = []
    price = _number_or_none(current_price)
    trigger = _number_or_none(trade_plan.get("trigger"))
    entry_min = _number_or_none(trade_plan.get("entry_min"))
    entry_max = _number_or_none(trade_plan.get("entry_max"))
    stop = _number_or_none(trade_plan.get("stop"))
    target_1 = _number_or_none(trade_plan.get("target_1"))

    has_entry_reference = any(v is not None for v in (trigger, entry_min, entry_max))

    if original_action in {"BUY", "SELL"}:
        if not has_entry_reference:
            issues.append("BUY/SELL sem gatilho ou zona de entrada.")
        if stop is None:
            issues.append("BUY/SELL sem stop técnico.")
        if target_1 is None:
            issues.append("BUY/SELL sem target_1.")

        reference = (
            trigger if trigger is not None
            else entry_min if entry_min is not None
            else entry_max if entry_max is not None
            else price
        )

        if stop is not None and reference is not None:
            if original_action == "BUY" and stop >= reference:
                issues.append("Stop de BUY deve ficar abaixo do preço de referência.")
            if original_action == "SELL" and stop <= reference:
                issues.append("Stop de SELL deve ficar acima do preço de referência.")

        if target_1 is not None and reference is not None:
            if original_action == "BUY" and target_1 <= reference:
                issues.append("Target_1 de BUY deve ficar acima do preço de referência.")
            if original_action == "SELL" and target_1 >= reference:
                issues.append("Target_1 de SELL deve ficar abaixo do preço de referência.")

    downgraded = original_action in {"BUY", "SELL"} and bool(issues)
    validated_action = "WAIT" if downgraded else original_action

    if downgraded:
        trade_plan["conditional_bias"] = original_action
        trade_plan["action_now"] = "WAIT"

        thesis = final.get("current_thesis")
        if not isinstance(thesis, dict):
            thesis = {}
        thesis["action_now"] = "WAIT"
        thesis["conditional_bias"] = original_action
        final["current_thesis"] = thesis

        risk_flags = final.get("risk_flags")
        if not isinstance(risk_flags, list):
            risk_flags = []
        risk_flags.append(
            "Ação rebaixada para WAIT pela validação determinística do plano."
        )
        final["risk_flags"] = list(dict.fromkeys(risk_flags))

        summary = str(final.get("summary") or "").strip()
        suffix = (
            " A direção foi preservada como viés condicional, mas a entrada "
            "não é executável sem gatilho, stop e alvo coerentes."
        )
        final["summary"] = (summary + suffix).strip()

    final["action"] = validated_action
    final["trade_plan"] = trade_plan
    final["decision_validation"] = {
        "passed": not issues,
        "original_action": original_action,
        "validated_action": validated_action,
        "downgraded_to_wait": downgraded,
        "issues": issues,
    }
    return final


def final_pick(s:S):
    if s['mode'] == 'single':
        ok = [x for x in s.get('analyst_results', []) if x.get('success')]
        if not ok:
            return {
                'action': 'WAIT', 'confidence': 'LOW',
                'summary': 'Nenhuma resposta válida.',
                'previous_thesis_evaluation': {
                    'status': 'NO_PREVIOUS_THESIS',
                    'reason': 'Não houve resposta válida para avaliar a memória.',
                },
                'trade_plan': {
                    'action_now': 'WAIT', 'conditional_bias': 'NEUTRAL',
                    'trigger': None, 'entry_min': None, 'entry_max': None,
                    'stop': None, 'target_1': None, 'target_2': None,
                },
                'current_thesis': {}, 'source': 'fallback',
            }
        c = ok[0]['content']
        previous_eval = c.get('previous_thesis_evaluation', {
            'status': 'NO_PREVIOUS_THESIS', 'reason': ''
        })
        return {
            'action': norm_action(c.get('action')),
            'confidence': c.get('confidence', 'LOW'),
            'summary': c.get('summary', ''),
            'previous_thesis_evaluation': previous_eval,
            'previous_thesis_status': previous_eval.get('status', 'NO_PREVIOUS_THESIS'),
            'trade_plan': c.get('trade_plan', {}),
            'levels': c.get('levels', {}),
            'confirmation_conditions': c.get('confirmation_conditions', []),
            'invalidation_conditions': c.get('invalidation_conditions', []),
            'risk_flags': c.get('risk_flags', []),
            'current_thesis': c.get('current_thesis', {}),
            'source': ok[0]['role_id'],
        }

    a = s.get('arbiter_result')
    if a and a.get('success'):
        c = a['content']
        previous_eval = c.get('previous_thesis_evaluation')
        if not isinstance(previous_eval, dict):
            previous_eval = {
                'status': norm_status(c.get('previous_thesis_status')),
                'reason': '',
            }
        return {
            'action': norm_action(c.get('final_action')),
            'confidence': c.get('confidence', 'LOW'),
            'summary': c.get('summary', ''),
            'previous_thesis_evaluation': previous_eval,
            'previous_thesis_status': previous_eval.get('status', 'NO_PREVIOUS_THESIS'),
            'trade_plan': c.get('trade_plan', {}),
            'levels': c.get('levels', {}),
            'confirmation_conditions': c.get('confirmation_conditions', []),
            'invalidation_conditions': c.get('invalidation_conditions', []),
            'risk_flags': c.get('risk_flags', []),
            'current_thesis': c.get('current_thesis', {}),
            'source': 'arbiter',
        }

    c = s.get('critic_result')
    if c and c.get('success'):
        z = c['content']
        previous_eval = {
            'status': norm_status(z.get('previous_thesis_status')),
            'reason': z.get('summary', ''),
        }
        levels = z.get('recommended_levels', {})
        action = norm_action(z.get('recommended_action'))
        return {
            'action': action, 'confidence': 'MODERATE',
            'summary': z.get('summary', ''),
            'previous_thesis_evaluation': previous_eval,
            'previous_thesis_status': previous_eval['status'],
            'trade_plan': {
                'action_now': action, 'conditional_bias': 'NEUTRAL',
                'trigger': levels.get('trigger'), 'entry_min': None,
                'entry_max': None, 'stop': levels.get('invalidation'),
                'target_1': levels.get('target_1'),
                'target_2': levels.get('target_2'),
            },
            'levels': levels, 'current_thesis': {}, 'source': 'critic',
        }

    action = norm_action((s.get('consensus') or {}).get('majority_action', 'WAIT'))
    return {
        'action': action, 'confidence': 'LOW',
        'summary': 'Fallback por consenso bruto.',
        'previous_thesis_evaluation': {
            'status': 'NO_PREVIOUS_THESIS',
            'reason': 'Crítico e árbitro indisponíveis.',
        },
        'previous_thesis_status': 'NO_PREVIOUS_THESIS',
        'trade_plan': {
            'action_now': action, 'conditional_bias': 'NEUTRAL',
            'trigger': None, 'entry_min': None, 'entry_max': None,
            'stop': None, 'target_1': None, 'target_2': None,
        },
        'current_thesis': {}, 'source': 'consensus_fallback',
    }

async def finalize(s:S):
    cfg = s['config']
    sym = s['symbol']
    f = final_pick(s)
    f = validate_decision_integrity(
        f,
        s['payload'].get('current_price'),
    )
    ts = now()
    rec={'@timestamp':ts,'run_id':s['run_id'],'project':cfg.get('project',{}).get('name','TradingAgent'),'environment':cfg.get('project',{}).get('environment','dev'),'symbol':sym,'analysis_type':'intraday','execution':{'mode':s['mode'],'selected_analyst':s.get('selected_analyst'),'analysts_requested':len(s.get('analyst_results',[])),'analysts_successful':sum(1 for x in s.get('analyst_results',[]) if x.get('success')),'critic_called':bool(s.get('critic_result')),'arbiter_called':bool(s.get('arbiter_result')),'total_latency_ms':round((time.perf_counter()-s['started_perf'])*1000),'success':True,'errors':s.get('errors',[])},'market':{'payload_schema_version':s['payload'].get('payload_schema_version'),'generated_at_utc':s['payload'].get('generated_at_utc'),'current_price':s['payload'].get('current_price'),'market_status':s['payload'].get('market_status')},'memory_before':s.get('memory'),'analyst_results':s.get('analyst_results',[]),'consensus':s.get('consensus'),'critic_result':s.get('critic_result'),'arbiter_result':s.get('arbiter_result'),'final':f}
    previous_eval = f.get('previous_thesis_evaluation', {
        'status': f.get('previous_thesis_status', 'NO_PREVIOUS_THESIS'),
        'reason': '',
    })
    trade_plan = f.get('trade_plan', {})
    active_thesis = f.get('current_thesis', {})
    mem = {
        'schema_version': '1.1',
        'symbol': sym,
        'updated_at_utc': ts,
        'last_run_id': s['run_id'],
        'last_action': f['action'],
        'last_price': s['payload'].get('current_price'),
        'previous_thesis_evaluation': previous_eval,
        'active_thesis': active_thesis,
        'trade_plan': trade_plan,
        'confirmation_conditions': f.get('confirmation_conditions', []),
        'invalidation_conditions': f.get('invalidation_conditions', []),
        # Compatibilidade temporária com consumidores do schema 1.0.
        'previous_action': f['action'],
        'previous_price': s['payload'].get('current_price'),
        'previous_thesis_status': previous_eval.get('status', 'NO_PREVIOUS_THESIS'),
        'levels': f.get('levels', {}),
    }
    paths=cfg['agent']['paths']; write_json(path_tpl(paths['state_template'],sym),mem); write_json(path_tpl(paths['latest_result_template'],sym),rec); append_jsonl(path_tpl(paths['runs_template'],sym),rec)
    return {'final_result':rec,'memory':mem}
def graph():
    g=StateGraph(S)
    for n,f in [('prepare',prepare),('analysts',analysts),('consensus',consensus),('critic',critic),('arbiter',arbiter),('finalize',finalize)]: g.add_node(n,f)
    g.add_edge(START,'prepare'); g.add_edge('prepare','analysts'); g.add_edge('analysts','consensus'); g.add_edge('consensus','critic'); g.add_edge('critic','arbiter'); g.add_edge('arbiter','finalize'); g.add_edge('finalize',END)
    return g.compile()
async def run(args):
    cfg=read_json(CONFIG); mode=mode_from(cfg,args.mode); sym=args.symbol.upper(); sel=None
    log(f'Execução iniciada | symbol={sym} | mode={mode}')
    if mode=='single': sel=args.analyst or cfg['agent']['single_mode'].get('analyst_id','analyst_1'); role_by_id(cfg,sel)
    payload=read_json(path_tpl(cfg['agent']['paths']['payload_template'],sym)); sp=path_tpl(cfg['agent']['paths']['state_template'],sym); mem=read_json(sp) if sp.exists() else None
    init:S={'run_id':f"{sym}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",'symbol':sym,'mode':mode,'selected_analyst':sel,'config':cfg,'payload':payload,'memory':mem,'analyst_results':[],'consensus':None,'critic_result':None,'arbiter_result':None,'final_result':None,'errors':[],'started_perf':time.perf_counter()}
    round_timeout = float(cfg['agent']['execution']['round_timeout_seconds'])
    try:
        out = await asyncio.wait_for(graph().ainvoke(init), timeout=round_timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f'Rodada excedeu round_timeout_seconds={round_timeout}. '
            f'Modo={mode}, símbolo={sym}. Verifique os heartbeats acima.'
        ) from exc
    return out['final_result']
def args():
    p=argparse.ArgumentParser(); p.add_argument('--symbol',required=True); p.add_argument('--mode',choices=['single','ensemble']); p.add_argument('--analyst'); return p.parse_args()
def main():
    try: r=asyncio.run(run(args()))
    except Exception as e: print(f'ERRO: {type(e).__name__}: {e}',file=sys.stderr); return 1
    print(f"Run concluído | símbolo={r['symbol']} | modo={r['execution']['mode']} | ação={r['final']['action']} | fonte={r['final']['source']} | latency_ms={r['execution']['total_latency_ms']}")
    return 0
if __name__=='__main__': raise SystemExit(main())
