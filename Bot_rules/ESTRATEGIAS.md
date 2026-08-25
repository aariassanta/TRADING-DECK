# Estrategias de Trading — Trading Deck Bot

## Overview

El bot opera en paper trading sobre opciones de SPX/SPXW (0DTE). Cada estrategia es independiente — solo se ejecuta una posición por estrategia simultáneamente. Límites globales: máximo 3 operaciones/día, pérdida diaria máxima 5% del capital ($25,000), hora límite de entrada 13:00 EST.

---

## 1. FLIP — GEX Cross

### Descripción
Detecta cuando el **Gamma Exposure (GEX) total cruza de positivo a negativo** (o viceversa), indicando un cambio de régimen en la dinámica del mercado. Cuando los dealers pasan de net-long-gamma a net-short-gamma, la volatilidad aumenta y los precios se mueven más fuerte en la dirección del sesgo.

### Condiciones de señal
| Condición | Requisito |
|---|---|
| `net_gex_total` previo | `> 0` o `< 0` |
| `net_gex_total` actual | signo opuesto al previo |
| Magnitud del flip | `|net_gex| >= 5M` (no cruzado en zona neutra) |
| Bias | `BULLISH` o `BEARISH` (no NEUTRAL) |
| Posición activa | No hay posición abierta para FLIP |
| Estrategia habilitada | FLIP checkbox activo |

### Cálculo de la señal
- **BULLISH** → Bull Put Spread: short put en `put_wall`, long put 5 strikes más abajo
- **BEARISH** → Bear Call Spread: short call en `call_wall`, long call 5 strikes más arriba
- **Ancho:** 5 strikes
- **Crédito de entrada:** $2.50 (PCS) / $4.00 (IC)
- **TP:** 50% del crédito
- **SL:** 2× el crédito

### Lógica de detección
```
prev_net_gex > 0 AND curr_net_gex < 0 → FLIP TO NEGATIVE → BEARISH
prev_net_gex < 0 AND curr_net_gex > 0 → FLIP TO POSITIVE → BULLISH
```

### Métricas usadas
- `net_gex_total` — gamma total de los dealers
- `bias` — dirección del flujo de órdenes
- `put_wall` / `call_wall` — niveles de soporte/resistencia del GEX

---

## 2. PINNING — Iron Condor

### Descripción
Opera en régimen **LONG_GAMMA**, donde los dealers son net-long-gamma y actúan como imán del precio hacia niveles de alta.open interest. Cuando hay un candidato de pinning (precio cerca de un strike con alta OI) y riesgo de breakout bajo, se coloca un Iron Condor para capturar prima.

### Condiciones de señal
| Condición | Requisito |
|---|---|
| `regime` | `LONG_GAMMA` |
| `breakout_risk` | `MEDIUM` o `LOW` (no HIGH) |
| `pinning_candidate` | disponible (precio cerca de strike con alta OI) |
| `put_wall` / `call_wall` | disponibles |
| Posición activa | No hay posición abierta para PINNING |
| Estrategia habilitada | PINNING checkbox activo |

### Cálculo de la señal
- **Iron Condor** simétrico:
  - Short put en `put_wall`, long put 5 strikes más abajo
  - Short call en `call_wall`, long call 5 strikes más arriba
- **Crédito de entrada:** ~$4.00 (prima de ambos spreads)
- **TP:** 50% del crédito
- **SL:** 2× el crédito (por cada lado)

### Lógica de detección
```
regime == LONG_GAMMA AND breakout_risk != HIGH
→ rango esperado estable → Iron Condor para cobrar prima
```

### Métricas usadas
- `regime` — régimen actual del mercado
- `breakout_risk` — riesgo de ruptura de rango
- `pinning_candidate` — strike con alta OI cerca del precio actual
- `put_wall` / `call_wall` — paredes de gamma

---

## 3. TREND — Directional Breakout

### Descripción
Opera en régimen **SHORT_GAMMA** con sesgo direccional claro y riesgo de breakout bajo. Cuando los dealers son net-short-gamma, cualquier movimiento direccional se amplifica. Si además el precio está en tendencia y el breakout risk es bajo, se busca capturar el movimiento con un credit spread direccional.

### Condiciones de señal
| Condición | Requisito |
|---|---|
| `regime` | `SHORT_GAMMA` |
| `bias` | `BULLISH` o `BEARISH` (no NEUTRAL) |
| `breakout_risk` | `LOW` |
| Posición activa | No hay posición abierta para TREND |
| Estrategia habilitada | TREND checkbox activo |

### Cálculo de la señal
- **BULLISH** → Bull Put Spread: short put en `put_wall`, long put 5 strikes más abajo
- **BEARISH** → Bear Call Spread: short call en `call_wall`, long call 5 strikes más arriba
- **Crédito de entrada:** $2.50
- **TP:** 60% del crédito (mayor R:R que FLIP/PINNING)
- **SL:** 2× el crédito

### Diferencia con FLIP
FLIP reacciona a un cambio de signo del GEX (cruce). TREND opera con GEX ya negativo (SHORT_GAMMA) y requiere confirmación de dirección + riesgo de breakout bajo.

### Métricas usadas
- `regime` — debe ser SHORT_GAMMA explícitamente
- `bias` — direccionalidad confirmada
- `breakout_risk` — debe ser LOW

---

## 4. ORB — Opening Range Breakout

### Descripción
Estrategia basada en el **Opening Range Breakout (ORB)** de la primera hora de sesión (9:30–10:30 EST). Durante este窗口 se registran los precios máximo y mínimo de SPX. Al cierre del ORB se determina la dirección del sesgo intradía y se coloca una orden condicionada.

### Fase 1 — Tracking ORB (9:30–10:30 EST)
El bot recibe el precio spot de SPX cada 15 segundos y mantiene:
- `orb_high` — precio máximo registrado
- `orb_low` — precio mínimo registrado
- `orb_mid = (orb_high + orb_low) / 2`

### Fase 2 — Dirección al cierre del ORB (10:30 EST)
Se evalúa qué nivel se rompió primero:
- `orb_low` roto al alza primero → sesgo **BULLISH** → comprar CALL
- `orb_high` roto a la baja primero → sesgo **BEARISH** → comprar PUT

### Condiciones de señal
| Condición | Requisito |
|---|---|
| ORB evaluado | `orb_session_active == False` Y `orb_evaluated == True` |
| Dirección establecida | `orb_direction` no es null |
| Sin posición ORB activa | No hay posición abierta para ORB |
| Estrategia habilitada | ORB checkbox activo |

### Cálculo de la señal
| Elemento | CALL (bullish) | PUT (bearish) |
|---|---|---|
| Strike comprado | `orb_mid + 5` (1 strike above) | `orb_mid - 5` (1 strike below) |
| Entry trigger | SPX > `orb_mid` | SPX > `orb_mid` |
| TP trigger | SPX > `orb_high` | SPX < `orb_low` |
| SL trigger | SPX < `orb_low` | SPX > `orb_high` |
| Duración máxima | 15 minutos (GTD) | 15 minutos (GTD) |

### Orden brackets (3 componentes)
1. **Parent BUY LMT** — compra la call/put al precio estimado; activada cuando SPX cruza `orb_mid` via `PriceCondition`
2. **TP child SELL LMT** — cierra la posición a `fill_price × 1.20` (+20%); activada cuando SPX cruza el nivel correspondiente
3. **SL child SELL LMT** — cierra con pérdida limitada a `fill_price × 0.85` (-15%); activada cuando SPX cruza en dirección contraria

**Importante:** Los niveles de TP y SL son **basados en el subyacente (SPX)**, no en el precio de la opción. Se usan `PriceCondition` nativas de IBKR sobre el contrato SPX en CBOE.

### Parámetros de la orden
```
Strike: orb_mid ± 5 (1 strike SPX)
Entry:  LMT condicionada a SPX > orb_mid (PriceCondition)
TP:     SELL LMT a fill_price × 1.20 con PriceCondition
SL:     SELL LMT a fill_price × 0.85 con PriceCondition
TIF:    GTD 15 min para TP y SL
```

### Métricas usadas
- `orb_high` / `orb_low` / `orb_mid` — niveles del ORB
- `spot` — precio en tiempo real de SPX

---

## Límites Globales (todas las estrategias)

| Límite | Valor |
|---|---|
| Máximo trades/día | 3 |
| Pérdida diaria máxima | 5% del capital ($1,250) |
| Hora límite de entrada | 13:00 EST |
| Time exit forzado | 15:30 EST |
| Entorno | Paper trading únicamente |

---

## Campos de la señal

```typescript
interface BotSignal {
  strategy: 'FLIP' | 'PINNING' | 'TREND' | 'ORB';
  direction: 'BULL_PUT' | 'BEAR_CALL' | 'IC' | 'BUY_CALL' | 'BUY_PUT';
  short_strike: number;   // FLIP/PINNING/TREND
  long_strike: number;    // FLIP/PINNING/TREND
  width: number;
  entry_credit: number;
  tp_credit: number;
  sl_credit: number;
  confidence: number;    // 0-1
  reason: string;
  timestamp: number;
  // ORB-specific
  entry_trigger?: number;  // precio SPX que activa la entrada
  tp_trigger?: number;      // precio SPX que activa el TP
  sl_trigger?: number;     // precio SPX que activa el SL
}
```

---

## Campos del estado ORB

```typescript
interface OrbStatus {
  high: number | null;         // orb_high
  low: number | null;          // orb_low
  mid: number | null;         // (high + low) / 2
  session_active: boolean;     // tracking en curso 9:30-10:30
  evaluated: boolean;         // ORB cerrado y dirección establecida
  direction: 'BULLISH' | 'BEARISH' | null;
}
```
