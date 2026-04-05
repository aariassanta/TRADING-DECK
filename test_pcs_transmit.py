import asyncio
import sys

if sys.platform == 'darwin':
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

from engine import IBKREngine

async def main():
    engine = IBKREngine()
    engine.client_id = 9183
    await engine.connect_async()
    
    print("\n--- Sending Transmitted PCS with Brackets ---")
    try:
        # PCS, qty=1, Delta=20, Width=10, TP=50%, SL=2.0, Transmit=True
        trade = await engine.execute_spread('PCS', 1, 20.0, 10, 50.0, 2.0, True)
        print(f"PCS Parent Status: {trade.orderStatus.status}")
        print(f"PCS Parent Log: {trade.log}")
    except Exception as e:
        print(f"Failed: {e}")
        
    engine.disconnect()

asyncio.run(main())
