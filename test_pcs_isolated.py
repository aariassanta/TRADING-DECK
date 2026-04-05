import asyncio
import sys
from ib_insync import TagValue

if sys.platform == 'darwin':
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

from engine import IBKREngine

async def main():
    engine = IBKREngine()
    engine.client_id = 9184
    await engine.connect_async()
    
    print("\n--- Sending ISOLATED Transmitted PCS (No Brackets) ---")
    try:
        # Re-creating the PCS manually to bypass the bracket logic in execute_spread
        contract, combo_legs = await engine.build_combo_contract('PCS', 20.0, 10)
        
        # Fake mid price debit
        limit_price = -2.50
        
        from ib_insync import LimitOrder
        order = LimitOrder('BUY', 1, limit_price)
        order.tif = 'DAY'
        order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        order.transmit = True
        
        trade = engine.ib.placeOrder(contract, order)
        
        for _ in range(20):
            await asyncio.sleep(0.1)
            
        print(f"PCS Parent Status: {trade.orderStatus.status}")
        print(f"PCS Parent Log: {trade.log}")
        
    except Exception as e:
        print(f"Failed: {e}")
        
    engine.disconnect()

asyncio.run(main())
