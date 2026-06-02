import asyncio
import logging
import time
import traceback
import os
import glob
import datetime
import math
import pandas as pd

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from engine import IBKREngine

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class IBFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "Error 354" in msg or "Error 300" in msg:
            return False
        return True

logging.getLogger('ib_async.wrapper').addFilter(IBFilter())

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
        self.engine_live = None
        self.connected_live = False
        self.active_websockets = []
        # Cache of the last successful fetch_market_metrics() result.
        # Used by monitor_levels() to compare spot vs Walls without re-fetching.
        self.metrics_cache: dict = {}
        self.is_fetching: bool = False
        # Track previous side of gamma flip to detect crossings
        self._prev_above_flip: bool | None = None
        # Track two consecutive ticks for Wall-break confirmation
        self._call_wall_breach_count: int = 0
        self._put_wall_breach_count: int = 0
        # Health & observability
        self.start_time: float = time.time()
        self.last_refresh_time: float | None = None
        self.last_error: str | None = None

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
        """Fan-out a message to all clients in parallel. Drop closed connections."""
        connections = list(state.active_websockets)  # Snapshot
        if not connections:
            return
        results = await asyncio.gather(
            *[conn.send_json(message) for conn in connections],
            return_exceptions=True
        )
        # Drop connections that failed
        for conn, result in zip(connections, results):
            if isinstance(result, Exception):
                self.disconnect(conn)

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
    target_env: str = "paper"  # "paper" or "live"
    
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
        state.engine = None
        state.connected = False
        
    if state.engine_live:
        try:
            state.engine_live.disconnect()
        except:
            pass
        state.engine_live = None
        state.connected_live = False
        
    return {"status": "success", "message": "Disconnected from all IBKR engines."}

@app.post("/api/connect_live")
async def connect_live_ibkr():
    if state.connected_live and state.engine_live and state.engine_live.ib.isConnected():
        return {"status": "success", "message": "Already connected to Live IBKR."}
    
    try:
        from engine import IBKREngine
        logger.info("Connecting to LIVE IBKR on port 4001...")
        
        state.engine_live = IBKREngine(port=4001, client_id=2) # Ensure a different client_id
        success, err = await state.engine_live.connect_async()
        
        if success and state.engine_live.ib.isConnected():
            state.connected_live = True
            return {"status": "success", "message": "Connected to Live account on port 4001"}
        else:
            return {"status": "error", "message": f"Live Connection Failed: {err}"}
            
    except Exception as e:
        logger.error(f"Live Connection error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def get_status():
    is_connected = state.connected and state.engine and state.engine.ib.isConnected()
    is_connected_live = state.connected_live and state.engine_live and state.engine_live.ib.isConnected()
    return {"connected": is_connected, "connected_live": is_connected_live}

@app.get("/api/health")
async def health():
    """Health check endpoint with server uptime, last refresh age, and client count."""
    last_refresh_age = (
        time.time() - state.last_refresh_time if state.last_refresh_time else None
    )
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - state.start_time, 1),
        "last_refresh_age_seconds": round(last_refresh_age, 1) if last_refresh_age is not None else None,
        "metrics_loaded": bool(state.metrics_cache),
        "ws_clients": len(state.active_websockets),
    }

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

@app.get("/api/history/net_drift")
async def get_premium_drift():
    """Reads the premium drift CSV from history/ and returns data points for the 0DTE Net Drift chart."""
    history_dir = os.path.join(os.path.dirname(__file__), 'history')
    if not os.path.exists(history_dir):
        return {"data": [], "date": ""}

    today_str = datetime.date.today().strftime('%Y%m%d')
    # Use today's file or the most recent historical file if today's is missing
    target_file = os.path.join(history_dir, f"premium_drift_0dte_{today_str}.csv")

    if not os.path.exists(target_file):
        all_files = glob.glob(os.path.join(history_dir, "premium_drift_0dte_*.csv"))
        if not all_files:
            return {"data": [], "date": ""}
        target_file = max(all_files, key=os.path.getctime)

    date_str = os.path.basename(target_file).split('_')[2]
    
    try:
        df = pd.read_csv(target_file)
        if df.empty:
            return {"data": [], "date": date_str}
            
        data_list = []
        for _, row in df.iterrows():
            data_list.append({
                "time": row["Timestamp"],
                "Spot": float(row["Spot"]),
                "Calls": float(row["CallPremium"]),
                "Puts": float(row["PutPremium"]),
                "Volume": int(row["Volume"])
            })
            
        return {"data": data_list, "date": date_str}
    except Exception as e:
        logger.error(f"Error reading premium drift history: {e}")
        return {"data": [], "date": ""}

@app.get("/api/history")
async def get_history():
    """Reads today's intraday CSV from history/ and returns points for the Bubble Map.
    Falls back to the most recent file if today's file doesn't exist yet.
    """
    history_dir = os.path.join(os.path.dirname(__file__), 'history')
    if not os.path.exists(history_dir):
        return {"data": [], "date": ""}

    today_str = datetime.date.today().strftime('%Y%m%d')
    
    # Try to find today's file first (any expiry suffix is fine, grab any matching today)
    today_files = glob.glob(os.path.join(history_dir, f"gex_intraday_{today_str}_*.csv"))
    
    if today_files:
        # Actively select the file that is currently receiving data (latest modification), 
        # bypassing stale nocturnal chains that sort alphabetically higher.
        target_file = max(today_files, key=os.path.getmtime)
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
        
        # You can optionally filter here if needed, but returning all 
        # collected intraday data is better so the pre-market is visible.
        # if 'Timestamp' in df.columns:
        #     df = df[df['Timestamp'] >= '09:30:00']
        
        records = df.to_dict(orient='records')
        return {"data": records, "date": date_str}
        
    except Exception as e:
        logger.error(f"Error reading history: {e}")
        return {"data": [], "date": ""}

@app.post("/api/trade")
async def execute_trade(req: SpreadRequest):
    if not state.connected or not state.engine:
        raise HTTPException(status_code=400, detail="Primary Data/Paper engine not connected to IBKR.")
        
    try:
        await manager.broadcast({"type": "log", "message": f"[{req.trade_type}] Structuring Order (Mode: {req.target_mode}={req.target_value}, W:{req.width}, Env:{req.target_env.upper()})..."})
        
        async def run_and_notify():
            # Dual-routing logic: Paper is always mandatory.
            target_engines = [state.engine]
            if req.target_env == "live":
                if not state.engine_live or not state.engine_live.ib.isConnected():
                    await manager.broadcast({"type": "log", "message": f"❌ ABORTED: Live engine not connected. Connect Live first."})
                    return
                target_engines.append(state.engine_live)
            
            for index, target_eng in enumerate(target_engines):
                env_label = "LIVE" if req.target_env == "live" and index == 1 else "PAPER"
                try:
                    await manager.broadcast({"type": "log", "message": f"[{req.trade_type}] Submitting to {env_label} engine..."})
                    await target_eng.execute_spread(
                        spread_type=req.trade_type,
                        qty=req.qty,
                        target_mode=req.target_mode,
                        target_value=req.target_value,
                        width=req.width,
                        tp_pct=req.tp_pct,
                        sl_ratio=req.sl_ratio,
                        transmit=req.transmit
                    )
                except Exception as ex:
                    logger.error(f"Trade execution failed on {env_label}: {ex}")
                    await manager.broadcast({"type": "log", "message": f"❌ [{env_label}] ABORTED: {str(ex)}"})

        # execute_spread is an async function
        asyncio.create_task(run_and_notify())
        
        await manager.broadcast({"type": "log", "message": f"[{req.trade_type}] Order engine task started successfully."})
        return {"status": "success", "message": "Trade execution initiated in background."}
        
    except Exception as e:
        logger.error(f"Trade error: {traceback.format_exc()}")
        await manager.broadcast({"type": "log", "message": f"ERROR: {str(e)}"})
        raise HTTPException(status_code=500, detail=str(e))

# --- WebSockets ---

@app.websocket("/ws/market_data")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Send initial connection status so the client doesn't need a separate /api/status fetch
    is_connected = state.connected and state.engine and state.engine.ib.isConnected()
    is_connected_live = state.connected_live and state.engine_live and state.engine_live.ib.isConnected()
    try:
        await websocket.send_json({"type": "status", "connected": is_connected, "connected_live": is_connected_live})
    except Exception:
        pass  # If send fails, the disconnect handler will clean up
    try:
        while True:
            # One-way server-push socket — wait for disconnect only
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- Background Loops ---

async def auto_refresh_loop():
    """Background task that ticks every minute and pushes full metrics.
    Wraps each iteration in try/except so a single failure cannot kill the loop."""
    logger.info("Started 1-minute Auto-Refresh loop.")
    while True:
        try:
            await asyncio.sleep(60)

            if state.connected and state.engine:
                logger.info("Executing periodic 1-minute GEX refresh...")
                state.last_refresh_time = time.time()
                await manager.broadcast({"type": "log", "message": "Auto-refresh: 1-minute tick triggered."})
                data = await state.engine.fetch_market_metrics()
                if data:
                    data['_timestamp'] = state.last_refresh_time  # For client-side ordering
                    state.metrics_cache = data  # Keep cache in sync
                    await manager.broadcast({"type": "metrics", "data": data})
                    await manager.broadcast({"type": "log", "message": "Display updated successfully."})
        except asyncio.CancelledError:
            logger.info("Auto-refresh loop cancelled (shutdown).")
            break
        except Exception as e:
            logger.error(f"Auto-refresh error: {e}", exc_info=True)
            await asyncio.sleep(5)  # Backoff before retrying after a failure


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
                spx_contract = Index('SPX', 'CBOE', currency='USD', conId=416904)
                try:
                    await asyncio.wait_for(engine.ib.qualifyContractsAsync(spx_contract), timeout=3.0)
                except Exception:
                    # Ignore timeout, conId is hardcoded so hashability is preserved
                    pass

            engine.ib.reqMarketDataType(3)  # Delayed/live
            ticker = engine.ib.reqMktData(spx_contract, '', False, False)
            # Wait a bit longer to allow the ticker to populate
            await asyncio.sleep(1.5)

            spot = ticker.marketPrice()
            import math

            # Fallback for pre-market or illiquid hours when marketPrice() is NaN
            if not spot or math.isnan(spot) or spot <= 0:
                if ticker.last and ticker.last > 0:
                    spot = ticker.last
                elif ticker.close and ticker.close > 0:
                    spot = ticker.close
                else:
                    # Second attempt: wait a bit more and retry
                    await asyncio.sleep(2.0)
                    spot = ticker.marketPrice()
                    if not spot or math.isnan(spot) or spot <= 0:
                        if ticker.last and ticker.last > 0:
                            spot = ticker.last
                        elif ticker.close and ticker.close > 0:
                            spot = ticker.close

            # NOTE: We do NOT call cancelMktData(spx_contract) here.
            # Leaving it open prevents ib_insync Error 300 collisions and
            # ensures background tickers update much faster.

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
