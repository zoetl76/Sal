//+------------------------------------------------------------------+
//|                                            GridScalperBTC.mq5    |
//|  Grid scalper BTC — version Expert Advisor native MetaTrader 5.  |
//|                                                                  |
//|  Meme logique que le bot Python du depot :                       |
//|    - pas de grille adaptatif (ATR) ou fixe                       |
//|    - ordres limites de part et d'autre d'une ancre               |
//|    - take profit d'un pas sur chaque position                    |
//|    - filtres spread / session / tendance                         |
//|    - garde-fous : drawdown, perte du jour, marge, basket TP/SL   |
//|                                                                  |
//|  A tester en compte demo avant toute utilisation en reel.        |
//+------------------------------------------------------------------+
#property copyright "Grid Scalper BTC"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- Grille -------------------------------------------------------------
enum ENUM_GRID_MODE { GRID_BOTH, GRID_LONG, GRID_SHORT, GRID_TREND };
enum ENUM_STEP_MODE { STEP_ATR, STEP_FIXED };

input group "=== Grille ==="
input ENUM_GRID_MODE InpMode            = GRID_BOTH;   // Sens autorises
input int            InpLevels          = 6;           // Paliers de chaque cote
input ENUM_STEP_MODE InpStepMode        = STEP_ATR;    // Calcul du pas
input double         InpStepFixed       = 250.0;       // Pas fixe (USD)
input ENUM_TIMEFRAMES InpAtrTimeframe   = PERIOD_M15;  // Unite de temps ATR
input int            InpAtrPeriod       = 14;          // Periode ATR
input double         InpAtrMult         = 0.5;         // Pas = ATR x ce facteur
input double         InpStepMin         = 100.0;       // Pas minimum (USD)
input double         InpStepMax         = 1500.0;      // Pas maximum (USD)
input double         InpTpMult          = 1.0;         // TP = pas x ce facteur
input double         InpSlMult          = 0.0;         // SL = pas x ce facteur (0 = aucun)
input int            InpRearmCooldownS  = 30;          // Delai de re-armement (s)
input double         InpReanchorMult    = 1.5;         // Re-centrage au-dela de pas x paliers x ce facteur
input bool           InpTrailGrid       = false;       // Grille suiveuse

input group "=== Filtre de tendance ==="
input bool           InpTrendFilter     = false;       // Activer le filtre EMA
input ENUM_TIMEFRAMES InpTrendTimeframe = PERIOD_H1;   // Unite de temps
input int            InpEmaFast         = 50;          // EMA rapide
input int            InpEmaSlow         = 200;         // EMA lente

input group "=== Volume ==="
input double         InpLot             = 0.01;        // Lot par palier
input double         InpLotMax          = 0.05;        // Lot maximum
input double         InpMartingale      = 1.0;         // Facteur par palier (1.0 = desactive)

input group "=== Risque ==="
input int            InpMaxPositions    = 10;          // Positions + ordres maximum
input double         InpMaxTotalLots    = 0.20;        // Exposition brute maximale
input double         InpMaxNetLots      = 0.15;        // Exposition nette maximale
input double         InpMaxSpread       = 60.0;        // Spread maximum (USD)
input double         InpMaxDrawdownPct  = 15.0;        // Drawdown maximum (%) -> arret
input double         InpDailyLossPct    = 5.0;         // Perte du jour maximum (%)
input double         InpMinFreeMarginPct= 40.0;        // Marge libre minimale (%)
input double         InpBasketTP        = 0.0;         // Cloture globale si flottant >= (0 = off)
input double         InpBasketSL        = 0.0;         // Cloture globale si flottant <= - (0 = off)

input group "=== Session (heure serveur) ==="
input bool           InpUseSession      = false;       // Restreindre les horaires
input int            InpStartHour       = 0;           // Heure de debut
input int            InpEndHour         = 24;          // Heure de fin
input bool           InpTradeWeekend    = true;        // Trader le week-end

input group "=== Divers ==="
input long           InpMagic           = 990101;      // Numero magique
input string         InpTag             = "GS";        // Prefixe de commentaire
input int            InpSlippagePoints  = 50;          // Slippage tolere (points)
input int            InpThrottleMs      = 1000;        // Intervalle minimum entre cycles (ms)
input bool           InpVerbose         = true;        // Journalisation detaillee

//--- Etat global --------------------------------------------------------
CTrade   g_trade;
int      g_atr_handle   = INVALID_HANDLE;
int      g_ema_fast     = INVALID_HANDLE;
int      g_ema_slow     = INVALID_HANDLE;

double   g_anchor       = 0.0;
double   g_step         = 0.0;
double   g_peak_equity  = 0.0;
double   g_day_equity   = 0.0;
int      g_day          = -1;
bool     g_halted       = false;
bool     g_halt_terminal= false;
string   g_halt_reason  = "";
ulong    g_last_cycle   = 0;

// Cooldowns par palier : index 0..InpLevels-1 pour les achats, puis les ventes.
datetime g_cooldown[];
bool     g_was_occupied[];

#define SIDE_BUY  0
#define SIDE_SELL 1

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpLevels < 1 || InpStepMin <= 0 || InpStepMax < InpStepMin)
     {
      Print("Parametres de grille incoherents.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpTpMult <= 0.0 || (InpSlMult > 0.0 && InpSlMult <= InpTpMult))
     {
      Print("TP/SL incoherents : le SL doit etre plus loin que le TP.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpMartingale < 1.0)
     {
      Print("Le facteur martingale doit etre >= 1.0.");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   if(InpStepMode == STEP_ATR)
     {
      g_atr_handle = iATR(_Symbol, InpAtrTimeframe, InpAtrPeriod);
      if(g_atr_handle == INVALID_HANDLE)
        {
         Print("Impossible de creer l'indicateur ATR.");
         return(INIT_FAILED);
        }
     }
   if(InpTrendFilter || InpMode == GRID_TREND)
     {
      g_ema_fast = iMA(_Symbol, InpTrendTimeframe, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
      g_ema_slow = iMA(_Symbol, InpTrendTimeframe, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
      if(g_ema_fast == INVALID_HANDLE || g_ema_slow == INVALID_HANDLE)
        {
         Print("Impossible de creer les moyennes mobiles.");
         return(INIT_FAILED);
        }
     }

   ArrayResize(g_cooldown, InpLevels * 2);
   ArrayResize(g_was_occupied, InpLevels * 2);
   for(int i = 0; i < InpLevels * 2; i++)
     {
      g_cooldown[i]     = 0;
      g_was_occupied[i] = false;
     }

   g_step        = ClampStep(InpStepFixed);
   g_peak_equity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_day_equity  = g_peak_equity;

   PrintFormat("GridScalperBTC demarre sur %s | pas initial %.2f | magic %I64d",
               _Symbol, g_step, InpMagic);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_ema_fast   != INVALID_HANDLE) IndicatorRelease(g_ema_fast);
   if(g_ema_slow   != INVALID_HANDLE) IndicatorRelease(g_ema_slow);
   PrintFormat("GridScalperBTC arrete (raison %d).", reason);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   ulong now_ms = GetTickCount64();
   if(now_ms - g_last_cycle < (ulong)InpThrottleMs) return;
   g_last_cycle = now_ms;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0) return;

   UpdateRiskWindows();

   if(g_halted)
     {
      if(!g_halt_terminal && NewDayStarted()) ResumeAfterDailyHalt();
      else return;
     }

   double floating = FloatingProfit();
   if(CheckHalts(floating)) return;

   if(InpBasketTP > 0.0 && CountPositions() > 0 && floating >= InpBasketTP)
     {
      PrintFormat("Basket TP atteint (%.2f) -> cloture globale", floating);
      CloseEverything();
      g_anchor = 0.0;
      return;
     }

   UpdateStep();
   UpdateAnchor(bid, ask);
   TrackReleasedLevels();
   EnsureTakeProfits();

   if(!CanOpen(bid, ask)) return;
   ArmLevels(bid, ask);
  }

//+------------------------------------------------------------------+
//| Pas de grille                                                    |
//+------------------------------------------------------------------+
double ClampStep(double value)
  {
   return MathMax(InpStepMin, MathMin(InpStepMax, value));
  }

void UpdateStep()
  {
   if(InpStepMode == STEP_FIXED)
     {
      g_step = ClampStep(InpStepFixed);
      return;
     }
   double buffer[];
   if(CopyBuffer(g_atr_handle, 0, 0, 1, buffer) <= 0) return;
   double target = ClampStep(buffer[0] * InpAtrMult);
   if(g_step <= 0.0 || MathAbs(target - g_step) / g_step > 0.15)
     {
      if(InpVerbose) PrintFormat("Pas de grille : %.2f -> %.2f (ATR %.2f)", g_step, target, buffer[0]);
      g_step = target;
     }
  }

//+------------------------------------------------------------------+
//| Ancre                                                            |
//+------------------------------------------------------------------+
void UpdateAnchor(double bid, double ask)
  {
   double mid = (bid + ask) / 2.0;
   if(g_anchor <= 0.0)
     {
      g_anchor = NormalizeDouble(mid, _Digits);
      PrintFormat("Ancre initialisee a %.2f (pas %.2f, %d paliers/cote)",
                  g_anchor, g_step, InpLevels);
      return;
     }

   double span  = g_step * InpLevels;
   double drift = mid - g_anchor;
   if(MathAbs(drift) <= span * InpReanchorMult) return;

   if(CountPositions() == 0)
     {
      PrintFormat("Re-centrage de la grille : %.2f -> %.2f", g_anchor, mid);
      CancelAllOrders();
      g_anchor = NormalizeDouble(mid, _Digits);
     }
   else if(InpTrailGrid)
     {
      double shift = drift - span * InpReanchorMult * (drift > 0 ? 1.0 : -1.0);
      g_anchor = NormalizeDouble(g_anchor + shift, _Digits);
      PrintFormat("Grille suiveuse : nouvelle ancre %.2f", g_anchor);
     }
  }

//+------------------------------------------------------------------+
//| Geometrie des paliers                                            |
//+------------------------------------------------------------------+
double LevelPrice(int side, int index)
  {
   if(side == SIDE_BUY) return NormalizeDouble(g_anchor - index * g_step, _Digits);
   return NormalizeDouble(g_anchor + index * g_step, _Digits);
  }

int CooldownSlot(int side, int index)
  {
   return (side == SIDE_BUY ? 0 : InpLevels) + (index - 1);
  }

string LevelComment(int side, int index)
  {
   return StringFormat("%s%s%d", InpTag, (side == SIDE_BUY ? "B" : "S"), index);
  }

//--- Un palier est occupe si une position OU un ordre du bot se trouve
//--- a moins de 40% du pas de son prix theorique (robuste aux commentaires
//--- tronques par certains brokers et au slippage d'execution).
bool LevelOccupied(int side, int index)
  {
   double target    = LevelPrice(side, index);
   double tolerance = g_step * 0.4;
   ENUM_POSITION_TYPE want_pos = (side == SIDE_BUY ? POSITION_TYPE_BUY : POSITION_TYPE_SELL);
   ENUM_ORDER_TYPE    want_ord = (side == SIDE_BUY ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !IsOurPosition()) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != want_pos) continue;
      if(MathAbs(PositionGetDouble(POSITION_PRICE_OPEN) - target) <= tolerance) return true;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !IsOurOrder()) continue;
      if((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE) != want_ord) continue;
      if(MathAbs(OrderGetDouble(ORDER_PRICE_OPEN) - target) <= tolerance) return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Selection : la position/l'ordre courant appartient-il au bot ?    |
//+------------------------------------------------------------------+
bool IsOurPosition()
  {
   return (PositionGetString(POSITION_SYMBOL) == _Symbol
           && PositionGetInteger(POSITION_MAGIC) == InpMagic);
  }

bool IsOurOrder()
  {
   return (OrderGetString(ORDER_SYMBOL) == _Symbol
           && OrderGetInteger(ORDER_MAGIC) == InpMagic);
  }

int CountPositions()
  {
   int total = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && IsOurPosition()) total++;
   return total;
  }

int CountOrders()
  {
   int total = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
      if(OrderGetTicket(i) > 0 && IsOurOrder()) total++;
   return total;
  }

double FloatingProfit()
  {
   double total = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) == 0 || !IsOurPosition()) continue;
      total += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   return total;
  }

void LotExposure(double &gross, double &net)
  {
   double buys = 0.0, sells = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(PositionGetTicket(i) == 0 || !IsOurPosition()) continue;
      double vol = PositionGetDouble(POSITION_VOLUME);
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) buys += vol;
      else sells += vol;
     }
   gross = buys + sells;
   net   = MathAbs(buys - sells);
  }

//+------------------------------------------------------------------+
//| Risque                                                           |
//+------------------------------------------------------------------+
void UpdateRiskWindows()
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > g_peak_equity) g_peak_equity = equity;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day != g_day)
     {
      g_day        = dt.day;
      g_day_equity = equity;
     }
  }

bool NewDayStarted()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.day != g_day);
  }

void ResumeAfterDailyHalt()
  {
   g_halted      = false;
   g_halt_reason = "";
   Print("Reprise apres arret journalier.");
  }

void Halt(string reason, bool terminal)
  {
   g_halted        = true;
   g_halt_terminal = terminal;
   g_halt_reason   = reason;
   PrintFormat("ARRET RISQUE (%s) : %s", terminal ? "terminal" : "journalier", reason);
   CloseEverything();
   g_anchor = 0.0;
  }

bool CheckHalts(double floating)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);

   if(g_peak_equity > 0.0)
     {
      double dd = (g_peak_equity - equity) / g_peak_equity * 100.0;
      if(dd >= InpMaxDrawdownPct)
        { Halt(StringFormat("drawdown %.2f%%", dd), true); return true; }
     }
   if(g_day_equity > 0.0)
     {
      double day = (g_day_equity - equity) / g_day_equity * 100.0;
      if(day >= InpDailyLossPct)
        { Halt(StringFormat("perte du jour %.2f%%", day), false); return true; }
     }
   if(InpBasketSL > 0.0 && floating <= -MathAbs(InpBasketSL))
     { Halt(StringFormat("basket SL (%.2f)", floating), false); return true; }

   double margin = AccountInfoDouble(ACCOUNT_MARGIN);
   if(margin > 0.0 && equity > 0.0)
     {
      double free_pct = AccountInfoDouble(ACCOUNT_MARGIN_FREE) / equity * 100.0;
      if(free_pct < InpMinFreeMarginPct)
        { Halt(StringFormat("marge libre %.1f%%", free_pct), true); return true; }
     }
   return false;
  }

bool InSession()
  {
   if(!InpUseSession) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(!InpTradeWeekend && (dt.day_of_week == 0 || dt.day_of_week == 6)) return false;
   if(InpStartHour <= InpEndHour) return (dt.hour >= InpStartHour && dt.hour < InpEndHour);
   return (dt.hour >= InpStartHour || dt.hour < InpEndHour);   // fenetre a cheval sur minuit
  }

bool CanOpen(double bid, double ask)
  {
   if(!InSession()) return false;
   if(ask - bid > InpMaxSpread) return false;
   if(CountPositions() + CountOrders() >= InpMaxPositions) return false;

   double gross, net;
   LotExposure(gross, net);
   if(gross >= InpMaxTotalLots) return false;
   if(net   >= InpMaxNetLots)   return false;
   return true;
  }

//+------------------------------------------------------------------+
//| Tendance                                                         |
//+------------------------------------------------------------------+
int TrendBias()   // 0 = neutre, 1 = haussier, -1 = baissier
  {
   if(!(InpTrendFilter || InpMode == GRID_TREND)) return 0;
   double fast[], slow[];
   if(CopyBuffer(g_ema_fast, 0, 0, 1, fast) <= 0) return 0;
   if(CopyBuffer(g_ema_slow, 0, 0, 1, slow) <= 0) return 0;
   return (fast[0] > slow[0]) ? 1 : -1;
  }

bool SideAllowed(int side)
  {
   if(InpMode == GRID_LONG)  return (side == SIDE_BUY);
   if(InpMode == GRID_SHORT) return (side == SIDE_SELL);
   int bias = TrendBias();
   if(InpMode == GRID_TREND)
     {
      if(bias > 0) return (side == SIDE_BUY);
      if(bias < 0) return (side == SIDE_SELL);
      return true;
     }
   if(InpTrendFilter && bias != 0)
      return (bias > 0 ? side == SIDE_BUY : side == SIDE_SELL);
   return true;
  }

//+------------------------------------------------------------------+
//| Volume                                                           |
//+------------------------------------------------------------------+
double VolumeForLevel(int index)
  {
   double volume = InpLot * MathPow(InpMartingale, index - 1);
   double vmin   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   volume = MathMin(volume, InpLotMax);
   volume = MathMax(vmin, MathMin(vmax, volume));
   if(vstep > 0.0) volume = MathRound(volume / vstep) * vstep;
   return NormalizeDouble(volume, 3);
  }

//+------------------------------------------------------------------+
//| Un palier qui vient de se liberer (TP touche) part en cooldown   |
//+------------------------------------------------------------------+
void TrackReleasedLevels()
  {
   datetime now = TimeCurrent();
   for(int index = 1; index <= InpLevels; index++)
      for(int side = SIDE_BUY; side <= SIDE_SELL; side++)
        {
         int  slot     = CooldownSlot(side, index);
         bool occupied = LevelOccupied(side, index);
         if(g_was_occupied[slot] && !occupied)
           {
            g_cooldown[slot] = now + InpRearmCooldownS;
            if(InpVerbose)
               PrintFormat("Palier %s libere, re-armement dans %d s",
                           LevelComment(side, index), InpRearmCooldownS);
           }
         g_was_occupied[slot] = occupied;
        }
  }

//+------------------------------------------------------------------+
//| Armement des paliers                                             |
//+------------------------------------------------------------------+
void ArmLevels(double bid, double ask)
  {
   double stops_gap = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(stops_gap < _Point) stops_gap = _Point;
   datetime now  = TimeCurrent();
   int      slots= InpMaxPositions - CountPositions() - CountOrders();

   for(int index = 1; index <= InpLevels && slots > 0; index++)
     {
      for(int side = SIDE_BUY; side <= SIDE_SELL; side++)
        {
         if(slots <= 0) break;
         if(!SideAllowed(side)) continue;

         int slot = CooldownSlot(side, index);
         if(g_cooldown[slot] > now) continue;
         if(LevelOccupied(side, index)) continue;

         double price = LevelPrice(side, index);
         if(side == SIDE_BUY  && price > ask - stops_gap) continue;
         if(side == SIDE_SELL && price < bid + stops_gap) continue;

         double volume = VolumeForLevel(index);
         double tp, sl;
         if(side == SIDE_BUY)
           {
            tp = NormalizeDouble(price + g_step * InpTpMult, _Digits);
            sl = (InpSlMult > 0.0) ? NormalizeDouble(price - g_step * InpSlMult, _Digits) : 0.0;
           }
         else
           {
            tp = NormalizeDouble(price - g_step * InpTpMult, _Digits);
            sl = (InpSlMult > 0.0) ? NormalizeDouble(price + g_step * InpSlMult, _Digits) : 0.0;
           }

         string comment = LevelComment(side, index);
         bool   ok = (side == SIDE_BUY)
                     ? g_trade.BuyLimit(volume, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment)
                     : g_trade.SellLimit(volume, price, _Symbol, sl, tp, ORDER_TIME_GTC, 0, comment);

         if(ok)
           {
            slots--;
            g_was_occupied[slot] = true;
            if(InpVerbose)
               PrintFormat("Palier %s arme : %.3f @ %.2f (TP %.2f)", comment, volume, price, tp);
           }
         else if(InpVerbose)
            PrintFormat("Echec palier %s : retcode %d (%s)",
                        comment, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
        }
     }
  }

//+------------------------------------------------------------------+
//| Filet : replacer un TP manquant (rejet broker, redemarrage)       |
//+------------------------------------------------------------------+
void EnsureTakeProfits()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !IsOurPosition()) continue;
      if(PositionGetDouble(POSITION_TP) > 0.0) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      bool   is_buy = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double tp = is_buy ? entry + g_step * InpTpMult : entry - g_step * InpTpMult;
      double sl = PositionGetDouble(POSITION_SL);
      if(InpSlMult > 0.0 && sl == 0.0)
         sl = is_buy ? entry - g_step * InpSlMult : entry + g_step * InpSlMult;

      g_trade.PositionModify(ticket, NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits));
     }
  }

//+------------------------------------------------------------------+
//| Clotures                                                         |
//+------------------------------------------------------------------+
void CancelAllOrders()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !IsOurOrder()) continue;
      g_trade.OrderDelete(ticket);
     }
  }

void CloseAllPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !IsOurPosition()) continue;
      g_trade.PositionClose(ticket, InpSlippagePoints);
     }
  }

void CloseEverything()
  {
   CancelAllOrders();
   CloseAllPositions();
  }
//+------------------------------------------------------------------+
