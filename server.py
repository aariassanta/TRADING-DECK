import asyncio
import logging
import traceback

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from engine import IBKREngine

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="SPX Trading Deck API")

# Allow requests from our React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
class AppState:
    """Holds IBKR connection state, active WebSockets, and a last-metrics cache."""

    def __init__(self):
        self.engine = None
        self.connected = False
        self.active_websockets = []
        # Cache of the last successful fetch_market_metrics() result.
        # Used by monitor_levels() to compare spot vs Walls without re-fetching.
        self.metrics_cache: dict = {}
        # Track previous side of gamma flip to detect crossings
        self._prev_above_flip: bool | None = None
        # Track two consecutive ticks for Wall-break confirmation
        self._call_wall_breach_count: int = 0
        self._put_wall_breach_count: int = 0

state = AppState()

# WebSocket Manager
class ConnectionManager:
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        state.active_websockets.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(state.active_websockets)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in state.active_websockets:
            state.active_websockets.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total: {len(state.active_websockets)}")

    async def broadcast(self, message: dict):
        for connection in state.active_websockets:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                self.disconnect(connection)

manager = ConnectionManager()

# --- Models ---
class ConnectRequest(BaseModel):
    port: int = 4002

class SpreadRequest(BaseModel):
    """Parameters for a spread order request sent by the frontend."""

    trade_type: str  # "CCS", "PCS", "IC"
    qty: int
    target_mode: str  # "Delta", "R:R", or "GEX"
    target_value: float  # Ignored when target_mode == "GEX"
    width: int
    tp_pct: float
    sl_ratio: float
    transmit: bool = False
    
class StatusResponse(BaseModel):
    status: str
    message: str

# --- API Endpoints ---

@app.post("/api/connect")
async def connect_ibkr(req: ConnectRequest):
    if state.connected and state.engine and state.engine.ib.isConnected():
        return {"status": "success", "message": "Already connected to IBKR."}
    
    try:
        from engine import IBKREngine
        import ib_async.util
        # We don't want to block the FastAPI async loop, so IBKR runs natively inside it.
        # But IBKREngine's ib.connect() is synchronous, so we run it carefully or use ib.connectAsync()
        logger.info(f"Connecting to IBKR on port {req.port}...")
        
        # IBKREngine does ib.connect() locally which creates a nested loop if not careful.
        # It's better to wrap in a thread or just rely on ib_insync's async magic 
        # (It uses util.patchAsyncio automatically).
        state.engine = IBKREngine(port=req.port)
        success, err = await state.engine.connect_async()
        
        if success and state.engine.ib.isConnected():
            state.connected = True
            # Override logging to broadcast to frontend!
            # wait, IBKREngine doesn't have .log directly, but we can intercept it if we want.
            return {"status": "success", "message": f"Connected on port {req.port}"}
        else:
            return {"status": "error", "message": f"Failed: {err}"}
            
    except Exception as e:
        logger.error(f"Connection error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/disconnect")
async def disconnect_ibkr():
    if state.engine:
        try:
            state.engine.disconnect()
        except:
            pass
    state.connected = False
    state.engine = None
    return {"status": "success", "message": "Disconnected."}

@app.get("/api/status")
async def get_status():
    is_connected = state.connected and state.engine and state.engine.ib.isConnected()
    return {"connected": is_connected}

@app.get("/api/metrics")
async def get_metrics():
    """Manually triggers a fresh GEX scan, caches the result, and returns the payload."""
    if not state.connected or not state.engine:
        raise HTTPException(status_code=400, detail="Not connected to IBKR.")

    try:
        await manager.broadcast({"type": "log", "message": "Fetching 0DTE chain data. This takes a few seconds..."})
        data = await state.engine.fetch_market_metrics()

        if data:
            # Cache for monitor_levels() to use without re-fetching
            state.metrics_cache = data
            await manager.broadcast({"type": "metrics", "data": data})
            return {"status": "success", "data": data}
        else:
            raise HTTPException(status_code=500, detail="Failed to calculate metrics.")

    except Exception as e:
        logger.error(f"Metrics error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
async def get_history():
    """Reads today's intraday CSV from history/ and returns points for the Bubble Map.
    Falls back to the most recent file if today's file doesn't exist yet.
    """
    import os, glob
    import datetime
    import pandas as pd
    
    history_dir = os.path.join(os.path.dirname(__file__), 'history')
    if not os.path.exists(history_dir):
        return {"data": [], "date": ""}

    today_str = datetime.date.today().strftime('%Y%m%d')
    
    # Try to find today's file first (any expiry suffix is fine, grab any matching today)
    today_files = glob.glob(os.path.join(history_dir, f"gex_intraday_{today_str}_*.csv"))
    
    if today_files:
        # Merge all expiry files for today into a single DataFrame if multiple exist
        target_file = sorted(today_files)[0]
        date_str = today_str
    else:
        # No data yet for today — fall back to most recent historical file
        all_files = glob.glob(os.path.join(history_dir, "gex_intraday_*.csv"))
        if not all_files:
            return {"data": [], "date": ""}
        target_file = max(all_files, key=os.path.getctime)
        date_str = os.path.basename(target_file).split('_')[2]
    
    try:
        df = pd.read_csv(target_file)
        if df.empty:
            return {"data": [], "date": date_str}
        
        # Filter to market hours only: 09:30 to 16:15 EST
        if 'Timestamp' in df.columns:
            df = df[df['Timestamp'] >= '09:30:00']
        
        records = df.to_dict(orient='records')
        return {"data": records, "date": date_str}
        
    except Exception as e:
        logger.error(f"Error reading history: {e}")
        return {"data": [], "date": ""}

@app.post("/api/trade")
async def execute_trade(req: SpreadRequest):
    if not state.connected or not state.engine:
        raise HTTPException(status_code=400, detail="Not connected to IBKR.")
        
    try:
        await manager.broadcast({"type": "log", "message": f"[{req.trade_type}] Structuring Order (Mode: {req.target_mode}={req.target_value}, W:{req.width}, Stop:{req.sl_ratio}x)..."})
        
        # execute_spread is an async function
        asyncio.create_task(state.engine.execute_spread(
            spread_type=req.trade_type,
            qty=req.qty,
            target_mode=req.target_mode,
            target_value=req.target_value,
            width=req.width,
            tp_pct=req.tp_pct,
            sl_ratio=req.sl_ratio,
            transmit=req.transmit
        ))
        
        await manager.broadcast({"type": "log", "message": f"[{req.trade_type}] Order engine task started successfully."})
        return {"status": "success", "message": "Order processing started."}
        
    except Exception as e:
        logger.error(f"Trade error: {traceback.format_exc()}")
        await manager.broadcast({"type": "log", "message": f"ERROR: {str(e)}"})
        raise HTTPException(status_code=500, detail=str(e))

# --- WebSockets ---

@app.websocket("/ws/market_data")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages from the client right now, so we just keep the socket open
            # and wait for an unexpected disconnect
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- Background Loops ---

async def auto_refresh_loop():
    """Background task that ticks every 2 minutes and pushes full metrics."""
    logger.info("Started 2-minute Auto-Refresh loop.")
    while True:
        await asyncio.sleep(120)  # 2 minutes

        if state.connected and state.engine:
            try:
                logger.info("Executing periodic 2-minute GEX refresh...")
                await manager.broadcast({"type": "log", "message": "Auto-refresh: 2-minute tick triggered."})
                data = await state.engine.fetch_market_metrics()
                if data:
                    state.metrics_cache = data  # Keep cache in sync
                    await manager.broadcast({"type": "metrics", "data": data})
                    await manager.broadcast({"type": "log", "message": "Display updated successfully."})
            except Exception as e:
                logger.error(f"Auto-refresh error: {e}")


async def monitor_levels():
    """
    Lightweight spot-only monitor that runs every 30 seconds.

    Reads the last cached market metrics (no full chain re-fetch) and compares
    the current SPX spot price against the key GEX levels. Emits WebSocket
    'alert' messages when thresholds are crossed.

    Alert types emitted:
      GAMMA_FLIP_CROSS        - spot crossed the gamma flip line
      APPROACHING_CALL_WALL   - spot within 0.25% of call wall (from below)
      APPROACHING_PUT_WALL    - spot within 0.25% of put wall (from above)
      CALL_WALL_BREAK         - spot closed above call wall for 2 consecutive ticks
      PUT_WALL_BREAK          - spot closed below put wall for 2 consecutive ticks
      ENTERING_BREAKOUT_ZONE  - spot is inside a BREAKOUT (GEX-negative) zone
      CONFLUENCE_SPIKE        - a BREAKOUT zone with confluence is active near spot
    """
    logger.info("Started 30-second Level Monitor loop.")

    # Keep a persistent SPX index contract to avoid re-qualifying each tick
    spx_contract = None

    while True:
        await asyncio.sleep(30)  # 30-second check interval

        if not state.connected or not state.engine or not state.metrics_cache:
            continue  # Nothing to compare against yet

        try:
            from ib_async import Index
            engine = state.engine
            cache = state.metrics_cache

            # --- Fetch spot price with a short-lived ticker ---
            if spx_contract is None:
                spx_contract = Index('SPX', 'CBOE')
                await engine.ib.qualifyContractsAsync(spx_contract)

            engine.ib.reqMarketDataType(3)  # Delayed/live
            ticker = engine.ib.reqMktData(spx_contract, '', False, False)
            await asyncio.sleep(1.5)  # Brief wait for data
            spot = ticker.marketPrice()
            engine.ib.cancelMktData(spx_contract)

            import math
            if not spot or math.isnan(spot) or spot <= 0:
                logger.warning("monitor_levels: could not read spot price, skipping tick.")
                continue

            # --- Pull levels from cache ---
            call_wall = cache.get('call_wall')
            put_wall = cache.get('put_wall')
            gamma_flip = cache.get('gamma_flip')
            gex_zones = cache.get('gex_zones', [])

            alerts_to_emit = []

            # 1. Gamma Flip crossing detection
            if gamma_flip and isinstance(gamma_flip, (int, float)):
                above_flip = spot > gamma_flip
                if state._prev_above_flip is not None and above_flip != state._prev_above_flip:
                    alerts_to_emit.append({
                        "type": "alert",
                        "level": "GAMMA_FLIP_CROSS",
                        "value": gamma_flip,
                        "spot": round(spot, 2),
                        "distance_pct": round(abs(spot - gamma_flip) / spot * 100, 3),
                        "setup_suggestion": (
                            "Market regime changed: now LONG_GAMMA (stabilising)"
                            if above_flip else
                            "Market regime changed: now SHORT_GAMMA (volatile)"
                        ),
                    })
                state._prev_above_flip = above_flip

            # 2. Approaching Call Wall
            if call_wall:
                dist_call = (call_wall - spot) / spot  # positive = wall is above
                if 0 < dist_call < 0.0025:  # Within 0.25% above
                    alerts_to_emit.append({
                        "type": "alert",
                        "level": "APPROACHING_CALL_WALL",
                        "value": call_wall,
                        "spot": round(spot, 2),
                        "distance_pct": round(dist_call * 100, 3),
                        "setup_suggestion": f"CCS fade \u2264 {call_wall} | consider put credit spread below",
                        "prefill": {
                            "type": "CCS",
                            "target_mode": "GEX",
                            "anchor": call_wall,
                        },
                    })

            # 3. Approaching Put Wall
            if put_wall:
                dist_put = (spot - put_wall) / spot  # positive = wall is below
                if 0 < dist_put < 0.0025:  # Within 0.25% below
                    alerts_to_emit.append({
                        "type": "alert",
                        "level": "APPROACHING_PUT_WALL",
                        "value": put_wall,
                        "spot": round(spot, 2),
                        "distance_pct": round(dist_put * 100, 3),
                        "setup_suggestion": f"PCS fade \u2265 {put_wall} | consider call credit spread above",
                        "prefill": {
                            "type": "PCS",
                            "target_mode": "GEX",
                            "anchor": put_wall,
                        },
                    })

            # 4. Wall break confirmation (2 consecutive ticks)
            if call_wall and spot > call_wall:
                state._call_wall_breach_count += 1
                if state._call_wall_breach_count >= 2:
                    fade_zones_above = [
                        z for z in gex_zones
                        if z['type'] == 'FADE' and z['peak_strike'] > call_wall
                    ]
                    next_tp = fade_zones_above[0]['peak_strike'] if fade_zones_above else None
                    alerts_to_emit.append({
                        "type": "alert",
                        "level": "CALL_WALL_BREAK",
                        "value": call_wall,
                        "spot": round(spot, 2),
                        "distance_pct": round((spot - call_wall) / spot * 100, 3),
                        "setup_suggestion": (
                            f"Breakout ABOVE Call Wall {call_wall}"
                            + (f" | next FADE zone: {next_tp}" if next_tp else "")
                        ),
                        "prefill": {
                            "type": "CCS",
                            "target_mode": "GEX",
                            "anchor": next_tp or call_wall,
                        },
                    })
                    state._call_wall_breach_count = 0  # Reset after emitting
            else:
                state._call_wall_breach_count = 0

            if put_wall and spot < put_wall:
                state._put_wall_breach_count += 1
                if state._put_wall_breach_count >= 2:
                    fade_zones_below = [
                        z for z in gex_zones
                        if z['type'] == 'FADE' and z['peak_strike'] < put_wall
                    ]
                    next_tp = fade_zones_below[0]['peak_strike'] if fade_zones_below else None
                    alerts_to_emit.append({
                        "type": "alert",
                        "level": "PUT_WALL_BREAK",
                        "value": put_wall,
                        "spot": round(spot, 2),
                        "distance_pct": round((put_wall - spot) / spot * 100, 3),
                        "setup_suggestion": (
                            f"Breakdown BELOW Put Wall {put_wall}"
                            + (f" | next FADE zone: {next_tp}" if next_tp else "")
                        ),
                        "prefill": {
                            "type": "PCS",
                            "target_mode": "GEX",
                            "anchor": next_tp or put_wall,
                        },
                    })
                    state._put_wall_breach_count = 0
            else:
                state._put_wall_breach_count = 0

            # 5. Entering BREAKOUT zone (GEX-negative cluster near spot)
            for zone in gex_zones:
                if zone['type'] != 'BREAKOUT':
                    continue
                peak = zone['peak_strike']
                proximity = abs(peak - spot) / spot
                if proximity <= 0.002:  # Within 0.2% of zone peak
                    level_key = (
                        "CONFLUENCE_SPIKE" if zone['confluence']
                        else "ENTERING_BREAKOUT_ZONE"
                    )
                    direction = "CCS" if spot > peak else "PCS"
                    alerts_to_emit.append({
                        "type": "alert",
                        "level": level_key,
                        "value": peak,
                        "spot": round(spot, 2),
                        "distance_pct": round(proximity * 100, 3),
                        "setup_suggestion": (
                            f"{direction} breakout at {peak} "
                            f"{'(CONFLUENCE)' if zone['confluence'] else ''}"
                        ),
                        "prefill": {
                            "type": direction,
                            "target_mode": "GEX",
                            "anchor": peak,
                        },
                    })

            # Broadcast all alerts collected this tick
            for alert in alerts_to_emit:
                logger.info(f"Level alert: {alert['level']} @ {alert['value']} (spot={spot:.2f})")
                await manager.broadcast(alert)

        except Exception as e:
            logger.error(f"monitor_levels error: {e}")

@app.on_event("startup")
async def startup_event():
    """Launch both the 2-minute full-refresh loop and the 30-second level monitor."""
    asyncio.create_task(auto_refresh_loop())
    asyncio.create_task(monitor_levels())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
