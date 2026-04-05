import asyncio
import sys

if sys.platform == 'darwin':
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB

async def main():
    ib = IB()
    try:
        await ib.connectAsync('127.0.0.1', 4002, clientId=1111)
        print("Connected.")
        
        # Get all open trades
        trades = ib.openTrades()
        print(f"Found {len(trades)} open trades.")
        
        # Cancel each
        for t in trades:
            print(f"Cancelling order {t.order.orderId} (Status: {t.orderStatus.status})")
            ib.cancelOrder(t.order)
            
        await asyncio.sleep(2)
        print("Done cancelling.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
