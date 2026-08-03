//+------------------------------------------------------------------+
//| TradingAgent_SignalPanel_EA.mq5                                  |
//| Painel/alerta operacional baseado nas regras estudadas            |
//|                                                                  |
//| v8: level zones por TF, breakout power e entry check compacto.    |
//+------------------------------------------------------------------+
#property strict
#property version   "8.00"
#property description "TradingAgent signal-only panel: MA research replica, event state, level zones, breakout power, M5/M1 filter."

// -------------------------------------------------------------------
// IMPORTANTE
// -------------------------------------------------------------------
// Este EA e somente sinalizador/painel.
// Nao usa CTrade, nao chama OrderSend, nao abre/fecha posicoes.
// Pode ser usado em conta real como painel visual, mas valide sempre.
//
// Nota de fidelidade com o projeto Python:
// - O Python possui leitura mais rica: pattern_geometry, nearby level zones,
//   swings/ZigZag, BOS/CHOCH, sweeps, FVG e breakout_attempt_context.
// - Este EA v8 aproxima a leitura local usando candle fechado anterior e
//   zonas simples por lookback/swing. Nao e uma replica completa do Python.

input string             InpSymbol                    = "";
input bool               InpSignalOnlyMode            = true;
input bool               InpEnableAlerts              = true;
input bool               InpEnablePush                = false;
input int                InpTimerSeconds              = 2;

// Visual
input int                InpPanelX                    = 10;
input int                InpPanelY                    = 28;
input int                InpPanelWidth                = 900;
input int                InpPanelHeight               = 820;
input int                InpFontSize                  = 15;
input int                InpTitleFontSize             = 19;
input int                InpLineHeight                = 22;
input string             InpFontName                  = "Consolas";
input bool               InpDimCandles                = false;
input bool               InpHideCandles               = false;
input bool               InpShowBothSideTriggers      = false;
input bool               InpShowDebugDetails          = false;

// Medias
input ENUM_MA_METHOD     InpMAMethod                  = MODE_EMA;
input ENUM_APPLIED_PRICE InpMAPrice                   = PRICE_CLOSE;
input bool               InpUseClosedCandleForMA      = true;
input int                InpM5ClosedAllBars           = 3;

// MA Research Replica - parametros do estudo
input bool               InpMAResearchReplicaMode     = true;
input bool               InpUseSellCoreMA             = true;
input int                InpSellFast                  = 8;
input int                InpSellMid                   = 20;
input int                InpSellSlow                  = 63;
input double             InpSellStopATR               = 1.6;
input double             InpSellTargetATR             = 1.3;
input int                InpSellMaxHoldMin            = 20;

input bool               InpUseBuyCoreMA              = true;
input int                InpBuyFast                   = 6;
input int                InpBuyMid                    = 30;
input int                InpBuySlow                   = 85;
input double             InpBuyStopATR                = 1.0;
input double             InpBuyTargetATR              = 0.8;
input int                InpBuyMaxHoldMin             = 10;

input bool               InpUseBothGeneralMA          = true;
input int                InpBothFast                  = 5;
input int                InpBothMid                   = 30;
input int                InpBothSlow                  = 81;
input double             InpBothStopATR               = 1.3;
input double             InpBothTargetATR             = 1.0;
input int                InpBothMaxHoldMin            = 15;

// Niveis / breakout local
input bool               InpUseLevelZonesForBreakout  = true;
input int                InpZoneLookbackBars          = 36;
input double             InpZoneToleranceATR          = 0.18;
input int                InpAttemptLookbackBars       = 30;
input double             InpAttemptToleranceATR       = 0.20;

// Filtros operacionais
input bool               InpRequireM5Permission       = true;
input bool               InpRequireM1Trigger          = true;
input double             InpMaxM1RangeATRWarning      = 1.50;

string g_symbol;
string g_last_action = "";
datetime g_last_alert_time = 0;
string PREFIX = "TA_PANEL_";

struct TFState
{
   string pattern;
   int attempt;
   string basis;
   double breakout_level;
   double support;
   double resistance;
};

struct SignalContext
{
   string action;
   string reason;
   string event_state;
   string active_event;
   string active_side;

   string ma_selected;
   string ma_candidate;
   string ma_missing;
   string ma_side;
   string ma_state;
   string sell_core_state;
   string buy_core_state;
   string both_sell_state;
   string both_buy_state;

   TFState h1;
   TFState m15;
   TFState m5;
   TFState m1;

   string breakout_power;
   string breakout_power_detail;
   string breakout_basis_summary;

   bool m5_sell_ok;
   bool m5_buy_ok;
   bool m1_sell_ok;
   bool m1_buy_ok;
   string m5_sell_detail;
   string m5_buy_detail;
   string m1_sell_detail;
   string m1_buy_detail;

   string entry_side;
   string entry_status;
   string blocked_by;
   string next_step;
};

//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = (InpSymbol == "" ? _Symbol : InpSymbol);
   EventSetTimer(MathMax(1, InpTimerSeconds));
   ApplyChartVisuals();
   DrawPanel();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteObjects();
   Comment("");
}

void OnTick()  { UpdatePanel(); }
void OnTimer() { UpdatePanel(); }

//+------------------------------------------------------------------+
void ApplyChartVisuals()
{
   if(InpHideCandles)
   {
      ChartSetInteger(0, CHART_SHOW, false);
   }
   else
   {
      ChartSetInteger(0, CHART_SHOW, true);
      ChartSetInteger(0, CHART_SHOW_GRID, false);
      ChartSetInteger(0, CHART_SHOW_VOLUMES, false);
      ChartSetInteger(0, CHART_SHOW_TRADE_LEVELS, false);
      if(InpDimCandles)
      {
         ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, clrGainsboro);
         ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, clrLightGray);
         ChartSetInteger(0, CHART_COLOR_CHART_UP, clrGainsboro);
         ChartSetInteger(0, CHART_COLOR_CHART_DOWN, clrLightGray);
         ChartSetInteger(0, CHART_COLOR_GRID, clrWhiteSmoke);
      }
   }
}

void DeleteObjects()
{
   int total = ObjectsTotal(0, 0, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, 0, -1);
      if(StringFind(name, PREFIX) == 0)
         ObjectDelete(0, name);
   }
}

bool GetRates(const ENUM_TIMEFRAMES tf, const int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(g_symbol, tf, 0, count, rates);
   return copied >= count;
}

double Bid()
{
   double v = 0.0;
   SymbolInfoDouble(g_symbol, SYMBOL_BID, v);
   return v;
}

double Ask()
{
   double v = 0.0;
   SymbolInfoDouble(g_symbol, SYMBOL_ASK, v);
   return v;
}

string TFName(const ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M1) return "M1";
   if(tf == PERIOD_M5) return "M5";
   if(tf == PERIOD_M15) return "M15";
   if(tf == PERIOD_H1) return "H1";
   if(tf == PERIOD_H4) return "H4";
   return EnumToString(tf);
}

bool IsBullish(const MqlRates &bar){ return bar.close > bar.open; }
bool IsBearish(const MqlRates &bar){ return bar.close < bar.open; }

//+------------------------------------------------------------------+
double GetATR(const ENUM_TIMEFRAMES tf, const int period=14, const int shift=1)
{
   int handle = iATR(g_symbol, tf, period);
   if(handle == INVALID_HANDLE) return 0.0;
   double buffer[];
   ArraySetAsSeries(buffer, true);
   int copied = CopyBuffer(handle, 0, shift, 1, buffer);
   IndicatorRelease(handle);
   if(copied < 1) return 0.0;
   return buffer[0];
}

double GetMA(const ENUM_TIMEFRAMES tf, const int period, const int shift)
{
   int handle = iMA(g_symbol, tf, period, 0, InpMAMethod, InpMAPrice);
   if(handle == INVALID_HANDLE) return 0.0;
   double buffer[];
   ArraySetAsSeries(buffer, true);
   int copied = CopyBuffer(handle, 0, shift, 1, buffer);
   IndicatorRelease(handle);
   if(copied < 1) return 0.0;
   return buffer[0];
}

bool MAAlignedTF(const ENUM_TIMEFRAMES tf, const int fast, const int mid, const int slow, const string side, const int shift, string &detail)
{
   MqlRates r[];
   if(!GetRates(tf, shift + 3, r))
   {
      detail = TFName(tf) + " sem dados";
      return false;
   }

   double maFast = GetMA(tf, fast, shift);
   double maMid  = GetMA(tf, mid, shift);
   double maSlow = GetMA(tf, slow, shift);
   double closev = r[shift].close;

   bool ok = false;
   if(side == "SELL")
      ok = (maFast > 0 && maMid > 0 && maSlow > 0 && maFast < maMid && maMid < maSlow && closev <= maFast);
   else
      ok = (maFast > 0 && maMid > 0 && maSlow > 0 && maFast > maMid && maMid > maSlow && closev >= maFast);

   detail = StringFormat("%s %s close=%.2f ma(%d/%d/%d)=%.2f/%.2f/%.2f", TFName(tf), side, closev, fast, mid, slow, maFast, maMid, maSlow);
   return ok;
}

bool M5ClosedAllAligned(const int fast, const int mid, const int slow, const string side, string &detail)
{
   int bars = MathMax(1, InpM5ClosedAllBars);
   string d = "";
   for(int s = 1; s <= bars; s++)
   {
      string local = "";
      bool ok = MAAlignedTF(PERIOD_M5, fast, mid, slow, side, s, local);
      if(s == 1) d = local;
      if(!ok)
      {
         detail = "M5 closed_all=" + IntegerToString(bars) + " NO | " + local;
         return false;
      }
   }
   detail = "M5 closed_all=" + IntegerToString(bars) + " OK | " + d;
   return true;
}

string MAReplicaState(const string name, const string side, const int fast, const int mid, const int slow, string &missing, string &debug)
{
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   string m15d = "";
   string m5d = "";
   bool m15 = MAAlignedTF(PERIOD_M15, fast, mid, slow, side, shift, m15d);
   bool m5  = M5ClosedAllAligned(fast, mid, slow, side, m5d);

   debug = name + " | " + m15d + " | " + m5d;
   missing = "";
   if(!m15) missing = "M15";
   if(!m5)  missing = (missing == "" ? "M5_closed_all" : missing + "+M5_closed_all");

   if(m15 && m5) return "VALID";
   if(!m15 && m5) return "WAIT_M15";
   if(m15 && !m5) return "WAIT_M5";
   return "NO_SETUP";
}

//+------------------------------------------------------------------+
bool CalculateLevelZone(const ENUM_TIMEFRAMES tf, double &support, double &resistance, string &basis)
{
   int bars = MathMax(10, InpZoneLookbackBars);
   MqlRates r[];
   if(!GetRates(tf, bars + 5, r))
   {
      support = 0.0;
      resistance = 0.0;
      basis = "no_data";
      return false;
   }

   // usa candles fechados anteriores, ignorando candle atual e candle imediatamente anterior
   double highv = r[2].high;
   double lowv  = r[2].low;
   for(int i = 2; i < bars + 2; i++)
   {
      if(r[i].high > highv) highv = r[i].high;
      if(r[i].low  < lowv)  lowv  = r[i].low;
   }
   support = lowv;
   resistance = highv;
   basis = "zone_lookback_" + IntegerToString(bars);
   return true;
}

int CountAttempts(const ENUM_TIMEFRAMES tf, const bool upper, const double level)
{
   MqlRates r[];
   int need = MathMax(10, InpAttemptLookbackBars + 3);
   if(!GetRates(tf, need, r)) return 0;

   double atr = GetATR(tf, 14, 1);
   if(atr <= 0.0) atr = MathMax(_Point, MathAbs(r[1].high - r[1].low));
   double tol = atr * InpAttemptToleranceATR;
   int attempts = 0;

   for(int i = 1; i < need; i++)
   {
      double v = (upper ? r[i].high : r[i].low);
      if(MathAbs(v - level) <= tol) attempts++;
   }
   if(attempts < 1) attempts = 1;
   if(attempts > 3) attempts = 3;
   return attempts;
}

void BuildTFState(const ENUM_TIMEFRAMES tf, TFState &st)
{
   st.pattern = "NO_DATA";
   st.attempt = 0;
   st.basis = "none";
   st.breakout_level = 0.0;
   st.support = 0.0;
   st.resistance = 0.0;

   MqlRates r[];
   if(!GetRates(tf, MathMax(8, InpZoneLookbackBars + 5), r)) return;

   double price = (Bid() + Ask()) / 2.0;
   double atr = GetATR(tf, 14, 1);
   if(atr <= 0.0) atr = MathMax(_Point, MathAbs(r[1].high - r[1].low));
   double tol = atr * InpZoneToleranceATR;

   double prevHigh = r[1].high;
   double prevLow  = r[1].low;
   double support = 0.0;
   double resistance = 0.0;
   string basis = "prev_closed_candle";
   bool hasZone = false;

   if(InpUseLevelZonesForBreakout)
      hasZone = CalculateLevelZone(tf, support, resistance, basis);

   double upLevel = hasZone ? resistance : prevHigh;
   double dnLevel = hasZone ? support : prevLow;

   st.support = hasZone ? support : prevLow;
   st.resistance = hasZone ? resistance : prevHigh;
   st.basis = hasZone ? basis : "prev_closed_candle";

   bool breakoutUp = price > upLevel + tol;
   bool breakoutDn = price < dnLevel - tol;
   bool fakeUp = (r[0].high > upLevel + tol && price <= upLevel);
   bool fakeDn = (r[0].low < dnLevel - tol && price >= dnLevel);
   bool inside = (price <= upLevel && price >= dnLevel);

   if(fakeUp)
   {
      st.pattern = "FAKEOUT_UP";
      st.breakout_level = upLevel;
      st.attempt = CountAttempts(tf, true, upLevel);
      return;
   }
   if(fakeDn)
   {
      st.pattern = "FAKEOUT_DOWN";
      st.breakout_level = dnLevel;
      st.attempt = CountAttempts(tf, false, dnLevel);
      return;
   }
   if(breakoutUp)
   {
      st.pattern = "BREAKOUT_UP_LIVE";
      st.breakout_level = upLevel;
      st.attempt = CountAttempts(tf, true, upLevel);
      return;
   }
   if(breakoutDn)
   {
      st.pattern = "BREAKOUT_DOWN_LIVE";
      st.breakout_level = dnLevel;
      st.attempt = CountAttempts(tf, false, dnLevel);
      return;
   }
   if(inside)
   {
      st.pattern = "INSIDE_OR_CONSOLIDATION";
      st.attempt = 1;
      return;
   }

   st.pattern = "RANGE_CONTEXT";
   st.attempt = 1;
}

bool M5SellPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)){ detail = "M5 sem dados"; return false; }
   double bid = Bid();
   bool blockedAbovePrevHigh = bid > r[1].high;
   bool ok = !blockedAbovePrevHigh;
   detail = StringFormat("M5 SELL=%s | bid %.2f | prev H/L %.2f/%.2f", ok ? "OK" : "BLOCK", bid, r[1].high, r[1].low);
   return ok;
}

bool M5BuyPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)){ detail = "M5 sem dados"; return false; }
   double ask = Ask();
   bool blockedBelowPrevLow = ask < r[1].low;
   bool ok = !blockedBelowPrevLow;
   detail = StringFormat("M5 BUY=%s | ask %.2f | prev H/L %.2f/%.2f", ok ? "OK" : "BLOCK", ask, r[1].high, r[1].low);
   return ok;
}

bool M1SellTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)){ detail = "M1 sem dados"; return false; }
   double bid = Bid();
   bool previousRed = IsBearish(r[1]);
   bool brokeLow = bid < r[1].low;
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   bool ok = previousRed && brokeLow;
   detail = StringFormat("M1 SELL=%s | prevRed=%s | bid %.2f < low %.2f | rATR=%.2f", ok ? "OK" : "NO", previousRed ? "Y" : "N", bid, r[1].low, rangeAtr);
   return ok;
}

bool M1BuyTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)){ detail = "M1 sem dados"; return false; }
   double ask = Ask();
   bool previousGreen = IsBullish(r[1]);
   bool brokeHigh = ask > r[1].high;
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   bool ok = previousGreen && brokeHigh;
   detail = StringFormat("M1 BUY=%s | prevGreen=%s | ask %.2f > high %.2f | rATR=%.2f", ok ? "OK" : "NO", previousGreen ? "Y" : "N", ask, r[1].high, rangeAtr);
   return ok;
}

//+------------------------------------------------------------------+
void RegisterMAResult(SignalContext &ctx, const string state, const string label, const string side, const string missing)
{
   if(state == "VALID" && ctx.ma_selected == "NONE")
   {
      ctx.ma_selected = label;
      ctx.ma_side = side;
      ctx.ma_state = "VALID";
      ctx.ma_missing = "";
   }
   else if(ctx.ma_selected == "NONE" && ctx.ma_candidate == "NONE" && state != "NO_SETUP" && state != "DISABLED")
   {
      ctx.ma_candidate = label;
      ctx.ma_side = side;
      ctx.ma_state = state;
      ctx.ma_missing = missing;
   }
}

int PatternSideScore(const TFState &st, const string side)
{
   if(side == "BUY" && st.pattern == "BREAKOUT_UP_LIVE") return 1;
   if(side == "SELL" && st.pattern == "BREAKOUT_DOWN_LIVE") return 1;
   return 0;
}

string TFsAlignedForSide(const SignalContext &ctx, const string side)
{
   string text = "";
   if(PatternSideScore(ctx.h1, side) > 0)  text += (text == "" ? "H1" : "/H1");
   if(PatternSideScore(ctx.m15, side) > 0) text += (text == "" ? "M15" : "/M15");
   if(PatternSideScore(ctx.m5, side) > 0)  text += (text == "" ? "M5" : "/M5");
   if(PatternSideScore(ctx.m1, side) > 0)  text += (text == "" ? "M1" : "/M1");
   return text == "" ? "NONE" : text;
}

void BuildBreakoutPower(SignalContext &ctx)
{
   int buy = PatternSideScore(ctx.h1, "BUY") + PatternSideScore(ctx.m15, "BUY") + PatternSideScore(ctx.m5, "BUY") + PatternSideScore(ctx.m1, "BUY");
   int sell = PatternSideScore(ctx.h1, "SELL") + PatternSideScore(ctx.m15, "SELL") + PatternSideScore(ctx.m5, "SELL") + PatternSideScore(ctx.m1, "SELL");

   string side = "NONE";
   int score = 0;
   bool mixed = (buy > 0 && sell > 0);
   if(buy > sell){ side = "BUY"; score = buy; }
   else if(sell > buy){ side = "SELL"; score = sell; }
   else if(buy == sell && buy > 0){ side = "MIXED"; score = buy; }

   if(mixed || side == "MIXED")
      ctx.breakout_power = "MIXED";
   else if(score <= 0)
      ctx.breakout_power = "NONE";
   else if(score == 1)
      ctx.breakout_power = "WEAK";
   else if(score == 2)
      ctx.breakout_power = "MEDIUM";
   else if(score == 3)
      ctx.breakout_power = "STRONG";
   else
      ctx.breakout_power = "VERY_STRONG";

   string tfs = (side == "BUY" || side == "SELL") ? TFsAlignedForSide(ctx, side) : "mixed_tf";
   ctx.breakout_power_detail = ctx.breakout_power + " | " + tfs + " | side=" + side;
   ctx.breakout_basis_summary = "basis: level zones lookback/swing; fallback prev candle H/L";
}

void BuildEntryCheck(SignalContext &ctx)
{
   string side = ctx.ma_side;
   if(side == "NONE") side = ctx.active_side;
   ctx.entry_side = side;

   bool m5ok = false;
   bool m1ok = false;
   if(side == "SELL")
   {
      m5ok = ctx.m5_sell_ok;
      m1ok = ctx.m1_sell_ok;
   }
   else if(side == "BUY")
   {
      m5ok = ctx.m5_buy_ok;
      m1ok = ctx.m1_buy_ok;
   }

   ctx.blocked_by = "NONE";
   ctx.next_step = "aguardar novo contexto";
   ctx.entry_status = "side=" + side + " | M5=" + (m5ok ? "OK" : "NO") + " | M1=" + (m1ok ? "OK" : "NO");

   if(side == "NONE")
   {
      ctx.blocked_by = "NO_ACTIVE_SIDE";
      ctx.next_step = "aguardar padrao/evento ou MA valido";
   }
   else if(ctx.ma_candidate != "NONE" && ctx.ma_selected == "NONE")
   {
      ctx.blocked_by = ctx.ma_state;
      ctx.next_step = "aguardar " + ctx.ma_missing + " do MA_RESEARCH";
   }
   else if(ctx.event_state == "WAIT_ACCEPTANCE_OR_RETEST")
   {
      ctx.blocked_by = "WAIT_ACCEPTANCE_OR_RETEST";
      ctx.next_step = "aguardar candle fechado/reteste da regiao rompida";
   }
   else if(ctx.event_state == "WAIT_FAKEOUT_RETURN")
   {
      if(!m5ok)
      {
         ctx.blocked_by = "M5_PERMISSION";
         ctx.next_step = "aguardar M5 permitir o lado do fade";
      }
      else if(!m1ok)
      {
         ctx.blocked_by = "M1_TRIGGER";
         ctx.next_step = "aguardar gatilho M1 no lado do fade";
      }
      else
      {
         ctx.blocked_by = "FAKEOUT_RETURN_CONFIRMATION";
         ctx.next_step = "aguardar confirmacao/reteste do retorno";
      }
   }
   else if(!m5ok)
   {
      ctx.blocked_by = "M5_PERMISSION";
      ctx.next_step = "aguardar M5 permitir o lado relevante";
   }
   else if(!m1ok)
   {
      ctx.blocked_by = "M1_TRIGGER";
      ctx.next_step = "aguardar gatilho M1";
   }
   else
   {
      ctx.blocked_by = "NONE";
      ctx.next_step = "entrada operacional alinhada, validar risco manual";
   }

   ctx.entry_status += " | blocked_by=" + ctx.blocked_by;
}

void BuildContext(SignalContext &ctx)
{
   ctx.action = "WAIT";
   ctx.reason = "sem confluencia operacional";
   ctx.ma_selected = "NONE";
   ctx.ma_candidate = "NONE";
   ctx.ma_missing = "";
   ctx.ma_side = "NONE";
   ctx.ma_state = "NO_SETUP";

   BuildTFState(PERIOD_H1,  ctx.h1);
   BuildTFState(PERIOD_M15, ctx.m15);
   BuildTFState(PERIOD_M5,  ctx.m5);
   BuildTFState(PERIOD_M1,  ctx.m1);

   string miss = "";
   string dbg = "";
   ctx.sell_core_state = "DISABLED";
   ctx.buy_core_state = "DISABLED";
   ctx.both_sell_state = "DISABLED";
   ctx.both_buy_state = "DISABLED";

   if(InpUseSellCoreMA)
   {
      ctx.sell_core_state = MAReplicaState("SELL_CORE", "SELL", InpSellFast, InpSellMid, InpSellSlow, miss, dbg);
      RegisterMAResult(ctx, ctx.sell_core_state, "SELL_CORE 8/20/63", "SELL", miss);
   }
   if(InpUseBuyCoreMA)
   {
      ctx.buy_core_state = MAReplicaState("BUY_CORE", "BUY", InpBuyFast, InpBuyMid, InpBuySlow, miss, dbg);
      RegisterMAResult(ctx, ctx.buy_core_state, "BUY_CORE 6/30/85", "BUY", miss);
   }
   if(InpUseBothGeneralMA)
   {
      ctx.both_sell_state = MAReplicaState("BOTH_SELL", "SELL", InpBothFast, InpBothMid, InpBothSlow, miss, dbg);
      RegisterMAResult(ctx, ctx.both_sell_state, "BOTH_SELL 5/30/81", "SELL", miss);

      ctx.both_buy_state = MAReplicaState("BOTH_BUY", "BUY", InpBothFast, InpBothMid, InpBothSlow, miss, dbg);
      RegisterMAResult(ctx, ctx.both_buy_state, "BOTH_BUY 5/30/81", "BUY", miss);
   }

   ctx.active_event = "RANGE_OR_TRANSITION";
   ctx.event_state = "WAIT_CONTEXT";
   ctx.active_side = "NONE";

   if(ctx.m5.pattern == "BREAKOUT_UP_LIVE" || ctx.m1.pattern == "BREAKOUT_UP_LIVE")
   {
      ctx.active_event = "BREAKOUT_UP_WAIT_ACCEPTANCE";
      ctx.event_state = "WAIT_ACCEPTANCE_OR_RETEST";
      ctx.active_side = "BUY";
   }
   if(ctx.m5.pattern == "BREAKOUT_DOWN_LIVE" || ctx.m1.pattern == "BREAKOUT_DOWN_LIVE")
   {
      ctx.active_event = "BREAKOUT_DOWN_WAIT_ACCEPTANCE";
      ctx.event_state = "WAIT_ACCEPTANCE_OR_RETEST";
      ctx.active_side = "SELL";
   }
   if(ctx.m5.pattern == "FAKEOUT_UP" || ctx.m1.pattern == "FAKEOUT_UP" || ctx.m15.pattern == "FAKEOUT_UP")
   {
      ctx.active_event = "BREAKOUT_UP_FAILED_FAKEOUT";
      ctx.event_state = "WAIT_FAKEOUT_RETURN";
      ctx.active_side = "SELL";
   }
   if(ctx.m5.pattern == "FAKEOUT_DOWN" || ctx.m1.pattern == "FAKEOUT_DOWN" || ctx.m15.pattern == "FAKEOUT_DOWN")
   {
      ctx.active_event = "BREAKOUT_DOWN_FAILED_FAKEOUT";
      ctx.event_state = "WAIT_FAKEOUT_RETURN";
      ctx.active_side = "BUY";
   }

   ctx.m5_sell_ok = M5SellPermission(ctx.m5_sell_detail);
   ctx.m5_buy_ok  = M5BuyPermission(ctx.m5_buy_detail);
   ctx.m1_sell_ok = M1SellTrigger(ctx.m1_sell_detail);
   ctx.m1_buy_ok  = M1BuyTrigger(ctx.m1_buy_detail);

   BuildBreakoutPower(ctx);

   if(ctx.ma_selected != "NONE")
   {
      string side = ctx.ma_side;
      bool m5ok = (side == "SELL" ? ctx.m5_sell_ok : ctx.m5_buy_ok);
      bool m1ok = (side == "SELL" ? ctx.m1_sell_ok : ctx.m1_buy_ok);

      if(InpRequireM5Permission && !m5ok)
      {
         ctx.action = "WAIT_M5_CONFIRMATION";
         ctx.reason = "MA_RESEARCH valido, mas M5 ainda nao permite";
      }
      else if(InpRequireM1Trigger && !m1ok)
      {
         ctx.action = "WAIT_M1_TRIGGER";
         ctx.reason = "MA_RESEARCH valido, mas falta gatilho M1";
      }
      else
      {
         ctx.action = side;
         ctx.reason = "MA_RESEARCH valido + filtro operacional OK";
      }
   }
   else if(ctx.ma_candidate != "NONE")
   {
      if(ctx.ma_state == "WAIT_M15")
      {
         ctx.action = "WAIT_M15";
         ctx.reason = "MA_RESEARCH precisa M15 required";
      }
      else if(ctx.ma_state == "WAIT_M5")
      {
         ctx.action = "WAIT_M5";
         ctx.reason = "MA_RESEARCH precisa M5 closed_all";
      }
      else
      {
         ctx.action = "WAIT_MA_CONFIRMATION";
         ctx.reason = "MA_RESEARCH candidato, ainda nao valido";
      }
   }
   else if(ctx.event_state == "WAIT_FAKEOUT_RETURN")
   {
      ctx.action = "WAIT_FAKEOUT_CONFIRMATION";
      ctx.reason = "fakeout em observacao; precisa M5/M1";
   }
   else if(ctx.event_state == "WAIT_ACCEPTANCE_OR_RETEST")
   {
      ctx.action = "WAIT_ACCEPTANCE";
      ctx.reason = "rompimento vivo; precisa fechamento/reteste";
   }
   else
   {
      ctx.action = "WAIT";
      ctx.reason = "sem setup valido";
   }

   BuildEntryCheck(ctx);
}

//+------------------------------------------------------------------+
color ActionColor(const string value)
{
   if(StringFind(value, "BUY") >= 0) return clrLime;
   if(StringFind(value, "SELL") >= 0) return clrTomato;
   if(StringFind(value, "WAIT") >= 0) return clrGold;
   if(value == "VALID") return clrLime;
   return clrWhite;
}

void AddLabel(const string id, const int x, const int y, const string text, const color clr, const int size, const bool bold=false)
{
   string name = PREFIX + id;
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);

   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetString(0, name, OBJPROP_FONT, InpFontName);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void DrawBackground()
{
   string bg = PREFIX + "BG";
   if(ObjectFind(0, bg) < 0)
      ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);

   ObjectSetInteger(0, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, InpPanelY);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE, InpPanelWidth);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE, InpPanelHeight);
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, clrBlack);
   ObjectSetInteger(0, bg, OBJPROP_BORDER_COLOR, clrDimGray);
   ObjectSetInteger(0, bg, OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, bg, OBJPROP_BACK, false);
   ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, bg, OBJPROP_HIDDEN, true);
}

void DrawPanel()
{
   DrawBackground();
}

void AddRow(string id, int &row, const int x, const int y, const int lh, const string text, const color clr, const bool bold=false)
{
   AddLabel(id, x, y + row * lh, text, clr, InpFontSize, bold);
   row++;
}

//+------------------------------------------------------------------+
void UpdatePanel()
{
   ApplyChartVisuals();
   SignalContext ctx;
   BuildContext(ctx);

   DeleteObjects();
   DrawBackground();

   int x = InpPanelX + 16;
   int y = InpPanelY + 14;
   int lh = InpLineHeight;
   if(lh < InpFontSize + 4) lh = InpFontSize + 4;
   int row = 0;

   AddLabel("title", x, y + row * lh, "TradingAgent Signal Panel v8", clrWhite, InpTitleFontSize, true); row++;
   AddRow("sub", row, x, y, lh, StringFormat("%s | TF=%s | bid %.2f ask %.2f", g_symbol, TFName((ENUM_TIMEFRAMES)_Period), Bid(), Ask()), clrSilver);
   AddRow("mode", row, x, y, lh, "SIGNAL ONLY - no trades / no OrderSend", clrDeepSkyBlue, true);
   AddRow("action", row, x, y, lh, "ACTION: " + ctx.action, ActionColor(ctx.action), true);
   AddRow("reason", row, x, y, lh, "reason: " + ctx.reason, clrSilver);
   row++;

   AddRow("ma_h", row, x, y, lh, "MA RESEARCH REPLICA", clrAqua, true);
   AddRow("ma1", row, x, y, lh, StringFormat("SELL_CORE 8/20/63 : %-8s | SELL | %.1f/%.1fATR | %dm", ctx.sell_core_state, InpSellStopATR, InpSellTargetATR, InpSellMaxHoldMin), ctx.sell_core_state == "VALID" ? clrLime : clrSilver);
   AddRow("ma2", row, x, y, lh, StringFormat("BUY_CORE  6/30/85 : %-8s | BUY  | %.1f/%.1fATR | %dm", ctx.buy_core_state, InpBuyStopATR, InpBuyTargetATR, InpBuyMaxHoldMin), ctx.buy_core_state == "VALID" ? clrLime : clrSilver);
   AddRow("ma3", row, x, y, lh, StringFormat("BOTH_SELL 5/30/81: %-8s | %.1f/%.1fATR | %dm", ctx.both_sell_state, InpBothStopATR, InpBothTargetATR, InpBothMaxHoldMin), ctx.both_sell_state == "VALID" ? clrLime : clrSilver);
   AddRow("ma4", row, x, y, lh, StringFormat("BOTH_BUY  5/30/81: %-8s | %.1f/%.1fATR | %dm", ctx.both_buy_state, InpBothStopATR, InpBothTargetATR, InpBothMaxHoldMin), ctx.both_buy_state == "VALID" ? clrLime : clrSilver);

   if(ctx.ma_selected != "NONE")
   {
      AddRow("ma_selected", row, x, y, lh, "selected : " + ctx.ma_selected + " | side=" + ctx.ma_side, clrLime, true);
      AddRow("ma_selected_state", row, x, y, lh, "state    : VALID | candidate=NONE", clrLime, true);
   }
   else if(ctx.ma_candidate != "NONE")
   {
      AddRow("ma_candidate", row, x, y, lh, "candidate: " + ctx.ma_candidate + " | side=" + ctx.ma_side, clrGold, true);
      AddRow("ma_missing", row, x, y, lh, "missing  : " + ctx.ma_missing + " | selected=NONE", clrGold, true);
   }
   else
   {
      AddRow("ma_none", row, x, y, lh, "selected : NONE", clrSilver, true);
      AddRow("ma_none2", row, x, y, lh, "candidate: NONE", clrSilver, true);
   }
   row++;

   AddRow("ev_h", row, x, y, lh, "EVENT STATE", clrAqua, true);
   AddRow("ev1", row, x, y, lh, "active_event: " + ctx.active_event, clrOrange, true);
   AddRow("ev2", row, x, y, lh, "active_side : " + ctx.active_side + " | state: " + ctx.event_state, ActionColor(ctx.active_side), true);
   AddRow("evp", row, x, y, lh, "breakout_power: " + ctx.breakout_power_detail, ActionColor(ctx.breakout_power_detail), true);
   AddRow("evb", row, x, y, lh, ctx.breakout_basis_summary, clrSilver);
   AddRow("ev3", row, x, y, lh, StringFormat("H1:%s | M15:%s", ctx.h1.pattern, ctx.m15.pattern), clrSilver);
   AddRow("ev4", row, x, y, lh, StringFormat("M5:%s | M1:%s | att=%d", ctx.m5.pattern, ctx.m1.pattern, ctx.m1.attempt), clrSilver);
   row++;

   AddRow("lvl_h", row, x, y, lh, "LEVEL ZONES", clrAqua, true);
   AddRow("lvl1", row, x, y, lh, StringFormat("H1  sup/res %.2f / %.2f | %s", ctx.h1.support, ctx.h1.resistance, ctx.h1.basis), clrSilver);
   AddRow("lvl2", row, x, y, lh, StringFormat("M15 sup/res %.2f / %.2f | %s", ctx.m15.support, ctx.m15.resistance, ctx.m15.basis), clrSilver);
   AddRow("lvl3", row, x, y, lh, StringFormat("M5  sup/res %.2f / %.2f | %s", ctx.m5.support, ctx.m5.resistance, ctx.m5.basis), clrSilver);
   row++;

   string relevant = ctx.ma_side;
   if(relevant == "NONE") relevant = ctx.active_side;

   AddRow("op_h", row, x, y, lh, "OPERATIONAL FILTER", clrAqua, true);
   AddRow("rel", row, x, y, lh, "relevant side: " + relevant, ActionColor(relevant), true);
   AddRow("entry", row, x, y, lh, "entry_check: " + ctx.entry_status, ActionColor(relevant), true);
   AddRow("next", row, x, y, lh, "next: " + ctx.next_step, clrGold);

   if(InpShowBothSideTriggers || relevant == "SELL" || relevant == "NONE")
   {
      AddRow("m5s", row, x, y, lh, ctx.m5_sell_detail, ctx.m5_sell_ok ? clrLime : clrTomato);
      AddRow("m1s", row, x, y, lh, ctx.m1_sell_detail, ctx.m1_sell_ok ? clrLime : clrTomato);
   }
   if(InpShowBothSideTriggers || relevant == "BUY" || relevant == "NONE")
   {
      AddRow("m5b", row, x, y, lh, ctx.m5_buy_detail, ctx.m5_buy_ok ? clrLime : clrTomato);
      AddRow("m1b", row, x, y, lh, ctx.m1_buy_detail, ctx.m1_buy_ok ? clrLime : clrTomato);
   }

   if(InpShowDebugDetails)
   {
      row++;
      AddRow("dbg1", row, x, y, lh, "debug: M5 closed_all bars=" + IntegerToString(InpM5ClosedAllBars), clrDimGray);
      AddRow("dbg2", row, x, y, lh, StringFormat("M1 level %.2f | M5 level %.2f | M15 level %.2f", ctx.m1.breakout_level, ctx.m5.breakout_level, ctx.m15.breakout_level), clrDimGray);
   }

   if(ctx.action != g_last_action)
   {
      datetime now = TimeCurrent();
      if(g_last_action != "" && now != g_last_alert_time)
      {
         string msg = "TradingAgent " + g_symbol + " action changed: " + ctx.action;
         if(InpEnableAlerts) Alert(msg);
         if(InpEnablePush) SendNotification(msg);
         g_last_alert_time = now;
      }
      g_last_action = ctx.action;
   }

   ChartRedraw();
}

//+------------------------------------------------------------------+
