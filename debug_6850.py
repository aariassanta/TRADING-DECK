import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import datetime
import math
from ib_insync import IB
from engine import IBKREngine
import logging

ib_logger = logging.getLogger('ib_insync.wrapper')
ib_logger.setLevel(logging.FATAL)

async def debug():
    engine = IBKREngine(port=4002)
    success, _ = await engine.connect_async()
    if not success:
        return
        
    price, expirations, all_details = await engine._get_multiexpiry_chain_data(4)
    target_strike = 6850.0

    target_contracts = [d.contract for d in all_details if d.contract.strike == target_strike]
    print(f"\n--- DEBUGGING STRIKE {target_strike} ---")
    print(f"Spot Price: {price:.2f}")

    for c in target_contracts:
        engine.ib.reqMktData(c, '100,101,104,106', False, False)
        
    await asyncio.sleep(4.0)
    
    tickers = [engine.ib.ticker(c) for c in target_contracts]
    
    total_gex = 0
    for c in target_contracts:
        engine.ib.cancelMktData(c)
        
    for ticker in tickers:
        contract = ticker.contract
        T = engine._estimate_time_to_expiry(contract.lastTradeDateOrContractMonth)
        gamma = 0
        iv = 0.18
        source = "IBKR Live"
        if ticker.modelGreeks and ticker.modelGreeks.gamma is not None and ticker.modelGreeks.gamma > 0:
            gamma = ticker.modelGreeks.gamma
            iv = ticker.modelGreeks.impliedVol or 0.18
        else:
            gamma = engine._bs_gamma(price, target_strike, T, 0.05, iv)
            source = "BS Math"
        
        right = contract.right
        oi = getattr(ticker, 'callOpenInterest', 0) if right == 'C' else getattr(ticker, 'putOpenInterest', 0)
        if not oi: oi = getattr(ticker, 'openInterest', 0)
        if not oi: oi = 0
        if math.isnan(oi): oi = 0
            
        sign = 1.0 if right == 'C' else -1.0
        gex_millions = sign * gamma * oi * 100 * price * price * 0.01 / 1e6
        total_gex += gex_millions
        
        print(f"Expiry: {contract.lastTradeDateOrContractMonth} | Type: {right} | OI: {oi} | T: {T:.6f} | IV: {iv:.2f} | Gamma ({source}): {gamma:.8f} | GEX: {gex_millions:.2f}M")

    print(f"-> TOTAL NET GEX FOR {target_strike} across {len(expirations)} expiries: {total_gex:.2f}M")
    engine.disconnect()

if __name__ == "__main__":
    loop.run_until_complete(debug())
