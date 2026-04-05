from ib_async import *
import asyncio

async def main():
    ib = IB()
    await ib.connectAsync('127.0.0.1', 4002, clientId=999)
    print("Connected to IBKR")
    
    ib.reqMarketDataType(2) # 2 = Frozen, 3 = Delayed, 4 = Delayed Frozen
    
    # Let's get a random SPX contract for this week
    opt = Option('SPX', "20260324", right='C', strike=6500, exchange='SMART', tradingClass='SPXW')
    details = await ib.reqContractDetailsAsync(opt)
    if not details:
        print("Contract not found.")
        return
        
    contract = details[0].contract
    print(f"Contract: {contract.localSymbol}")
    
    # Test Data Type 2 (Frozen)
    print("--- Testing reqMarketDataType(2) ---")
    ib.reqMarketDataType(2)
    tickers = await ib.reqTickersAsync(contract)
    for t in tickers:
        print(f"OI: {t.openInterest}, Vol: {t.volume}, bid: {t.bid}, ask: {t.ask}")
        g = t.modelGreeks
        if g:
            print(f"Greeks -> Gamma: {g.gamma}, IV: {g.impliedVol}")
        else:
            print("Greeks -> None")
            
    # Test Data Type 4 (Delayed Frozen)
    print("--- Testing reqMarketDataType(4) ---")
    ib.reqMarketDataType(4)
    tickers = await ib.reqTickersAsync(contract)
    for t in tickers:
        print(f"OI: {t.openInterest}, Vol: {t.volume}, bid: {t.bid}, ask: {t.ask}")
        g = t.modelGreeks
        if g:
            print(f"Greeks -> Gamma: {g.gamma}, IV: {g.impliedVol}")
        else:
            print("Greeks -> None")
            
    # Test Data Type 3 (Delayed)
    print("--- Testing reqMarketDataType(3) ---")
    ib.reqMarketDataType(3)
    tickers = await ib.reqTickersAsync(contract)
    for t in tickers:
        print(f"OI: {t.openInterest}, Vol: {t.volume}, bid: {t.bid}, ask: {t.ask}")
        g = t.modelGreeks
        if g:
            print(f"Greeks -> Gamma: {g.gamma}, IV: {g.impliedVol}")
        else:
            print("Greeks -> None")

    ib.disconnect()

asyncio.run(main())
