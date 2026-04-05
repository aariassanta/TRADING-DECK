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
    engine.client_id = 9182
    await engine.connect_async()
    
    print("\n--- Sending IC with Brackets ---")
    try:
        trade = await engine.execute_spread('IC', 1, 20.0, 10, 50.0, 2.0, False)
        print(f"IC Parent Status: {trade.orderStatus.status}")
        print(f"IC Parent Log: {trade.log}")
    except Exception as e:
        print(f"Failed: {e}")
        
    engine.disconnect()

asyncio.run(main())
