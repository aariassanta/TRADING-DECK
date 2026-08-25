import asyncio
from engine import IBKREngine

async def main():
    e = IBKREngine("SPX")
    await e.connect(port=4002)
    # Fetch metrics
    data = await e.fetch_market_metrics()
    print("Call Wall:", data["call_wall"])
    print("Put Wall:", data["put_wall"])
    print("Spot:", data["spot"])
    e.disconnect()

asyncio.run(main())
