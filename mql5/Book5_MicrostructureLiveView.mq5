#property strict
#property version   "1.02"
#property description "Book5 Microstructure Live View - observational only"
#property description "No orders, no entry thresholds, no runtime promotion."

// ============================================================================
// Book5_MicrostructureLiveView.mq5
// ----------------------------------------------------------------------------
// Visual microscope for Map02/Map03/Map04 quote-path quantities.
// OBSERVATIONAL ONLY: no orders, no BUY/SELL classifier, no entry threshold.
//
// LIVE WINDOW
//   MID        = (BID + ASK) / 2
//   NET        = abs(MID_now - MID_reference)
//   TOTAL      = sum(abs(delta MID))
//   SUPPORT    = (TOTAL + NET) / 2
//   OPPOSING   = (TOTAL - NET) / 2
//   EFFICIENCY = NET / TOTAL
//
// Direction on screen is only the sign of current net MID migration.
// It is NOT the frozen PASS direction used by the research scorers.
//
// MT5 may coalesce OnTick callbacks. The observer therefore reconstructs the
// tick sequence with CopyTicksRange instead of assuming one OnTick == one tick.
// ============================================================================

input group "Live window"
input int   InpWindowMs             = 1000;
input int   InpRefreshMs            = 100;
input int   InpMaxBufferedTicks     = 50000;
input int   InpSeedHistoryMs        = 6000;

input group "Compact panel"
input bool             InpShowPanel        = true;
input ENUM_BASE_CORNER InpPanelCorner      = CORNER_RIGHT_UPPER;
input int              InpPanelX           = 12;
input int              InpPanelY           = 42;
input int              InpPanelWidth       = 272;
input int              InpPanelFontSize    = 9;
input color            InpPanelBgColor     = clrWhite;
input color            InpPanelTextColor   = clrBlack;
input color            InpPanelBorderColor = clrSilver;
input color            InpUpColor          = clrSeaGreen;
input color            InpDownColor        = clrTomato;
input color            InpFlatColor        = clrDimGray;
input color            InpSupportColor     = clrDodgerBlue;
input color            InpOpposingColor    = clrDarkOrange;

input group "Current MID marker"
input bool  InpDrawCurrentMarker = true;
input int   InpMarkerBars        = 2;
input int   InpMarkerWidth       = 2;

#define PREFIX "BOOK5_MSLIVE_"
#define EPS_MSLIVE 1.0e-12
#define PANEL_ROWS 10

long   g_ms[];
double g_bid[];
double g_ask[];
double g_mid[];
int    g_count = 0;
int    g_capacity = 0;

struct MicroSnapshot
{
   bool   ready;
   long   now_ms;
   double bid;
   double ask;
   double mid;
   double spread_points;
   double net_signed_points;
   double net_abs_points;
   double total_path_points;
   double supporting_path_points;
   double opposing_path_points;
   double efficiency;
   double directional_update_fraction;
   double both_quote_change_fraction;
   int    ticks_in_window;
   int    direction;
};

// ----------------------------------------------------------------------------
// Utility
// ----------------------------------------------------------------------------
string Obj(const string suffix)
{
   return PREFIX + suffix;
}

color DirectionColor(const int direction)
{
   if(direction > 0) return InpUpColor;
   if(direction < 0) return InpDownColor;
   return InpFlatColor;
}

string DirectionText(const int direction)
{
   if(direction > 0) return "UP";
   if(direction < 0) return "DOWN";
   return "FLAT";
}

string Signed1(const double value)
{
   if(!MathIsValidNumber(value)) return "n/a";
   string s = DoubleToString(value, 1);
   if(value > 0.0) s = "+" + s;
   return s;
}

string Pct1(const double value)
{
   if(!MathIsValidNumber(value) || value < 0.0 || value > 1.0000001)
      return "n/a";
   return DoubleToString(100.0 * value, 1) + "%";
}

string Path1(const double value)
{
   if(!MathIsValidNumber(value)) return "n/a";
   return DoubleToString(value, 1);
}

string ForceBar(const double value, const double max_value, const int width = 14)
{
   int fill = 0;
   if(max_value > EPS_MSLIVE)
      fill = (int)MathRound((double)width * value / max_value);
   fill = MathMax(0, MathMin(width, fill));

   string out = "";
   for(int i = 0; i < width; ++i)
   {
      if(i < fill) out += "#";
      else         out += "-";
   }
   return out;
}

ENUM_ANCHOR_POINT PanelAnchor()
{
   if(InpPanelCorner == CORNER_RIGHT_UPPER) return ANCHOR_RIGHT_UPPER;
   if(InpPanelCorner == CORNER_RIGHT_LOWER) return ANCHOR_RIGHT_LOWER;
   if(InpPanelCorner == CORNER_LEFT_LOWER)  return ANCHOR_LEFT_LOWER;
   return ANCHOR_LEFT_UPPER;
}

int PanelRowHeight()
{
   return InpPanelFontSize + 7;
}

int PanelHeight()
{
   return 12 + PANEL_ROWS * PanelRowHeight();
}

// ----------------------------------------------------------------------------
// Tick buffer
// ----------------------------------------------------------------------------
void CompactBuffer()
{
   if(g_count < g_capacity) return;

   int keep = g_capacity / 2;
   if(keep < 1000) keep = MathMin(g_capacity, 1000);
   int first = g_count - keep;

   for(int i = 0; i < keep; ++i)
   {
      int src = first + i;
      g_ms[i]  = g_ms[src];
      g_bid[i] = g_bid[src];
      g_ask[i] = g_ask[src];
      g_mid[i] = g_mid[src];
   }
   g_count = keep;
}

bool SameQuote(const long ms, const double bid, const double ask, const MqlTick &tick)
{
   return (
      ms == tick.time_msc &&
      MathAbs(bid - tick.bid) <= EPS_MSLIVE &&
      MathAbs(ask - tick.ask) <= EPS_MSLIVE
   );
}

void AppendTick(const MqlTick &tick)
{
   if(tick.bid <= 0.0 || tick.ask <= 0.0 || tick.time_msc <= 0)
      return;

   if(g_count > 0)
   {
      int last = g_count - 1;
      if(SameQuote(g_ms[last], g_bid[last], g_ask[last], tick))
         return;
   }

   CompactBuffer();
   if(g_count >= g_capacity) return;

   g_ms[g_count]  = tick.time_msc;
   g_bid[g_count] = tick.bid;
   g_ask[g_count] = tick.ask;
   g_mid[g_count] = (tick.bid + tick.ask) / 2.0;
   ++g_count;
}

void SeedHistory()
{
   MqlTick now_tick;
   if(!SymbolInfoTick(_Symbol, now_tick)) return;

   long from_l = now_tick.time_msc - (long)MathMax(InpSeedHistoryMs, InpWindowMs + 1000);
   if(from_l < 0) from_l = 0;

   MqlTick ticks[];
   int copied = CopyTicksRange(
      _Symbol,
      ticks,
      COPY_TICKS_ALL,
      (ulong)from_l,
      (ulong)now_tick.time_msc
   );

   if(copied <= 0) return;
   for(int i = 0; i < copied; ++i)
      AppendTick(ticks[i]);
}

void SyncTicks()
{
   MqlTick now_tick;
   if(!SymbolInfoTick(_Symbol, now_tick)) return;

   if(g_count <= 0)
   {
      SeedHistory();
      return;
   }

   int last_idx = g_count - 1;
   long last_ms = g_ms[last_idx];
   double last_bid = g_bid[last_idx];
   double last_ask = g_ask[last_idx];

   if(now_tick.time_msc < last_ms) return;

   MqlTick ticks[];
   int copied = CopyTicksRange(
      _Symbol,
      ticks,
      COPY_TICKS_ALL,
      (ulong)last_ms,
      (ulong)now_tick.time_msc
   );
   if(copied <= 0) return;

   int start = 0;
   int last_match = -1;
   for(int i = 0; i < copied; ++i)
   {
      if(SameQuote(last_ms, last_bid, last_ask, ticks[i]))
         last_match = i;
   }

   if(last_match >= 0)
      start = last_match + 1;
   else
   {
      while(start < copied && ticks[start].time_msc <= last_ms)
         ++start;
   }

   for(int i = start; i < copied; ++i)
      AppendTick(ticks[i]);
}

int RefIndexAtOrBefore(const long target_ms)
{
   for(int i = g_count - 1; i >= 0; --i)
      if(g_ms[i] <= target_ms)
         return i;
   return -1;
}

int FirstIndexAtOrAfter(const long target_ms)
{
   for(int i = 0; i < g_count; ++i)
      if(g_ms[i] >= target_ms)
         return i;
   return -1;
}

// ----------------------------------------------------------------------------
// Measurement
// ----------------------------------------------------------------------------
MicroSnapshot Measure()
{
   MicroSnapshot s;
   s.ready = false;
   s.now_ms = 0;
   s.bid = 0.0;
   s.ask = 0.0;
   s.mid = 0.0;
   s.spread_points = 0.0;
   s.net_signed_points = 0.0;
   s.net_abs_points = 0.0;
   s.total_path_points = 0.0;
   s.supporting_path_points = 0.0;
   s.opposing_path_points = 0.0;
   s.efficiency = 0.0;
   s.directional_update_fraction = -1.0;
   s.both_quote_change_fraction = -1.0;
   s.ticks_in_window = 0;
   s.direction = 0;

   if(g_count < 2) return s;

   int last = g_count - 1;
   long target_ms = g_ms[last] - (long)InpWindowMs;
   int ref = RefIndexAtOrBefore(target_ms);
   if(ref < 0 || ref >= last) return s;

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(point <= 0.0) return s;

   double net = (g_mid[last] - g_mid[ref]) / point;
   double net_abs = MathAbs(net);
   int direction = 0;
   if(net > EPS_MSLIVE) direction = +1;
   else if(net < -EPS_MSLIVE) direction = -1;

   double total = 0.0;
   int changed_mid = 0;
   int favorable_mid = 0;
   int transitions = 0;
   int both_quotes = 0;

   for(int i = ref + 1; i <= last; ++i)
   {
      double dmid = (g_mid[i] - g_mid[i - 1]) / point;
      double dbid = g_bid[i] - g_bid[i - 1];
      double dask = g_ask[i] - g_ask[i - 1];

      total += MathAbs(dmid);
      ++transitions;

      if(MathAbs(dmid) > EPS_MSLIVE)
      {
         ++changed_mid;
         if(direction > 0 && dmid > 0.0) ++favorable_mid;
         if(direction < 0 && dmid < 0.0) ++favorable_mid;
      }

      if(MathAbs(dbid) > EPS_MSLIVE && MathAbs(dask) > EPS_MSLIVE)
         ++both_quotes;
   }

   double support = 0.0;
   double opposing = 0.0;
   double efficiency = 0.0;
   if(total > EPS_MSLIVE)
   {
      support = (total + net_abs) / 2.0;
      opposing = (total - net_abs) / 2.0;
      if(opposing < 0.0 && opposing > -1.0e-8) opposing = 0.0;
      efficiency = net_abs / total;
   }

   double directional_fraction = -1.0;
   if(direction != 0 && changed_mid > 0)
      directional_fraction = (double)favorable_mid / (double)changed_mid;

   double both_fraction = -1.0;
   if(transitions > 0)
      both_fraction = (double)both_quotes / (double)transitions;

   int first_window = FirstIndexAtOrAfter(target_ms);
   int ticks_window = (first_window >= 0 ? last - first_window + 1 : 0);

   s.ready = true;
   s.now_ms = g_ms[last];
   s.bid = g_bid[last];
   s.ask = g_ask[last];
   s.mid = g_mid[last];
   s.spread_points = (g_ask[last] - g_bid[last]) / point;
   s.net_signed_points = net;
   s.net_abs_points = net_abs;
   s.total_path_points = total;
   s.supporting_path_points = support;
   s.opposing_path_points = opposing;
   s.efficiency = efficiency;
   s.directional_update_fraction = directional_fraction;
   s.both_quote_change_fraction = both_fraction;
   s.ticks_in_window = ticks_window;
   s.direction = direction;
   return s;
}

// ----------------------------------------------------------------------------
// Compact chart UI
// ----------------------------------------------------------------------------
void EnsureBackground()
{
   string name = Obj("BG");
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);

   ObjectSetInteger(0, name, OBJPROP_CORNER, InpPanelCorner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, InpPanelX);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, InpPanelY);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, InpPanelWidth);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, PanelHeight());
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, InpPanelBgColor);
   ObjectSetInteger(0, name, OBJPROP_COLOR, InpPanelBorderColor);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 100);
}

void SetRow(const int row, const string text, const color clr)
{
   string name = Obj("ROW_" + IntegerToString(row));
   int y = InpPanelY + 7 + row * PanelRowHeight();

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);

   ObjectSetInteger(0, name, OBJPROP_CORNER, InpPanelCorner);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, PanelAnchor());
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, InpPanelX + 10);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpPanelFontSize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 101);
   ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void ClearRows()
{
   for(int r = 0; r < PANEL_ROWS; ++r)
      ObjectDelete(0, Obj("ROW_" + IntegerToString(r)));
}

void DrawMarker(const MicroSnapshot &s)
{
   string name = Obj("CURRENT_MID");
   if(!InpDrawCurrentMarker || !s.ready)
   {
      ObjectDelete(0, name);
      return;
   }

   datetime t1 = TimeCurrent();
   int sec = PeriodSeconds(_Period);
   if(sec <= 0) sec = 60;
   datetime t2 = t1 + (datetime)(sec * MathMax(1, InpMarkerBars));

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, s.mid, t2, s.mid);
   else
   {
      ObjectMove(0, name, 0, t1, s.mid);
      ObjectMove(0, name, 1, t2, s.mid);
   }

   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_COLOR, DirectionColor(s.direction));
   ObjectSetInteger(0, name, OBJPROP_WIDTH, MathMax(1, InpMarkerWidth));
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void RefreshPanel()
{
   MicroSnapshot s = Measure();

   if(!InpShowPanel)
   {
      ClearRows();
      ObjectDelete(0, Obj("BG"));
      DrawMarker(s);
      return;
   }

   EnsureBackground();

   if(!s.ready)
   {
      SetRow(0, "MICRO  " + IntegerToString(InpWindowMs) + "ms", InpPanelTextColor);
      SetRow(1, "warming tick buffer...", InpFlatColor);
      SetRow(2, "", InpPanelTextColor);
      SetRow(3, "", InpPanelTextColor);
      SetRow(4, "", InpPanelTextColor);
      SetRow(5, "", InpPanelTextColor);
      SetRow(6, "", InpPanelTextColor);
      SetRow(7, "", InpPanelTextColor);
      SetRow(8, "", InpPanelTextColor);
      SetRow(9, "NO SIGNAL / NO THRESHOLD", InpFlatColor);
      DrawMarker(s);
      ChartRedraw(0);
      return;
   }

   color dclr = DirectionColor(s.direction);
   double force_max = MathMax(s.supporting_path_points, s.opposing_path_points);
   string sup_bar = ForceBar(s.supporting_path_points, force_max, 14);
   string opp_bar = ForceBar(s.opposing_path_points, force_max, 14);

   SetRow(0,
      "MICRO " + IntegerToString(InpWindowMs) + "ms          " + DirectionText(s.direction),
      dclr
   );
   SetRow(1,
      "NET    " + Signed1(s.net_signed_points) + " pt",
      dclr
   );
   SetRow(2,
      "TOTAL  " + Path1(s.total_path_points) + " pt   EFF " + Pct1(s.efficiency),
      InpPanelTextColor
   );
   SetRow(3,
      "SUP    " + Path1(s.supporting_path_points) + " pt",
      InpSupportColor
   );
   SetRow(4,
      "       [" + sup_bar + "]",
      InpSupportColor
   );
   SetRow(5,
      "OPP    " + Path1(s.opposing_path_points) + " pt",
      InpOpposingColor
   );
   SetRow(6,
      "       [" + opp_bar + "]",
      InpOpposingColor
   );
   SetRow(7,
      "DIR " + Pct1(s.directional_update_fraction) +
      "   BID+ASK " + Pct1(s.both_quote_change_fraction),
      InpPanelTextColor
   );
   SetRow(8,
      "SPR " + Path1(s.spread_points) +
      "   TICKS " + IntegerToString(s.ticks_in_window) +
      "   MID " + DoubleToString(s.mid, _Digits),
      InpPanelTextColor
   );
   SetRow(9,
      "OBSERVATIONAL - NO THRESHOLD",
      InpFlatColor
   );

   DrawMarker(s);
   ChartRedraw(0);
}

// ----------------------------------------------------------------------------
// EA lifecycle
// ----------------------------------------------------------------------------
int OnInit()
{
   if(InpWindowMs < 100)
   {
      Print("Book5 Microstructure Live View: InpWindowMs must be >= 100");
      return INIT_PARAMETERS_INCORRECT;
   }

   g_capacity = MathMax(2000, InpMaxBufferedTicks);
   ArrayResize(g_ms,  g_capacity);
   ArrayResize(g_bid, g_capacity);
   ArrayResize(g_ask, g_capacity);
   ArrayResize(g_mid, g_capacity);
   g_count = 0;

   SeedHistory();
   EventSetMillisecondTimer(MathMax(50, InpRefreshMs));
   RefreshPanel();

   Print("Book5 Microstructure Live View v1.02 initialized: OBSERVATIONAL ONLY.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PREFIX);
   ChartRedraw(0);
}

void OnTick()
{
   SyncTicks();
}

void OnTimer()
{
   SyncTicks();
   RefreshPanel();
}
