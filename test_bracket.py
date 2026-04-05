import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *

# This script simulates a simple combo bracket order to see if it shows up in TWS.
async def run_test():
    ib = IB()
    try:
        await ib.connectAsync('127.0.0.1', 4002, clientId=12)
    except Exception as e:
        print("Could not connect", e)
        return

    # Let's create a simple SPY combo
    contract1 = Option('SPY', '20250620', 500, 'P', 'SMART')
    contract2 = Option('SPY', '20250620', 495, 'P', 'SMART')
    ib.qualifyContracts(contract1, contract2)

    leg1 = ComboLeg(conId=contract1.conId, ratio=1, action='SELL', exchange='SMART')
    leg2 = ComboLeg(conId=contract2.conId, ratio=1, action='BUY', exchange='SMART')
    
    bag = Contract()
    bag.symbol = 'SPY'
    bag.secType = 'BAG'
    bag.currency = 'USD'
    bag.exchange = 'SMART'
    bag.comboLegs = [leg1, leg2]

    parent_id = ib.client.getReqId()
    order = LimitOrder('BUY', 1, -1.0)
    order.orderId = parent_id
    order.transmit = False
    order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]

    tp_order = LimitOrder('SELL', 1, -0.5)
    tp_order.parentId = parent_id
    tp_order.orderId = ib.client.getReqId()
    tp_order.transmit = False
    tp_order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]

    t1 = ib.placeOrder(bag, order)
    t2 = ib.placeOrder(bag, tp_order)
    
    await asyncio.sleep(2)
    print(t1.orderStatus.status)
    print(t2.orderStatus.status)

    ib.disconnect()

if __name__ == '__main__':
    asyncio.run(run_test())
