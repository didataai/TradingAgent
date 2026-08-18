#property strict
#property version   "1.00"
#property description "Book5 Micro Flow Shadow01 - research display only"
#property description "Historical development probability; no BUY/SELL, no orders, no runtime promotion."

// ============================================================================
// Book5_MicroFlowShadow01.mq5
// ----------------------------------------------------------------------------
// Live Map01R-style FlowMark PASS state + frozen SHADOW01 development model.
//
// Continuation = historical-development estimate of:
//   hit +200 points in PASS direction before next retest (within frozen 60s horizon).
//
// IMPORTANT:
//   - NOT formally validated.
//   - NOT a generic up/down probability.
//   - Confidence is a relative historical percentile bucket inside the PASS group.
//   - BIAS is the current FlowMark PASS direction, not an order instruction.
//   - This EA never sends orders.
// ============================================================================

input group "Live reconstruction"
input int   InpRefreshMs          = 100;
input int   InpSeedHistoryMs      = 120000;  // includes 30s baseline warm-up
input int   InpMaxBufferedTicks   = 150000;
input int   InpPredictionMaxAgeMs = 60000;

input group "Panel"
input bool             InpShowPanel        = true;
input ENUM_BASE_CORNER InpPanelCorner      = CORNER_RIGHT_UPPER;
input int              InpPanelX           = 12;
input int              InpPanelY           = 42;
input int              InpPanelWidth       = 270;
input int              InpPanelFontSize    = 10;
input color            InpPanelBgColor     = clrWhite;
input color            InpPanelTextColor   = clrBlack;
input color            InpPanelBorderColor = clrSilver;
input color            InpUpColor          = clrSeaGreen;
input color            InpDownColor        = clrTomato;
input color            InpFlatColor        = clrDimGray;

input group "PASS marker"
input bool InpDrawPassMarker = true;
input int  InpMarkerBars     = 2;
input int  InpMarkerWidth    = 2;

#define PREFIX "BOOK5_MFLOW01_"
#define EPS_FLOW 1.0e-12
#define BASELINE_SECONDS 30
#define SEC_HISTORY 96
#define PANEL_ROWS 10
#define MAX_TRACKED_MARKS 256
#define TARGET_POINTS 200.0

long   g_ms[];
double g_bid[];
double g_ask[];
double g_mid[];
int    g_count = 0;
int    g_capacity = 0;
double g_point = 0.0;

// ----------------------------------------------------------------------------
// Per-second spread baseline state
// ----------------------------------------------------------------------------
long   g_current_sec = -1;
double g_current_baseline = 0.0;
bool   g_current_baseline_valid = false;
double g_sec_spreads[];
int    g_sec_count = 0;
int    g_sec_capacity = 0;

long   g_hist_sec[SEC_HISTORY];
double g_hist_median[SEC_HISTORY];
bool   g_hist_valid[SEC_HISTORY];
int    g_hist_count = 0;

bool   g_have_prev_spread = false;
double g_prev_spread = 0.0;

// ----------------------------------------------------------------------------
// Episode / FlowMark state
// ----------------------------------------------------------------------------
struct EpisodeWork
{
   bool   open;
   long   birth_ms;
   long   last_qual_sec;
   double birth_mid;
   int    direction;
   double peak_bid;
   double peak_ask;
   double peak_spread;
   long   peak_ms;
};

enum MarkState
{
   MARK_WAIT_DEPARTURE = 0,
   MARK_PASS           = 1,
   MARK_RETEST         = 2,
   MARK_FAILED         = 3
};

struct FlowMark
{
   long      id;
   int       direction;
   double    low;
   double    high;
   long      activation_ms;
   MarkState state;
   int       pass_no;
   long      last_pass_ms;
   double    last_pass_mid;
   bool      terminal;
};

struct MicroFlowEvent
{
   bool   active;
   long   mark_id;
   long   pass_ms;
   double pass_mid;
   int    direction;
   int    pass_no;
   double raw_net_points;
   double signed_x_points;
   double total_path_points;
   double counterflow_points;
   double continuation_probability;
   string confidence;
};

EpisodeWork  g_episode;
FlowMark     g_marks[];
long         g_next_mark_id = 1;
MicroFlowEvent g_latest;

// ----------------------------------------------------------------------------
// UI helpers
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
   return "--";
}

string BiasArrow(const int direction)
{
   if(direction > 0) return "↑";
   if(direction < 0) return "↓";
   return "-";
}

string Signed1(const double value)
{
   if(!MathIsValidNumber(value)) return "n/a";
   string s = DoubleToString(value, 1);
   if(value > 0.0) s = "+" + s;
   return s;
}

string PctProb(const double p)
{
   if(!MathIsValidNumber(p) || p < 0.0 || p > 1.0) return "n/a";
   return DoubleToString(100.0 * p, 1) + "%";
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
   return InpPanelFontSize + 8;
}

int PanelHeight()
{
   return 14 + PANEL_ROWS * PanelRowHeight();
}

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
   int y = InpPanelY + 8 + row * PanelRowHeight();

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

void DrawPassMarker()
{
   string name = Obj("PASS_MARKER");

   if(!InpDrawPassMarker || !g_latest.active)
   {
      ObjectDelete(0, name);
      return;
   }

   long age_ms = 0;
   if(g_count > 0)
      age_ms = g_ms[g_count - 1] - g_latest.pass_ms;

   if(age_ms < 0 || age_ms > (long)InpPredictionMaxAgeMs)
   {
      ObjectDelete(0, name);
      return;
   }

   datetime t1 = (datetime)(g_latest.pass_ms / 1000);
   int sec = PeriodSeconds(_Period);
   if(sec <= 0) sec = 60;
   datetime t2 = t1 + (datetime)(sec * MathMax(1, InpMarkerBars));

   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, g_latest.pass_mid, t2, g_latest.pass_mid);
   else
   {
      ObjectMove(0, name, 0, t1, g_latest.pass_mid);
      ObjectMove(0, name, 1, t2, g_latest.pass_mid);
   }

   ObjectSetInteger(0, name, OBJPROP_RAY_LEFT, false);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_COLOR, DirectionColor(g_latest.direction));
   ObjectSetInteger(0, name, OBJPROP_WIDTH, MathMax(1, InpMarkerWidth));
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

// ----------------------------------------------------------------------------
// Generic numeric helpers
// ----------------------------------------------------------------------------
double MedianArray(double &src[], const int n)
{
   if(n <= 0) return 0.0;

   double tmp[];
   ArrayResize(tmp, n);
   for(int i = 0; i < n; ++i)
      tmp[i] = src[i];

   ArraySort(tmp);
   if((n % 2) == 1)
      return tmp[n / 2];

   return 0.5 * (tmp[n / 2 - 1] + tmp[n / 2]);
}

double AsinhSafe(const double x)
{
   return MathLog(x + MathSqrt(x * x + 1.0));
}

double Logistic(const double eta)
{
   double z = MathMax(-30.0, MathMin(30.0, eta));
   return 1.0 / (1.0 + MathExp(-z));
}

// ----------------------------------------------------------------------------
// Frozen SHADOW01 model
// ----------------------------------------------------------------------------
double ShadowProbability(const int pass_no, const double x, const double counterflow)
{
   double intercept = 0.0;
   double bx = 0.0;
   double bc = 0.0;

   if(pass_no <= 1)
   {
      intercept = -3.9428766403356286;
      bx        =  0.41954426272480366;
      bc        =  0.16817135923298430;
   }
   else if(pass_no == 2)
   {
      intercept = -4.3910705931584700;
      bx        =  0.28449971217439424;
      bc        =  0.26039027817580020;
   }
   else
   {
      intercept = -4.8730026409947770;
      bx        =  0.47301521137832470;
      bc        =  0.37804446547486326;
   }

   double tx = AsinhSafe(x / 20.0);
   double tc = MathLog(1.0 + MathMax(0.0, counterflow));
   return Logistic(intercept + bx * tx + bc * tc);
}

string ShadowConfidence(const int pass_no, const double p)
{
   double med_cut = 0.0;
   double high_cut = 0.0;

   if(pass_no <= 1)
   {
      med_cut  = 0.04202876;
      high_cut = 0.06016286;
   }
   else if(pass_no == 2)
   {
      med_cut  = 0.02636092;
      high_cut = 0.03833246;
   }
   else
   {
      med_cut  = 0.02074484;
      high_cut = 0.03190625;
   }

   if(p >= high_cut) return "HIGH";
   if(p >= med_cut)  return "MEDIUM";
   return "LOW";
}

// ----------------------------------------------------------------------------
// Tick buffer
// ----------------------------------------------------------------------------
void ResetLatest()
{
   g_latest.active = false;
   g_latest.mark_id = -1;
   g_latest.pass_ms = 0;
   g_latest.pass_mid = 0.0;
   g_latest.direction = 0;
   g_latest.pass_no = 0;
   g_latest.raw_net_points = 0.0;
   g_latest.signed_x_points = 0.0;
   g_latest.total_path_points = 0.0;
   g_latest.counterflow_points = 0.0;
   g_latest.continuation_probability = 0.0;
   g_latest.confidence = "LOW";
}

void ResetFlowState()
{
   g_current_sec = -1;
   g_current_baseline = 0.0;
   g_current_baseline_valid = false;
   g_sec_count = 0;
   g_hist_count = 0;
   g_have_prev_spread = false;
   g_prev_spread = 0.0;

   g_episode.open = false;
   g_episode.birth_ms = 0;
   g_episode.last_qual_sec = 0;
   g_episode.birth_mid = 0.0;
   g_episode.direction = 0;
   g_episode.peak_bid = 0.0;
   g_episode.peak_ask = 0.0;
   g_episode.peak_spread = 0.0;
   g_episode.peak_ms = 0;

   ArrayResize(g_marks, 0);
   g_next_mark_id = 1;
   ResetLatest();
}

void CompactTickBuffer()
{
   if(g_count < g_capacity) return;

   int keep = g_capacity / 2;
   if(keep < 5000) keep = MathMin(g_capacity, 5000);
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

int RefIndexAtOrBefore(const long target_ms)
{
   for(int i = g_count - 1; i >= 0; --i)
      if(g_ms[i] <= target_ms)
         return i;
   return -1;
}

bool PathAtCurrentTick(
   const int direction,
   double &raw_net,
   double &signed_x,
   double &total_path,
   double &counterflow
)
{
   if(g_count < 2 || g_point <= 0.0)
      return false;

   int last = g_count - 1;
   long target_ms = g_ms[last] - 1000;
   int ref = RefIndexAtOrBefore(target_ms);
   if(ref < 0 || ref >= last)
      return false;

   raw_net = (g_mid[last] - g_mid[ref]) / g_point;
   signed_x = direction * raw_net;
   total_path = 0.0;

   for(int i = ref + 1; i <= last; ++i)
      total_path += MathAbs((g_mid[i] - g_mid[i - 1]) / g_point);

   counterflow = (total_path - signed_x) / 2.0;
   if(counterflow < 0.0)
      counterflow = 0.0;

   return true;
}

// ----------------------------------------------------------------------------
// 30 completed-second spread baseline
// ----------------------------------------------------------------------------
void EnsureSecCapacity()
{
   if(g_sec_capacity <= 0)
   {
      g_sec_capacity = 4096;
      ArrayResize(g_sec_spreads, g_sec_capacity);
      return;
   }

   if(g_sec_count < g_sec_capacity)
      return;

   g_sec_capacity *= 2;
   ArrayResize(g_sec_spreads, g_sec_capacity);
}

void AppendCurrentSpread(const double spread)
{
   EnsureSecCapacity();
   g_sec_spreads[g_sec_count++] = spread;
}

void AppendSecHistory(const long sec, const double median, const bool valid)
{
   if(g_hist_count < SEC_HISTORY)
   {
      g_hist_sec[g_hist_count] = sec;
      g_hist_median[g_hist_count] = median;
      g_hist_valid[g_hist_count] = valid;
      ++g_hist_count;
      return;
   }

   for(int i = 1; i < SEC_HISTORY; ++i)
   {
      g_hist_sec[i - 1] = g_hist_sec[i];
      g_hist_median[i - 1] = g_hist_median[i];
      g_hist_valid[i - 1] = g_hist_valid[i];
   }

   g_hist_sec[SEC_HISTORY - 1] = sec;
   g_hist_median[SEC_HISTORY - 1] = median;
   g_hist_valid[SEC_HISTORY - 1] = valid;
}

void FinalizeCurrentSecond()
{
   if(g_current_sec < 0)
      return;

   if(g_sec_count > 0)
   {
      double med = MedianArray(g_sec_spreads, g_sec_count);
      AppendSecHistory(g_current_sec, med, true);
   }
   else
   {
      AppendSecHistory(g_current_sec, 0.0, false);
   }
}

bool ComputeBaselineForSecond(const long sec, double &out)
{
   if(g_hist_count < BASELINE_SECONDS)
      return false;

   int start = g_hist_count - BASELINE_SECONDS;
   double vals[];
   ArrayResize(vals, BASELINE_SECONDS);

   for(int i = 0; i < BASELINE_SECONDS; ++i)
   {
      int idx = start + i;
      long expected_sec = sec - BASELINE_SECONDS + i;

      if(g_hist_sec[idx] != expected_sec || !g_hist_valid[idx])
         return false;

      vals[i] = g_hist_median[idx];
   }

   ArraySort(vals);
   if((BASELINE_SECONDS % 2) == 1)
      out = vals[BASELINE_SECONDS / 2];
   else
      out = 0.5 * (
         vals[BASELINE_SECONDS / 2 - 1] +
         vals[BASELINE_SECONDS / 2]
      );

   return (MathIsValidNumber(out) && out > 0.0);
}

void AdvanceSecond(const long new_sec)
{
   if(g_current_sec < 0)
   {
      g_current_sec = new_sec;
      g_sec_count = 0;
      g_current_baseline_valid = ComputeBaselineForSecond(new_sec, g_current_baseline);
      return;
   }

   if(new_sec == g_current_sec)
      return;

   if(new_sec < g_current_sec)
      return;

   long old_sec = g_current_sec;
   FinalizeCurrentSecond();

   for(long s = old_sec + 1; s < new_sec; ++s)
      AppendSecHistory(s, 0.0, false);

   g_current_sec = new_sec;
   g_sec_count = 0;
   g_current_baseline_valid = ComputeBaselineForSecond(new_sec, g_current_baseline);
}

// ----------------------------------------------------------------------------
// FlowMark episode + lifecycle
// ----------------------------------------------------------------------------
void StartEpisode(const MqlTick &tick, const double spread)
{
   int last = g_count - 1;
   long birth_ms = tick.time_msc;
   int ref = RefIndexAtOrBefore(birth_ms - 1000);

   int direction = 0;
   if(ref >= 0 && ref < last)
   {
      double delta = g_mid[last] - g_mid[ref];
      if(delta > EPS_FLOW) direction = +1;
      else if(delta < -EPS_FLOW) direction = -1;
   }

   g_episode.open = true;
   g_episode.birth_ms = birth_ms;
   g_episode.last_qual_sec = birth_ms / 1000;
   g_episode.birth_mid = g_mid[last];
   g_episode.direction = direction;
   g_episode.peak_bid = tick.bid;
   g_episode.peak_ask = tick.ask;
   g_episode.peak_spread = spread;
   g_episode.peak_ms = birth_ms;
}

void ExtendEpisode(const MqlTick &tick, const double spread)
{
   g_episode.last_qual_sec = tick.time_msc / 1000;

   if(spread > g_episode.peak_spread + EPS_FLOW)
   {
      g_episode.peak_spread = spread;
      g_episode.peak_bid = tick.bid;
      g_episode.peak_ask = tick.ask;
      g_episode.peak_ms = tick.time_msc;
   }
}

void CompactMarks()
{
   int n = ArraySize(g_marks);
   if(n <= MAX_TRACKED_MARKS)
      return;

   FlowMark tmp[];
   int kept = 0;

   for(int i = 0; i < n; ++i)
   {
      if(!g_marks[i].terminal)
      {
         ArrayResize(tmp, kept + 1);
         tmp[kept++] = g_marks[i];
      }
   }

   if(kept > MAX_TRACKED_MARKS)
   {
      int start = kept - MAX_TRACKED_MARKS;
      FlowMark tail[];
      ArrayResize(tail, MAX_TRACKED_MARKS);
      for(int i = 0; i < MAX_TRACKED_MARKS; ++i)
         tail[i] = tmp[start + i];

      ArrayResize(g_marks, MAX_TRACKED_MARKS);
      for(int i = 0; i < MAX_TRACKED_MARKS; ++i)
         g_marks[i] = tail[i];
   }
   else
   {
      ArrayResize(g_marks, kept);
      for(int i = 0; i < kept; ++i)
         g_marks[i] = tmp[i];
   }
}

void AddMarkFromEpisode(const long activation_ms)
{
   if(g_episode.direction == 0)
      return;

   FlowMark m;
   m.id = g_next_mark_id++;
   m.direction = g_episode.direction;
   m.low = g_episode.peak_bid;
   m.high = g_episode.peak_ask;
   m.activation_ms = activation_ms;
   m.state = MARK_WAIT_DEPARTURE;
   m.pass_no = 0;
   m.last_pass_ms = 0;
   m.last_pass_mid = 0.0;
   m.terminal = false;

   int n = ArraySize(g_marks);
   ArrayResize(g_marks, n + 1);
   g_marks[n] = m;

   CompactMarks();
}

void MaybeCloseEpisode(const long now_ms)
{
   if(!g_episode.open)
      return;

   long close_ms = (g_episode.last_qual_sec + 2) * 1000 - 1;
   if(now_ms <= close_ms)
      return;

   AddMarkFromEpisode(now_ms);
   g_episode.open = false;
}

void PublishPass(const int mark_index, const MqlTick &tick)
{
   if(mark_index < 0 || mark_index >= ArraySize(g_marks))
      return;

   double raw_net = 0.0;
   double x = 0.0;
   double total = 0.0;
   double counterflow = 0.0;

   if(!PathAtCurrentTick(
      g_marks[mark_index].direction,
      raw_net,
      x,
      total,
      counterflow
   ))
      return;

   int pno = g_marks[mark_index].pass_no;
   double prob = ShadowProbability(pno, x, counterflow);

   g_latest.active = true;
   g_latest.mark_id = g_marks[mark_index].id;
   g_latest.pass_ms = tick.time_msc;
   g_latest.pass_mid = (tick.bid + tick.ask) / 2.0;
   g_latest.direction = g_marks[mark_index].direction;
   g_latest.pass_no = pno;
   g_latest.raw_net_points = raw_net;
   g_latest.signed_x_points = x;
   g_latest.total_path_points = total;
   g_latest.counterflow_points = counterflow;
   g_latest.continuation_probability = prob;
   g_latest.confidence = ShadowConfidence(pno, prob);
}

void StartPass(const int mark_index, const MqlTick &tick)
{
   g_marks[mark_index].pass_no += 1;
   g_marks[mark_index].state = MARK_PASS;
   g_marks[mark_index].last_pass_ms = tick.time_msc;
   g_marks[mark_index].last_pass_mid = (tick.bid + tick.ask) / 2.0;

   PublishPass(mark_index, tick);
}

void ExpireLatestIfMark(const long mark_id)
{
   if(g_latest.active && g_latest.mark_id == mark_id)
      g_latest.active = false;
}

void CheckLatestResolution(const FlowMark &mark, const MqlTick &tick)
{
   if(!g_latest.active || g_latest.mark_id != mark.id)
      return;

   long age_ms = tick.time_msc - g_latest.pass_ms;
   if(age_ms < 0 || age_ms > (long)InpPredictionMaxAgeMs)
   {
      g_latest.active = false;
      return;
   }

   double mid = (tick.bid + tick.ask) / 2.0;
   double progress = mark.direction * (mid - g_latest.pass_mid) / g_point;
   if(progress >= TARGET_POINTS)
      g_latest.active = false;
}

void ProcessMarks(const MqlTick &tick)
{
   int n = ArraySize(g_marks);

   for(int i = 0; i < n; ++i)
   {
      if(g_marks[i].terminal)
         continue;

      if(tick.time_msc < g_marks[i].activation_ms)
         continue;

      CheckLatestResolution(g_marks[i], tick);

      int dir = g_marks[i].direction;
      double low = g_marks[i].low;
      double high = g_marks[i].high;

      if(g_marks[i].state == MARK_WAIT_DEPARTURE)
      {
         bool depart = (dir > 0 ? tick.bid > high : tick.ask < low);
         if(depart)
            StartPass(i, tick);
         continue;
      }

      if(g_marks[i].state == MARK_PASS)
      {
         bool retest = (dir > 0 ? tick.bid <= high : tick.ask >= low);
         if(!retest)
            continue;

         ExpireLatestIfMark(g_marks[i].id);

         bool failed_now = (dir > 0 ? tick.ask < low : tick.bid > high);
         if(failed_now)
         {
            g_marks[i].state = MARK_FAILED;
            g_marks[i].terminal = true;
         }
         else
         {
            g_marks[i].state = MARK_RETEST;
         }
         continue;
      }

      if(g_marks[i].state == MARK_RETEST)
      {
         bool failure = (dir > 0 ? tick.ask < low : tick.bid > high);
         if(failure)
         {
            ExpireLatestIfMark(g_marks[i].id);
            g_marks[i].state = MARK_FAILED;
            g_marks[i].terminal = true;
            continue;
         }

         bool recross = (dir > 0 ? tick.bid > high : tick.ask < low);
         if(recross)
            StartPass(i, tick);
      }
   }
}

void ProcessFlowTick(const MqlTick &tick)
{
   if(g_count <= 0)
      return;

   long sec = tick.time_msc / 1000;
   AdvanceSecond(sec);

   double spread = tick.ask - tick.bid;

   // Close previous episode before this tick can start/extend a new one.
   MaybeCloseEpisode(tick.time_msc);

   // Newly activated marks are eligible on this same first post-close tick.
   ProcessMarks(tick);

   bool widening = (
      g_have_prev_spread &&
      spread > g_prev_spread + EPS_FLOW
   );

   bool expanded = (
      g_current_baseline_valid &&
      spread > g_current_baseline + EPS_FLOW
   );

   bool qualify = expanded && widening;

   if(qualify)
   {
      long qsec = tick.time_msc / 1000;

      if(!g_episode.open)
      {
         StartEpisode(tick, spread);
      }
      else if(qsec - g_episode.last_qual_sec <= 1)
      {
         ExtendEpisode(tick, spread);
      }
      else
      {
         // Defensive fallback; normal closure occurs in MaybeCloseEpisode above.
         g_episode.open = false;
         StartEpisode(tick, spread);
      }
   }

   AppendCurrentSpread(spread);
   g_prev_spread = spread;
   g_have_prev_spread = true;
}

void AppendTickRaw(const MqlTick &tick)
{
   if(tick.bid <= 0.0 || tick.ask <= 0.0 || tick.time_msc <= 0)
      return;

   CompactTickBuffer();
   if(g_count >= g_capacity)
      return;

   g_ms[g_count] = tick.time_msc;
   g_bid[g_count] = tick.bid;
   g_ask[g_count] = tick.ask;
   g_mid[g_count] = (tick.bid + tick.ask) / 2.0;
   ++g_count;

   ProcessFlowTick(tick);
}

void SeedHistory()
{
   MqlTick now_tick;
   if(!SymbolInfoTick(_Symbol, now_tick))
      return;

   long from_ms = now_tick.time_msc - (long)MathMax(InpSeedHistoryMs, 45000);
   if(from_ms < 0) from_ms = 0;

   MqlTick ticks[];
   int copied = CopyTicksRange(
      _Symbol,
      ticks,
      COPY_TICKS_ALL,
      (ulong)from_ms,
      (ulong)now_tick.time_msc
   );

   if(copied <= 0)
      return;

   for(int i = 0; i < copied; ++i)
      AppendTickRaw(ticks[i]);
}

int TailCountAtMs(const long ms)
{
   int count = 0;
   for(int i = g_count - 1; i >= 0; --i)
   {
      if(g_ms[i] != ms)
         break;
      ++count;
   }
   return count;
}

void SyncTicks()
{
   MqlTick now_tick;
   if(!SymbolInfoTick(_Symbol, now_tick))
      return;

   if(g_count <= 0)
   {
      SeedHistory();
      return;
   }

   long last_ms = g_ms[g_count - 1];
   if(now_tick.time_msc < last_ms)
      return;

   int already_same_ms = TailCountAtMs(last_ms);

   MqlTick ticks[];
   int copied = CopyTicksRange(
      _Symbol,
      ticks,
      COPY_TICKS_ALL,
      (ulong)last_ms,
      (ulong)now_tick.time_msc
   );

   if(copied <= 0)
      return;

   int skipped_same = 0;

   for(int i = 0; i < copied; ++i)
   {
      if(ticks[i].time_msc < last_ms)
         continue;

      if(ticks[i].time_msc == last_ms && skipped_same < already_same_ms)
      {
         ++skipped_same;
         continue;
      }

      AppendTickRaw(ticks[i]);
   }
}

// ----------------------------------------------------------------------------
// Panel
// ----------------------------------------------------------------------------
bool LatestUsable()
{
   if(!g_latest.active || g_count <= 0)
      return false;

   long age_ms = g_ms[g_count - 1] - g_latest.pass_ms;
   if(age_ms < 0 || age_ms > (long)InpPredictionMaxAgeMs)
   {
      g_latest.active = false;
      return false;
   }

   return true;
}

void RefreshPanel()
{
   if(!InpShowPanel)
   {
      ClearRows();
      ObjectDelete(0, Obj("BG"));
      ObjectDelete(0, Obj("PASS_MARKER"));
      return;
   }

   EnsureBackground();

   if(!LatestUsable())
   {
      SetRow(0, "MICRO FLOW [SHADOW]", InpPanelTextColor);
      SetRow(1, "Direction       --", InpFlatColor);
      SetRow(2, "Continuation    --", InpFlatColor);
      SetRow(3, "Confidence      --", InpFlatColor);
      SetRow(4, "", InpPanelTextColor);
      SetRow(5, "NET             --", InpFlatColor);
      SetRow(6, "COUNTERFLOW     --", InpFlatColor);
      SetRow(7, "PASS            --", InpFlatColor);
      SetRow(8, "BIAS            -", InpFlatColor);
      SetRow(9, "WAITING FLOWMARK PASS", InpFlatColor);
      DrawPassMarker();
      ChartRedraw(0);
      return;
   }

   color dclr = DirectionColor(g_latest.direction);

   SetRow(0, "MICRO FLOW [SHADOW]", InpPanelTextColor);
   SetRow(1, "Direction       " + DirectionText(g_latest.direction), dclr);
   SetRow(2, "Continuation    " + PctProb(g_latest.continuation_probability), InpPanelTextColor);
   SetRow(3, "Confidence      " + g_latest.confidence, InpPanelTextColor);
   SetRow(4, "", InpPanelTextColor);
   SetRow(5, "NET             " + Signed1(g_latest.raw_net_points), dclr);
   SetRow(6, "COUNTERFLOW     " + DoubleToString(g_latest.counterflow_points, 1), InpPanelTextColor);
   SetRow(7, "PASS            " + IntegerToString(g_latest.pass_no), InpPanelTextColor);
   SetRow(8, "BIAS            " + BiasArrow(g_latest.direction), dclr);
   SetRow(9, "SHADOW +200 / NOT VALIDATED", InpFlatColor);

   DrawPassMarker();
   ChartRedraw(0);
}

// ----------------------------------------------------------------------------
// EA lifecycle
// ----------------------------------------------------------------------------
int OnInit()
{
   if(InpRefreshMs < 50)
   {
      Print("Micro Flow Shadow01: InpRefreshMs must be >= 50");
      return INIT_PARAMETERS_INCORRECT;
   }

   g_point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(g_point <= 0.0)
   {
      Print("Micro Flow Shadow01: invalid symbol point");
      return INIT_FAILED;
   }

   g_capacity = MathMax(10000, InpMaxBufferedTicks);
   ArrayResize(g_ms,  g_capacity);
   ArrayResize(g_bid, g_capacity);
   ArrayResize(g_ask, g_capacity);
   ArrayResize(g_mid, g_capacity);
   g_count = 0;

   g_sec_capacity = 4096;
   ArrayResize(g_sec_spreads, g_sec_capacity);

   ResetFlowState();
   SeedHistory();

   EventSetMillisecondTimer(MathMax(50, InpRefreshMs));
   RefreshPanel();

   Print(
      "Book5 Micro Flow Shadow01 initialized: HISTORICAL DEVELOPMENT MODEL; ",
      "target=+200 before retest; NO BUY/SELL; NO RUNTIME PROMOTION."
   );

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
