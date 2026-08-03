//+------------------------------------------------------------------+
//| TradingAgent_SignalPanel_EA.mq5                                  |
//| Painel/alerta operacional baseado nas regras estudadas            |
//|                                                                  |
//| v3: SIGNAL ONLY + MA Research Replica + Operational Filters       |
//+------------------------------------------------------------------+
#property strict
#property version   "3.00"
#property description "TradingAgent signal-only panel: MA research replica, M1 trigger, M5 permission, breakout/fakeout context."

// -------------------------------------------------------------------
// IMPORTANTE
// -------------------------------------------------------------------
// Este EA e somente sinalizador/painel.
// Nao usa CTrade, nao chama OrderSend, nao abre/fecha posicoes.
// A secao MA_RESEARCH tenta replicar o estudo das medias.
// A secao OPERATIONAL aplica filtros/leituras operacionais separados.

input string             InpSymbol                    = "";          // Vazio = simbolo do grafico
input bool               InpSignalOnlyMode            = true;        // Sempre true: sem trades
input bool               InpEnableAlerts              = true;        // Alerta popup quando acao muda
input bool               InpEnablePush                = false;       // Push notification quando acao muda
input int                InpTimerSeconds              = 3;           // Atualizacao do painel

input bool               InpHideCandles               = false;       // Esconde candles/grafico
input bool               InpDimCandles                = true;        // Apaga visual dos candles
input bool               InpCompactPanel              = true;        // Painel compacto
input bool               InpShowDebugDetails          = false;       // Mostra detalhes de MA/trigger
input int                InpPanelX                    = 8;
input int                InpPanelY                    = 28;
input int                InpPanelWidth                = 455;
input int                InpFontSize                  = 8;

input ENUM_MA_METHOD     InpMAMethod                  = MODE_EMA;
input ENUM_APPLIED_PRICE InpMAPrice                   = PRICE_CLOSE;
input bool               InpUseClosedCandleForMA      = true;        // Estudo: candle fechado

// -------------------------------------------------------------------
// MA RESEARCH REPLICA - parametros do estudo
// -------------------------------------------------------------------
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

input bool               InpUseQuadMA_5_10_20_80      = true;        // Contexto extra citado
input int                InpQuadFast                  = 5;
input int                InpQuadMid1                  = 10;
input int                InpQuadMid2                  = 20;
input int                InpQuadSlow                  = 80;

// -------------------------------------------------------------------
// OPERATIONAL FILTERS - nao fazem parte do WR original automaticamente
// -------------------------------------------------------------------
input bool               InpRequireM5Permission       = true;        // Regra pessoal M5 Diego
input bool               InpRequireM1Trigger          = true;        // M1 candle anterior + rompimento
input int                InpAttemptLookbackBars       = 30;
input double             InpAttemptToleranceATR       = 0.20;
input double             InpMaxM1RangeATRWarning      = 1.50;

string PREFIX = "TA_PANEL_V3_";
string g_symbol;
string g_last_action = "";

struct MAReplicaResult
{
   string name;
   string side;
   bool   valid;
   string state;
   string m15_state;
   string m5_state;
   double stop_atr;
   double target_atr;
   int    hold_min;
   string detail;
};

//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = (InpSymbol == "" ? _Symbol : InpSymbol);
   EventSetTimer(MathMax(1, InpTimerSeconds));
   ApplyChartStyle();
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
   ChartSetInteger(0, CHART_SHOW_TRADE_LEVELS, false);
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_SHOW_VOLUMES, false);

   if(InpHideCandles)
   {
      ChartSetInteger(0, CHART_SHOW, false);
   }
   else
   {
      ChartSetInteger(0, CHART_SHOW, true);
      if(InpDimCandles)
      {
         ChartSetInteger(0, CHART_COLOR_BACKGROUND, clrWhiteSmoke);
         ChartSetInteger(0, CHART_COLOR_FOREGROUND, clrDimGray);
         ChartSetInteger(0, CHART_COLOR_GRID, clrWhiteSmoke);
         ChartSetInteger(0, CHART_COLOR_CHART_UP, clrSilver);
         ChartSetInteger(0, CHART_COLOR_CHART_DOWN, clrSilver);
         ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, clrGainsboro);
         ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, clrLightGray);
      }
   }
   ChartRedraw();
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

string TFName(const ENUM_TIMEFRAMES tf)
{
   if(tf==PERIOD_M1) return "M1";
   if(tf==PERIOD_M5) return "M5";
   if(tf==PERIOD_M15) return "M15";
   if(tf==PERIOD_H1) return "H1";
   if(tf==PERIOD_H4) return "H4";
   return EnumToString(tf);
}

bool IsBullish(const MqlRates &bar){ return bar.close > bar.open; }
bool IsBearish(const MqlRates &bar){ return bar.close < bar.open; }

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
bool M15RequiredOK(const string side, const int fast, const int mid, const int slow, string &state, string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M15, 5, r))
   {
      state = "NO_DATA";
      detail = "M15 sem dados";
      return false;
   }

   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double maF = GetMA(PERIOD_M15, fast, shift);
   double maM = GetMA(PERIOD_M15, mid, shift);
   double maS = GetMA(PERIOD_M15, slow, shift);
   double c   = r[shift].close;

   if(maF<=0 || maM<=0 || maS<=0)
   {
      state = "NO_MA";
      detail = "M15 medias indisponiveis";
      return false;
   }

   bool ok=false;
   if(side == "SELL")
      ok = (maF < maM && maM < maS && c <= maF);
   else
      ok = (maF > maM && maM > maS && c >= maF);

   state = (ok ? "OK" : "WAIT_M15");
   detail = StringFormat("M15 %s required | close=%.2f | ma=%d/%d/%d %.2f/%.2f/%.2f | %s",
                         side, c, fast, mid, slow, maF, maM, maS, state);
   return ok;
}

// M5 closed_all: candle fechado do M5 precisa fechar acima/abaixo de todas as medias do setup.
bool M5ClosedAllOK(const string side, const int fast, const int mid, const int slow, string &state, string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 5, r))
   {
      state = "NO_DATA";
      detail = "M5 sem dados";
      return false;
   }

   int shift = 1; // replica do estudo: sempre candle fechado
   double maF = GetMA(PERIOD_M5, fast, shift);
   double maM = GetMA(PERIOD_M5, mid, shift);
   double maS = GetMA(PERIOD_M5, slow, shift);
   double c   = r[shift].close;

   if(maF<=0 || maM<=0 || maS<=0)
   {
      state = "NO_MA";
      detail = "M5 medias indisponiveis";
      return false;
   }

   bool ok=false;
   if(side == "SELL")
      ok = (c <= maF && c <= maM && c <= maS);
   else
      ok = (c >= maF && c >= maM && c >= maS);

   state = (ok ? "OK" : "WAIT_M5_CLOSED_ALL");
   detail = StringFormat("M5 %s closed_all | close=%.2f | ma=%d/%d/%d %.2f/%.2f/%.2f | %s",
                         side, c, fast, mid, slow, maF, maM, maS, state);
   return ok;
}

MAReplicaResult EvaluateMAReplica(const string name, const string side, const int fast, const int mid, const int slow,
                                  const double stopATR, const double targetATR, const int holdMin)
{
   MAReplicaResult res;
   res.name = name;
   res.side = side;
   res.stop_atr = stopATR;
   res.target_atr = targetATR;
   res.hold_min = holdMin;

   string m15_detail="", m5_detail="";
   bool m15 = M15RequiredOK(side, fast, mid, slow, res.m15_state, m15_detail);
   bool m5  = M5ClosedAllOK(side, fast, mid, slow, res.m5_state, m5_detail);

   res.valid = (m15 && m5);
   if(res.valid) res.state = "VALID";
   else if(!m15) res.state = "WAIT_M15";
   else if(!m5) res.state = "WAIT_M5_CLOSED_ALL";
   else res.state = "NO_SETUP";

   res.detail = m15_detail + " | " + m5_detail;
   return res;
}

//+------------------------------------------------------------------+
bool QuadContext(const string side, string &state)
{
   string s1="", s2="";
   bool m15 = M15RequiredOK(side, InpQuadFast, InpQuadMid1, InpQuadSlow, s1, s2);
   string s3="", s4="";
   bool m5  = M5ClosedAllOK(side, InpQuadFast, InpQuadMid1, InpQuadSlow, s3, s4);
   state = (m15 && m5 ? "OK" : "NO");
   return (m15 && m5);
}

//+------------------------------------------------------------------+
bool M5PermissionSell(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)) { detail="M5 sem dados"; return false; }
   double bid = Bid();
   bool blockedAbovePrevHigh = (bid > r[1].high);
   bool insideBody = (bid <= MathMax(r[1].open,r[1].close) && bid >= MathMin(r[1].open,r[1].close));
   bool breakPrevLow = (bid < r[1].low);
   bool ok = !blockedAbovePrevHigh && (insideBody || breakPrevLow || bid <= r[1].high);
   detail = StringFormat("M5 SELL=%s | bid %.2f | prev H/L %.2f/%.2f", ok?"OK":"BLOCK", bid, r[1].high, r[1].low);
   return ok;
}

bool M5PermissionBuy(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)) { detail="M5 sem dados"; return false; }
   double ask = Ask();
   bool blockedBelowPrevLow = (ask < r[1].low);
   bool insideBody = (ask <= MathMax(r[1].open,r[1].close) && ask >= MathMin(r[1].open,r[1].close));
   bool breakPrevHigh = (ask > r[1].high);
   bool ok = !blockedBelowPrevLow && (insideBody || breakPrevHigh || ask >= r[1].low);
   detail = StringFormat("M5 BUY=%s | ask %.2f | prev H/L %.2f/%.2f", ok?"OK":"BLOCK", ask, r[1].high, r[1].low);
   return ok;
}

bool M1SellTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)) { detail="M1 sem dados"; return false; }
   double bid = Bid();
   double atr = GetATR(PERIOD_M1,14,1);
   double rangeAtr = (atr>0 ? (r[1].high-r[1].low)/atr : 0.0);
   bool ok = IsBearish(r[1]) && bid < r[1].low;
   detail = StringFormat("M1 SELL=%s | prevRed=%s | bid %.2f < low %.2f | rATR=%.2f",
                         ok?"OK":"NO", IsBearish(r[1])?"Y":"N", bid, r[1].low, rangeAtr);
   return ok;
}

bool M1BuyTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)) { detail="M1 sem dados"; return false; }
   double ask = Ask();
   double atr = GetATR(PERIOD_M1,14,1);
   double rangeAtr = (atr>0 ? (r[1].high-r[1].low)/atr : 0.0);
   bool ok = IsBullish(r[1]) && ask > r[1].high;
   detail = StringFormat("M1 BUY=%s | prevGreen=%s | ask %.2f > high %.2f | rATR=%.2f",
                         ok?"OK":"NO", IsBullish(r[1])?"Y":"N", ask, r[1].high, rangeAtr);
   return ok;
}

//+------------------------------------------------------------------+
string PatternState(const ENUM_TIMEFRAMES tf)
{
   MqlRates r[];
   if(!GetRates(tf, 5, r)) return "NO_DATA";
   if(r[0].high > r[1].high && r[0].close < r[1].high) return "FAKEOUT_UP";
   if(r[0].low  < r[1].low  && r[0].close > r[1].low)  return "FAKEOUT_DOWN";
   if(r[0].high > r[1].high) return "BREAKOUT_UP_LIVE";
   if(r[0].low  < r[1].low)  return "BREAKOUT_DOWN_LIVE";
   return "INSIDE_OR_CONSOLIDATION";
}

int CountAttempts(const ENUM_TIMEFRAMES tf, const string side)
{
   int need = MathMax(10, InpAttemptLookbackBars+2);
   MqlRates r[];
   if(!GetRates(tf, need, r)) return 0;
   double atr = GetATR(tf,14,1);
   if(atr<=0) atr = (r[1].high-r[1].low);
   double tol = atr * InpAttemptToleranceATR;
   double level = (side=="UP" ? r[1].high : r[1].low);
   int attempts = 0;
   for(int i=1; i<need-1; i++)
   {
      if(side=="UP" && MathAbs(r[i].high-level)<=tol) attempts++;
      if(side=="DOWN" && MathAbs(r[i].low-level)<=tol) attempts++;
   }
   if(attempts<1) attempts=1;
   if(attempts>3) attempts=3;
   return attempts;
}

//+------------------------------------------------------------------+
void DeletePanelObjects()
{
   int total = ObjectsTotal(0, -1, -1);
   for(int i=total-1; i>=0; i--)
   {
      string name = ObjectName(0, i, -1, -1);
      if(StringFind(name, PREFIX) == 0) ObjectDelete(0, name);
   }
}

void AppendLine(string &lines[], color &cols[], int &n, const string text, const color c)
{
   ArrayResize(lines, n+1);
   ArrayResize(cols, n+1);
   lines[n] = text;
   cols[n] = c;
   n++;
}

color ActionColor(const string action)
{
   if(StringFind(action,"BUY")>=0) return clrLimeGreen;
   if(StringFind(action,"SELL")>=0) return clrTomato;
   if(StringFind(action,"WAIT")>=0) return clrGold;
   return clrWhite;
}

void DrawPanel(string &lines[], color &cols[], const int n)
{
   DeletePanelObjects();
   int lineH = InpFontSize + 5;
   int height = 16 + n * lineH;
   string bg = PREFIX + "BG";
   ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, InpPanelY);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE, InpPanelWidth);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE, height);
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, clrBlack);
   ObjectSetInteger(0, bg, OBJPROP_COLOR, clrDimGray);
   ObjectSetInteger(0, bg, OBJPROP_BACK, false);
   ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);

   for(int i=0; i<n; i++)
   {
      string nm = PREFIX + "L" + IntegerToString(i);
      ObjectCreate(0, nm, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, nm, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, nm, OBJPROP_XDISTANCE, InpPanelX + 10);
      ObjectSetInteger(0, nm, OBJPROP_YDISTANCE, InpPanelY + 8 + i*lineH);
      ObjectSetInteger(0, nm, OBJPROP_COLOR, cols[i]);
      ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, InpFontSize);
      ObjectSetString(0, nm, OBJPROP_FONT, "Consolas");
      ObjectSetString(0, nm, OBJPROP_TEXT, lines[i]);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   }
   ChartRedraw();
}

//+------------------------------------------------------------------+
void UpdatePanel()
{
   if(g_symbol == "") g_symbol = _Symbol;

   string pH1 = PatternState(PERIOD_H1);
   string pM15 = PatternState(PERIOD_M15);
   string pM5 = PatternState(PERIOD_M5);
   string pM1 = PatternState(PERIOD_M1);

   int attM15 = CountAttempts(PERIOD_M15, (StringFind(pM15,"UP")>=0 ? "UP" : "DOWN"));
   int attM5  = CountAttempts(PERIOD_M5,  (StringFind(pM5,"UP")>=0  ? "UP" : "DOWN"));
   int attM1  = CountAttempts(PERIOD_M1,  (StringFind(pM1,"UP")>=0  ? "UP" : "DOWN"));

   MAReplicaResult sellCore = EvaluateMAReplica("SELL_CORE", "SELL", InpSellFast, InpSellMid, InpSellSlow, InpSellStopATR, InpSellTargetATR, InpSellMaxHoldMin);
   MAReplicaResult buyCore  = EvaluateMAReplica("BUY_CORE",  "BUY",  InpBuyFast,  InpBuyMid,  InpBuySlow,  InpBuyStopATR,  InpBuyTargetATR,  InpBuyMaxHoldMin);
   MAReplicaResult bothSell = EvaluateMAReplica("BOTH_SELL", "SELL", InpBothFast, InpBothMid, InpBothSlow, InpBothStopATR, InpBothTargetATR, InpBothMaxHoldMin);
   MAReplicaResult bothBuy  = EvaluateMAReplica("BOTH_BUY",  "BUY",  InpBothFast, InpBothMid, InpBothSlow, InpBothStopATR, InpBothTargetATR, InpBothMaxHoldMin);

   string quadSellState="", quadBuyState="";
   bool quadSell = (InpUseQuadMA_5_10_20_80 ? QuadContext("SELL", quadSellState) : false);
   bool quadBuy  = (InpUseQuadMA_5_10_20_80 ? QuadContext("BUY", quadBuyState) : false);

   string m5sd="", m5bd="", m1sd="", m1bd="";
   bool m5Sell = M5PermissionSell(m5sd);
   bool m5Buy  = M5PermissionBuy(m5bd);
   bool m1Sell = M1SellTrigger(m1sd);
   bool m1Buy  = M1BuyTrigger(m1bd);

   string maSide = "NONE";
   string maState = "NO_SETUP";
   string selectedPlan = "NONE";
   double selectedStop = 0, selectedTarget = 0;
   int selectedHold = 0;

   if(InpUseSellCoreMA && sellCore.valid)
   {
      maSide="SELL"; maState="VALID"; selectedPlan="SELL_CORE"; selectedStop=sellCore.stop_atr; selectedTarget=sellCore.target_atr; selectedHold=sellCore.hold_min;
   }
   else if(InpUseBuyCoreMA && buyCore.valid)
   {
      maSide="BUY"; maState="VALID"; selectedPlan="BUY_CORE"; selectedStop=buyCore.stop_atr; selectedTarget=buyCore.target_atr; selectedHold=buyCore.hold_min;
   }
   else if(InpUseBothGeneralMA && bothSell.valid)
   {
      maSide="SELL"; maState="VALID"; selectedPlan="BOTH_SELL"; selectedStop=bothSell.stop_atr; selectedTarget=bothSell.target_atr; selectedHold=bothSell.hold_min;
   }
   else if(InpUseBothGeneralMA && bothBuy.valid)
   {
      maSide="BUY"; maState="VALID"; selectedPlan="BOTH_BUY"; selectedStop=bothBuy.stop_atr; selectedTarget=bothBuy.target_atr; selectedHold=bothBuy.hold_min;
   }
   else
   {
      if(sellCore.state=="WAIT_M5_CLOSED_ALL" || bothSell.state=="WAIT_M5_CLOSED_ALL") { maSide="SELL"; maState="WAIT_M5_CLOSED_ALL"; selectedPlan=(sellCore.state=="WAIT_M5_CLOSED_ALL" ? "SELL_CORE" : "BOTH_SELL"); }
      else if(buyCore.state=="WAIT_M5_CLOSED_ALL" || bothBuy.state=="WAIT_M5_CLOSED_ALL") { maSide="BUY"; maState="WAIT_M5_CLOSED_ALL"; selectedPlan=(buyCore.state=="WAIT_M5_CLOSED_ALL" ? "BUY_CORE" : "BOTH_BUY"); }
      else if(sellCore.state=="WAIT_M15" || bothSell.state=="WAIT_M15") { maSide="SELL"; maState="WAIT_M15"; selectedPlan=(sellCore.state=="WAIT_M15" ? "SELL_CORE" : "BOTH_SELL"); }
      else if(buyCore.state=="WAIT_M15" || bothBuy.state=="WAIT_M15") { maSide="BUY"; maState="WAIT_M15"; selectedPlan=(buyCore.state=="WAIT_M15" ? "BUY_CORE" : "BOTH_BUY"); }
   }

   string activeEvent = "RANGE_INSIDE";
   string activeSide = "NONE";
   if(StringFind(pM5,"BREAKOUT_UP")>=0 || StringFind(pM1,"BREAKOUT_UP")>=0) { activeEvent="BREAKOUT_UP_WAIT_ACCEPTANCE"; activeSide="BUY"; }
   if(StringFind(pM5,"BREAKOUT_DOWN")>=0 || StringFind(pM1,"BREAKOUT_DOWN")>=0) { activeEvent="BREAKOUT_DOWN_WAIT_ACCEPTANCE"; activeSide="SELL"; }
   if(StringFind(pM5,"FAKEOUT_UP")>=0 || StringFind(pM1,"FAKEOUT_UP")>=0) { activeEvent="BREAKOUT_UP_FAILED_FAKEOUT"; activeSide="SELL"; }
   if(StringFind(pM5,"FAKEOUT_DOWN")>=0 || StringFind(pM1,"FAKEOUT_DOWN")>=0) { activeEvent="BREAKOUT_DOWN_FAILED_FAKEOUT"; activeSide="BUY"; }

   string action = "WAIT";
   string reason = "sem setup MA valido";

   if(maState == "VALID")
   {
      if(maSide == "SELL")
      {
         if(InpRequireM5Permission && !m5Sell) { action="WAIT_M5_CONFIRMATION"; reason="MA SELL valido, mas M5 nao permite venda"; }
         else if(InpRequireM1Trigger && !m1Sell) { action="WAIT_M1_TRIGGER"; reason="MA SELL valido, aguardando gatilho M1"; }
         else { action="SELL_SIGNAL"; reason="MA_RESEARCH valido + operacional SELL confirmado"; }
      }
      else if(maSide == "BUY")
      {
         if(InpRequireM5Permission && !m5Buy) { action="WAIT_M5_CONFIRMATION"; reason="MA BUY valido, mas M5 nao permite compra"; }
         else if(InpRequireM1Trigger && !m1Buy) { action="WAIT_M1_TRIGGER"; reason="MA BUY valido, aguardando gatilho M1"; }
         else { action="BUY_SIGNAL"; reason="MA_RESEARCH valido + operacional BUY confirmado"; }
      }
   }
   else if(activeEvent=="BREAKOUT_UP_FAILED_FAKEOUT" || activeEvent=="BREAKOUT_DOWN_FAILED_FAKEOUT")
   {
      action="WAIT_FAKEOUT_CONFIRMATION";
      reason="fakeout em observacao; precisa M5/M1";
   }
   else if(maState=="WAIT_M5_CLOSED_ALL")
   {
      action="WAIT_M5_CLOSED_ALL";
      reason="MA_RESEARCH precisa M5 closed_all";
   }
   else if(maState=="WAIT_M15")
   {
      action="WAIT_M15";
      reason="MA_RESEARCH precisa M15 required";
   }

   string lines[];
   color cols[];
   int n=0;

   AppendLine(lines, cols, n, "TradingAgent Signal Panel v3", clrWhite);
   AppendLine(lines, cols, n, StringFormat("%s | TF=%s | bid %.2f ask %.2f", g_symbol, TFName(_Period), Bid(), Ask()), clrSilver);
   AppendLine(lines, cols, n, "SIGNAL ONLY - no trades / no OrderSend", clrDodgerBlue);
   AppendLine(lines, cols, n, "ACTION: " + action, ActionColor(action));
   AppendLine(lines, cols, n, "reason: " + reason, clrSilver);
   AppendLine(lines, cols, n, " ", clrWhite);

   AppendLine(lines, cols, n, "MA RESEARCH REPLICA", clrDeepSkyBlue);
   if(InpUseSellCoreMA)
      AppendLine(lines, cols, n, StringFormat(" SELL_CORE 8/20/63 : %s | %s | %.1f/%.1fATR | %dm", sellCore.state, sellCore.side, sellCore.stop_atr, sellCore.target_atr, sellCore.hold_min), sellCore.valid?clrLimeGreen:clrSilver);
   if(InpUseBuyCoreMA)
      AppendLine(lines, cols, n, StringFormat(" BUY_CORE 6/30/85  : %s | %s | %.1f/%.1fATR | %dm", buyCore.state, buyCore.side, buyCore.stop_atr, buyCore.target_atr, buyCore.hold_min), buyCore.valid?clrLimeGreen:clrSilver);
   if(InpUseBothGeneralMA)
   {
      AppendLine(lines, cols, n, StringFormat(" BOTH_SELL 5/30/81 : %s | %.1f/%.1fATR | %dm", bothSell.state, bothSell.stop_atr, bothSell.target_atr, bothSell.hold_min), bothSell.valid?clrLimeGreen:clrSilver);
      AppendLine(lines, cols, n, StringFormat(" BOTH_BUY  5/30/81 : %s | %.1f/%.1fATR | %dm", bothBuy.state, bothBuy.stop_atr, bothBuy.target_atr, bothBuy.hold_min), bothBuy.valid?clrLimeGreen:clrSilver);
   }
   if(InpUseQuadMA_5_10_20_80 && !InpCompactPanel)
   {
      AppendLine(lines, cols, n, " QUAD SELL 5/10/20/80: " + quadSellState, quadSell?clrLimeGreen:clrSilver);
      AppendLine(lines, cols, n, " QUAD BUY  5/10/20/80: " + quadBuyState, quadBuy?clrLimeGreen:clrSilver);
   }
   AppendLine(lines, cols, n, " selected: " + selectedPlan + " | side=" + maSide + " | state=" + maState, clrGold);
   AppendLine(lines, cols, n, " ", clrWhite);

   AppendLine(lines, cols, n, "EVENT STATE", clrDeepSkyBlue);
   AppendLine(lines, cols, n, " active_event: " + activeEvent, clrGold);
   AppendLine(lines, cols, n, " active_side : " + activeSide, ActionColor(activeSide));
   AppendLine(lines, cols, n, StringFormat(" H1:%s | M15:%s", pH1, pM15), clrSilver);
   AppendLine(lines, cols, n, StringFormat(" M5:%s att=%d | M1:%s att=%d", pM5, attM5, pM1, attM1), clrSilver);
   AppendLine(lines, cols, n, " ", clrWhite);

   AppendLine(lines, cols, n, "OPERATIONAL FILTER", clrDeepSkyBlue);
   if(maSide=="SELL" || activeSide=="SELL")
   {
      AppendLine(lines, cols, n, " relevant side: SELL", clrTomato);
      AppendLine(lines, cols, n, " " + m5sd, m5Sell?clrLimeGreen:clrTomato);
      AppendLine(lines, cols, n, " " + m1sd, m1Sell?clrLimeGreen:clrTomato);
   }
   else if(maSide=="BUY" || activeSide=="BUY")
   {
      AppendLine(lines, cols, n, " relevant side: BUY", clrLimeGreen);
      AppendLine(lines, cols, n, " " + m5bd, m5Buy?clrLimeGreen:clrTomato);
      AppendLine(lines, cols, n, " " + m1bd, m1Buy?clrLimeGreen:clrTomato);
   }
   else
   {
      AppendLine(lines, cols, n, " relevant side: NONE", clrSilver);
   }

   if(InpShowDebugDetails)
   {
      AppendLine(lines, cols, n, " ", clrWhite);
      AppendLine(lines, cols, n, "DEBUG MA DETAILS", clrSlateGray);
      AppendLine(lines, cols, n, sellCore.detail, clrSlateGray);
      AppendLine(lines, cols, n, buyCore.detail, clrSlateGray);
      AppendLine(lines, cols, n, bothSell.detail, clrSlateGray);
      AppendLine(lines, cols, n, bothBuy.detail, clrSlateGray);
      AppendLine(lines, cols, n, m5bd, clrSlateGray);
      AppendLine(lines, cols, n, m1bd, clrSlateGray);
   }

   DrawPanel(lines, cols, n);

   if((InpEnableAlerts || InpEnablePush) && action != g_last_action)
   {
      string msg = "TradingAgent " + g_symbol + " -> " + action + " | " + reason;
      if(InpEnableAlerts) Alert(msg);
      if(InpEnablePush) SendNotification(msg);
      g_last_action = action;
   }
}
//+------------------------------------------------------------------+
