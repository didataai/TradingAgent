//+------------------------------------------------------------------+
//| TradingAgent_SignalPanel_EA.mq5                                  |
//| Painel/alerta operacional baseado nas regras estudadas            |
//|                                                                  |
//| v5: painel maior, fonte global escalavel, SIGNAL ONLY.            |
//+------------------------------------------------------------------+
#property strict
#property version   "5.00"
#property description "TradingAgent signal-only panel: MA research replica, event state, M5/M1 operational filter."

// -------------------------------------------------------------------
// IMPORTANTE
// -------------------------------------------------------------------
// Este EA e somente sinalizador/painel.
// Nao usa CTrade, nao chama OrderSend, nao abre/fecha posicoes.
// Pode ser usado em conta real como painel visual, mas valide sempre.

input string             InpSymbol                    = "";          // Vazio = simbolo do grafico
input bool               InpSignalOnlyMode            = true;        // Sempre true: sem trades
input bool               InpEnableAlerts              = true;        // Alerta popup quando acao muda
input bool               InpEnablePush                = false;       // Push notification quando acao muda
input int                InpTimerSeconds              = 2;           // Atualizacao do painel

// Visual
input int                InpPanelX                    = 10;
input int                InpPanelY                    = 28;
input int                InpPanelWidth                = 760;         // Quadro maior
input int                InpPanelHeight               = 700;         // Quadro maior
input int                InpFontSize                  = 14;          // Fonte de TODAS as infos
input int                InpTitleFontSize             = 18;          // Fonte do titulo
input int                InpLineHeight                = 20;          // Espacamento vertical
input string             InpFontName                  = "Consolas";
input bool               InpDimCandles                = false;       // Apagar visualmente candles
input bool               InpHideCandles               = false;       // Esconder grafico
input bool               InpShowBothSideTriggers      = false;       // Mostra BUY/SELL completos
input bool               InpShowDebugDetails          = false;       // Detalhes longos

// Medias
input ENUM_MA_METHOD     InpMAMethod                  = MODE_EMA;
input ENUM_APPLIED_PRICE InpMAPrice                   = PRICE_CLOSE;
input bool               InpUseClosedCandleForMA      = true;
input int                InpM5ClosedAllBars           = 3;           // Aproximacao do closed_all

// MA Research Replica - parametros do estudo
input bool               InpMAResearchReplicaMode     = true;
input bool               InpUseSellCoreMA             = true;        // SELL_CORE 8/20/63
input int                InpSellFast                  = 8;
input int                InpSellMid                   = 20;
input int                InpSellSlow                  = 63;
input double             InpSellStopATR               = 1.6;
input double             InpSellTargetATR             = 1.3;
input int                InpSellMaxHoldMin            = 20;

input bool               InpUseBuyCoreMA              = true;        // BUY_CORE 6/30/85
input int                InpBuyFast                   = 6;
input int                InpBuyMid                    = 30;
input int                InpBuySlow                   = 85;
input double             InpBuyStopATR                = 1.0;
input double             InpBuyTargetATR              = 0.8;
input int                InpBuyMaxHoldMin             = 10;

input bool               InpUseBothGeneralMA          = true;        // BOTH_GENERAL 5/30/81
input int                InpBothFast                  = 5;
input int                InpBothMid                   = 30;
input int                InpBothSlow                  = 81;
input double             InpBothStopATR               = 1.3;
input double             InpBothTargetATR             = 1.0;
input int                InpBothMaxHoldMin            = 15;

// Filtros operacionais
input bool               InpRequireM5Permission       = true;
input bool               InpRequireM1Trigger          = true;
input int                InpAttemptLookbackBars       = 30;
input double             InpAttemptToleranceATR       = 0.20;
input double             InpMaxM1RangeATRWarning      = 1.50;

string g_symbol;
string g_last_action = "";
datetime g_last_alert_time = 0;
string PREFIX = "TA_PANEL_";

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
   string h1_pattern;
   string m15_pattern;
   string m5_pattern;
   string m1_pattern;
   int h1_attempt;
   int m15_attempt;
   int m5_attempt;
   int m1_attempt;
   bool m5_sell_ok;
   bool m5_buy_ok;
   bool m1_sell_ok;
   bool m1_buy_ok;
   string m5_sell_detail;
   string m5_buy_detail;
   string m1_sell_detail;
   string m1_buy_detail;
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

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteObjects();
   Comment("");
}

//+------------------------------------------------------------------+
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
   ChartRedraw();
}

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
bool GetRates(const ENUM_TIMEFRAMES tf, const int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(g_symbol, tf, 0, count, rates);
   return copied >= count;
}

double Bid(){ double v=0.0; SymbolInfoDouble(g_symbol, SYMBOL_BID, v); return v; }
double Ask(){ double v=0.0; SymbolInfoDouble(g_symbol, SYMBOL_ASK, v); return v; }

string TFName(const ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M1) return "M1";
   if(tf == PERIOD_M5) return "M5";
   if(tf == PERIOD_M15) return "M15";
   if(tf == PERIOD_H1) return "H1";
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

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
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

   detail = StringFormat("%s %s close=%.2f ma(%d/%d/%d)=%.2f/%.2f/%.2f",
                         TFName(tf), side, closev, fast, mid, slow, maFast, maMid, maSlow);
   return ok;
}

//+------------------------------------------------------------------+
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

//+------------------------------------------------------------------+
string MAReplicaState(const string name, const string side, const int fast, const int mid, const int slow, string &missing, string &debug)
{
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   string m15d="", m5d="";
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
int CountAttempts(const ENUM_TIMEFRAMES tf, const bool upper)
{
   MqlRates r[];
   int need = MathMax(10, InpAttemptLookbackBars + 3);
   if(!GetRates(tf, need, r)) return 0;
   double atr = GetATR(tf, 14, 1);
   if(atr <= 0.0) atr = MathMax(_Point, MathAbs(r[1].high - r[1].low));
   double ref = (upper ? r[1].high : r[1].low);
   double tol = atr * InpAttemptToleranceATR;
   int attempts = 0;
   for(int i = 2; i < need; i++)
   {
      double v = (upper ? r[i].high : r[i].low);
      if(MathAbs(v - ref) <= tol) attempts++;
   }
   attempts++; // tentativa atual
   if(attempts > 3) attempts = 3;
   return attempts;
}

//+------------------------------------------------------------------+
string PatternTF(const ENUM_TIMEFRAMES tf, int &attempt)
{
   MqlRates r[];
   if(!GetRates(tf, 4, r))
   {
      attempt = 0;
      return "NO_DATA";
   }
   double price = (Bid() + Ask()) / 2.0;
   bool breakoutUp = price > r[1].high;
   bool breakoutDn = price < r[1].low;
   bool fakeUp = (r[0].high > r[1].high && price <= r[1].high);
   bool fakeDn = (r[0].low < r[1].low && price >= r[1].low);
   bool inside = (price <= r[1].high && price >= r[1].low);

   if(fakeUp){ attempt = CountAttempts(tf, true); return "FAKEOUT_UP"; }
   if(fakeDn){ attempt = CountAttempts(tf, false); return "FAKEOUT_DOWN"; }
   if(breakoutUp){ attempt = CountAttempts(tf, true); return "BREAKOUT_UP_LIVE"; }
   if(breakoutDn){ attempt = CountAttempts(tf, false); return "BREAKOUT_DOWN_LIVE"; }
   if(inside){ attempt = 1; return "INSIDE_OR_CONSOLIDATION"; }
   attempt = 1;
   return "RANGE_CONTEXT";
}

//+------------------------------------------------------------------+
bool M5SellPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)){ detail="M5 sem dados"; return false; }
   double bid = Bid();
   bool blockedAbovePrevHigh = bid > r[1].high;
   bool ok = !blockedAbovePrevHigh;
   detail = StringFormat("M5 SELL=%s | bid %.2f | prev H/L %.2f/%.2f", ok ? "OK" : "BLOCK", bid, r[1].high, r[1].low);
   return ok;
}

bool M5BuyPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)){ detail="M5 sem dados"; return false; }
   double ask = Ask();
   bool blockedBelowPrevLow = ask < r[1].low;
   bool ok = !blockedBelowPrevLow;
   detail = StringFormat("M5 BUY=%s | ask %.2f | prev H/L %.2f/%.2f", ok ? "OK" : "BLOCK", ask, r[1].high, r[1].low);
   return ok;
}

bool M1SellTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)){ detail="M1 sem dados"; return false; }
   double bid = Bid();
   bool previousRed = IsBearish(r[1]);
   bool brokeLow = bid < r[1].low;
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   bool ok = previousRed && brokeLow;
   detail = StringFormat("M1 SELL=%s | prevRed=%s | bid %.2f < low %.2f | rATR=%.2f",
                         ok ? "OK" : "NO", previousRed ? "Y" : "N", bid, r[1].low, rangeAtr);
   return ok;
}

bool M1BuyTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)){ detail="M1 sem dados"; return false; }
   double ask = Ask();
   bool previousGreen = IsBullish(r[1]);
   bool brokeHigh = ask > r[1].high;
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   bool ok = previousGreen && brokeHigh;
   detail = StringFormat("M1 BUY=%s | prevGreen=%s | ask %.2f > high %.2f | rATR=%.2f",
                         ok ? "OK" : "NO", previousGreen ? "Y" : "N", ask, r[1].high, rangeAtr);
   return ok;
}

//+------------------------------------------------------------------+
void BuildContext(SignalContext &ctx)
{
   ctx.action = "WAIT";
   ctx.reason = "sem confluencia operacional";
   ctx.ma_selected = "NONE";
   ctx.ma_candidate = "NONE";
   ctx.ma_missing = "";
   ctx.ma_side = "NONE";
   ctx.ma_state = "NO_SETUP";

   ctx.h1_pattern  = PatternTF(PERIOD_H1,  ctx.h1_attempt);
   ctx.m15_pattern = PatternTF(PERIOD_M15, ctx.m15_attempt);
   ctx.m5_pattern  = PatternTF(PERIOD_M5,  ctx.m5_attempt);
   ctx.m1_pattern  = PatternTF(PERIOD_M1,  ctx.m1_attempt);

   // MA Research Replica
   string miss="", dbg="";
   ctx.sell_core_state = "DISABLED";
   ctx.buy_core_state = "DISABLED";
   ctx.both_sell_state = "DISABLED";
   ctx.both_buy_state = "DISABLED";

   if(InpUseSellCoreMA)
   {
      ctx.sell_core_state = MAReplicaState("SELL_CORE", "SELL", InpSellFast, InpSellMid, InpSellSlow, miss, dbg);
      if(ctx.sell_core_state == "VALID")
      {
         ctx.ma_selected = "SELL_CORE 8/20/63";
         ctx.ma_side = "SELL";
         ctx.ma_state = "VALID";
      }
      else if(ctx.ma_candidate == "NONE" && ctx.sell_core_state != "NO_SETUP")
      {
         ctx.ma_candidate = "SELL_CORE 8/20/63";
         ctx.ma_side = "SELL";
         ctx.ma_state = ctx.sell_core_state;
         ctx.ma_missing = miss;
      }
   }

   if(ctx.ma_selected == "NONE" && InpUseBuyCoreMA)
   {
      ctx.buy_core_state = MAReplicaState("BUY_CORE", "BUY", InpBuyFast, InpBuyMid, InpBuySlow, miss, dbg);
      if(ctx.buy_core_state == "VALID")
      {
         ctx.ma_selected = "BUY_CORE 6/30/85";
         ctx.ma_side = "BUY";
         ctx.ma_state = "VALID";
      }
      else if(ctx.ma_candidate == "NONE" && ctx.buy_core_state != "NO_SETUP")
      {
         ctx.ma_candidate = "BUY_CORE 6/30/85";
         ctx.ma_side = "BUY";
         ctx.ma_state = ctx.buy_core_state;
         ctx.ma_missing = miss;
      }
   }
   else if(InpUseBuyCoreMA)
   {
      ctx.buy_core_state = MAReplicaState("BUY_CORE", "BUY", InpBuyFast, InpBuyMid, InpBuySlow, miss, dbg);
   }

   if(ctx.ma_selected == "NONE" && InpUseBothGeneralMA)
   {
      ctx.both_sell_state = MAReplicaState("BOTH_SELL", "SELL", InpBothFast, InpBothMid, InpBothSlow, miss, dbg);
      if(ctx.both_sell_state == "VALID")
      {
         ctx.ma_selected = "BOTH_SELL 5/30/81";
         ctx.ma_side = "SELL";
         ctx.ma_state = "VALID";
      }
      else if(ctx.ma_candidate == "NONE" && ctx.both_sell_state != "NO_SETUP")
      {
         ctx.ma_candidate = "BOTH_SELL 5/30/81";
         ctx.ma_side = "SELL";
         ctx.ma_state = ctx.both_sell_state;
         ctx.ma_missing = miss;
      }
   }
   else if(InpUseBothGeneralMA)
   {
      ctx.both_sell_state = MAReplicaState("BOTH_SELL", "SELL", InpBothFast, InpBothMid, InpBothSlow, miss, dbg);
   }

   if(ctx.ma_selected == "NONE" && InpUseBothGeneralMA)
   {
      ctx.both_buy_state = MAReplicaState("BOTH_BUY", "BUY", InpBothFast, InpBothMid, InpBothSlow, miss, dbg);
      if(ctx.both_buy_state == "VALID")
      {
         ctx.ma_selected = "BOTH_BUY 5/30/81";
         ctx.ma_side = "BUY";
         ctx.ma_state = "VALID";
      }
      else if(ctx.ma_candidate == "NONE" && ctx.both_buy_state != "NO_SETUP")
      {
         ctx.ma_candidate = "BOTH_BUY 5/30/81";
         ctx.ma_side = "BUY";
         ctx.ma_state = ctx.both_buy_state;
         ctx.ma_missing = miss;
      }
   }
   else if(InpUseBothGeneralMA)
   {
      ctx.both_buy_state = MAReplicaState("BOTH_BUY", "BUY", InpBothFast, InpBothMid, InpBothSlow, miss, dbg);
   }

   // Event state
   ctx.active_event = "RANGE_OR_TRANSITION";
   ctx.event_state = "WAIT_CONTEXT";
   ctx.active_side = "NONE";

   if(ctx.m5_pattern == "BREAKOUT_UP_LIVE" || ctx.m1_pattern == "BREAKOUT_UP_LIVE")
   {
      ctx.active_event = "BREAKOUT_UP_WAIT_ACCEPTANCE";
      ctx.event_state = "WAIT_ACCEPTANCE_OR_RETEST";
      ctx.active_side = "BUY";
   }
   if(ctx.m5_pattern == "BREAKOUT_DOWN_LIVE" || ctx.m1_pattern == "BREAKOUT_DOWN_LIVE")
   {
      ctx.active_event = "BREAKOUT_DOWN_WAIT_ACCEPTANCE";
      ctx.event_state = "WAIT_ACCEPTANCE_OR_RETEST";
      ctx.active_side = "SELL";
   }
   if(ctx.m5_pattern == "FAKEOUT_UP" || ctx.m1_pattern == "FAKEOUT_UP" || ctx.m15_pattern == "FAKEOUT_UP")
   {
      ctx.active_event = "BREAKOUT_UP_FAILED_FAKEOUT";
      ctx.event_state = "WAIT_FAKEOUT_RETURN";
      ctx.active_side = "SELL";
   }
   if(ctx.m5_pattern == "FAKEOUT_DOWN" || ctx.m1_pattern == "FAKEOUT_DOWN" || ctx.m15_pattern == "FAKEOUT_DOWN")
   {
      ctx.active_event = "BREAKOUT_DOWN_FAILED_FAKEOUT";
      ctx.event_state = "WAIT_FAKEOUT_RETURN";
      ctx.active_side = "BUY";
   }

   ctx.m5_sell_ok = M5SellPermission(ctx.m5_sell_detail);
   ctx.m5_buy_ok  = M5BuyPermission(ctx.m5_buy_detail);
   ctx.m1_sell_ok = M1SellTrigger(ctx.m1_sell_detail);
   ctx.m1_buy_ok  = M1BuyTrigger(ctx.m1_buy_detail);

   // Decision
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
}

//+------------------------------------------------------------------+
color ActionColor(const string action)
{
   if(StringFind(action, "BUY") >= 0) return clrLime;
   if(StringFind(action, "SELL") >= 0) return clrTomato;
   if(StringFind(action, "WAIT") >= 0) return clrGold;
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
   ObjectSetString(0, name, OBJPROP_FONT, bold ? InpFontName + " Bold" : InpFontName);
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
   int lh = MathMax(InpFontSize + 4, InpLineHeight);
   int row = 0;

   AddLabel("title", x, y + row*lh, "TradingAgent Signal Panel v5", clrWhite, InpTitleFontSize, true); row++;
   AddLabel("sub", x, y + row*lh, StringFormat("%s | TF=%s | bid %.2f ask %.2f", g_symbol, TFName((ENUM_TIMEFRAMES)_Period), Bid(), Ask()), clrSilver, InpFontSize); row++;
   AddLabel("mode", x, y + row*lh, "SIGNAL ONLY - no trades / no OrderSend", clrDeepSkyBlue, InpFontSize, true); row++;
   AddLabel("action", x, y + row*lh, "ACTION: " + ctx.action, ActionColor(ctx.action), InpFontSize, true); row++;
   AddLabel("reason", x, y + row*lh, "reason: " + ctx.reason, clrSilver, InpFontSize); row++;
   row++;

   AddLabel("ma_h", x, y + row*lh, "MA RESEARCH REPLICA", clrAqua, InpFontSize, true); row++;
   AddLabel("ma1", x, y + row*lh, StringFormat("SELL_CORE 8/20/63 : %-8s | SELL | %.1f/%.1fATR | %dm", ctx.sell_core_state, InpSellStopATR, InpSellTargetATR, InpSellMaxHoldMin), ctx.sell_core_state=="VALID"?clrLime:clrSilver, InpFontSize); row++;
   AddLabel("ma2", x, y + row*lh, StringFormat("BUY_CORE  6/30/85 : %-8s | BUY  | %.1f/%.1fATR | %dm", ctx.buy_core_state, InpBuyStopATR, InpBuyTargetATR, InpBuyMaxHoldMin), ctx.buy_core_state=="VALID"?clrLime:clrSilver, InpFontSize); row++;
   AddLabel("ma3", x, y + row*lh, StringFormat("BOTH_SELL 5/30/81: %-8s | %.1f/%.1fATR | %dm", ctx.both_sell_state, InpBothStopATR, InpBothTargetATR, InpBothMaxHoldMin), ctx.both_sell_state=="VALID"?clrLime:clrSilver, InpFontSize); row++;
   AddLabel("ma4", x, y + row*lh, StringFormat("BOTH_BUY  5/30/81: %-8s | %.1f/%.1fATR | %dm", ctx.both_buy_state, InpBothStopATR, InpBothTargetATR, InpBothMaxHoldMin), ctx.both_buy_state=="VALID"?clrLime:clrSilver, InpFontSize); row++;

   if(ctx.ma_selected != "NONE")
      AddLabel("ma_selected", x, y + row*lh, "selected : " + ctx.ma_selected + " | side=" + ctx.ma_side + " | state=VALID", clrLime, InpFontSize, true);
   else if(ctx.ma_candidate != "NONE")
      AddLabel("ma_selected", x, y + row*lh, "candidate: " + ctx.ma_candidate + " | side=" + ctx.ma_side + " | missing=" + ctx.ma_missing + " | selected=NONE", clrGold, InpFontSize, true);
   else
      AddLabel("ma_selected", x, y + row*lh, "selected : NONE | candidate=NONE", clrSilver, InpFontSize, true);
   row++;
   row++;

   AddLabel("ev_h", x, y + row*lh, "EVENT STATE", clrAqua, InpFontSize, true); row++;
   AddLabel("ev1", x, y + row*lh, "active_event: " + ctx.active_event, clrOrange, InpFontSize, true); row++;
   AddLabel("ev2", x, y + row*lh, "active_side : " + ctx.active_side + " | state: " + ctx.event_state, ActionColor(ctx.active_side), InpFontSize, true); row++;
   AddLabel("ev3", x, y + row*lh, StringFormat("H1:%s | M15:%s", ctx.h1_pattern, ctx.m15_pattern), clrSilver, InpFontSize); row++;
   AddLabel("ev4", x, y + row*lh, StringFormat("M5:%s | M1:%s | att=%d", ctx.m5_pattern, ctx.m1_pattern, ctx.m1_attempt), clrSilver, InpFontSize); row++;
   row++;

   string relevant = ctx.ma_side;
   if(relevant == "NONE") relevant = ctx.active_side;
   AddLabel("op_h", x, y + row*lh, "OPERATIONAL FILTER", clrAqua, InpFontSize, true); row++;
   AddLabel("rel", x, y + row*lh, "relevant side: " + relevant, ActionColor(relevant), InpFontSize, true); row++;

   if(InpShowBothSideTriggers || relevant == "SELL" || relevant == "NONE")
   {
      AddLabel("m5s", x, y + row*lh, ctx.m5_sell_detail, ctx.m5_sell_ok?clrLime:clrTomato, InpFontSize); row++;
      AddLabel("m1s", x, y + row*lh, ctx.m1_sell_detail, ctx.m1_sell_ok?clrLime:clrTomato, InpFontSize); row++;
   }
   if(InpShowBothSideTriggers || relevant == "BUY" || relevant == "NONE")
   {
      AddLabel("m5b", x, y + row*lh, ctx.m5_buy_detail, ctx.m5_buy_ok?clrLime:clrTomato, InpFontSize); row++;
      AddLabel("m1b", x, y + row*lh, ctx.m1_buy_detail, ctx.m1_buy_ok?clrLime:clrTomato, InpFontSize); row++;
   }

   if(InpShowDebugDetails)
   {
      row++;
      AddLabel("dbg", x, y + row*lh, "debug: M5 closed_all bars=" + IntegerToString(InpM5ClosedAllBars), clrDimGray, InpFontSize); row++;
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
