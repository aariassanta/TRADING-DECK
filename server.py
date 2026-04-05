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
    def __init__(self):
        self.engine = None
        self.connected = False
        self.active_websockets = []

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
    trade_type: str # "CCS", "PCS", "IC"
    qty: int
    target_mode: str # "Delta" or "R:R"
    target_value: float
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
    """Manually triggers a fresh GEX scan and returns the payload."""
    if not state.connected or not state.engine:
        raise HTTPException(status_code=400, detail="Not connected to IBKR.")
    
    try:
        # Generate the data payload
        await manager.broadcast({"type": "log", "message": "Fetching 0DTE chain data. This takes a few seconds..."})
        data = await state.engine.fetch_market_metrics()
        
        # We wrap the successful hit and push it down websockets too
        if data:
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
    """Background task that ticks every 2 minutes and pushes metrics."""
    logger.info("Started 2-minute Auto-Refresh loop.")
    while True:
        await asyncio.sleep(120) # 2 minutes
        
        if state.connected and state.engine:
            try:
                logger.info("Executing periodic 2-minute GEX refresh...")
                await manager.broadcast({"type": "log", "message": "Auto-refresh: 2-minute tick triggered."})
                data = await state.engine.fetch_market_metrics()
                if data:
                    await manager.broadcast({"type": "metrics", "data": data})
                    await manager.broadcast({"type": "log", "message": "Display updated successfully."})
            except Exception as e:
                logger.error(f"Auto-refresh error: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_refresh_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
