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
    engine.client_id = 9991
    await engine.connect_async()
    
    print("\n--- Sending IC 1 ---")
    trade1 = await engine.execute_spread('IC', 1, 20.0, 10, 50.0, 2.0, False)
    print(f"IC 1 Status: {trade1.orderStatus.status}")
    print(f"IC 1 Log: {trade1.log}")
    
    await asyncio.sleep(3)
    
    print("\n--- Sending IC 2 ---")
    trade2 = await engine.execute_spread('IC', 1, 20.0, 10, 50.0, 2.0, False)
    print(f"IC 2 Status: {trade2.orderStatus.status}")
    print(f"IC 2 Log: {trade2.log}")
    
    await asyncio.sleep(5)
    print(f"IC 2 Status after 5s: {trade2.orderStatus.status}")
    print(f"IC 2 Log after 5s: {trade2.log}")
    
    engine.disconnect()

asyncio.run(main())
