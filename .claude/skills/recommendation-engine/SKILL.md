---
name: recommendation-engine
description: Complete rule book for trade recommendations in TRADING-DECK. Covers the Recommendation Engine (server.py scoring → direction → instrument → legs) AND the Bot Engine strategies (FLIP, PINNING, TREND, ORB, ORB15, IRON_FLY, MILK_MAN). Use when changing thresholds, weights, or adding factors.
metadata:
  type: skill
  scope: project
  repo: TRADING-DECK
---

# Recommendation & Bot Strategy Rule Book

Two independent paths produce trade signals in TRADING-DECK:

1. **Recommendation Engine** — score-based, runs every 10 min on the metrics
   cache, broadcasts via WebSocket. Drives the "Operación recomendada" card.
2. **Bot Engine** — strategy-by-strategy state machines, fires only when
   AUTO_MODE is on and the strategy is enabled.

This skill maps every rule that gates either path.

---

## A. Recommendation Engine

Pipeline:

```
metrics_cache
  → score ∈ [-3, +3]    (_score_recommendation)
  → direction            (_score_to_direction)
  → instrument/style/expiry (_choose_instrument_v2)
  → concrete legs        (_recommend_legs)
  → payload broadcast    (_emit_recommendation, every 600s)
```

### A.1 Score factors — `_score_recommendation` (server.py:125-477)

Score starts at 0.0. Each factor adds/subtracts; final value is clamped
to `[-3.0, +3.0]`.

| # | Factor | Rule | Score contribution |
|---|---|---|---|
| 1 | **Regime + Bias** | SHORT_GAMMA ∧ BULLISH | **+2** |
|   |   | SHORT_GAMMA ∧ BEARISH | −1 |
|   |   | LONG_GAMMA ∧ BEARISH | **−2** |
|   |   | LONG_GAMMA ∧ BULLISH | +1 |
|   |   | NEUTRAL | 0 |
| 2 | **Wall proximity (0.3% band)** | spot a <0.3% del Call_Wall | **+1.5** si BULLISH, +0.5 si otro |
|   |   | spot a <0.3% del Put_Wall | **−1.5** si BEARISH, −0.5 si otro |
| 3 | **Wall break** (`alert_state`) | CALL_WALL_BREAK ∧ ¬PUT_WALL_BREAK | **+2** |
|   |   | PUT_WALL_BREAK ∧ ¬CALL_WALL_BREAK | **−2** |
|   |   | ambos a la vez (whipsaw) | **0** (resetea) |
| 4 | **Dark gamma** | `dark_gamma[]` no vacío | **+1** |
| 5 | **Vol vs OI divergence (nuanced)** | pcr_vol > 1.3 ∧ pcr_oi < 1.1 | −0.5 si BULL / +0.5 (contrarian) |
|   |   | pcr_vol < 0.7 ∧ pcr_oi > 1.1 | **+0.5** |
|   |   | pcr_vol > 1.2 ∧ BULLISH (fallback simple) | +1.0 |
|   |   | pcr_vol < 0.8 ∧ BEARISH (fallback simple) | −1.0 |
| 6 | **OI buildup en wall** | wall OI > 2× avg OI | ±0.5 (put wall → −0.5, call wall → +0.5) |
| 7 | **Volume leading spot** | vol(strikes ±1% spot) > 3× avg | **+0.5** |
| 8 | **DEX imbalance** (`_dex_ratio_near_spot`) | \|dex_ratio\| > 0.40 ∧ bias ≠ NEUTRAL |  |
|   |   | bias alineado con dealer | **+1.5** |
|   |   | bias opuesto a dealer | **−0.5** |
| 9 | **Gamma wall stickiness** | gamma_share > 0.40 ∧ bias ≠ NEUTRAL | **+0.5** |
|   |   | gamma_share < 0.15 ∧ breakout_risk HIGH | **−0.5** |
| 10 | **Theta bleed** (`_theta_bleed_penalty`) | \|θ\| acumulado ±15 pts > 50 | penalización negativa |
| 11 | **Breakout risk** | LOW ∧ bias ≠ NEUTRAL | **+1** |
|   |   | HIGH | **−1** |
| 12 | **Net GEX multiplier** | \|net_gex\| > 10 | score × **1.2** |
|   |   | \|net_gex\| < 2 | score × **0.8** |
| 13 | **Regime magnitude multiplier** | \|regime_score\| > 0.5 | score × **1.2** |
| 14 | **Pinning candidate** | spot a <0.3% del pin | **+0.5** |
|   |   | spot a >1% del pin | **−0.3** |
| 15 | **VIX context** | vix < 12 | +0.5 contrarian BEAR / −0.5 si BEARISH bias |
|   |   | vix > 25 ∧ BEARISH | −0.5 |
|   |   | vix > 30 | **+0.5** (contrarian bullish) |
| 16 | **Setup confluence** | fade_setups ≥ 2 ∧ bias ∈ BULL/BEAR | **+0.5** |
|   |   | breakout_setups ≥ 2 ∧ breakout_risk HIGH | **+0.5** |
| 17 | **GEX flip event** | prev_net_gex y net_gex de signo distinto | **±1.5** (signo del nuevo) |
| 18 | **Calendar weekday** | Lunes | −0.3 (overnight gap) |
|   |   | Miércoles | +0.5 (OpEx pin) |
|   |   | Jueves | −0.2 (gamma decay asim.) |
|   |   | Viernes antes 14:30 | −0.5 |
| 19 | **Session phase** | 9:30-10:30 ∧ breakout_risk HIGH | +0.5 |
|   |   | 14:30-15:50 (power hour) | −0.3 |
|   |   | 15:50-16:00 (MOC) | **score = 0** (forzado NEUTRAL) |
| 20 | **Position state** | posición abierta misma dirección | **−1** (no doble) |
|   |   | posición abierta opuesta | +0.5 |
| 21 | **Max-pain pull** | spot a <0.3% del max-pain | +0.5 |
|   |   | spot a >1% del max-pain | −0.3 |
| 22 | **Spread efficiency** | ATM premium / width > 0.50 | +0.5 |
|   |   | < 0.15 | −0.5 |
| 23 | **OI delta** (`_oi_delta_profile`) | strikes ±0.5% spot con gamma expansion >+10%, cluster más cerca de un wall | ±0.3 |

**Final:** `score = max(-3.0, min(3.0, score))`.

### A.2 Score → Direction — `_score_to_direction` (server.py:716-721)

| score | direction |
|---|---|
| ≥ +0.5 | **BULLISH** |
| ≤ −0.5 | **BEARISH** |
| resto | NEUTRAL |

### A.3 Direction → Instrument — `_choose_instrument_v2` (server.py:728-764)

NEUTRAL → `(NO_TRADE, WAIT, None)` sin más procesado.

| Prioridad | Condición | Instrumento | Style | Expiry |
|---|---|---|---|---|
| 1 | `\|score\| ≥ 2.0 ∧ breakout_risk == HIGH ∧ direction == BULLISH` | **BUY_CALL** | DIRECTIONAL | 0DTE |
| 1' | idem BEARISH | **BUY_PUT** | DIRECTIONAL | 0DTE |
| 2 | `\|dex_ratio\| < 0.20 ∧ gamma_share > 0.30 ∧ regime ≠ SHORT_GAMMA ∧ \|score\| < 1.5` | **IC** (Iron Condor) | BUTTERFLY si `thetaBleed < 0`, si no PINNING | 0DTE |
| 3 | BULLISH default | **PCS** | WALL_PUT | 0DTE |
| 3' | BEARISH default | **CCS** | WALL_CALL | 0DTE |

### A.4 Width — `_recommend_legs` (server.py:799-806)

| Condición | Width (pts) |
|---|---|
| gamma_share > 0.40 | **5** |
| gamma_share > 0.20 | **10** |
| breakout_risk HIGH | 20 |
| resto | 15 |

### A.5 Strikes concretos — `_recommend_legs` (server.py:767-880)

- **PCS**: short = `_round5(put_wall)`, long = short − width. `tp_pct=50`, `sl_ratio=2.0`.
- **CCS**: short = `_round5(call_wall)`, long = short + width. `tp_pct=50`, `sl_ratio=2.0`.
- **IC**: shorts en ambos walls; si `(call_wall − put_wall) < width × 2.5`, fallback a butterfly ATM con center = `_round5(spot)`. `tp_pct=50`, `sl_ratio=2.0`.
- **BUY_CALL**: strike = `_round5(spot + 5)`. `tp_pct=50`, `sl_ratio=1.5`.
- **BUY_PUT**: strike = `_round5(spot − 5)`. `tp_pct=50`, `sl_ratio=1.5`.
- **Clamp**: si `|wall − spot| > 300`, se ancla a `spot ± 300` (no toca los valores mostrados en UI).

### A.6 Confidence — `_confidence_label` (server.py:903-909)

| `|score|` | Label |
|---|---|
| ≥ 2.0 | **HIGH** |
| ≥ 1.0 | MEDIUM |
| < 1.0 | LOW |

### A.7 Cadencia y entrega

- Background loop `_emit_recommendation` corre cada **600 s** (10 min) y
  emite vía WebSocket broadcast.
- `/api/recommendation/refresh` fuerza recálculo on-demand.
- `state.last_recommendation` cachea el último payload — sirve a clientes
  que conectan mid-cycle sin esperar 10 min.

---

## B. Bot Engine — Estrategias (bot_engine.py)

Estas son reglas que AUTO_MODE evalúa para abrir posiciones
automáticamente. **Independientes** de la Recommendation Engine.

### B.1 FLIP
- Régimen de gamma cambia de signo entre ticks consecutivos.
- Posición no abierta aún para esta estrategia.

### B.2 PINNING
- `regime == LONG_GAMMA`
- `breakout_risk ≠ HIGH`
- `put_wall or call_wall presentes`
- Genera **Iron Condor simétrico ancho $5**.
- Credit ≈ $4.00, TP = 50%, SL = 2×.

### B.3 TREND
- `regime == SHORT_GAMMA`
- `bias ≠ NEUTRAL`
- `breakout_risk == LOW`
- Genera **PCS** si BULLISH, **CCS** si BEARISH.
- TP 60%, SL 2×.

### B.4 ORB (legacy, daily)
- Activa después de las 10:30 ET.
- BBR (Bull Breakout Rising) / BFR (Bear Failure Rising) según
  comportamiento post-ORB.

### B.5 ORB15 — state machine (bot_engine.py:1000-1196)

Pipeline `idle → forming → breakout → pullback → rebreakout → signalled`:

| Estado | Entrada | Salida |
|---|---|---|
| `idle` | Day rollover reset | fetch_5min_bars() |
| `breakout` | (post-load) | spot > ORB_high → `pullback` bull; spot < ORB_low → `pullback` bear |
| `pullback` | bull: spot < ORB_low; bear: spot > ORB_high | `rebreakout` (con `pullback_seen=True`) |
| `rebreakout` | bar close más allá del ORB level **en dirección** ∧ body ≥ `ORB15_DISP_MIN × median_body` | `signalled` |
| `signalled` | — | trigger `_evaluate_orb15` → BotSignal |

Constantes: `ORB15_DISP_MIN=2`, `ORB15_WIDTH=20`, `ORB15_BUFFER_PCT=0.005`,
session 9:30-13:00 ET.

Emite **PCS** (bullish) o **CCS** (bearish) con strikes
`short_strike = ORB_low/high ∓ buffer` y width 20.

### B.6 IRON_FLY — `_evaluate_iron_fly`

| Condición | Regla |
|---|---|
| Día | skip Miércoles (OpEx) |
| Hora | 13:40 ≤ ET ≤ 13:55 |
| **VIX** | **14 ≤ vix ≤ 20** (cambios `cd4cf86`+`2df36ab`) |
| Strikes | short put @ Δ −0.50, short call @ Δ +0.40 |
| Wings | $15 wide cada lado |
| Sin TP/SL | hold-to-expiry |

### B.7 MILK_MAN — `_evaluate_milk_man`

| Condición | Regla |
|---|---|
| Día | solo Lunes |
| Hora | 10:00 ≤ ET ≤ 10:15 |
| Short strike | `prev_week_close − ATR_weekly`, redondeado a 5 |
| Width | 50 pts |
| Credit gate | `credit > 0` (skip si inverted) |
| Odds gate | `odds < median_1y` (con historial ≥ 12 entries) |
| Cierre | 15:30-16:00 ET |

**Sin filtro de VIX** actualmente.

---

## C. Variables de soporte (no afectan al score por sí solas)

- `state._alert_state` — alert engines disparan CALL_WALL_BREAK /
  PUT_WALL_BREAK basados en breaches de walls vs spot. Alimenta factor #3.
- `state._last_position_summary` — alimenta factor #20.
- `state._prev_net_gex` — alimenta factor #17 (GEX flip).
- `_oi_delta_profile()` — strikes con >+10% gamma expansion intraday,
  alimenta factor #23.
- `metrics_cache.regime_score` — alimenta factor #13 (regime magnitude).
- `metrics_cache.dark_gamma[]` — alimenta factor #4.

---

## D. Anti-patterns al tocar reglas

- ❌ Cambiar un peso sin actualizar la tabla correspondiente aquí — la
  siguiente iteración de tuning pierde trazabilidad.
- ❌ Hardcodear thresholds en sitios distintos de los listados (UI tiene
  duplicados en `BotPanel.tsx` — sincronizar siempre).
- ❌ Añadir un factor que dependa de UI state — score se computa sobre
  `metrics_cache`, estado puro del engine.
- ❌ Asumir que los filtros de Recommendation Engine y Bot Engine son los
  mismos. Son paths independientes. Un cambio en uno no afecta al otro.

---

## E. Test coverage mínima cuando se cambia una regla

- Para `_score_recommendation`: añadir caso en `test_recommendation_*.py`
  con fixtures de `metrics_cache` que dispare el factor tocado.
- Para `_choose_instrument_v2` / `_recommend_legs`: añadir caso que
  verifique el instrumento y strikes resultantes.
- Para estrategias Bot: `test_bot_engine_<strategy>.py` cubre gates;
  añadir caso cuando se cambia un threshold.
- Para cambios de UI (hardcoded ranges): revisar `BotPanel.tsx` además
  de `bot_engine.py` — el caso de `IRON_FLY VIX 14-20` es el ejemplo
  reciente (`2df36ab`).
