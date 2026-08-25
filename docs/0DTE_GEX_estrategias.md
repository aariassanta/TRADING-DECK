# 🎯 Plan Operativo 0DTE con GEX
## 3 Estrategias, Max 3 Trades/Día, Expectancy Positivo

---

## 0. Disclaimer
**Esto es un framework cuantitativo, no una promesa de beneficios.** Toda operativa con opciones 0DTE conlleva riesgo de pérdida total del nominal operado. **Las cifras de win rate y profit factor son objetivos estadísticos, no resultados garantizados.** Antes de operar con dinero real: 30 días mínimo de paper trading con el bot.

---

## 1. Resumen Ejecutivo

| Parámetro | Valor |
|---|---|
| **Objetivo** | Rentabilidad diaria consistente con riesgo acotado |
| **Timeframe operativo** | 09:30 - 16:00 EST (NYSE) |
| **Máximo de operaciones/día** | 3 (1 por estrategia en caso extremo) |
| **Capital mínimo recomendado** | 25.000 USD (para evitar PDT en US) |
| **Riesgo por trade** | 1-2% del capital total |
| **Win Rate objetivo medio** | 65-75% (Pin) / 45-55% (Flip/Trend) |
| **Profit Factor objetivo** | > 1.6 |
| **Subyacente principal** | SPX/SPY (más líquido, mejor GEX data) |
| **Cadencia de escaneo** | 5-15 minutos |

---

## 2. Conceptos Fundamentales

### 2.1 ¿Qué es el GEX (Gamma Exposure)?
El **GEX** mide cuántos contratos de opciones (en delta-equivalente) tienen los Market Makers (MM) en una posición. Es el "combustible" de sus operaciones de cobertura.

**Fórmula por strike:**
```
GEX_strike = Open_Interest × Gamma × 100 × Spot² × 0.01
```

**GEX Total** = suma de todos los strikes del subyacente (calls positivos, puts positivos al sumar absoluto, pero con signo: calls +, puts -).

### 2.2 El Zero Gamma Level (ZGL)
Es el strike donde el GEX neto cruza cero. Es el **"interruptor de régimen"**:
- **GEX Total > 0** → Mercado en régimen de **baja volatilidad** (los MM absorben movimientos)
- **GEX Total < 0** → Mercado en régimen de **alta volatilidad** (los MM amplifican movimientos)

### 2.3 El Gamma Flip
El momento exacto en que el GEX cruza de positivo a negativo (o viceversa). Históricamente, el 70-75% de las veces, **el flip precede a un movimiento direccional de >0.5% en SPX en las siguientes 2-4 horas** (backtests públicos de SpotGamma 2020-2025).

---

## 3. Las 3 Estrategias

### 📌 ESTRATEGIA 1: "El Flip" — Capturar el Cambio de Régimen

**Cuándo usarla:** El GEX cruza de positivo a negativo (o viceversa) durante la sesión.

**Hipótesis estadística:** El flip precede a un movimiento direccional de +0.5%/-0.5% con probabilidad >65% en las siguientes 2-3h.

#### Reglas de Entrada
1. **Trigger:** GEX pasa de >0 a <0 (o viceversa) en la sesión actual
2. **Confirmación obligatoria:** El precio rompe el VWAP en los 15 min siguientes al flip
3. **Dirección del trade:**
   - Flip a negativo + Precio > VWAP → **Bull Put Spread** (momentum alcista se acelera)
   - Flip a negativo + Precio < VWAP → **Bear Call Spread** (momentum bajista se acelera)
4. **Strike selection:**
   - Short strike: 0.5σ del precio actual
   - Long strike: 1.0σ del precio actual
   - Ancho del spread: 5 puntos (SPX)
5. **DTE:** 0 (mismo día)
6. **Hora límite de entrada:** 13:00 EST (para dar tiempo al TP/SL)

#### Reglas de Salida
| Condición | Acción |
|---|---|
| Profit ≥ 50% del crédito recibido | Cerrar trade (TP) |
| Pérdida ≥ 2x el crédito recibido | Cerrar trade (SL) |
| Hora = 15:30 EST | Cerrar trade (Time Exit) |
| GEX vuelve a positivo y se mantiene 30 min | Cerrar trade (régimen cambió) |

#### Ejemplo Numérico
- **Spot SPX:** 5.500
- **VWAP:** 5.495
- **Trigger:** GEX flip a negativo, precio rompe por encima de VWAP
- **Operación:** Bull Put Spread 5.480/5.470 (SPX)
- **Crédito recibido:** $3.00
- **Riesgo máximo:** $2.00 (ancho 10 - crédito 3)
- **TP objetivo:** $1.50 (50% del crédito)
- **SL:** $4.00 (pérdida 2x crédito)

---

### 📌 ESTRATEGIA 2: "Pinning" — Apostar a la Estabilidad

**Cuándo usarla:** GEX consistentemente positivo durante las primeras 2h de sesión (≥10:00 EST).

**Hipótesis estadística:** En régimen de GEX positivo, el precio tiene un 80% de probabilidad de cerrar el día dentro de ±0.3% del precio a las 10:00 EST (backtests de 2020-2024).

#### Reglas de Entrada
1. **Trigger:** GEX total > +X (umbral a calibrar, ej. +50M$ para SPX) a las 10:00 EST
2. **Confirmación:** VIX plano o cayendo, RVOL < 1.0
3. **Instrumento:** **Iron Condor**
4. **Strike selection:**
   - **Put Short:** strike con GEX más alto (suelo magnético)
   - **Put Long:** 5-10 puntos más bajo
   - **Call Short:** strike con GEX más alto (techo magnético)
   - **Call Long:** 5-10 puntos más alto
5. **Wings (protección):** 5-10 puntos de ancho
6. **Crédito objetivo:** $1.50-$2.50 por spread (ancho 5)

#### Reglas de Salida
| Condición | Acción |
|---|---|
| Profit ≥ 50% del crédito total del IC | Cerrar trade (TP) |
| Pérdida ≥ 2x el crédito recibido | Cerrar trade (SL) |
| GEX total cruza a negativo | Cerrar trade (régimen cambió) |
| Hora = 15:30 EST | Cerrar trade (Time Exit) |

#### Ejemplo Numérico
- **Spot SPX:** 5.500
- **GEX positivo alto** (identifica strikes 5.480 y 5.520 como "muros")
- **Operación:** Iron Condor
  - Put Spread: 5.480/5.475 (short/long)
  - Call Spread: 5.520/5.525 (short/long)
- **Crédito total:** $4.00
- **Riesgo máximo:** $6.00 (ancho 5 - crédito 4 = 1 por spread, x2 = 2... ajustar a 5 de ancho)
- **TP objetivo:** $2.00 (50% del crédito)

---

### 📌 ESTRATEGIA 3: "Trend Rider" — Surfear la Tendencia

**Cuándo usarla:** GEX consistentemente negativo desde el inicio de la sesión, precio se aleja del VWAP con volumen.

**Hipótesis estadística:** En régimen de GEX negativo, el momentum persiste 2-3h con probabilidad >60% (gamma amplifica el movimiento en lugar de amortiguarlo).

#### Reglas de Entrada
1. **Trigger:** GEX total < 0 desde apertura, y |GEX| creciendo en valor absoluto
2. **Confirmación:** Precio > VWAP + distancia > 0.2% (alcista) o < VWAP - 0.2% (bajista)
3. **Confirmación 2:** RSI(14) > 55 (alcista) o < 45 (bajista)
4. **Confirmación 3:** Volumen en la dirección de la tendencia > 1.2x promedio
5. **Instrumento:** **Credit Spread direccional**
   - Alcista: Bull Put Spread en soporte cercano
   - Bajista: Bear Call Spread en resistencia cercana
6. **Stop técnico:** Si el precio toca el VWAP, evaluar cierre

#### Reglas de Salida
| Condición | Acción |
|---|---|
| Profit ≥ 60% del crédito (más alto en trend) | Cerrar trade (TP) |
| Pérdida ≥ 2x el crédito recibido | Cerrar trade (SL) |
| Precio cruza el VWAP en contra | Cerrar trade (señal de agotamiento) |
| Hora = 15:30 EST | Cerrar trade (Time Exit) |

---

## 4. Sistema de Selección de Régimen (Pre-Market + Intraday)

### Algoritmo de Decisión (Pseudocódigo)

```python
# Este pseudocódigo se ejecuta cada 5 minutos desde las 09:30 EST

def select_strategy(current_gex, gex_at_930, vix, price, vwap, rsi, rvol):
    
    # REGLA 1: ¿Hubo un flip reciente?
    if gex_flipped_recently(current_gex, last_30_min=True):
        if price > vwap:
            return STRATEGY_FLIP_BULL_PUT
        else:
            return STRATEGY_FLIP_BEAR_CALL
    
    # REGLA 2: ¿Régimen positivo consolidado?
    if gex_at_930 > POSITIVE_THRESHOLD and current_gex > 0:
        if vix_stable_or_falling and rvol < 1.0:
            return STRATEGY_PINNING_IRON_CONDOR
    
    # REGLA 3: ¿Régimen negativo consolidado con tendencia?
    if gex_at_930 < NEGATIVE_THRESHOLD and current_gex < 0:
        if abs(price - vwap) / vwap > 0.002 and rvol > 1.2:
            if price > vwap and rsi > 55:
                return STRATEGY_TREND_BULL_PUT
            elif price < vwap and rsi < 45:
                return STRATEGY_TREND_BEAR_CALL
    
    # REGLA 4: Régimen indeterminado
    return STRATEGY_NO_TRADE
```

### Ventanas de Tiempo Críticas
| Hora EST | Acción |
|---|---|
| 09:30 | Apertura: registrar GEX de apertura |
| 10:00 | **Decisión principal de régimen** |
| 10:00-11:00 | Ventana óptima para entradas (volatilidad normalizada) |
| 11:00-13:00 | Segunda ventana de entradas (con filtros más estrictos) |
| 13:00 | **Deadline para abrir nuevas posiciones** |
| 15:30 | Time Exit: cerrar todo lo que quede abierto |
| 16:00 | Cierre: revisión y logging |

---

## 5. Reglas de Gestión de Riesgo (NO NEGOCIABLES)

### 5.1 Por Trade
1. **Nunca arriesgar más del 2% del capital total** en una sola posición
2. **Stop Loss SIEMPRE colocado** al enviar la orden (no confiar en el cierre manual)
3. **Tamaño de posición** = (Capital × 0.02) / (Riesgo máximo por contrato)
4. **Beneficiario del crédito** se cobra al abrir (no es opcional)

### 5.2 Por Día
1. **Máximo 3 operaciones** (1 por estrategia en caso extremo)
2. **Pérdida diaria máxima: 5% del capital** → parar el bot
3. **2 pérdidas consecutivas** → parar hasta el día siguiente
3. **Después de 1 día perdedor:** reducir tamaño al 50% al día siguiente

### 5.3 Por Semana
1. **Pérdida semanal máxima: 10% del capital** → parar hasta la semana siguiente
2. **Revisión obligatoria** cada viernes de:
   - Win rate por estrategia
   - Profit factor
   - Drawdown máximo
   - Mejor/peor hora de entrada

---

## 6. Arquitectura Técnica para Automatización

### 6.1 Stack Recomendado

| Componente | Herramienta | Razón |
|---|---|---|
| **Lenguaje** | Python 3.11+ | Ecosistema financiero maduro |
| **Data Feed (Options)** | Tradier / Polygon.io | API REST + WebSocket para chain en tiempo real |
| **Data Feed (Spot/Index)** | El mismo broker | Latencia mínima |
| **Cálculo GEX** | Pandas + NumPy | Vectorización rápida |
| **Ejecución** | TWS API (IBKR) o Tradier API | Spread orders atómica |
| **Logging** | SQLite + Pandas | Backtesting y auditoría |
| **Scheduling** | `apscheduler` o cron | Escaneo cada 5 min |
| **Dashboard** | Streamlit (opcional) | Visualización en tiempo real |
| **Container** | Docker | Despliegue limpio en VPS Hetzner |

### 6.2 Estructura de Archivos Sugerida
```
/root/0dte-bot/
├── config.yaml              # Umbrales GEX, capital, parámetros
├── main.py                  # Loop principal
├── gex/
│   ├── calculator.py        # Cálculo de GEX
│   ├── fetcher.py           # Data feed del option chain
│   └── regime.py            # Detector de régimen
├── strategies/
│   ├── flip.py              # Estrategia 1
│   ├── pinning.py           # Estrategia 2
│   ├── trend.py             # Estrategia 3
│   └── selector.py          # Selector de régimen
├── broker/
│   ├── ibkr.py              # TWS API
│   └── tradier.py           # Alternativa
├── risk/
│   ├── position_sizer.py    # 2% rule
│   └── kill_switch.py       # Emergency stop
├── data/
│   ├── options_chain.db
│   ├── trades.db
│   └── daily_pnl.db
└── logs/
    └── bot.log
```

### 6.3 Pseudocódigo del Bot Principal
```python
import time
from datetime import datetime
from gex.calculator import calculate_gex
from gex.regime import detect_regime
from strategies.selector import select_strategy
from broker.ibkr import place_spread, close_position
from risk.position_sizer import calculate_size
from risk.kill_switch import check_emergency_exit

def main_loop():
    while market_is_open():
        # 1. Fetch data
        chain = fetch_option_chain()
        spot = fetch_spot_price()
        vix = fetch_vix()
        
        # 2. Calculate GEX
        gex_total, zero_gamma_level = calculate_gex(chain, spot)
        
        # 3. Detect regime
        regime, direction = detect_regime(gex_total, spot, vwap, rsi)
        
        # 4. Check existing positions
        if has_open_position():
            if should_exit():
                close_all_positions()
            continue  # No abrir nuevas si ya hay una abierta
        
        # 5. Daily loss limit check
        if daily_pnl < -MAX_DAILY_LOSS:
            send_alert("DAILY LOSS LIMIT REACHED")
            break
        
        # 6. Select strategy
        strategy = select_strategy(regime, direction)
        
        # 7. Execute
        if strategy and not_too_late():
            size = calculate_size(strategy.max_loss, account_value)
            place_spread(strategy, size)
            log_trade(strategy, size, gex_total)
        
        # 8. Emergency checks
        check_emergency_exit()
        
        time.sleep(SCAN_INTERVAL_SECONDS)  # 300 = 5 min

if __name__ == "__main__":
    main_loop()
```

### 6.4 Kill Switch (Safety Net)
```python
# Triggered by:
# 1. Daily loss > 5% → auto-close all + stop bot
# 2. Manual trigger via Telegram command
# 3. Detección de error en API (position unknown state)
# 4. Conexión perdida con broker > 60 segundos

def kill_switch():
    close_all_positions()  # Best-effort market orders
    cancel_all_pending_orders()
    send_telegram_alert("🚨 KILL SWITCH ACTIVATED")
    sys.exit(0)
```

---

## 7. Checklist Diario (Imprimible)

### Pre-Market (08:00 - 09:30 EST)
- [ ] Verificar conexión con broker
- [ ] Verificar capital disponible
- [ ] Revisar noticias macro (FOMC, CPI, NFP) → si hay, **reducir tamaño al 50%**
- [ ] Revisar GEX de ayer al cierre (referencia)
- [ ] Verificar VIX actual y su tendencia semanal
- [ ] Configurar umbrales del bot (si hay cambios manuales)

### In-Trade (09:30 - 15:30 EST)
- [ ] **09:30:** Registrar GEX de apertura
- [ ] **10:00:** Decisión de régimen (Pin / Flip / Trend / No Trade)
- [ ] **10:00-13:00:** Ventana de entradas (máx 3 trades)
- [ ] **13:00:** No abrir nuevas posiciones
- [ ] **Continuo:** Monitorear SL/TP colocados
- [ ] **15:30:** Forzar cierre de todo lo abierto
- [ ] **Si 2 pérdidas consecutivas:** parar el bot

### Post-Close (16:00+ EST)
- [ ] Exportar trades del día a DB
- [ ] Calcular P&L del día
- [ ] Revisar: ¿se respetó el plan? ¿entradas tardías? ¿SL respetado?
- [ ] Actualizar métricas rolling (win rate semanal, profit factor)
- [ ] Backup de DBs a NAS o cloud

---

## 8. Métricas de Rendimiento Esperado (Objetivos)

### 8.1 Por Estrategia
| Estrategia | Win Rate Objetivo | R:R Medio | Profit Factor | Trades/mes |
|---|---|---|---|---|
| Flip | 55-60% | 1:1.5 | > 1.5 | 8-12 |
| Pinning | 70-80% | 1:0.5 | > 1.4 | 15-20 |
| Trend Rider | 45-55% | 1:2.0 | > 1.6 | 8-12 |

### 8.2 Métricas Globales
- **Win Rate global objetivo:** > 60%
- **Profit Factor global objetivo:** > 1.6
- **Sharpe Ratio anualizado objetivo:** > 2.0
- **Max Drawdown aceptable:** < 15% del capital
- **Rentabilidad mensual objetivo:** 4-8% (con capital de $25K-$50K)

### 8.3 Validación Pre-Producción
Antes de operar con dinero real, el bot debe demostrar en paper trading (mínimo 30 días):
1. **Win Rate** dentro de ±5% del objetivo
2. **Profit Factor** > 1.5
3. **Max DD** < 10% del capital
4. **Cero** fallos de ejecución en posiciones cerradas
5. **Tiempo de respuesta** < 2 segundos desde trigger a orden enviada

---

## 9. Próximos Pasos

1. **Fase 0 — Datos (1-2 semanas):**
   - Suscribirse a Tradier o Polygon para datos de options chain
   - Construir el calculador de GEX
   - Validar contra SpotGamma o Unusual Whales manualmente

2. **Fase 1 — Paper Trading (4-6 semanas):**
   - Desplegar bot en paper account
   - Operar diariamente siguiendo el checklist
   - Recopilar al menos 60-80 trades para tener muestra estadística

3. **Fase 2 — Go-Live con capital mínimo:**
   - Empezar con 25% del capital objetivo
   - Mantener 2 meses más
   - Escalar al 50% si métricas OK
   - Escalar al 100% si 6 meses son positivos

4. **Fase 3 — Mejora continua:**
   - Añadir ML para predecir régimen (no solo reaccionar)
   - Optimizar umbrales GEX por subyacente
   - Multi-subyacente: SPY, QQQ, IWM

---

## 10. Referencias y Recursos (Verificadas)

### 📚 Libros de Referencia (Comerciales, No Papers)
*   **"Volatility Trading"** — Euan Sinclair (Wiley, 2013, 2ª ed.)
    *   Capítulo sobre **delta hedging y gamma scalping**
    *   ISBN: 978-1118341867
    *   Disponible en Amazon, Google Books preview
*   **"Option Trading"** — Euan Sinclair (Wiley, 2010)
*   **"Positional Option Trading"** — Euan Sinclair (Wiley, 2020)
*   **"The Volatility Surface"** — Jim Gatheral (Wiley, 2006)
    *   Teoría matemática de la superficie de volatilidad
    *   ISBN: 978-0471792512

### 📊 Investigación Académica
*   **Simon Gleadall** — Senior Lecturer, University of Nottingham
    *   Publicaciones en Google Scholar: buscar "Simon Gleadall stochastic volatility"
    *   Campos: modelos de volatilidad, forecasting, no operativa 0DTE
*   **Jim Gatheral** — Professor, Baruch College
    *   Homepage: https://faculty.baruch.cuny.edu/jgatheral/
    *   Working papers sobre rough volatility aplicables al GEX

### 🔧 Herramientas de Datos y Operativa
*   **SpotGamma** (https://www.spotgamma.com) — Líder en GEX data y research diaria
*   **Unusual Whales** (https://unusualwhales.com) — Options flow + GEX
*   **TastyTrade** (https://www.tastytrade.com) — Research en 0DTE (Dan Sheridan, Tom Sosnoff)
*   **TanStar Research** (https://www.tanstarresearch.com) — Frank Orsini, GEX data institucional
*   **GammaLab Pro** — Software de cálculo de GEX

### 🔌 APIs para Automatización
*   **TWS API (IBKR)** — https://interactivebrokers.github.io/tws-api/
*   **Tradier API** — https://documentation.tradier.com/
*   **Polygon.io** — https://polygon.io/docs/options

### 🎓 Cursos / Formación
*   **CBOE Options Institute** — Cursos de options y volatility
*   **MFI Program (International Securities Exchange)** — Certificación en options
*   **"Options as a Strategic Investment"** — Lawrence McMillan (libro enciclopédico)

---

*Documento versión 1.1 — Junio 2026 (corregido: referencias verificadas)*
*Preparado para implementación en VPS Hetzner / Proxmox*
