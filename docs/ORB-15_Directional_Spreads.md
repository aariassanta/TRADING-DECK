# ORB-15 + Directional Spreads (SPX / NDX)

## Resumen

Estrategia de opciones 0DTE que combina ORB (Opening Range Breakout) con spreads direccionales en SPXW o NDX. Usa la señal de dirección del ORB para decidir entre PCS (Bull Put Spread) o CCS (Bear Call Spread).

La estrategia puede operarse en **SPX** o **NDX** — ambos funcionan, pero NDX ha mostrado mejor rendimiento en el backtest.

## Señal de Dirección (ORB)

| Parámetro | Valor |
|-----------|-------|
| Mercado | SPX o NDX (datos 5min desde IBKR) |
| Ventana ORB | 9:30 - 9:45 ET (3 velas de 5 min) |
| Filtro | Displacement REL ≥ 2.0× mediana cuerpo |

## Confirmación de Tendencia (4 pasos)

La estrategia usa una **secuencia de 4 pasos** para confirmar la dirección del trade:

### Paso 1: Definir el Rango de Apertura (ORB)
- **Horario:** 9:30 - 9:45 ET (primeras 3 velas de 5 min)
- `ORB_high = max(High de las 3 velas)`
- `ORB_low = min(Low de las 3 velas)`
- `ORB_range = ORB_high - ORB_low`

### Paso 2: Breakout Inicial
- Precio rompe **por fuera** del rango ORB
- Rompe arriba de ORB_high → señal **alcista**
- Rompe abajo de ORB_low → señal **bajista**

### Paso 3: Pullback (confirmación de fake breakout)
- El precio **regresa dentro** del rango ORB
- Esto "barre" los stops de quienes entraron en el falso breakout
- Es requisito indispensable: sin pullback, no hay entrada

### Paso 4: Re-breakout con filtro displacement (ENTRADA)
- La siguiente vela rompe el ORB de nuevo **EN LA MISMA DIRECCIÓN**
- **+ Filtro de displacement**: el cuerpo de esa vela debe ser ≥ 2× la mediana de cuerpos de la sesión

```
                    ORB High
                       │
    Breakout ──────────┼──────────> Pullback (regresa dentro)
                       │
    Re-breakout ───────┼──────────> ENTRADA AQUÍ (con displacement)
                       │
                    ORB Low
```

## Qué es el "cuerpo" de una vela

El **cuerpo** de una vela es la diferencia entre el precio de apertura y cierre:

```
        H
        │
   ┌────┴────┐   ← Cuerpo (O-C) - la parte "sólida" de la vela
   │        │
   │        │   ← Sombras/mechas
   └────────┤
        │
        L
```

- **Cuerpo** = `|Close - Open|` (no High - Low)
- **Sombras** = High - Low (rango completo de la vela)

El filtro usa el **cuerpo** porque representa el movimiento "real" de precio desde la apertura al cierre, no las sombras que pueden ser solo ruido o stops barridos.

## Filtro de Displacement

El displacement filtra señales falsas requiriendo que la vela de entrada tenga un cuerpo grande (actividad institucional):

```
body = |Close - Open|
entry_condition = body ≥ 2.0 × median_body_session
```

donde `median_body_session` = mediana de todos los cuerpos de las velas de 5 min de la sesión RTH hasta ese momento.

**Por qué funciona:** Un cuerpo grande indica que hubo fuerza institucional real detrás del movimiento, no solo ruido o un spike temporal.

## Ejemplo Práctico (10 ago 2026 - SPX)

| Paso | Hora ET | Precio SPX | Acción |
|------|---------|------------|--------|
| 1. ORB | 9:45 | H=7761.44, L=7748.42 | Definir rango |
| 2. Breakout | 10:00 | 7762 > 7761.44 | Rompe arriba → señal long |
| 3. Pullback | 10:55 | 7758 < 7761.44 | Regresa dentro |
| 4. Re-breakout | 11:50 | 7765.30 > 7761.44 | **ENTRADA** (cuerpo ≥ 2× mediana) |

## Dirección del Trade

| Breakout | Spread | Dirección |
|----------|--------|-----------|
| Arriba de ORB High | **PCS** (Bull Put Spread) | Long |
| Abajo de ORB Low | **CCS** (Bear Call Spread) | Short |

## Strikes (modelo OTM)

El **buffer** es un margen de seguridad que aleja el strike vendido del ORB para aumentar la probabilidad de éxito. Se calcula como **porcentaje del precio de SPX**.

### Fórmula

```
buffer_pts = SPX_open × buffer%
strike_vendido = ORB_low - buffer_pts     # para PCS
strike_vendido = ORB_high + buffer_pts    # para CCS
strike_comprado = strike_vendido ± width
```

**Nota:** Se usa SPX Open (sin look-ahead bias, disponible al inicio de la sesión).

### Ejemplo

| Parámetro | Valor |
|-----------|-------|
| SPX Close | 5,800 |
| Buffer | 0.5% |
| Buffer en puntos | 5,800 × 0.005 = **29 pts** |
| ORB Low | 5,780 |
| **Strike vendido (PCS)** | 5,780 - 29 = **5,751** |
| Width | 40 pts |
| **Strike comprado** | 5,751 - 40 = 5,711 |

### Parámetros del backtest

| Buffer | Equivalente en pts (SPX=5800) |
|--------|------------------------------|
| 0.5% | ~29 pts |
| 1.0% | ~58 pts |
| 1.5% | ~87 pts |

## Gestión del Trade

| Parámetro | Valor |
|-----------|-------|
| Expiración | 0DTE (mismo día) |
| Evaluación | Cierre vs strike vendido |
| Win condition (PCS) | Close > strike vendido |
| Win condition (CCS) | Close < strike vendido |

## P&L

| Escenario | P&L |
|-----------|-----|
| **Win** | Crédito recibido |
| **Loss** | Ancho spread - Crédito |

**Ejemplo (Width=20, Crédito=$487):**
- Win: +$487
- Loss: +($487 - $2000) = -$1,513

## Parámetros

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| SPREAD_WIDTH | 20-40 pts (recomendado) | Ancho del spread |
| BUFFER | 0.5% del SPX | Margen de seguridad para strikes |
| DISP_REL_MULT | 2.0 | Body vela entrada ≥ 2× mediana cuerpos sesión |
| ORB_BARS | 3 | Primeras 3 velas de 5min (15 min) |
| VOLATILIDAD | 0.15 (SPX) / 0.25 (NDX) | Sigma para pricing BS |

## Resultados YTD (datos reales desde IBKR)

### SPX

| Métrica | Valor |
|---------|-------|
| Trades | 92 |
| WR | 89.1% |
| PF | 3.68 |
| PnL Total | $24,721 |
| Avg Credit | $486 |
| Max Drawdown | $-2,016 |

### NDX

| Métrica | Valor |
|---------|-------|
| Trades | 96 |
| WR | 89.6% |
| PF | 5.19 |
| PnL Total | $36,139 |
| Avg Credit | $585 |
| Max Drawdown | $-966 |

### Comparación SPX vs NDX

| Métrica | SPX | NDX | Mejor |
|---------|-----|-----|-------|
| Trades | 92 | 96 | - |
| WR | 89.1% | 89.6% | NDX |
| PF | 3.68 | **5.19** | NDX |
| PnL | $24,721 | **$36,139** | NDX |
| MaxDD | -$2,016 | **-$966** | NDX |

**NDX es la opción preferida** por mejor profit factor, mayor P&L, y menor drawdown.

## Semana 11-14 Agosto 2026

### SPX

| Fecha | Tipo | ORB H | ORB L | Entry | Strike | SPX Close | Resultado | PnL |
|-------|------|-------|-------|-------|--------|-----------|-----------|------|
| 10 ago | PCS | 7761.44 | 7748.42 | 7759.20 | 7741.91 | 7753.11 | WIN | +$750 |
| 11 ago | CCS | 7767.51 | 7752.23 | 7752.78 | 7775.15 | 7728.20 | WIN | +$435 |
| 12 ago | CCS | 7766.01 | 7748.37 | 7749.64 | 7774.83 | 7748.50 | WIN | +$620 |
| 13 ago | PCS | 7787.16 | 7763.18 | 7783.52 | 7751.19 | 7798.99 | WIN | +$410 |
| 14 ago | PCS | 7807.71 | 7797.81 | 7801.24 | 7792.86 | 7785.76 | LOSS | -$1,047 |

**Total SPX: 4/5 wins (+$1,168)**

### NDX

| Fecha | Tipo | ORB H | ORB L | Entry | Strike | NDX Close | Resultado | PnL |
|-------|------|-------|-------|-------|--------|-----------|-----------|------|
| 10 ago | PCS | 29730.31 | 29610.01 | 29724.97 | 29549.86 | 29623.77 | WIN | +$847 |
| 11 ago | CCS | 29705.80 | 29575.73 | 29596.16 | 29770.83 | 29522.92 | WIN | +$570 |
| 12 ago | CCS | 29881.50 | 29750.34 | 29812.92 | 29947.08 | 29743.69 | WIN | +$640 |
| 13 ago | - | 29944.83 | 29757.62 | - | - | - | Sin señal | - |
| 14 ago | PCS | 30176.68 | 30072.63 | 30159.81 | 30020.61 | 30050.44 | WIN | +$925 |

**Total NDX: 4/4 wins (+$2,982)**

**Nota 13 ago:** No hubo operación en NDX porque el precio rompió el ORB pero nunca hubo pullback (se mantuvo在上面 todo el día). La estrategia requiere la secuencia completa: breakout → pullback → re-breakout.

## Comparación con ORB-15 Futuros

| Aspecto | ORB-15 Futuros | ORB-15 Spreads |
|----------|----------------|-----------------|
| MaxDD | -$409 | -$966 (NDX) |
| Capital requerido | Alto | Bajo (spreads definidos) |
| Riesgo | Ilimitado | Limitado |
| WR | 58% | 89.6% |

## Backtest: Sweep Width 5-50 con diferentes Buffers y SL

**Configuración:** Black-Scholes (sigma = 0.15), Disp Mult = 2.0

### SL = Strike (Stop en el strike vendido)

| Width | Buffer | WR% | W/L | PnL | Avg$ | MaxDD | PF |
|-------|--------|-----|-----|------|------|-------|-----|
| 5 | 0.5% | 98.8% | 80/1 | $6,374 | $79 | -$159 | 41.16 |
| 10 | 0.5% | 98.8% | 80/1 | $12,102 | $149 | -$332 | 37.51 |
| 15 | 0.5% | 98.8% | 80/1 | $17,227 | $213 | -$519 | 34.21 |
| 20 | 0.5% | 98.8% | 80/1 | $21,788 | $269 | -$721 | 31.22 |
| 25 | 0.5% | 98.8% | 80/1 | $25,825 | $319 | -$938 | 28.52 |
| 30 | 0.5% | 98.8% | 80/1 | $29,379 | $363 | -$1,171 | 26.09 |
| 35 | 0.5% | 98.8% | 80/1 | $32,488 | $401 | -$1,419 | 23.89 |
| 40 | 0.5% | 98.8% | 80/1 | $35,188 | $434 | -$1,683 | 21.91 |
| 45 | 0.5% | 98.8% | 80/1 | $37,517 | $463 | -$1,962 | 20.12 |
| 50 | 0.5% | 98.8% | 80/1 | $39,507 | $488 | -$2,256 | 18.51 |
| 5 | 1.0% | 98.8% | 80/1 | $2,624 | $32 | -$261 | 11.07 |
| 10 | 1.0% | 98.8% | 80/1 | $4,884 | $60 | -$537 | 10.10 |
| 15 | 1.0% | 98.8% | 80/1 | $6,812 | $84 | -$828 | 9.23 |
| 20 | 1.0% | 98.8% | 80/1 | $8,440 | $104 | -$1,134 | 8.44 |
| 25 | 1.0% | 98.8% | 80/1 | $9,799 | $121 | -$1,455 | 7.73 |
| 30 | 1.0% | 98.8% | 80/1 | $10,917 | $135 | -$1,791 | 7.10 |
| 35 | 1.0% | 98.8% | 80/1 | $11,819 | $146 | -$2,140 | 6.52 |
| 40 | 1.0% | 98.8% | 80/1 | $12,530 | $155 | -$2,503 | 6.01 |
| 45 | 1.0% | 98.8% | 80/1 | $13,072 | $161 | -$2,879 | 5.54 |
| 50 | 1.0% | 98.8% | 80/1 | $13,464 | $166 | -$3,266 | 5.12 |
| 5 | 1.5% | 100% | 81/0 | $1,180 | $15 | $0 | - |
| 10 | 1.5% | 100% | 81/0 | $2,194 | $27 | $0 | - |
| 15 | 1.5% | 100% | 81/0 | $3,064 | $38 | $0 | - |
| 20 | 1.5% | 100% | 81/0 | $3,805 | $47 | $0 | - |
| 25 | 1.5% | 100% | 81/0 | $4,435 | $55 | $0 | - |
| 30 | 1.5% | 100% | 81/0 | $4,969 | $61 | $0 | - |
| 35 | 1.5% | 100% | 81/0 | $5,419 | $67 | $0 | - |
| 40 | 1.5% | 100% | 81/0 | $5,797 | $72 | $0 | - |
| 45 | 1.5% | 100% | 81/0 | $6,113 | $75 | $0 | - |
| 50 | 1.5% | 100% | 81/0 | $6,377 | $79 | $0 | - |

### SL = Extremo Opuesto (ORB High para PCS, ORB Low para CCS)

| Width | Buffer | WR% | W/L | PnL | Avg$ | MaxDD | PF |
|-------|--------|-----|-----|------|------|-------|-----|
| 5 | 0.5% | 65.4% | 53/28 | -$7,126 | -$88 | -$7,264 | 0.27 |
| 10 | 0.5% | 65.4% | 53/28 | -$14,898 | -$184 | -$15,108 | 0.25 |
| 15 | 0.5% | 65.4% | 53/28 | -$23,273 | -$287 | -$23,540 | 0.23 |
| 20 | 0.5% | 65.4% | 53/28 | -$32,212 | -$398 | -$32,549 | 0.22 |
| 25 | 0.5% | 65.4% | 53/28 | -$41,675 | -$515 | -$42,073 | 0.20 |
| 30 | 0.5% | 65.4% | 53/28 | -$51,621 | -$637 | -$52,073 | 0.19 |
| 35 | 0.5% | 65.4% | 53/28 | -$62,012 | -$766 | -$62,512 | 0.17 |
| 40 | 0.5% | 65.4% | 53/28 | -$72,812 | -$899 | -$73,352 | 0.16 |
| 45 | 0.5% | 65.4% | 53/28 | -$83,983 | -$1,037 | -$84,560 | 0.15 |
| 50 | 0.5% | 65.4% | 53/28 | -$95,493 | -$1,179 | -$96,100 | 0.14 |

### SL = Mitad del ORB

| Width | Buffer | WR% | W/L | PnL | Avg$ | MaxDD | PF |
|-------|--------|-----|-----|------|------|-------|-----|
| 5 | 0.5% | 79.0% | 64/17 | -$1,626 | -$20 | -$2,784 | 0.70 |
| 10 | 0.5% | 79.0% | 64/17 | -$3,898 | -$48 | -$5,864 | 0.65 |
| 15 | 0.5% | 79.0% | 64/17 | -$6,773 | -$84 | -$9,221 | 0.60 |
| 20 | 0.5% | 79.0% | 64/17 | -$10,212 | -$126 | -$12,838 | 0.56 |
| 25 | 0.5% | 79.0% | 64/17 | -$14,175 | -$175 | -$16,901 | 0.52 |
| 30 | 0.5% | 79.0% | 64/17 | -$18,621 | -$230 | -$21,276 | 0.48 |
| 35 | 0.5% | 79.0% | 64/17 | -$23,512 | -$290 | -$25,929 | 0.45 |
| 40 | 0.5% | 79.0% | 64/17 | -$28,812 | -$356 | -$30,838 | 0.42 |
| 45 | 0.5% | 79.0% | 64/17 | -$34,483 | -$426 | -$35,983 | 0.39 |
| 50 | 0.5% | 79.0% | 64/17 | -$40,493 | -$500 | -$41,343 | 0.37 |

### Resumen: Mejores Configuraciones

| Rank | Width | Buffer | SL Type | WR% | PnL | MaxDD | PF |
|------|-------|--------|---------|-----|------|-------|-----|
| 1 | 50 | 0.5% | Strike | 98.8% | $39,507 | -$2,256 | 18.51 |
| 2 | 45 | 0.5% | Strike | 98.8% | $37,517 | -$1,962 | 20.12 |
| 3 | 40 | 0.5% | Strike | 98.8% | $35,188 | -$1,683 | 21.91 |
| 4 | 35 | 0.5% | Strike | 98.8% | $32,488 | -$1,419 | 23.89 |
| 5 | 30 | 0.5% | Strike | 98.8% | $29,379 | -$1,171 | 26.09 |

### Conclusiones

1. **SL = Strike**: 
   - WR 98.8% (80/81 trades winners) - el strike queda muy lejos del precio
   - PF excellent (18-41) para buffer 0.5%
   - Mayor width = mayor PnL (más crédito) pero mayor MaxDD
   - **Recomendado: Width 20-40 con buffer 0.5%** (balance PnL/MaxDD)

2. **SL = Extremo opuesto del ORB**:
   - WR 65.4% (53/81)
   - **No rentable** — el precio frecuentemente cruza el ORB opuesto

3. **SL = Mitad del ORB**:
   - WR 79% (64/81)
   - **No rentable** — aunque el WR es alto, el R:R no compensa

**Conclusión clave**: La estrategia solo es rentable con SL = Strike (donde pierdes todo el spread). El trade-off es: mayor width = más crédito = más PnL, pero también mayor riesgo por contrato.

### Parámetros del Backtest

| Parámetro | Valor |
|-----------|-------|
| Período de datos | 2 ene 2026 - 14 ago 2026 (~160 sesiones) |
| Sesiones con setup ORB-15 | 81 (de las ~160 disponibles) |
| Ancho Spread | 5-50 pts |
| Buffer | 0.5%, 1.0%, 1.5% |
| SL Type | Strike, Extremo Opp, Mitad ORB |
| Volatilidad (IV) | 15% (Black-Scholes) |
| Tasa libre de riesgo | 5% |
| Días a expiración | 1 (0DTE) |
| Multiplicador SPX | 100x |
| Displacement | 2.0× mediana cuerpo |

## Limitaciones

1. **Primas**: Calculadas con Black-Scholes, no reales (sigma=0.15 SPX, 0.25 NDX)
2. **Período**: Solo sesiones YTD 2026
3. **Slippage**: No considerado en el backtest
4. **Ejecución**: Requiere IBKR TWS conexión activa

## Archivos

- `orb15_spreads_spx_ibkr.csv` — Backtest SPX desde IBKR
- `orb15_spreads_ndx_ibkr.csv` — Backtest NDX desde IBKR
- `spx_5m_ytd.csv` — Datos SPX 5min (desde IBKR)
- `ndx_5m_ytd.csv` — Datos NDX 5min (desde IBKR)
- `orb15_rel3_daemon.py` — Daemon unificado (MES + SPX + NDX)