import asyncio
import os
import sys

# Add current path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import IBKREngine

async def test():
    e = IBKREngine("SPX")
    pass
    
    price, expiries, details = await e._get_multiexpiry_chain_data(expirations_count=1)
    
    # Do exactly what fetch_market_metrics does
    contracts_by_expiry = {exp: {} for exp in expiries}
    for d in details:
        expiry = d.contract.lastTradeDateOrContractMonth
        if expiry in contracts_by_expiry:
            c = d.contract
            key = (c.strike, c.right)
            if key not in contracts_by_expiry[expiry]:
                contracts_by_expiry[expiry][key] = c
            elif c.tradingClass == 'SPXW':
                contracts_by_expiry[expiry][key] = c
                
    exp_list = list(contracts_by_expiry[expiries[0]].values())
    closest = sorted(exp_list, key=lambda c: abs(c.strike - price))[:60]
    
    print(f"Tracking 0DTE on {expiries[0]} for spot: {price}")
    for c in closest:
        e.ib.reqMktData(c, '100,101,104,106', False, False)
        
    await asyncio.sleep(2)
    tickers = [e.ib.ticker(c) for c in closest]
    
    call_oi = {}
    put_oi = {}
    
    for ticker in tickers:
        if not ticker or not ticker.contract: continue
        c = ticker.contract
        oi = ticker.callOpenInterest if c.right == 'C' else ticker.putOpenInterest
        if not oi or oi <= 0:
            oi = ticker.openInterest
        if not oi or oi <= 0:
            oi = ticker.volume
            
        if c.right == 'C':
            call_oi[c.strike] = call_oi.get(c.strike, 0) + (oi or 0)
        else:
            put_oi[c.strike] = put_oi.get(c.strike, 0) + (oi or 0)
            
    print("\nTop 5 CALL OI:")
    for strike, oi in sorted(call_oi.items(), key=lambda i: i[1], reverse=True)[:5]:
        print(f"  {strike}: {oi}")
        
    print("\nTop 5 PUT OI:")
    for strike, oi in sorted(put_oi.items(), key=lambda i: i[1], reverse=True)[:5]:
        print(f"  {strike}: {oi}")

    e.disconnect()

if __name__ == "__main__":
    asyncio.run(test())
