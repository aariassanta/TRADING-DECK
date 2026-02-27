import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import *

ib = IB()

try:
    ib.connect('127.0.0.1', 4002, clientId=999)
    print("Connected.")
    
    spx = Index('SPX', 'CBOE')
    ib.qualifyContracts(spx)
    
    # Try reqHistoricalData
    bars = ib.reqHistoricalData(
        spx,
        endDateTime='',
        durationStr='1 D',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True
    )
    
    if bars:
        print(f"TRADES Price: {bars[-1].close}")
    else:
        print("No TRADES bars returned.")
        
except Exception as e:
    print(f"ERROR: {e}")
finally:
    ib.disconnect()
