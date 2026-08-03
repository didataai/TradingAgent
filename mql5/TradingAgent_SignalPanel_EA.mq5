//+------------------------------------------------------------------+
//| TradingAgent_SignalPanel_EA.mq5                                  |
//| Painel/alerta operacional baseado nas regras estudadas            |
//|                                                                  |
//| v2: painel visual limpo, SIGNAL ONLY, sem qualquer envio de ordem. |
//+------------------------------------------------------------------+
#property strict
#property version   "2.00"
#property description "TradingAgent signal-only panel: MA confluence, M1 trigger, M5 permission, breakout/fakeout context."

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
input bool               InpHideCandles               = false;       // Esconder grafico/candles
input bool               InpDimCandles                = true;        // Apagar candles mantendo grafico
input bool               InpCompactPanel              = true;        // Painel compacto
input bool               InpShowDebugDetails          = false;       // Mostrar detalhes extras de MA/trigger
input ENUM_BASE_CORNER   InpPanelCorner               = CORNER_LEFT_UPPER;
input int                InpPanelX                    = 12;
input int                InpPanelY                    = 24;
input int                InpPanelWidth                = 455;
input int                InpLineHeight                = 17;
input int                InpFontSize                  = 9;
input string             InpFontName                  = "Consolas";

// Medias
input ENUM_MA_METHOD     InpMAMethod                  = MODE_EMA;
input ENUM_APPLIED_PRICE InpMAPrice                   = PRICE_CLOSE;
input bool               InpUseClosedCandleForMA      = true;

// Estrategias de medias descobertas no estudo
input bool               InpUseSellCoreMA             = true;        // SELL_CORE 8/20/63
input int                InpSellFast                  = 8;
input int                InpSellMid                   = 20;
input int                InpSellSlow                  = 63;

input bool               InpUseBuyCoreMA              = true;        // BUY_CORE 6/30/85
input int                InpBuyFast                   = 6;
input int                InpBuyMid                    = 30;
input int                InpBuySlow                   = 85;

input bool               InpUseBothGeneralMA          = true;        // BOTH_GENERAL 5/30/81
input int                InpBothFast                  = 5;
input int                InpBothMid                   = 30;
input int                InpBothSlow                  = 81;

input bool               InpUseQuadMA_5_10_20_80      = true;        // Familia citada: 5/10/20/80
input int                InpQuadFast                  = 5;
input int                InpQuadMid1                  = 10;
input int                InpQuadMid2                  = 20;
input int                InpQuadSlow                  = 80;

// Filtros e gatilhos
input bool               InpRequireM15MA              = true;
input bool               InpRequireM5MA               = true;
input bool               InpRequireM5Permission       = true;
input bool               InpRequireM1Trigger          = true;
input int                InpAttemptLookbackBars       = 30;
input double             InpAttemptToleranceATR       = 0.20;
input double             InpMaxM1RangeATRWarning      = 1.50;

string   g_symbol;
string   g_last_action = "";
datetime g_last_alert_bar = 0;
string   PFX = "TA_PANEL_";

// -------------------------------------------------------------------
struct TfRead
{
   string tf;
   string pattern;
   string state;
   string wait;
   string fakeout_state;
   string fakeout_side;
   int    attempt;
};

// -------------------------------------------------------------------
int OnInit()
{
   g_symbol = (InpSymbol == "" ? _Symbol : InpSymbol);
   EventSetTimer(MathMax(1, InpTimerSeconds));
   ApplyChartStyle();
   RenderStatus("Inicializando painel...");
   return(INIT_SUCCEEDED);
}

// -------------------------------------------------------------------
void OnDeinit(const int reason)
{
   EventKillTimer();
   DeletePanelObjects();
   Comment("");
   ChartSetInteger(0, CHART_SHOW, true);
}

// -------------------------------------------------------------------
void OnTick(){ UpdatePanel(); }
void OnTimer(){ UpdatePanel(); }

// -------------------------------------------------------------------
void ApplyChartStyle()
{
   ChartSetInteger(0, CHART_SHOW_TRADE_LEVELS, false);
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   ChartSetInteger(0, CHART_SHOW_VOLUMES, false);
   ChartSetInteger(0, CHART_SHOW_PERIOD_SEP, false);

   if(InpHideCandles)
   {
      ChartSetInteger(0, CHART_SHOW, false);
   }
   else if(InpDimCandles)
   {
      ChartSetInteger(0, CHART_COLOR_BACKGROUND, clrWhite);
      ChartSetInteger(0, CHART_COLOR_FOREGROUND, clrSilver);
      ChartSetInteger(0, CHART_COLOR_GRID, clrWhite);
      ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, clrGainsboro);
      ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, clrLightGray);
      ChartSetInteger(0, CHART_COLOR_CHART_UP, clrGainsboro);
      ChartSetInteger(0, CHART_COLOR_CHART_DOWN, clrLightGray);
      ChartSetInteger(0, CHART_COLOR_BID, clrSilver);
      ChartSetInteger(0, CHART_COLOR_ASK, clrSilver);
   }
   ChartRedraw();
}

// -------------------------------------------------------------------
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
   if(tf==PERIOD_M1)  return "M1";
   if(tf==PERIOD_M5)  return "M5";
   if(tf==PERIOD_M15) return "M15";
   if(tf==PERIOD_H1)  return "H1";
   if(tf==PERIOD_H4)  return "H4";
   return EnumToString(tf);
}

bool IsBullish(const MqlRates &bar){ return bar.close > bar.open; }
bool IsBearish(const MqlRates &bar){ return bar.close < bar.open; }

// -------------------------------------------------------------------
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

// -------------------------------------------------------------------
bool MAAlignedSellTF(const ENUM_TIMEFRAMES tf, const int fast, const int mid, const int slow)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r)) return false;
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double f = GetMA(tf, fast, shift);
   double m = GetMA(tf, mid,  shift);
   double s = GetMA(tf, slow, shift);
   double c = r[shift].close;
   return (f>0 && m>0 && s>0 && f<m && m<s && c<=f);
}

bool MAAlignedBuyTF(const ENUM_TIMEFRAMES tf, const int fast, const int mid, const int slow)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r)) return false;
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double f = GetMA(tf, fast, shift);
   double m = GetMA(tf, mid,  shift);
   double s = GetMA(tf, slow, shift);
   double c = r[shift].close;
   return (f>0 && m>0 && s>0 && f>m && m>s && c>=f);
}

bool QuadAlignedSellTF(const ENUM_TIMEFRAMES tf)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r)) return false;
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double ma5=GetMA(tf,InpQuadFast,shift), ma10=GetMA(tf,InpQuadMid1,shift);
   double ma20=GetMA(tf,InpQuadMid2,shift), ma80=GetMA(tf,InpQuadSlow,shift);
   double c=r[shift].close;
   return (ma5>0 && ma10>0 && ma20>0 && ma80>0 && ma5<ma10 && ma10<ma20 && ma20<ma80 && c<=ma5);
}

bool QuadAlignedBuyTF(const ENUM_TIMEFRAMES tf)
{
   MqlRates r[];
   if(!GetRates(tf, 3, r)) return false;
   int shift = (InpUseClosedCandleForMA ? 1 : 0);
   double ma5=GetMA(tf,InpQuadFast,shift), ma10=GetMA(tf,InpQuadMid1,shift);
   double ma20=GetMA(tf,InpQuadMid2,shift), ma80=GetMA(tf,InpQuadSlow,shift);
   double c=r[shift].close;
   return (ma5>0 && ma10>0 && ma20>0 && ma80>0 && ma5>ma10 && ma10>ma20 && ma20>ma80 && c>=ma5);
}

bool StrategySellMA(const int fast, const int mid, const int slow)
{
   bool ok=true;
   if(InpRequireM15MA) ok = ok && MAAlignedSellTF(PERIOD_M15, fast, mid, slow);
   if(InpRequireM5MA)  ok = ok && MAAlignedSellTF(PERIOD_M5,  fast, mid, slow);
   return ok;
}

bool StrategyBuyMA(const int fast, const int mid, const int slow)
{
   bool ok=true;
   if(InpRequireM15MA) ok = ok && MAAlignedBuyTF(PERIOD_M15, fast, mid, slow);
   if(InpRequireM5MA)  ok = ok && MAAlignedBuyTF(PERIOD_M5,  fast, mid, slow);
   return ok;
}

bool StrategyQuadSell()
{
   bool ok=true;
   if(InpRequireM15MA) ok = ok && QuadAlignedSellTF(PERIOD_M15);
   if(InpRequireM5MA)  ok = ok && QuadAlignedSellTF(PERIOD_M5);
   return ok;
}

bool StrategyQuadBuy()
{
   bool ok=true;
   if(InpRequireM15MA) ok = ok && QuadAlignedBuyTF(PERIOD_M15);
   if(InpRequireM5MA)  ok = ok && QuadAlignedBuyTF(PERIOD_M5);
   return ok;
}

// -------------------------------------------------------------------
bool M1SellTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)){ detail="M1 sem dados"; return false; }
   double bid = Bid();
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr>0 ? (r[1].high-r[1].low)/atr : 0.0);
   bool ok = IsBearish(r[1]) && bid < r[1].low;
   detail = StringFormat("SELL:%s | prevRed=%s | bid %.2f < low %.2f | rngATR %.2f",
                         ok?"OK":"NO", IsBearish(r[1])?"Y":"N", bid, r[1].low, rangeAtr);
   return ok;
}

bool M1BuyTrigger(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M1, 3, r)){ detail="M1 sem dados"; return false; }
   double ask = Ask();
   double atr = GetATR(PERIOD_M1, 14, 1);
   double rangeAtr = (atr>0 ? (r[1].high-r[1].low)/atr : 0.0);
   bool ok = IsBullish(r[1]) && ask > r[1].high;
   detail = StringFormat("BUY:%s | prevGreen=%s | ask %.2f > high %.2f | rngATR %.2f",
                         ok?"OK":"NO", IsBullish(r[1])?"Y":"N", ask, r[1].high, rangeAtr);
   return ok;
}

bool M5SellPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)){ detail="M5 sem dados"; return false; }
   double bid = Bid();
   bool brokeAgainst = (r[0].high > r[1].high || bid > r[1].high);
   bool ok = !brokeAgainst;
   detail = StringFormat("SELL:%s | bid %.2f | prevHigh %.2f | currentHigh %.2f",
                         ok?"OK":"NO", bid, r[1].high, r[0].high);
   return ok;
}

bool M5BuyPermission(string &detail)
{
   MqlRates r[];
   if(!GetRates(PERIOD_M5, 3, r)){ detail="M5 sem dados"; return false; }
   double ask = Ask();
   bool brokeAgainst = (r[0].low < r[1].low || ask < r[1].low);
   bool ok = !brokeAgainst;
   detail = StringFormat("BUY:%s | ask %.2f | prevLow %.2f | currentLow %.2f",
                         ok?"OK":"NO", ask, r[1].low, r[0].low);
   return ok;
}

// -------------------------------------------------------------------
int CountAttempts(const ENUM_TIMEFRAMES tf, const double level, const bool resistance)
{
   int need = MathMax(10, InpAttemptLookbackBars + 5);
   MqlRates r[];
   if(!GetRates(tf, need, r)) return 1;
   double atr = GetATR(tf, 14, 1);
   if(atr <= 0.0) atr = MathMax(_Point, MathAbs(r[1].high-r[1].low));
   double tol = atr * InpAttemptToleranceATR;
   int count = 0;
   for(int i=1; i<MathMin(need, InpAttemptLookbackBars+1); i++)
   {
      double probe = resistance ? r[i].high : r[i].low;
      if(MathAbs(probe-level) <= tol) count++;
   }
   if(count < 1) count = 1;
   if(count > 3) count = 3;
   return count;
}

TfRead ReadTF(const ENUM_TIMEFRAMES tf)
{
   TfRead out;
   out.tf = TFName(tf);
   out.pattern="NO_SETUP";
   out.state="MIXED";
   out.wait="WAIT_CONFIRMATION/LOW";
   out.fakeout_state="NO_SETUP";
   out.fakeout_side="NONE";
   out.attempt=1;

   MqlRates r[];
   if(!GetRates(tf, 5, r)) return out;

   bool breakUpLive   = (r[0].high > r[1].high && r[0].close > r[1].high);
   bool breakDownLive = (r[0].low  < r[1].low  && r[0].close < r[1].low);
   bool fakeUp        = (r[0].high > r[1].high && r[0].close <= r[1].high);
   bool fakeDown      = (r[0].low  < r[1].low  && r[0].close >= r[1].low);
   bool inside        = (r[0].high <= r[1].high && r[0].low >= r[1].low);

   if(fakeDown)
   {
      out.pattern="FAKEOUT_DOWN";
      out.fakeout_state="RETURN_CONFIRMATION_PENDING";
      out.fakeout_side="BUY";
      out.wait="WAIT_M5_M1_CONFIRMATION/MED";
      out.attempt=CountAttempts(tf, r[1].low, false);
   }
   else if(fakeUp)
   {
      out.pattern="FAKEOUT_UP";
      out.fakeout_state="RETURN_CONFIRMATION_PENDING";
      out.fakeout_side="SELL";
      out.wait="WAIT_M5_M1_CONFIRMATION/MED";
      out.attempt=CountAttempts(tf, r[1].high, true);
   }
   else if(breakDownLive)
   {
      out.pattern="BREAKOUT_DOWN_LIVE";
      out.fakeout_state="WATCHING_FAKEOUT";
      out.fakeout_side="NONE";
      out.wait="WAIT_ACCEPTANCE_OR_RETEST/LOW";
      out.attempt=CountAttempts(tf, r[1].low, false);
   }
   else if(breakUpLive)
   {
      out.pattern="BREAKOUT_UP_LIVE";
      out.fakeout_state="WATCHING_FAKEOUT";
      out.fakeout_side="NONE";
      out.wait="WAIT_ACCEPTANCE_OR_RETEST/LOW";
      out.attempt=CountAttempts(tf, r[1].high, true);
   }
   else if(inside)
   {
      out.pattern="INSIDE_OR_CONSOLIDATION";
      out.wait="WAIT_CONFIRMATION/LOW";
   }
   else
   {
      out.pattern = IsBearish(r[0]) ? "BEARISH_CONTEXT" : (IsBullish(r[0]) ? "BULLISH_CONTEXT" : "DOJI_CONTEXT");
      out.wait="WAIT_CONFIRMATION/LOW";
   }
   return out;
}

// -------------------------------------------------------------------
void DeletePanelObjects()
{
   for(int i=ObjectsTotal(0)-1; i>=0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, PFX) == 0)
         ObjectDelete(0, name);
   }
}

void ObjRect(const string name, const int x, const int y, const int w, const int h, const color bg, const color border)
{
   string n=PFX+name;
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_CORNER,InpPanelCorner);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,n,OBJPROP_XSIZE,w);
   ObjectSetInteger(0,n,OBJPROP_YSIZE,h);
   ObjectSetInteger(0,n,OBJPROP_BGCOLOR,bg);
   ObjectSetInteger(0,n,OBJPROP_COLOR,border);
   ObjectSetInteger(0,n,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(0,n,OBJPROP_BACK,false);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

void ObjText(const string name, const string text, const int x, const int y, const color c, const int size=0, const string font="")
{
   string n=PFX+name;
   if(ObjectFind(0,n)<0) ObjectCreate(0,n,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,n,OBJPROP_CORNER,InpPanelCorner);
   ObjectSetInteger(0,n,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,n,OBJPROP_YDISTANCE,y);
   ObjectSetInteger(0,n,OBJPROP_COLOR,c);
   ObjectSetInteger(0,n,OBJPROP_FONTSIZE,(size>0?size:InpFontSize));
   ObjectSetString(0,n,OBJPROP_FONT,(font==""?InpFontName:font));
   ObjectSetString(0,n,OBJPROP_TEXT,text);
   ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,n,OBJPROP_HIDDEN,true);
}

color ActionColor(const string action)
{
   if(StringFind(action,"BUY")>=0) return clrLimeGreen;
   if(StringFind(action,"SELL")>=0) return clrTomato;
   if(StringFind(action,"WAIT")>=0) return clrGold;
   return clrWhite;
}

void AddLine(string &lines[], color &colors[], int &n, const string txt, const color c)
{
   ArrayResize(lines, n+1);
   ArrayResize(colors, n+1);
   lines[n]=txt;
   colors[n]=c;
   n++;
}

string YesNo(const bool v){ return v ? "YES" : "NO"; }

// -------------------------------------------------------------------
void RenderStatus(const string msg)
{
   DeletePanelObjects();
   ObjRect("BG", InpPanelX, InpPanelY, InpPanelWidth, 90, clrBlack, clrDimGray);
   ObjText("TITLE", "TradingAgent Signal Panel", InpPanelX+12, InpPanelY+10, clrWhite, InpFontSize+2, "Consolas");
   ObjText("MSG", msg, InpPanelX+12, InpPanelY+38, clrSilver, InpFontSize, "Consolas");
   ChartRedraw();
}

// -------------------------------------------------------------------
void UpdatePanel()
{
   ApplyChartStyle();

   string m1SellD="", m1BuyD="", m5SellD="", m5BuyD="";
   bool m1Sell = M1SellTrigger(m1SellD);
   bool m1Buy  = M1BuyTrigger(m1BuyD);
   bool m5Sell = M5SellPermission(m5SellD);
   bool m5Buy  = M5BuyPermission(m5BuyD);

   bool sellCore = InpUseSellCoreMA        && StrategySellMA(InpSellFast, InpSellMid, InpSellSlow);
   bool buyCore  = InpUseBuyCoreMA         && StrategyBuyMA(InpBuyFast, InpBuyMid, InpBuySlow);
   bool bothSell = InpUseBothGeneralMA     && StrategySellMA(InpBothFast, InpBothMid, InpBothSlow);
   bool bothBuy  = InpUseBothGeneralMA     && StrategyBuyMA(InpBothFast, InpBothMid, InpBothSlow);
   bool quadSell = InpUseQuadMA_5_10_20_80 && StrategyQuadSell();
   bool quadBuy  = InpUseQuadMA_5_10_20_80 && StrategyQuadBuy();

   bool maSell = (sellCore || bothSell || quadSell);
   bool maBuy  = (buyCore  || bothBuy  || quadBuy);

   TfRead h1  = ReadTF(PERIOD_H1);
   TfRead m15 = ReadTF(PERIOD_M15);
   TfRead m5  = ReadTF(PERIOD_M5);
   TfRead m1  = ReadTF(PERIOD_M1);

   string action="WAIT";
   string reason="sem confluencia operacional";

   if(maSell && (!InpRequireM5Permission || m5Sell) && (!InpRequireM1Trigger || m1Sell))
   {
      action="SELL";
      reason="MA sell + M5 permission + M1 sell trigger";
   }
   else if(maBuy && (!InpRequireM5Permission || m5Buy) && (!InpRequireM1Trigger || m1Buy))
   {
      action="BUY";
      reason="MA buy + M5 permission + M1 buy trigger";
   }
   else if((maSell && InpRequireM5Permission && !m5Sell) || (maBuy && InpRequireM5Permission && !m5Buy))
   {
      action="WAIT_M5_CONFIRMATION";
      reason="confluencia existe, mas M5 ainda nao permite";
   }
   else if((maSell && InpRequireM1Trigger && !m1Sell) || (maBuy && InpRequireM1Trigger && !m1Buy))
   {
      action="WAIT_M1_TRIGGER";
      reason="confluencia existe, mas M1 ainda nao deu gatilho";
   }
   else if(m15.fakeout_side!="NONE" || m1.fakeout_side!="NONE")
   {
      action="WAIT_FAKEOUT_CONFIRMATION";
      reason="possivel retorno de fakeout; precisa M5/M1";
   }

   string lines[];
   color  colors[];
   int n=0;

   AddLine(lines,colors,n,"TradingAgent Signal Panel  v2",clrWhite);
   AddLine(lines,colors,n,StringFormat("%s | %s | bid %.2f ask %.2f", g_symbol, EnumToString((ENUM_TIMEFRAMES)_Period), Bid(), Ask()),clrSilver);
   AddLine(lines,colors,n,"SIGNAL ONLY - no trades / no OrderSend",clrAqua);
   AddLine(lines,colors,n,"",clrWhite);

   AddLine(lines,colors,n,"ACTION: " + action, ActionColor(action));
   AddLine(lines,colors,n,"reason: " + reason, clrSilver);
   AddLine(lines,colors,n,"",clrWhite);

   AddLine(lines,colors,n,"patterns",clrDeepSkyBlue);
   AddLine(lines,colors,n,StringFormat("  H1 : %-22s | att=%d | %s", h1.pattern,  h1.attempt,  h1.wait), clrWhite);
   AddLine(lines,colors,n,StringFormat("  M15: %-22s | att=%d | %s", m15.pattern, m15.attempt, m15.wait),clrWhite);
   AddLine(lines,colors,n,StringFormat("  M5 : %-22s | att=%d | %s", m5.pattern,  m5.attempt,  m5.wait), clrWhite);
   AddLine(lines,colors,n,StringFormat("  M1 : %-22s | att=%d | %s", m1.pattern,  m1.attempt,  m1.wait), clrWhite);
   AddLine(lines,colors,n,"",clrWhite);

   AddLine(lines,colors,n,"MA confluence",clrDeepSkyBlue);
   AddLine(lines,colors,n,StringFormat("  SELL_CORE 8/20/63 : %s", YesNo(sellCore)), sellCore?clrTomato:clrSilver);
   AddLine(lines,colors,n,StringFormat("  BUY_CORE  6/30/85 : %s", YesNo(buyCore)),  buyCore?clrLimeGreen:clrSilver);
   AddLine(lines,colors,n,StringFormat("  BOTH SELL 5/30/81 : %s", YesNo(bothSell)), bothSell?clrTomato:clrSilver);
   AddLine(lines,colors,n,StringFormat("  BOTH BUY  5/30/81 : %s", YesNo(bothBuy)),  bothBuy?clrLimeGreen:clrSilver);
   AddLine(lines,colors,n,StringFormat("  QUAD SELL 5/10/20/80: %s", YesNo(quadSell)), quadSell?clrTomato:clrSilver);
   AddLine(lines,colors,n,StringFormat("  QUAD BUY  5/10/20/80: %s", YesNo(quadBuy)),  quadBuy?clrLimeGreen:clrSilver);
   AddLine(lines,colors,n,"",clrWhite);

   AddLine(lines,colors,n,"edge / fakeout",clrDeepSkyBlue);
   AddLine(lines,colors,n,StringFormat("  M15: %s | att=%d | AVOID_CHASE/%s", m15.pattern, m15.attempt, (m15.attempt<3?"HIGH_FAKEOUT_RISK":"WAIT_ACCEPTANCE")), clrGold);
   AddLine(lines,colors,n,StringFormat("  M5 : %s | att=%d | AVOID_CHASE/%s", m5.pattern,  m5.attempt,  (m5.attempt<3?"HIGH_FAKEOUT_RISK":"WAIT_ACCEPTANCE")), clrGold);
   AddLine(lines,colors,n,StringFormat("  M1 : %s | %s | side=%s", m1.pattern,  m1.fakeout_state,  m1.fakeout_side),  m1.fakeout_side=="BUY"?clrLimeGreen:(m1.fakeout_side=="SELL"?clrTomato:clrSilver));
   AddLine(lines,colors,n,StringFormat("  M15: %s | side=%s", m15.fakeout_state, m15.fakeout_side), m15.fakeout_side=="BUY"?clrLimeGreen:(m15.fakeout_side=="SELL"?clrTomato:clrSilver));
   AddLine(lines,colors,n,"",clrWhite);

   AddLine(lines,colors,n,"triggers",clrDeepSkyBlue);
   AddLine(lines,colors,n,"  M5 permission SELL: " + m5SellD, m5Sell?clrTomato:clrSilver);
   AddLine(lines,colors,n,"  M5 permission BUY : " + m5BuyD,  m5Buy?clrLimeGreen:clrSilver);
   AddLine(lines,colors,n,"  M1 trigger SELL   : " + m1SellD, m1Sell?clrTomato:clrSilver);
   AddLine(lines,colors,n,"  M1 trigger BUY    : " + m1BuyD,  m1Buy?clrLimeGreen:clrSilver);

   if(InpShowDebugDetails)
   {
      AddLine(lines,colors,n,"",clrWhite);
      AddLine(lines,colors,n,"debug",clrDeepSkyBlue);
      AddLine(lines,colors,n,"  InpSignalOnlyMode=true; no trading calls exist in EA",clrSilver);
      AddLine(lines,colors,n,"  MA is checked on M15/M5 using closed candle when enabled",clrSilver);
   }

   int panelH = 22 + (n * InpLineHeight) + 16;
   ObjRect("BG", InpPanelX, InpPanelY, InpPanelWidth, panelH, clrBlack, clrDimGray);

   for(int i=0; i<n; i++)
      ObjText("L"+IntegerToString(i), lines[i], InpPanelX+12, InpPanelY+10+(i*InpLineHeight), colors[i], (i==0?InpFontSize+2:InpFontSize), InpFontName);

   if(action != g_last_action)
   {
      MqlRates r[];
      GetRates(PERIOD_M1, 2, r);
      datetime nowBar = (ArraySize(r)>0 ? r[0].time : TimeCurrent());
      if(g_last_action != "" && g_last_alert_bar != nowBar)
      {
         string msg = StringFormat("TradingAgent %s | %s | %s", g_symbol, action, reason);
         if(InpEnableAlerts) Alert(msg);
         if(InpEnablePush)   SendNotification(msg);
         g_last_alert_bar = nowBar;
      }
      g_last_action = action;
   }

   ChartRedraw();
}
