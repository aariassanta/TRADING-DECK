import asyncio
import sys

# Patch for python 3.14 event loop
if sys.platform == 'darwin':
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
from engine import IBKREngine

async def test_ic():
    engine = IBKREngine()
    
    # Custom error handler to capture reject reason
    def printing_error_handler(reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode not in [2104, 2106, 2158]:
            print(f"🛑 IBKR ERROR [{errorCode}]: {errorString}")
    
    import random
    engine.client_id = random.randint(1000, 9999)
    await engine.connect_async()
    engine.ib.client.wrapper.error = printing_error_handler

    print("\n--- Sending Iron Condor (transmit=False) ---")
    try:
        # spread_type: 'IC', qty: 1, target_delta: 20, width: 10
        # tp_pct: 50, sl_ratio: 2.0, transmit: False
        trade = await engine.execute_spread('IC', 1, 20.0, 10, 50.0, 2.0, False)
        print("\n--- Placed Contract details ---")
        if trade and getattr(trade, 'contract', None):
            print(trade.contract)
            for leg in getattr(trade.contract, 'comboLegs', []):
                print(f"Leg: {leg}")
        print(f"Result: {trade.orderStatus.status}")
    except Exception as e:
        print(f"Exception: {e}")
        
    await asyncio.sleep(2)
    engine.ib.disconnect()

if __name__ == "__main__":
    asyncio.run(test_ic())
