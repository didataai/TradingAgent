//+------------------------------------------------------------------+
//| TradingAgent_SignalPanel_EA.mq5                                  |
//| Painel/alerta operacional baseado nas regras estudadas            |
//|                                                                  |
//| Filosofia                                                        |
//| - Sinalizador, nao executor automatico.                           |
//| - Nao inventa direcao.                                            |
//| - Usa candles, medias, rompimento, fakeout e M1/M5 permission.    |
//| - M1 da gatilho fino; M5 autoriza/bloqueia; M15/H1 contextualizam.|
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "TradingAgent signal panel: MA confluence, M1 trigger, M5 permission, breakout/fakeout context."

input string          InpSymbol                    = "";          // Vazio = simbolo do grafico
input bool            InpEnableAlerts              = true;        // Alerta popup quando a acao muda
input bool            InpEnablePush                = false;       // Push notification quando a acao muda
input int             InpTimerSeconds              = 3;           // Atualizacao do painel
input ENUM_MA_METHOD  InpMAMethod                  = MODE_EMA;    // Metodo das medias
input ENUM_APPLIED_PRICE InpMAPrice                = PRICE_CLOSE;

// Estrategias de medias descobertas no estudo
input bool            InpUseSellCoreMA             = true;        // SELL_CORE 8/20/63
input int             InpSellFast                  = 8;
input int             InpSellMid                   = 20;
input int             InpSellSlow                  = 63;

input bool            InpUseBuyCoreMA              = true;        // BUY_CORE 6/30/85
input int             InpBuyFast                   = 6;
input int             InpBuyMid                    = 30;
input int             InpBuySlow                   = 85;

input bool            InpUseBothGeneralMA          = true;        // BOTH_GENERAL 5/30/81
input int             InpBothFast                  = 5;
input int             InpBothMid                   = 30;
input int             InpBothSlow                  = 81;

input bool            InpUseQuadMA_5_10_20_80      = true;        // Familia citada: 5/10/20/80
input int             InpQuadFast                  = 5;
input int             InpQuadMid1                  = 10;
input int             InpQuadMid2                  = 20;
input int             InpQuadSlow                  = 80;

// Filtros e gatilhos
input bool            InpRequireM15MA              = true;        // M15 alinhado para medias
input bool            InpRequireM5MA               = true;        // M5 alinhado para medias
input bool            InpRequireM5Permission       = true;        // Regra pessoal M5 do Diego
input bool            InpRequireM1Trigger          = true;        // M1 candle anterior + rompimento
input int             InpAttemptLookbackBars       = 30;          // Barras para contar tentativas
input double          InpAttemptToleranceATR       = 0.20;        // Tolerancia tentativa em ATR
input double          InpMaxM1RangeATRWarning      = 1.50;        // Warning de candle M1 longo
input bool            InpUseClosedCandleForMA      = true;        // Medias em candle fechado

// Pesos visuais apenas para painel
input bool            InpShowDebugLevels           = true;

string g_symbol;
string g_last_action = "";
datetime g_last_alert_bar = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = (InpSymbol == "" ? _Symbol : InpSymbol);
   EventSetTimer(MathMax(1, InpTimerSeconds));
   Comment("TradingAgent Signal Panel inicializado em ", g_symbol);
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   UpdatePanel();
}

//+------------------------------------------------------------------+
void OnTimer()
{
   UpdatePanel();
}

//+------------------------------------------------------------------+
bool GetRates(const ENUM_TIMEFRAMES tf, const int count, MqlRates &rates[])
{
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(g_symbol, tf, 0, count, rates);
   return (copied >= count);
}

//+------------------------------------------------------------------+
double Bid()
{
   double v = 0.0;
   SymbolInfoDouble(g_symbol, SYMBOL_BID, v);
   return v;
}

//+------------------------------------------------------------------+
double Ask()
{
   double v = 0.0;
   SymbolInfoDouble(g_symbol, SYMBOL_ASK, v);
   return v;
}

//+------------------------------------------------------------------+
string TFName(const ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M1)  return "M1";
   if(tf == PERIOD_M5)  return "M5";
   if(tf == PERIOD_M15) return "M15";
   if(tf == PERIOD_H1)  return "H1";
   if(tf == PERIOD_H4)  return "H4";
   return EnumToString(tf);
}

//+------------------------------------------------------------------+
bool IsBullish(const MqlRates &bar)
{
   return bar.close > bar.open;
}

//+------------------------------------------------------------------+
bool IsBearish(const MqlRates &bar)
{
   return bar.close < bar.open;
}

//+------------------------------------------------------------------+
double GetATR(const ENUM_TIMEFRAMES tf, const int period=14, const int shift=1)
{
   int handle = iATR(g_symbol, tf, period);
   if(handle == INVALID_HANDLE)
      return 0.0;

   double buffer[];
   ArraySetAsSeries(buffer, true);
   int copied = CopyBuffer(handle, 0, shift, 1, buffer);
   IndicatorRelease(handle);
   if(copied < 1)
      return 0.0;
   return buffer[0];
}

//+------------------------------------------------------------------+
double GetMA(const ENUM_TIMEFRAMES tf, const int period, const int shift)
{
   int handle = iMA(g_symbol, tf, period, 0, InpMAMethod, InpMAPrice);
   if(handle == INVALID_HANDLE)
      return 0.0;

   double buffer[];
   ArraySetAsSeries(buffer, true);
   int copied = CopyBuffer(handle, 0, shift, 1, buffer);
   IndicatorRelease(handle);
   if(copied < 1)
      return 0.0;
   return buffer[0];
}

//+------------------------------------------------------------------+
bool MAAlignedSellTF(const ENUM_TIMEFRAMES tf, const int fast, const int mid, const int slow, string &detail)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r))
   {
      detail = TFName(tf) + " sem dados";
      return false;
   }

   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double maFast = GetMA(tf, fast, shift);
   double maMid  = GetMA(tf, mid, shift);
   double maSlow = GetMA(tf, slow, shift);
   double closev = r[shift].close;

   bool ok = (maFast > 0 && maMid > 0 && maSlow > 0 && maFast < maMid && maMid < maSlow && closev <= maFast);
   detail = StringFormat("%s SELL ma(%d/%d/%d) fast=%.2f mid=%.2f slow=%.2f close=%.2f => %s",
                         TFName(tf), fast, mid, slow, maFast, maMid, maSlow, closev, ok ? "OK" : "NO");
   return ok;
}

//+------------------------------------------------------------------+
bool MAAlignedBuyTF(const ENUM_TIMEFRAMES tf, const int fast, const int mid, const int slow, string &detail)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r))
   {
      detail = TFName(tf) + " sem dados";
      return false;
   }

   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double maFast = GetMA(tf, fast, shift);
   double maMid  = GetMA(tf, mid, shift);
   double maSlow = GetMA(tf, slow, shift);
   double closev = r[shift].close;

   bool ok = (maFast > 0 && maMid > 0 && maSlow > 0 && maFast > maMid && maMid > maSlow && closev >= maFast);
   detail = StringFormat("%s BUY ma(%d/%d/%d) fast=%.2f mid=%.2f slow=%.2f close=%.2f => %s",
                         TFName(tf), fast, mid, slow, maFast, maMid, maSlow, closev, ok ? "OK" : "NO");
   return ok;
}

//+------------------------------------------------------------------+
bool QuadAlignedSellTF(const ENUM_TIMEFRAMES tf, string &detail)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r))
   {
      detail = TFName(tf) + " sem dados";
      return false;
   }

   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double ma5  = GetMA(tf, InpQuadFast, shift);
   double ma10 = GetMA(tf, InpQuadMid1, shift);
   double ma20 = GetMA(tf, InpQuadMid2, shift);
   double ma80 = GetMA(tf, InpQuadSlow, shift);
   double closev = r[shift].close;

   bool ok = (ma5 > 0 && ma10 > 0 && ma20 > 0 && ma80 > 0 && ma5 < ma10 && ma10 < ma20 && ma20 < ma80 && closev <= ma5);
   detail = StringFormat("%s SELL ma(%d/%d/%d/%d) %.2f/%.2f/%.2f/%.2f close=%.2f => %s",
                         TFName(tf), InpQuadFast, InpQuadMid1, InpQuadMid2, InpQuadSlow,
                         ma5, ma10, ma20, ma80, closev, ok ? "OK" : "NO");
   return ok;
}

//+------------------------------------------------------------------+
bool QuadAlignedBuyTF(const ENUM_TIMEFRAMES tf, string &detail)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r))
   {
      detail = TFName(tf) + " sem dados";
      return false;
   }

   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double ma5  = GetMA(tf, InpQuadFast, shift);
   double ma10 = GetMA(tf, InpQuadMid1, shift);
   double ma20 = GetMA(tf, InpQuadMid2, shift);
   double ma80 = GetMA(tf, InpQuadSlow, shift);
   double closev = r[shift].close;

   bool ok = (ma5 > 0 && ma10 > 0 && ma20 > 0 && ma80 > 0 && ma5 > ma10 && ma10 > ma20 && ma20 > ma80 && closev >= ma5);
   detail = StringFormat("%s BUY ma(%d/%d/%d/%d) %.2f/%.2f/%.2f/%.2f close=%.2f => %s",
                         TFName(tf), InpQuadFast, InpQuadMid1, InpQuadMid2, InpQuadSlow,
                         ma5, ma10, ma20, ma80, closev, ok ? "OK" : "NO");
   return ok;
}

//+------------------------------------------------------------------+
bool StrategySellMA(const int fast, const int mid, const int slow, const string name, string &detail)
{
   string m15d = "", m5d = "";
   bool m15 = MAAlignedSellTF(PERIOD_M15, fast, mid, slow, m15d);
   bool m5  = MAAlignedSellTF(PERIOD_M5,  fast, mid, slow, m5d);

   bool ok = true;
   if(InpRequireM15MA) ok = ok && m15;
   if(InpRequireM5MA)  ok = ok && m5;

   detail = name + " SELL => " + (ok ? "OK" : "NO") + " | " + m15d + " | " + m5d;
   return ok;
}

//+------------------------------------------------------------------+
bool StrategyBuyMA(const int fast, const int mid, const int slow, const string name, string &detail)
{
   string m15d = "", m5d = "";
   bool m15 = MAAlignedBuyTF(PERIOD_M15, fast, mid, slow, m15d);
   bool m5  = MAAlignedBuyTF(PERIOD_M5,  fast, mid, slow, m5d);

   bool ok = true;
   if(InpRequireM15MA) ok = ok && m15;
   if(InpRequireM5MA)  ok = ok && m5;

   detail = name + " BUY => " + (ok ? "OK" : "NO") + " | " + m15d + " | " + m5d;
   return ok;
}

//+------------------------------------------------------------------+
bool StrategyQuadSell(string &detail)
{
   string m15d = "", m5d = "";
   bool m15 = QuadAlignedSellTF(PERIOD_M15, m15d);
   bool m5  = QuadAlignedSellTF(PERIOD_M5,  m5d);

   bool ok = true;
   if(InpRequireM15MA) ok = ok && m15;
   if(InpRequireM5MA)  ok = ok && m5;

   detail = "QUAD_5_10_20_80 SELL => " + (ok ? "OK" : "NO") + " | " + m15d + " | " + m5d;
   return ok;
}

//+------------------------------------------------------------------+
bool StrategyQuadBuy(string &detail)
{
   string m15d = "", m5d = "";
   bool m15 = QuadAlignedBuyTF(PERIOD_M15, m15d);
   bool m5  = QuadAlignedBuyTF(PERIOD_M5,  m5d);

   bool ok = true;
   if(InpRequireM15MA) ok = ok && m15;
   if(InpRequireM5MA)  ok = ok && m5;

   detail = "QUAD_5_10_20_80 BUY => " + (ok ? "OK" : "NO") + " | " + m15d + " | " + m5d;
   return ok;
}

//+------------------------------------------------------------------+
bool M1SellTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r))
   {
      detail = "M1 sem dados";
      return false;
   }

   double bid = Bid();
   bool previousRed = IsBearish(r[1]);
   bool brokeLow = bid < r[1].low;
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   string warn = (rangeAtr > InpMaxM1RangeATRWarning ? " WARNING:candle_M1_longo" : "");

   bool ok = previousRed && brokeLow;
   detail = StringFormat("M1 SELL trigger=%s | prev_red=%s | bid %.2f < prev_low %.2f | rangeATR=%.2f%s",
                         ok ? "OK" : "NO", previousRed ? "true" : "false", bid, r[1].low, rangeAtr, warn);
   return ok;
}

//+------------------------------------------------------------------+
bool M1BuyTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r))
   {
      detail = "M1 sem dados";
      return false;
   }

   double ask = Ask();
   bool previousGreen = IsBullish(r[1]);
   bool brokeHigh = ask > r[1].high;
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr > 0.0 ? (r[1].high - r[1].low) / atr : 0.0);
   string warn = (rangeAtr > InpMaxM1RangeATRWarning ? " WARNING:candle_M1_longo" : "");

   bool ok = previousGreen && brokeHigh;
   detail = StringFormat("M1 BUY trigger=%s | prev_green=%s | ask %.2f > prev_high %.2f | rangeATR=%.2f%s",
                         ok ? "OK" : "NO", previousGreen ? "true" : "false", ask, r[1].high, rangeAtr, warn);
   return ok;
}

//+------------------------------------------------------------------+
bool M5SellPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r))
   {
      detail = "M5 sem dados";
      return false;
   }

   double bid = Bid();
   double bodyHigh = MathMax(r[1].open, r[1].close);
   double bodyLow  = MathMin(r[1].open, r[1].close);
   bool insidePrevBody = (bid <= bodyHigh && bid >= bodyLow);
   bool breakingPrevLow = (bid < r[1].low);
   bool blockedAgainstSell = (bid > r[1].high);

   bool ok = (!blockedAgainstSell && (insidePrevBody || breakingPrevLow));
   detail = StringFormat("M5 SELL permission=%s | inside_body=%s | break_prev_low=%s | blocked_above_prev_high=%s | bid=%.2f body=[%.2f..%.2f] prevLow=%.2f prevHigh=%.2f",
                         ok ? "OK" : "NO", insidePrevBody ? "true" : "false", breakingPrevLow ? "true" : "false",
                         blockedAgainstSell ? "true" : "false", bid, bodyLow, bodyHigh, r[1].low, r[1].high);
   return ok;
}

//+------------------------------------------------------------------+
bool M5BuyPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r))
   {
      detail = "M5 sem dados";
      return false;
   }

   double ask = Ask();
   double bodyHigh = MathMax(r[1].open, r[1].close);
   double bodyLow  = MathMin(r[1].open, r[1].close);
   bool insidePrevBody = (ask <= bodyHigh && ask >= bodyLow);
   bool breakingPrevHigh = (ask > r[1].high);
   bool blockedAgainstBuy = (ask < r[1].low);

   bool ok = (!blockedAgainstBuy && (insidePrevBody || breakingPrevHigh));
   detail = StringFormat("M5 BUY permission=%s | inside_body=%s | break_prev_high=%s | blocked_below_prev_low=%s | ask=%.2f body=[%.2f..%.2f] prevLow=%.2f prevHigh=%.2f",
                         ok ? "OK" : "NO", insidePrevBody ? "true" : "false", breakingPrevHigh ? "true" : "false",
                         blockedAgainstBuy ? "true" : "false", ask, bodyLow, bodyHigh, r[1].low, r[1].high);
   return ok;
}

//+------------------------------------------------------------------+
int CountAttempts(const ENUM_TIMEFRAMES tf, const bool downSide, const double level)
{
   int bars = MathMax(5, InpAttemptLookbackBars);
   MqlRates r[];
   if(!GetRates(tf, bars + 2, r))
      return 0;

   double atr = GetATR(tf, 14, 1);
   double tol = (atr > 0.0 ? atr * InpAttemptToleranceATR : 0.0);
   int count = 0;
   bool lastWasTouch = false;

   for(int i = bars; i >= 1; --i)
   {
      bool touch = false;
      if(downSide)
         touch = (r[i].low <= level + tol);
      else
         touch = (r[i].high >= level - tol);

      if(touch && !lastWasTouch)
         count++;
      lastWasTouch = touch;
   }

   if(count > 3)
      count = 3;
   return count;
}

//+------------------------------------------------------------------+
string AttemptRead(const int attempts, const bool accepted)
{
   if(attempts <= 1)
      return accepted ? "att=1 accepted? confirmar" : "att=1 AVOID_CHASE/HIGH_FAKEOUT_RISK";
   if(attempts == 2)
      return accepted ? "att=2 accepted? confirmar" : "att=2 AVOID_CHASE/HIGH_FAKEOUT_RISK";
   return accepted ? "att=3 WATCH_ACCEPTANCE" : "att=3 precisa candle fechado/reteste";
}

//+------------------------------------------------------------------+
void BreakoutFakeoutContext(const ENUM_TIMEFRAMES tf, string &patternLine, string &edgeLine, string &fakeoutLine)
{
   MqlRates r[];
   if(!GetRates(tf, 4, r))
   {
      patternLine = TFName(tf) + ": sem dados";
      edgeLine = TFName(tf) + ": NA";
      fakeoutLine = TFName(tf) + ": NA";
      return;
   }

   double bid = Bid();
   double ask = Ask();
   double prevHigh = r[1].high;
   double prevLow  = r[1].low;

   bool breakoutDownLive = (bid < prevLow);
   bool breakoutUpLive   = (ask > prevHigh);
   bool falseDown        = (r[0].low < prevLow && bid > prevLow);
   bool falseUp          = (r[0].high > prevHigh && ask < prevHigh);

   string pattern = "RANGE/LEVEL";
   string phase = "WAIT_CONFIRMATION/LOW";
   string fakeState = "NO_SETUP";
   string side = "NONE";
   int attempts = 1;
   bool accepted = false;

   if(falseDown)
   {
      pattern = "FAKEOUT_DOWN";
      phase = "RETURN_INSIDE_PENDING/MIXED";
      fakeState = "FAKEOUT_RETURN_CONFIRMATION_PENDING";
      side = "BUY";
      attempts = CountAttempts(tf, true, prevLow);
   }
   else if(falseUp)
   {
      pattern = "FAKEOUT_UP";
      phase = "RETURN_INSIDE_PENDING/MIXED";
      fakeState = "FAKEOUT_RETURN_CONFIRMATION_PENDING";
      side = "SELL";
      attempts = CountAttempts(tf, false, prevHigh);
   }
   else if(breakoutDownLive)
   {
      pattern = "BREAKOUT_DOWN_LIVE";
      phase = "BREAKOUT_ATTEMPT/MIXED";
      fakeState = "WATCHING_FAKEOUT";
      side = "NONE";
      attempts = CountAttempts(tf, true, prevLow);
      accepted = (r[1].close < prevLow);
   }
   else if(breakoutUpLive)
   {
      pattern = "BREAKOUT_UP_LIVE";
      phase = "BREAKOUT_ATTEMPT/MIXED";
      fakeState = "WATCHING_FAKEOUT";
      side = "NONE";
      attempts = CountAttempts(tf, false, prevHigh);
      accepted = (r[1].close > prevHigh);
   }
   else
   {
      pattern = "INSIDE_OR_CONSOLIDATION";
      phase = "WAIT_CONFIRMATION/LOW";
      fakeState = "NO_SETUP";
      side = "NONE";
      attempts = 1;
   }

   patternLine = StringFormat("%s: %s (%s)", TFName(tf), pattern, phase);
   edgeLine = StringFormat("%s: %s | %s", TFName(tf), pattern, AttemptRead(attempts, accepted));
   fakeoutLine = StringFormat("%s: %s | side=%s", TFName(tf), fakeState, side);
}

//+------------------------------------------------------------------+
void AlertIfChanged(const string action, const string panel)
{
   if(action == g_last_action)
      return;

   g_last_action = action;
   if(!InpEnableAlerts && !InpEnablePush)
      return;

   string msg = "TradingAgent " + g_symbol + " | " + action;
   if(InpEnableAlerts)
      Alert(msg);
   if(InpEnablePush)
      SendNotification(msg + "\n" + panel);
}

//+------------------------------------------------------------------+
void UpdatePanel()
{
   if(g_symbol == "")
      g_symbol = _Symbol;

   if(!SymbolSelect(g_symbol, true))
   {
      Comment("TradingAgent: simbolo invalido: ", g_symbol);
      return;
   }

   string m1SellD = "", m1BuyD = "", m5SellD = "", m5BuyD = "";
   bool m1Sell = M1SellTrigger(m1SellD);
   bool m1Buy  = M1BuyTrigger(m1BuyD);
   bool m5Sell = M5SellPermission(m5SellD);
   bool m5Buy  = M5BuyPermission(m5BuyD);

   string sellCoreD = "", buyCoreD = "", bothSellD = "", bothBuyD = "", quadSellD = "", quadBuyD = "";
   bool sellCore = false, buyCore = false, bothSell = false, bothBuy = false, quadSell = false, quadBuy = false;

   if(InpUseSellCoreMA)
      sellCore = StrategySellMA(InpSellFast, InpSellMid, InpSellSlow, "SELL_CORE", sellCoreD);
   else
      sellCoreD = "SELL_CORE disabled";

   if(InpUseBuyCoreMA)
      buyCore = StrategyBuyMA(InpBuyFast, InpBuyMid, InpBuySlow, "BUY_CORE", buyCoreD);
   else
      buyCoreD = "BUY_CORE disabled";

   if(InpUseBothGeneralMA)
   {
      bothSell = StrategySellMA(InpBothFast, InpBothMid, InpBothSlow, "BOTH_GENERAL", bothSellD);
      bothBuy  = StrategyBuyMA(InpBothFast, InpBothMid, InpBothSlow, "BOTH_GENERAL", bothBuyD);
   }
   else
   {
      bothSellD = "BOTH_GENERAL SELL disabled";
      bothBuyD  = "BOTH_GENERAL BUY disabled";
   }

   if(InpUseQuadMA_5_10_20_80)
   {
      quadSell = StrategyQuadSell(quadSellD);
      quadBuy  = StrategyQuadBuy(quadBuyD);
   }
   else
   {
      quadSellD = "QUAD SELL disabled";
      quadBuyD  = "QUAD BUY disabled";
   }

   bool maSellContext = (sellCore || bothSell || quadSell);
   bool maBuyContext  = (buyCore || bothBuy || quadBuy);

   bool sellReady = maSellContext;
   bool buyReady  = maBuyContext;

   if(InpRequireM5Permission)
   {
      sellReady = sellReady && m5Sell;
      buyReady  = buyReady && m5Buy;
   }
   if(InpRequireM1Trigger)
   {
      sellReady = sellReady && m1Sell;
      buyReady  = buyReady && m1Buy;
   }

   string pM15, eM15, fM15;
   string pM5,  eM5,  fM5;
   string pM1,  eM1,  fM1;
   string pH1,  eH1,  fH1;
   BreakoutFakeoutContext(PERIOD_M15, pM15, eM15, fM15);
   BreakoutFakeoutContext(PERIOD_M5,  pM5,  eM5,  fM5);
   BreakoutFakeoutContext(PERIOD_M1,  pM1,  eM1,  fM1);
   BreakoutFakeoutContext(PERIOD_H1,  pH1,  eH1,  fH1);

   string action = "WAIT";
   string reason = "sem gatilho completo";

   if(sellReady && !buyReady)
   {
      action = "SELL";
      reason = "MA sell + M5 permission + M1 sell trigger";
   }
   else if(buyReady && !sellReady)
   {
      action = "BUY";
      reason = "MA buy + M5 permission + M1 buy trigger";
   }
   else if(sellReady && buyReady)
   {
      action = "WAIT_CONFLICT";
      reason = "BUY e SELL simultaneos; aguardar limpeza";
   }
   else if((maSellContext && !m5Sell) || (maBuyContext && !m5Buy))
   {
      action = "WAIT_M5_CONFIRMATION";
      reason = "contexto MA existe, mas M5 ainda nao permite";
   }
   else if((maSellContext && !m1Sell) || (maBuyContext && !m1Buy))
   {
      action = "WAIT_M1_TRIGGER";
      reason = "contexto MA existe, mas falta gatilho M1";
   }
   else
   {
      action = "WAIT";
      reason = "sem confluencia operacional";
   }

   string panel = "";
   panel += "TradingAgent MQL5 Signal Panel\n";
   panel += "symbol: " + g_symbol + " | bid=" + DoubleToString(Bid(), _Digits) + " ask=" + DoubleToString(Ask(), _Digits) + "\n";
   panel += "med: " + action + "\n";
   panel += "reason: " + reason + "\n\n";

   panel += "patterns:\n";
   panel += "  " + pM15 + "\n";
   panel += "  " + pM5  + "\n";
   panel += "  " + pM1  + "\n";
   panel += "  " + pH1  + "\n\n";

   panel += "edge:\n";
   panel += "  " + eM15 + "\n";
   panel += "  " + eM5  + "\n";
   panel += "  " + eM1  + "\n";
   panel += "  " + eH1  + "\n\n";

   panel += "fakeout:\n";
   panel += "  " + fM15 + "\n";
   panel += "  " + fM5  + "\n";
   panel += "  " + fM1  + "\n";
   panel += "  " + fH1  + "\n\n";

   panel += "MA strategies:\n";
   panel += "  SELL_CORE 8/20/63: " + (sellCore ? "OK" : "NO") + "\n";
   panel += "  BUY_CORE 6/30/85: " + (buyCore ? "OK" : "NO") + "\n";
   panel += "  BOTH SELL 5/30/81: " + (bothSell ? "OK" : "NO") + "\n";
   panel += "  BOTH BUY  5/30/81: " + (bothBuy ? "OK" : "NO") + "\n";
   panel += "  QUAD SELL 5/10/20/80: " + (quadSell ? "OK" : "NO") + "\n";
   panel += "  QUAD BUY  5/10/20/80: " + (quadBuy ? "OK" : "NO") + "\n\n";

   panel += "triggers:\n";
   panel += "  " + m5SellD + "\n";
   panel += "  " + m5BuyD  + "\n";
   panel += "  " + m1SellD + "\n";
   panel += "  " + m1BuyD  + "\n\n";

   if(InpShowDebugLevels)
   {
      panel += "MA detail:\n";
      panel += "  " + sellCoreD + "\n";
      panel += "  " + buyCoreD + "\n";
      panel += "  " + bothSellD + "\n";
      panel += "  " + bothBuyD + "\n";
      panel += "  " + quadSellD + "\n";
      panel += "  " + quadBuyD + "\n";
   }

   Comment(panel);
   AlertIfChanged(action, panel);
}
//+------------------------------------------------------------------+
