import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import datetime
import math
from ib_insync import *

ib = IB()

def calc_bs_delta(S, K, right_str, dte=0.2):
    t = max(dte / 365.0, 0.0001)
    vol = 0.15
    r = 0.053
    d1 = (math.log(S / K) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
    cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    return cdf if right_str == 'C' else cdf - 1.0

async def place_combo():
    try:
        await ib.connectAsync('127.0.0.1', 4002, clientId=999)
        print("Connected.")
        
        spx = Index('SPX', 'SMART')
        await ib.qualifyContractsAsync(spx)
        
        spx_cboe = Index('SPX', 'CBOE')
        await ib.qualifyContractsAsync(spx_cboe)
        bars = await ib.reqHistoricalDataAsync(
            spx_cboe, endDateTime='', durationStr='1 D',
            barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
        )
        price = bars[-1].close if bars else 6000
        print(f"Price: {price}")
        
        today = datetime.date.today().strftime('%Y%m%d')
        opt_search = Option(symbol='SPX', lastTradeDateOrContractMonth=today, exchange='SMART')
        details = await ib.reqContractDetailsAsync(opt_search)
        if not details:
            opt_search.exchange = 'CBOE'
            details = await ib.reqContractDetailsAsync(opt_search)
            
        strikes = sorted(list(set(d.contract.strike for d in details)))
        
        # PCS Delta 20, width 15
        candidates = sorted([s for s in strikes if s < price], reverse=True)[:30]
        contracts = []
        for s in candidates:
            for d in details:
                if d.contract.strike == s and d.contract.right == 'P':
                    contracts.append(d.contract)
                    break
                    
        target_abs = 0.20
        best_strike = None
        min_diff = float('inf')
        for contract in contracts:
            current_delta = abs(calc_bs_delta(price, contract.strike, 'P'))
            diff = abs(current_delta - target_abs)
            if diff < min_diff:
                min_diff = diff
                best_strike = contract.strike
            if current_delta < target_abs:
                break
                
        short_put = best_strike
        long_put_target = short_put - 15
        actual_long = min(strikes, key=lambda x: abs(x - long_put_target))
        
        short_contract = next((d.contract for d in details if d.contract.strike == short_put and d.contract.right == 'P'), None)
        long_contract = next((d.contract for d in details if d.contract.strike == actual_long and d.contract.right == 'P'), None)
        
        print(f"Short Put: {short_put}, Long Put: {actual_long}")
        
        combo_legs = [
            ComboLeg(conId=short_contract.conId, ratio=1, action='SELL', exchange=short_contract.exchange),
            ComboLeg(conId=long_contract.conId, ratio=1, action='BUY', exchange=long_contract.exchange)
        ]
        
        bag = Contract()
        bag.symbol = 'SPX'
        bag.secType = 'BAG'
        bag.currency = 'USD'
        bag.exchange = 'SMART'
        bag.comboLegs = combo_legs
        
        # Test 1: Staged Order (Transmit False)
        order1 = LimitOrder('SELL', 1, 14.50, tif='DAY')
        order1.transmit = False
        print("Placing Staged Combo...")
        trade1 = ib.placeOrder(bag, order1)
        await asyncio.sleep(2)
        print(f"Staged Status: {trade1.orderStatus.status}")
        for log in trade1.log: print(f"  {log}")
        
        # Test 2: Live Transmit (Transmit True)
        order2 = LimitOrder('SELL', 1, 14.50, tif='DAY')
        order2.transmit = True
        print("\nPlacing LIVE Combo...")
        trade2 = ib.placeOrder(bag, order2)
        await asyncio.sleep(3)
        print(f"Live Status: {trade2.orderStatus.status}")
        for log in trade2.log: print(f"  {log}")
        
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    asyncio.run(place_combo())
