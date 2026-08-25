# Plan Gamma Hunter — Trading Deck

## Fecha
2026-08-12

## Estado
Aprobado para implementación.

## 1. Objetivo

Añadir una nueva vista denominada **Gamma Hunter** al dashboard del Trading Deck. La vista mostrará datos operativos avanzados de opciones SPX 0DTE: escalera de strikes, Gamma Exposure, IV Skew, posición activa, salud del motor y un tape de señales del bot.

## 2. Decisiones de diseño

| Punto | Decisión |
|---|---|
| Ubicación | Nueva pestaña `gamma-hunter` junto a `heatmap`, `interval`, `netdrift`. El HeatMap actual se mantiene intacto. |
| Posición activa | Actualización en tiempo real vía WebSocket (`type: "position"`). |
| Bid/ask por strike | Se incluirán en `strike_ladder` porque están disponibles desde IBKR. |
| Signal Tape | Usará señales del bot (`bot_engine.py`). |

## 3. Backend

### 3.1 Enriquecer `fetch_market_metrics()` en `engine.py`

Añadir al payload:

- `strike_ladder`: lista de strikes con call/put bid, ask, last, volume, OI y GEX.
- `gex_summary`: totales de call GEX, put GEX, net GEX y máximo absoluto.
- `iv_skew`: IV por strike/moneyness para calls y puts.
- `put_call_ratio`: ratio de put/call por volumen y OI.
- `engine_health`: uptime, polls, last_poll_ms, strikes trackeados, errores.

### 3.2 Posición activa

- Nuevo método `get_position_summary()` en `engine.py` usando `ib.positions()` y `ib.portfolio()`.
- Nuevo endpoint `GET /api/position` en `server.py`.
- Broadcast WebSocket periódico: `{"type": "position", "data": {...}}`.

### 3.3 Señales del bot

- Extender `/api/bot/signals` para devolver:
  - `timestamp`, `side` (`C`/`P`), `strike`, `z_score`, `ratio`, `volume`, `ask`, `status` (`EXECUTED`, `PENDING`, `OUT WINDOW`).

## 4. Frontend

### 4.1 Tipos

Añadir en `useMarketData.ts`:

- `StrikeLadderRow`
- `GexSummary`
- `IvSkewPoint`
- `PositionData`
- `BotTapeSignal`

### 4.2 Hook

Extender `useMarketData` para:
- Escuchar mensajes `"position"` por WebSocket.
- Cargar señales iniciales desde `/api/bot/signals`.

### 4.3 Componentes

Crear en `frontend/src/components/gamma-hunter/`:

- `GammaHunter.tsx`: layout principal en grid de 12 columnas.
- `HeaderStats.tsx`: P&L, spot, strikes, señales, hit rate, P/C, next window.
- `StrikeLadder.tsx`: escalera de strikes.
- `GammaExposureBars.tsx`: barras de GEX por strike.
- `IvSkewChart.tsx`: gráfico de IV skew con `recharts`.
- `ActivePosition.tsx`: posición activa en tiempo real.
- `EngineHealth.tsx`: salud del motor.
- `SignalTape.tsx`: feed de señales del bot.

### 4.4 Integración

En `App.tsx`:
- Añadir `'gamma-hunter'` al tipo de tab.
- Lazy-load del componente.
- Añadir botón de navegación.

## 5. Fases de implementación

1. Backend: métricas enriquecidas.
2. Backend: posición activa y endpoint.
3. Backend: broadcast WebSocket de posición.
4. Backend: formatear señales del bot para el tape.
5. Frontend: tipos y hook.
6. Frontend: esqueleto Gamma Hunter + tab.
7. Frontend: paneles estáticos (header, ladder, gamma bars).
8. Frontend: gráfico IV Skew.
9. Frontend: posición activa + tape.
10. Pulido, verificación visual y ajustes.

## 6. Riesgos y mitigaciones

- Rate limits de IBKR: posición actualizada cada 15-30 segundos.
- Datos de IV faltantes: mostrar `--` como fallback.
- Bundle size: lazy-load completo del Gamma Hunter.
- No se modifica lógica de trading crítica; solo lectura de posiciones y enriquecimiento de métricas.

## 7. Notas

- Siguiendo `CLAUDE.md`, no se agrega funcionalidad de trading sin aprobar.
- `App.tsx` no se fragmenta; solo se añade navegación y lazy-load.
- `engine.py` solo recibe métodos de lectura/enriquecimiento, no cambios en estrategias ni órdenes.
