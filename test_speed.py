import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
import time
from ib_insync import *
import datetime

ib = IB()

async def run_profile():
    try:
        await ib.connectAsync('127.0.0.1', 4002, clientId=999)
        print("Connected.")
        
        spx = Index('SPX', 'SMART')
        await ib.qualifyContractsAsync(spx)
        
        t0 = time.time()
        spx_cboe = Index('SPX', 'CBOE')
        await ib.qualifyContractsAsync(spx_cboe)
        bars = await ib.reqHistoricalDataAsync(
            spx_cboe, endDateTime='', durationStr='1 D',
            barSizeSetting='1 day', whatToShow='TRADES', useRTH=True
        )
        price = bars[-1].close if bars else 6000
        t1 = time.time()
        print(f"Time to get historical price: {t1 - t0:.2f}s (Price: {price})")
        
        today = datetime.date.today().strftime('%Y%m%d')
        opt_search = Option(symbol='SPX', lastTradeDateOrContractMonth=today, exchange='SMART')
        
        t0 = time.time()
        details = await ib.reqContractDetailsAsync(opt_search)
        if not details:
            opt_search.exchange = 'CBOE'
            details = await ib.reqContractDetailsAsync(opt_search)
        t1 = time.time()
        print(f"Time to reqContractDetailsAsync ({len(details)} details): {t1 - t0:.2f}s")
        
        strikes = sorted(list(set(d.contract.strike for d in details)))
        candidates = sorted([s for s in strikes if s < price], reverse=True)[:30]
        contracts = []
        for s in candidates:
            for d in details:
                if d.contract.strike == s and d.contract.right == 'P':
                    contracts.append(d.contract)
                    break
        
        t0 = time.time()
        tickers = await ib.reqTickersAsync(*contracts)
        t1 = time.time()
        print(f"Time to reqTickersAsync for {len(contracts)} options: {t1 - t0:.2f}s")
        for ticker in tickers[:5]:
            print(f"  Strike {ticker.contract.strike} Delta: {ticker.modelGreeks.delta if ticker.modelGreeks else 'No Greeks'}")
            
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        ib.disconnect()

if __name__ == '__main__':
    asyncio.run(run_profile())
