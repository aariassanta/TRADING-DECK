import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *
import datetime

ib = IB()

try:
    ib.connect('127.0.0.1', 4002, clientId=999)
    print("Connected.")
    
    # Test finding options
    spx = Index('SPX', 'SMART')
    ib.qualifyContracts(spx)
    
    today = datetime.date.today().strftime('%Y%m%d')
    opt_search = Option('SPX', today, exchange='SMART')
    details = ib.reqContractDetails(opt_search)
    
    if not details:
        print("No details on SMART, trying CBOE")
        opt_search.exchange = 'CBOE'
        details = ib.reqContractDetails(opt_search)
        
    strikes = sorted(list(set(d.contract.strike for d in details)))
    print(f"Found {len(strikes)} strikes for {today}")
    
    short_strike = strikes[10]
    long_strike = short_strike - 15
    print(f"Testing Spreads: Short Put {short_strike} (Type: {type(short_strike)}), Long Put {long_strike} (Type: {type(long_strike)})")
    
    # Check matching logic
    def find_exact_contract(strike, right):
        matches = []
        for d in details:
            if d.contract.strike == strike and d.contract.right == right:
                matches.append(d.contract)
        print(f"Found {len(matches)} matches for {strike} {right}")
        return matches[0] if matches else None

    short_p = find_exact_contract(short_strike, 'P')
    long_p = find_exact_contract(long_strike, 'P')
    print(f"Matched Short P: {short_p}")
    print(f"Matched Long P: {long_p}")
    
    if not short_p or not long_p:
        print("MATCHING FAILED - Exiting test.")
        import sys
        sys.exit(1)
    
    # Try placing the long leg first
    print(f"Placing Long Leg first: BUY 1x SPX {long_strike} P")
    order_long = LimitOrder('BUY', 1, 100.00) # High price so it sits pending
    order_long.transmit = False
    trade_long = ib.placeOrder(long_p, order_long)
    
    ib.sleep(2)
    print(f"Long leg status: {trade_long.orderStatus.status}")
    for log in trade_long.log: print(f"  {log}")
    
    print(f"Placing Short Leg: SELL 1x SPX {short_strike} P")
    order_short = LimitOrder('SELL', 1, 0.05) # Low price so it sits pending
    order_short.transmit = False
    trade_short = ib.placeOrder(short_p, order_short)
    
    ib.sleep(2)
    print(f"Short leg status: {trade_short.orderStatus.status}")
    for log in trade_short.log: print(f"  {log}")
    
except Exception as e:
    print(f"ERROR: {e}")
finally:
    ib.disconnect()
