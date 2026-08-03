//+------------------------------------------------------------------+
//| TradingAgent_SignalPanel_EA.mq5                                  |
//| Painel/alerta operacional baseado nas regras estudadas            |
//|                                                                  |
//| v4: MA candidate/selected claro + fonte maior ajustavel.          |
//+------------------------------------------------------------------+
#property strict
#property version   "4.00"
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
input int                InpTimerSeconds              = 3;           // Atualizacao do painel

// Visual
input bool               InpHideCandles               = false;       // Esconder grafico e deixar so painel
input bool               InpDimCandles                = true;        // Apagar candles para melhorar leitura
input int                InpPanelX                    = 8;
input int                InpPanelY                    = 18;
input int                InpPanelWidth                = 520;
input int                InpPanelHeight               = 430;
input int                InpFontSize                  = 12;          // Fonte maior do painel
input int                InpTitleFontSize             = 14;          // Fonte do titulo
input bool               InpShowBothSideTriggers      = false;       // false = mostra so lado relevante; true = debug BUY/SELL
input bool               InpShowDebugDetails          = false;

// Medias
input ENUM_MA_METHOD     InpMAMethod                  = MODE_EMA;
input ENUM_APPLIED_PRICE InpMAPrice                   = PRICE_CLOSE;
input bool               InpUseClosedCandleForMA      = true;        // Replica usa candle fechado

// MA Research Replica - parametros do estudo
input bool               InpMAResearchReplicaMode     = true;
input int                InpSellFast                  = 8;
input int                InpSellMid                   = 20;
input int                InpSellSlow                  = 63;
input double             InpSellStopATR               = 1.6;
input double             InpSellTargetATR             = 1.3;
input int                InpSellHoldMinutes           = 20;

input int                InpBuyFast                   = 6;
input int                InpBuyMid                    = 30;
input int                InpBuySlow                   = 85;
input double             InpBuyStopATR                = 1.0;
input double             InpBuyTargetATR              = 0.8;
input int                InpBuyHoldMinutes            = 10;

input int                InpBothFast                  = 5;
input int                InpBothMid                   = 30;
input int                InpBothSlow                  = 81;
input double             InpBothStopATR               = 1.3;
input double             InpBothTargetATR             = 1.0;
input int                InpBothHoldMinutes           = 15;

// Regras operacionais
input bool               InpRequireM5Permission       = true;
input bool               InpRequireM1Trigger          = true;
input int                InpAttemptLookbackBars       = 30;
input double             InpAttemptToleranceATR       = 0.20;
input double             InpMaxM1RangeATRWarning      = 1.50;

string g_symbol;
string g_last_action = "";
datetime g_last_alert_bar = 0;

struct MAReplicaSignal
{
   string name;
   string side;
   string state;
   string missing;
   bool valid;
   double stop_atr;
   double target_atr;
   int hold_minutes;
};

struct EventState
{
   string active_event;
   string active_side;
   string state;
   string h1;
   string m15;
   string m5;
   string m1;
   int attempt;
};

//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = (InpSymbol == "" ? _Symbol : InpSymbol);
   EventSetTimer(MathMax(1, InpTimerSeconds));
   ApplyChartStyle();
   DrawPanelShell();
   UpdatePanel();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   DeletePanelObjects();
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick(){ UpdatePanel(); }
void OnTimer(){ UpdatePanel(); }

//+------------------------------------------------------------------+
void ApplyChartStyle()
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
         ChartSetInteger(0, CHART_COLOR_BACKGROUND, clrWhite);
         ChartSetInteger(0, CHART_COLOR_FOREGROUND, clrSilver);
         ChartSetInteger(0, CHART_COLOR_GRID, clrWhite);
         ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, clrSilver);
         ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, clrSilver);
         ChartSetInteger(0, CHART_COLOR_CHART_UP, clrSilver);
         ChartSetInteger(0, CHART_COLOR_CHART_DOWN, clrSilver);
      }
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
void DeletePanelObjects()
{
   for(int i=ObjectsTotal(0)-1; i>=0; i--)
   {
      string n = ObjectName(0, i);
      if(StringFind(n, "TA_PANEL_") == 0)
         ObjectDelete(0, n);
   }
}

//+------------------------------------------------------------------+
void DrawPanelShell()
{
   DeletePanelObjects();
   ObjectCreate(0, "TA_PANEL_BG", OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_YDISTANCE, InpPanelY);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_XSIZE, InpPanelWidth);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_YSIZE, InpPanelHeight);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_BGCOLOR, clrBlack);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_BACK, false);
   ObjectSetInteger(0, "TA_PANEL_BG", OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
void Label(const string name, const int x, const int y, const string text, const color c, const int size=0)
{
   string obj = "TA_PANEL_" + name;
   if(ObjectFind(0, obj) < 0)
   {
      ObjectCreate(0, obj, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, obj, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, obj, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, obj, OBJPROP_BACK, false);
      ObjectSetString(0, obj, OBJPROP_FONT, "Consolas");
   }
   ObjectSetInteger(0, obj, OBJPROP_XDISTANCE, InpPanelX + x);
   ObjectSetInteger(0, obj, OBJPROP_YDISTANCE, InpPanelY + y);
   ObjectSetInteger(0, obj, OBJPROP_COLOR, c);
   ObjectSetInteger(0, obj, OBJPROP_FONTSIZE, (size > 0 ? size : InpFontSize));
   ObjectSetString(0, obj, OBJPROP_TEXT, text);
}

//+------------------------------------------------------------------+
bool GetRates(const ENUM_TIMEFRAMES tf, const int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(g_symbol, tf, 0, count, rates);
   return (copied >= count);
}

double Bid(){ double v=0.0; SymbolInfoDouble(g_symbol, SYMBOL_BID, v); return v; }
double Ask(){ double v=0.0; SymbolInfoDouble(g_symbol, SYMBOL_ASK, v); return v; }
bool IsBullish(const MqlRates &bar){ return bar.close > bar.open; }
bool IsBearish(const MqlRates &bar){ return bar.close < bar.open; }

//+------------------------------------------------------------------+
double GetATR(const ENUM_TIMEFRAMES tf, const int period=14, const int shift=1)
{
   int handle = iATR(g_symbol, tf, period);
   if(handle == INVALID_HANDLE) return 0.0;
   double buffer[]; ArraySetAsSeries(buffer, true);
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
   double buffer[]; ArraySetAsSeries(buffer, true);
   int copied = CopyBuffer(handle, 0, shift, 1, buffer);
   IndicatorRelease(handle);
   if(copied < 1) return 0.0;
   return buffer[0];
}

//+------------------------------------------------------------------+
string MAStateTF(const ENUM_TIMEFRAMES tf, const int fast, const int mid, const int slow, const string side)
{
   MqlRates r[];
   if(!GetRates(tf, 5, r)) return "NO_DATA";
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double f = GetMA(tf, fast, shift);
   double m = GetMA(tf, mid, shift);
   double s = GetMA(tf, slow, shift);
   double c = r[shift].close;
   if(f <= 0 || m <= 0 || s <= 0) return "NO_DATA";

   if(side == "SELL")
   {
      if(f < m && m < s && c <= f) return "OK";
      if(f < m && m < s) return "STACK_OK_PRICE_WAIT";
      return "NO";
   }
   if(side == "BUY")
   {
      if(f > m && m > s && c >= f) return "OK";
      if(f > m && m > s) return "STACK_OK_PRICE_WAIT";
      return "NO";
   }
   return "NO";
}

//+------------------------------------------------------------------+
MAReplicaSignal BuildMAReplica(const string name, const string side, const int fast, const int mid, const int slow, const double stopATR, const double targetATR, const int holdMin)
{
   MAReplicaSignal sig;
   sig.name = name;
   sig.side = side;
   sig.stop_atr = stopATR;
   sig.target_atr = targetATR;
   sig.hold_minutes = holdMin;
   sig.valid = false;
   sig.missing = "";

   string m15 = MAStateTF(PERIOD_M15, fast, mid, slow, side);
   string m5  = MAStateTF(PERIOD_M5,  fast, mid, slow, side);

   if(m15 == "OK" && m5 == "OK")
   {
      sig.state = "VALID";
      sig.valid = true;
      sig.missing = "NONE";
   }
   else if(m15 != "OK")
   {
      sig.state = "WAIT_M15";
      sig.missing = "M15";
   }
   else if(m5 != "OK")
   {
      sig.state = "WAIT_M5_CLOSED_ALL";
      sig.missing = "M5_CLOSED_ALL";
   }
   else
   {
      sig.state = "NO_SETUP";
      sig.missing = "SETUP";
   }
   return sig;
}

//+------------------------------------------------------------------+
MAReplicaSignal BestMAReplica(MAReplicaSignal &sellCore, MAReplicaSignal &buyCore, MAReplicaSignal &bothSell, MAReplicaSignal &bothBuy)
{
   if(sellCore.valid) return sellCore;
   if(buyCore.valid)  return buyCore;
   if(bothSell.valid) return bothSell;
   if(bothBuy.valid)  return bothBuy;

   // candidato em observacao: preferir o que esta mais perto, sem chamar de selected
   if(sellCore.state != "NO_SETUP") return sellCore;
   if(buyCore.state  != "NO_SETUP") return buyCore;
   if(bothSell.state != "NO_SETUP") return bothSell;
   return bothBuy;
}

//+------------------------------------------------------------------+
string PatternTF(const ENUM_TIMEFRAMES tf)
{
   MqlRates r[];
   if(!GetRates(tf, 4, r)) return "NO_DATA";
   bool breakUp = r[0].high > r[1].high && r[0].close >= r[1].close;
   bool breakDn = r[0].low  < r[1].low  && r[0].close <= r[1].close;
   bool fakeUp  = r[0].high > r[1].high && r[0].close < r[1].high;
   bool fakeDn  = r[0].low  < r[1].low  && r[0].close > r[1].low;
   bool inside  = r[0].high <= r[1].high && r[0].low >= r[1].low;

   if(fakeUp) return "FAKEOUT_UP";
   if(fakeDn) return "FAKEOUT_DOWN";
   if(breakUp) return "BREAKOUT_UP_LIVE";
   if(breakDn) return "BREAKOUT_DOWN_LIVE";
   if(inside) return "INSIDE_OR_CONSOLIDATION";
   return "MIXED";
}

//+------------------------------------------------------------------+
int CountAttempts(const ENUM_TIMEFRAMES tf, const string pattern)
{
   MqlRates r[];
   if(!GetRates(tf, MathMax(10, InpAttemptLookbackBars), r)) return 1;
   double atr = GetATR(tf, 14, 1);
   if(atr <= 0.0) atr = r[1].high - r[1].low;
   double tol = atr * InpAttemptToleranceATR;
   double level = 0.0;
   if(StringFind(pattern, "UP") >= 0) level = r[1].high;
   else if(StringFind(pattern, "DOWN") >= 0) level = r[1].low;
   else return 1;

   int attempts = 0;
   int limit = MathMin(ArraySize(r)-1, InpAttemptLookbackBars-1);
   for(int i=1; i<=limit; i++)
   {
      if(StringFind(pattern, "UP") >= 0 && MathAbs(r[i].high - level) <= tol) attempts++;
      if(StringFind(pattern, "DOWN") >= 0 && MathAbs(r[i].low - level) <= tol) attempts++;
   }
   if(attempts < 1) attempts = 1;
   if(attempts > 3) attempts = 3;
   return attempts;
}

//+------------------------------------------------------------------+
EventState BuildEventState()
{
   EventState e;
   e.h1  = PatternTF(PERIOD_H1);
   e.m15 = PatternTF(PERIOD_M15);
   e.m5  = PatternTF(PERIOD_M5);
   e.m1  = PatternTF(PERIOD_M1);
   e.attempt = CountAttempts(PERIOD_M5, e.m5);
   e.active_event = "RANGE_INSIDE";
   e.active_side = "NONE";
   e.state = "WAIT";

   if(e.m5 == "FAKEOUT_UP" || e.m1 == "FAKEOUT_UP" || e.m15 == "FAKEOUT_UP")
   {
      e.active_event = "BREAKOUT_UP_FAILED_FAKEOUT";
      e.active_side = "SELL";
      e.state = "WAIT_FAKEOUT_RETURN";
   }
   else if(e.m5 == "FAKEOUT_DOWN" || e.m1 == "FAKEOUT_DOWN" || e.m15 == "FAKEOUT_DOWN")
   {
      e.active_event = "BREAKOUT_DOWN_FAILED_FAKEOUT";
      e.active_side = "BUY";
      e.state = "WAIT_FAKEOUT_RETURN";
   }
   else if(e.m5 == "BREAKOUT_UP_LIVE" || e.m1 == "BREAKOUT_UP_LIVE")
   {
      e.active_event = "BREAKOUT_UP_WAIT_ACCEPTANCE";
      e.active_side = "BUY";
      e.state = "WAIT_ACCEPTANCE_OR_RETEST";
   }
   else if(e.m5 == "BREAKOUT_DOWN_LIVE" || e.m1 == "BREAKOUT_DOWN_LIVE")
   {
      e.active_event = "BREAKOUT_DOWN_WAIT_ACCEPTANCE";
      e.active_side = "SELL";
      e.state = "WAIT_ACCEPTANCE_OR_RETEST";
   }
   return e;
}

//+------------------------------------------------------------------+
bool M5Permission(const string side, string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r))
   {
      detail = "M5 sem dados";
      return false;
   }
   double bid = Bid();
   double ask = Ask();
   bool ok = false;
   if(side == "SELL")
   {
      bool blocked = bid > r[1].high;
      ok = !blocked;
      detail = StringFormat("M5 SELL=%s | bid %.2f | prev H/L %.2f/%.2f", ok?"OK":"NO", bid, r[1].high, r[1].low);
   }
   else if(side == "BUY")
   {
      bool blocked = ask < r[1].low;
      ok = !blocked;
      detail = StringFormat("M5 BUY=%s | ask %.2f | prev H/L %.2f/%.2f", ok?"OK":"NO", ask, r[1].high, r[1].low);
   }
   else
   {
      detail = "M5 side=NONE";
   }
   return ok;
}

//+------------------------------------------------------------------+
bool M1Trigger(const string side, string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r))
   {
      detail = "M1 sem dados";
      return false;
   }
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   string warn = (rangeAtr > InpMaxM1RangeATRWarning ? " | WARNING:candle longo" : "");

   if(side == "SELL")
   {
      bool prevRed = IsBearish(r[1]);
      bool brokeLow = Bid() < r[1].low;
      bool ok = prevRed && brokeLow;
      detail = StringFormat("M1 SELL=%s | prevRed=%s | bid %.2f < low %.2f | rATR=%.2f%s",
                            ok?"OK":"NO", prevRed?"Y":"N", Bid(), r[1].low, rangeAtr, warn);
      return ok;
   }
   if(side == "BUY")
   {
      bool prevGreen = IsBullish(r[1]);
      bool brokeHigh = Ask() > r[1].high;
      bool ok = prevGreen && brokeHigh;
      detail = StringFormat("M1 BUY=%s | prevGreen=%s | ask %.2f > high %.2f | rATR=%.2f%s",
                            ok?"OK":"NO", prevGreen?"Y":"N", Ask(), r[1].high, rangeAtr, warn);
      return ok;
   }
   detail = "M1 side=NONE";
   return false;
}

//+------------------------------------------------------------------+
color ActionColor(const string action)
{
   if(StringFind(action, "BUY") >= 0) return clrLime;
   if(StringFind(action, "SELL") >= 0) return clrTomato;
   if(StringFind(action, "WAIT") >= 0) return clrGold;
   return clrWhite;
}

//+------------------------------------------------------------------+
void UpdatePanel()
{
   if(g_symbol == "") g_symbol = (InpSymbol == "" ? _Symbol : InpSymbol);

   MAReplicaSignal sellCore = BuildMAReplica("SELL_CORE 8/20/63", "SELL", InpSellFast, InpSellMid, InpSellSlow, InpSellStopATR, InpSellTargetATR, InpSellHoldMinutes);
   MAReplicaSignal buyCore  = BuildMAReplica("BUY_CORE 6/30/85",  "BUY",  InpBuyFast,  InpBuyMid,  InpBuySlow,  InpBuyStopATR,  InpBuyTargetATR,  InpBuyHoldMinutes);
   MAReplicaSignal bothSell = BuildMAReplica("BOTH_SELL 5/30/81", "SELL", InpBothFast, InpBothMid, InpBothSlow, InpBothStopATR, InpBothTargetATR, InpBothHoldMinutes);
   MAReplicaSignal bothBuy  = BuildMAReplica("BOTH_BUY 5/30/81",  "BUY",  InpBothFast, InpBothMid, InpBothSlow, InpBothStopATR, InpBothTargetATR, InpBothHoldMinutes);
   MAReplicaSignal best = BestMAReplica(sellCore, buyCore, bothSell, bothBuy);
   EventState ev = BuildEventState();

   string relevantSide = "NONE";
   if(best.valid) relevantSide = best.side;
   else if(ev.active_side != "NONE") relevantSide = ev.active_side;
   else relevantSide = best.side;

   string m5d="", m1d="";
   bool m5ok = M5Permission(relevantSide, m5d);
   bool m1ok = M1Trigger(relevantSide, m1d);

   string action = "WAIT";
   string reason = "sem setup validado";

   if(best.valid)
   {
      if(InpRequireM5Permission && !m5ok)
      {
         action = "WAIT_M5_CONFIRMATION";
         reason = "MA_RESEARCH validou, mas M5 nao permite";
      }
      else if(InpRequireM1Trigger && !m1ok)
      {
         action = "WAIT_M1_TRIGGER";
         reason = "MA_RESEARCH validou, falta gatilho M1";
      }
      else
      {
         action = best.side;
         reason = "MA_RESEARCH validado + filtros operacionais OK";
      }
   }
   else
   {
      action = best.state;
      reason = "MA_RESEARCH candidato; falta " + best.missing;
      if(StringFind(ev.active_event, "FAKEOUT") >= 0)
      {
         action = "WAIT_FAKEOUT_CONFIRMATION";
         reason = "fakeout em observacao; precisa M5/M1";
      }
   }

   DrawPanelShell();
   int y=10;
   Label("TITLE", 12, y, "TradingAgent Signal Panel v4", clrWhite, InpTitleFontSize); y += InpTitleFontSize + 6;
   Label("SYMBOL", 12, y, StringFormat("%s | TF=%s | bid %.2f ask %.2f", g_symbol, EnumToString((ENUM_TIMEFRAMES)_Period), Bid(), Ask()), clrSilver); y += InpFontSize + 6;
   Label("SAFE", 12, y, "SIGNAL ONLY - no trades / no OrderSend", clrDeepSkyBlue); y += InpFontSize + 6;
   Label("ACTION", 12, y, "ACTION: " + action, ActionColor(action)); y += InpFontSize + 6;
   Label("REASON", 12, y, "reason: " + reason, clrSilver); y += InpFontSize + 12;

   Label("MA_HEAD", 12, y, "MA RESEARCH REPLICA", clrDeepSkyBlue); y += InpFontSize + 6;
   Label("MA1", 12, y, StringFormat("%s : %s | %s | %.1f/%.1fATR | %dm", sellCore.name, sellCore.state, sellCore.side, sellCore.stop_atr, sellCore.target_atr, sellCore.hold_minutes), sellCore.valid?clrLime:clrSilver); y += InpFontSize + 4;
   Label("MA2", 12, y, StringFormat("%s  : %s | %s  | %.1f/%.1fATR | %dm", buyCore.name, buyCore.state, buyCore.side, buyCore.stop_atr, buyCore.target_atr, buyCore.hold_minutes), buyCore.valid?clrLime:clrSilver); y += InpFontSize + 4;
   Label("MA3", 12, y, StringFormat("%s: %s | %.1f/%.1fATR | %dm", bothSell.name, bothSell.state, bothSell.stop_atr, bothSell.target_atr, bothSell.hold_minutes), bothSell.valid?clrLime:clrSilver); y += InpFontSize + 4;
   Label("MA4", 12, y, StringFormat("%s : %s | %.1f/%.1fATR | %dm", bothBuy.name, bothBuy.state, bothBuy.stop_atr, bothBuy.target_atr, bothBuy.hold_minutes), bothBuy.valid?clrLime:clrSilver); y += InpFontSize + 6;

   if(best.valid)
      Label("MA_SELECTED", 12, y, "selected: " + best.name + " | side=" + best.side + " | state=VALID", clrLime);
   else
      Label("MA_SELECTED", 12, y, "candidate: " + best.name + " | side=" + best.side + " | missing=" + best.missing + " | selected=NONE", clrGold);
   y += InpFontSize + 12;

   Label("EV_HEAD", 12, y, "EVENT STATE", clrDeepSkyBlue); y += InpFontSize + 6;
   Label("EV1", 12, y, "active_event: " + ev.active_event, ActionColor(ev.active_side)); y += InpFontSize + 4;
   Label("EV2", 12, y, "active_side : " + ev.active_side + " | state: " + ev.state, ActionColor(ev.active_side)); y += InpFontSize + 4;
   Label("EV3", 12, y, "H1:" + ev.h1 + " | M15:" + ev.m15, clrSilver); y += InpFontSize + 4;
   Label("EV4", 12, y, "M5:" + ev.m5 + " | M1:" + ev.m1 + " | att=" + IntegerToString(ev.attempt), clrSilver); y += InpFontSize + 12;

   Label("OP_HEAD", 12, y, "OPERATIONAL FILTER", clrDeepSkyBlue); y += InpFontSize + 6;
   Label("OP0", 12, y, "relevant side: " + relevantSide, ActionColor(relevantSide)); y += InpFontSize + 4;
   Label("OP1", 12, y, m5d, m5ok?clrLime:clrTomato); y += InpFontSize + 4;
   Label("OP2", 12, y, m1d, m1ok?clrLime:clrTomato); y += InpFontSize + 4;

   if(InpShowBothSideTriggers)
   {
      string m5s="",m1s="",m5b="",m1b="";
      M5Permission("SELL", m5s); M1Trigger("SELL", m1s);
      M5Permission("BUY",  m5b); M1Trigger("BUY",  m1b);
      y += 6;
      Label("DBG1", 12, y, "debug SELL: " + m5s + " | " + m1s, clrDimGray); y += InpFontSize + 4;
      Label("DBG2", 12, y, "debug BUY : " + m5b + " | " + m1b, clrDimGray); y += InpFontSize + 4;
   }

   if(action != g_last_action)
   {
      datetime bar = iTime(g_symbol, PERIOD_M1, 0);
      if(InpEnableAlerts && bar != g_last_alert_bar)
      {
         Alert("TradingAgent ", g_symbol, " action=", action, " reason=", reason);
         if(InpEnablePush) SendNotification("TradingAgent " + g_symbol + " action=" + action + " reason=" + reason);
         g_last_alert_bar = bar;
      }
      g_last_action = action;
   }
}

//+------------------------------------------------------------------+
