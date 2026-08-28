# Estrategias del Bot

Cada estrategia se evalúa en cada **scan** (cada 5 minutos cuando el bot está activo).
La estrategia se ejecuta vía `BotEngine.execute_signal` y delega en
`engine.execute_spread` (o `execute_single_leg` para ORB) según el `target_mode`.

## Resumen rápido

| Estrategia | Underlying | Tipo de orden | Exit | Trigger horario |
|---|---|---|---|---|
| FLIP | SPX | PCS / CCS (en GEX walls) | TP 50% + SL 2× | continuo |
| PINNING | SPX | IC (5 wings) | TP 50% + SL 2× | continuo |
| TREND | SPX | PCS / CCS (en GEX walls) | TP 60% + SL 2× | continuo |
| ORB | SPX | single-leg call/put | TP/SL Bracket | 09:30 – 10:30 ET (ventana ORB) |
| ORB15 | SPX | PCS / CCS (en ORB levels) | TP 50% + SL 2× | 09:30 – 10:30 ET |
| IRON_FLY | SPXW | IC 4 legs (per-side delta) | **Hold-to-expiry** | 13:40 – 13:55 ET |

---

## FLIP — GEX Sign Change

**Detecta un cambio de signo en el net GEX**, lo que sugiere un cambio de régimen.

- **Condiciones**:
  - Net GEX cambió de `+` a `−` o viceversa
  - `|nuevo net_gex| ≥ $5M` (skip cambios pequeños/ruido)
  - **Bias direccional** debe coincidir con el nuevo signo:
    - BULLISH bias + flip a negativo → PCS (bearish rebalance)
    - BEARISH bias + flip a positivo → CCS (bullish rebalance)
- **Strikes**: anclados a `put_wall` / `call_wall` del metric snapshot
- **Wings**: 5 pts
- **Brackets**: TP al 50% del credit, SL al 2× del credit
- **Módulo**: `bot_engine._evaluate_flip` — `target_mode='GEX'`

## PINNING — LONG_GAMMA + Iron Condor

**Régimen LONG_GAMMA + breakout risk no alto** sugiere que el dealer está
disfrutando gamma (mercado se queda quieto). Vender un IC en los walls.

- **Condiciones**:
  - `regime == 'LONG_GAMMA'`
  - `breakout_risk != 'HIGH'`
  - `pinning_candidate` o `put_wall/call_wall` disponibles
- **Strikes**:
  - Short put = `put_wall`, long put = short put − 5
  - Short call = `call_wall`, long call = short call + 5
- **Brackets**: TP 50% / SL 2×
- **Módulo**: `bot_engine._evaluate_pinning` — `target_mode='GEX'`, `spread_type='IC'`

## TREND — SHORT_GAMMA + directional bias

**Régimen SHORT_GAMMA + bias no neutral + breakout risk low**.
Sin soporte gamma del dealer, el mercado tiende a continuar la dirección.

- **Condiciones**:
  - `regime == 'SHORT_GAMMA'`
  - `bias ∈ {'BULLISH', 'BEARISH'}`
  - `breakout_risk == 'LOW'`
- **Strikes**: anclados a `put_wall` (BULL) o `call_wall` (BEAR)
- **Wings**: 5 pts
- **Brackets**: TP al **60%** (mejor R:R que FLIP/PINNING), SL al 2×
- **Módulo**: `bot_engine._evaluate_trend` — `target_mode='GEX'`

## ORB — Open Range Breakout (single-leg)

Compra de un único call o put en función del breakout del rango de apertura.

- **Ventana**: 09:30 – 10:30 ET
- **Estrategia**:
  - Vela de 5 min rompe el rango de apertura (alto/bajo de los primeros 30 min)
  - Si rompe al alza: BUY_CALL
  - Si rompe a la baja: BUY_PUT
- **TP/SL**: definidos por los niveles del ORB (high/mid/low)
- **Módulo**: `bot_engine._evaluate_orb` — usa `engine.execute_single_leg`

## ORB15 — 4-step state machine → credit spread

**State machine de 4 pasos sobre el ORB de 9:30 a 9:45 ET** que termina en un
credit spread PCS/CCS anclado al ORB.

1. **idle**: esperando la apertura
2. **breakout**: la vela rompe arriba/abajo del ORB en los primeros 9:45 ET
3. **pullback**: el spot vuelve al ORB (o lo cruza)
4. **rebreakout**: nueva vela rompe en la misma dirección
5. **signalled**: se emite la señal con strikes anclados al ORB

- **Filtro displacement**: solo señaliza si el body de la vela de rebreakout
  es ≥ 2× la mediana de los bodies de la mañana (filtra rupturas falsas)
- **Strikes**:
  - BULL_PUT: short = ORB_low − `0.5% buffer`, long = short − 20
  - BEAR_CALL: short = ORB_high + `0.5% buffer`, long = short + 20
- **Wings**: 20 pts
- **Brackets**: TP 50% / SL 2×
- **Módulo**: `bot_engine._evaluate_orb15` — `target_mode='orb15'`

## IRON_FLY — 0DTE Iron Butterfly on SPXW

**Iron butterfly asimétrico que captura theta decay** durante la última hora
de cotización antes del cierre de SPXW 0DTE.

- **Días**: L, M, J, V (skip miércoles)
- **Ventana de entrada**: 13:40 – 13:55 ET
- **Exit**: **hold-to-expiry** (sin TP, sin SL bracket — el engine fuerza `bracket=False`)
- **Strike selection** (delta-based):
  | Leg | Right | Delta | Strike típicos (ej. SPX 7650) |
  |---|---|---|---|
  | Short Put | P | −0.50 | ATM (~7650) |
  | Long Put | P | — | Short − 15 |
  | Short Call | C | **+0.40** | ITM (~7655, +3 pts) |
  | Long Call | C | — | Short + 15 |
- **Filter**: `15 ≤ VIX ≤ 20` (fuera de este rango se skipea, sin tirar el `null` = fail-safe)
- **Módulo**: `bot_engine._evaluate_iron_fly` — `target_mode='iron_fly'`, `spread_type='IC'`

> **Importante**: a diferencia de las otras estrategias, el short call en el Iron
> Fly está **ITM** (delta +0.40 = spot + ~3pts al momento de entrada). Esto es
> intencional: da más premium y un sesgo bearish implícito (gana si SPX no sube
> mucho en la última hora). Resultado: la orden entra como **net DEBIT**, no
> credit. Esto es esperado para un Iron Fly.

---

## MILK_MAN — Weekly ATR Premium Selling

**Vende un Bull Put Spread cada lunes a las 10:00 ET usando ATR semanal(14) como
filtro de distancia del strike**, con hold-to-settlement y un filtro de odds.

- **Días**: Solo lunes
- **Ventana de entrada**: 10:00 – 10:15 ET
- **Short strike**: `prev_week_close − ATR_semanal(14)`, redondeado al múltiplo de 5
- **Long strike**: `short − 50 pts`
- **Width**: 50 pts
- **Expiry**: Viernes misma semana (SPXW)
- **Exit**: **hold-to-settlement** (`bracket=False`)
- **Filtro odds** (opcional, activa con ≥ 12 semanas de histórico):
  - `odds = put_price / 50`
  - `odds < mediana_1Y` → OPERAR (put barato)
  - `odds ≥ mediana_1Y` → SKIP (put caro)
- **Logs**: `history/milk_odds_log.csv` — odds de cada semana para la mediana
- **Módulo**: `bot_engine._evaluate_milk_man` — `target_mode='milk_man'`, `spread_type='PCS'`

---

## Cómo añadir una nueva estrategia

1. Extender el `Literal` en `BotSignal.strategy` (`bot_engine.py:42`)
2. Implementar `_evaluate_<name>(metrics, ...)` en `bot_engine.py`
3. Si requiere target_mode nuevo → añadir rama en `engine.execute_spread`
4. Wire en `scan_and_signal` (`bot_engine.py:434`) y `enabled_strategies` default
5. Añadir tests en `test_bot_engine_strategies.py`
6. (Opcional) Smoke test contra TWS paper
7. (Si tiene UI) añadir bloque en `BotPanel.tsx`
8. Documentar aquí
