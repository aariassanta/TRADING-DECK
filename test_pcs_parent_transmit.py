import asyncio
import sys

if sys.platform == 'darwin':
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import TagValue, LimitOrder

from engine import IBKREngine

async def main():
    engine = IBKREngine()
    engine.client_id = 9187
    await engine.connect_async()
    
    print("\n--- Sending PCS Transmitting PARENT Only ---")
    try:
        contract, combo_legs = await engine.build_combo_contract('PCS', 20.0, 10)
        limit_price = -2.50
        
        # Parent - Transmit=True
        parent_order = LimitOrder('BUY', 1, limit_price)
        parent_order.tif = 'DAY'
        parent_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
        parent_order.transmit = True
        
        # Place Parent
        parent_trade = engine.ib.placeOrder(contract, parent_order)
        parent_id = parent_order.orderId
        
        # Child TP - Transmit=False
        tp_limit = -1.25
        tp_order = LimitOrder('SELL', 1, tp_limit)
        tp_order.tif = 'DAY'
        tp_order.parentId = parent_id
        tp_order.ocaGroup = f"OCA_SPX_{parent_id}"
        tp_order.ocaType = 1
        tp_order.transmit = False
        tp_order.smartComboRoutingParams = []
        
        # Wait a tick before placing children to mimic sequential placement
        await asyncio.sleep(0.5)
        
        # Place child
        tp_trade = engine.ib.placeOrder(contract, tp_order)
        
        for _ in range(20):
            await asyncio.sleep(0.1)
            
        print(f"Parent Status: {parent_trade.orderStatus.status}")
        print(f"Child Status: {tp_trade.orderStatus.status}")
        print(f"Parent Log: {parent_trade.log}")
        
    except Exception as e:
        print(f"Failed: {e}")
        
    engine.disconnect()

asyncio.run(main())
