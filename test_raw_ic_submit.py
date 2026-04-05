import asyncio
import sys

# Patch for python 3.14 event loop
if sys.platform == 'darwin':
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *

def printing_error_handler(reqId, errorCode, errorString, advancedOrderRejectJson=""):
    if errorCode not in [2104, 2106, 2158]:
        print(f"🛑 IBKR ERROR [{errorCode}]: {errorString}")

async def main():
    ib = IB()
    ib.client.wrapper.error = printing_error_handler
    
    print("Connecting to 127.0.0.1:4002...")
    import random
    await ib.connectAsync('127.0.0.1', 4002, clientId=random.randint(1000, 9999))
    
    # Define an underlying
    spx = Index('SPX', 'CBOE')
    await ib.qualifyContractsAsync(spx)
    
    # Get arbitrary chains and pick 4 legs for an IC
    print("Fetching chains...")
    chains = await ib.reqSecDefOptParamsAsync(spx.symbol, '', spx.secType, spx.conId)
    chain = next(c for c in chains if c.exchange == 'SMART')
    
    # Take an arbitrary future date with strikes
    expiry = sorted(chain.expirations)[1]
    strikes = sorted(chain.strikes)
    mid_idx = len(strikes) // 2
    
    put_long = strikes[mid_idx - 10]
    put_short = strikes[mid_idx - 5]
    call_short = strikes[mid_idx + 5]
    call_long = strikes[mid_idx + 10]
    
    print(f"Expiry: {expiry}. Legs: P {put_long}/{put_short}, C {call_short}/{call_long}")
    
    c1 = Option('SPX', expiry, put_long, 'P', 'SMART')
    c2 = Option('SPX', expiry, put_short, 'P', 'SMART')
    c3 = Option('SPX', expiry, call_short, 'C', 'SMART')
    c4 = Option('SPX', expiry, call_long, 'C', 'SMART')
    
    contracts = [c1, c2, c3, c4]
    print("Qualifying legs...")
    await ib.qualifyContractsAsync(*contracts)
    
    combo_legs = [
        ComboLeg(conId=c1.conId, ratio=1, action='BUY', exchange='SMART'),
        ComboLeg(conId=c2.conId, ratio=1, action='SELL', exchange='SMART'),
        ComboLeg(conId=c3.conId, ratio=1, action='SELL', exchange='SMART'),
        ComboLeg(conId=c4.conId, ratio=1, action='BUY', exchange='SMART')
    ]
    
    # Sort for IC requirement
    legs = sorted(zip(contracts, combo_legs), key=lambda x: (x[0].lastTradeDateOrContractMonth, 0 if x[0].right=='C' else 1, x[0].strike))
    combo_legs_sorted = [l[1] for l in legs]
    
    bag = Contract(symbol='SPX', secType='BAG', exchange='SMART', currency='USD')
    bag.comboLegs = combo_legs_sorted
    bag.tradingClass = 'SPXW'
    
    order = LimitOrder('BUY', 1, -2.50)
    order.transmit = False
    # TagValue string format:
    order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]
    
    print("Placing order...")
    trade = ib.placeOrder(bag, order)
    await asyncio.sleep(2)
    print(f"Status: {trade.orderStatus.status}")
    ib.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
