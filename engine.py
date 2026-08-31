"""
engine.py - IBKR trading engine using ib_insync async API.

The IB object must be used exclusively within the event loop it was created on.
All public coroutines (async methods) must be dispatched via run_coroutine_threadsafe
from the GUI thread, targeting the single persistent 'ib_loop' stored in app.py.
"""

import asyncio
import datetime
import json
import logging
import math
import numpy as np
import os
import csv
from scipy.stats import norm
from ib_async import IB, Index, Option, LimitOrder, Order, Contract, ComboLeg, TagValue, PriceCondition
from typing import Literal


# --- JSON serialization helper ---
def _to_native(obj):
    """Recursively convert numpy/pandas types to native Python for FastAPI JSON serialization."""
    try:
        if hasattr(obj, 'item'):  # numpy scalar (bool_, int64, float64, etc.)
            return obj.item()
        if hasattr(obj, 'tolist'):  # numpy array or structured array field
            return obj.tolist()
    except (TypeError, ValueError):
        pass  # Some numpy types don't support these methods
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(x) for x in obj]
    return obj


# --- Module-level pure math helpers ---

def calc_bs_delta(S, K, right_str, dte=0.2, vol=0.15, r=0.053):
    """Black-Scholes delta estimate. Used when IBKR greeks are unavailable."""
    t = dte / 365.0
    if t <= 0:
        t = 0.0001
    d1 = (math.log(S / K) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
    cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    return cdf if right_str == 'C' else cdf - 1.0


class IBKREngine:
    """
    Manages a single persistent IBKR connection and exposes async methods
    for order building and placement. Everything runs on one shared event loop.
    """

    def __init__(self, host='127.0.0.1', port=4002, client_id=1):
        import random
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id if client_id != 1 else random.randint(100, 9999)
        self.symbol = 'SPX'
        self.exchange = 'SMART'

    # ------------------------------------------------------------------
    # Connection (called from the persistent IB background thread)
    # ------------------------------------------------------------------

    async def connect_async(self) -> tuple[bool, str]:
        """
        Async connect — must be called from inside the IB event loop.
        Returns (success, error_message).
        """
        print(f"Connecting to {self.host}:{self.port} (Client ID: {self.client_id})...")
        try:
            await self.ib.connectAsync(self.host, self.port, clientId=self.client_id)
            print("Connected successfully.")
            return True, ""
        except Exception as e:
            err = str(e)
            print(f"Failed to connect: {err}")
            return False, err

    def disconnect(self):
        """Synchronous disconnect — safe to call from any thread."""
        if self.ib.isConnected():
            self.ib.disconnect()
            print("Disconnected.")

    # ------------------------------------------------------------------
    # Chain & strike lookup
    # ------------------------------------------------------------------

    def _get_robust_price(self, ticker) -> float:
        """
        Returns a high-fidelity price for an option contract.
        Prioritizes:
        1. Tight Bid/Ask Mid
        2. Model Price (especially for ITM/illiquid)
        3. Simple marketPrice() / Last
        """
        import math
        def get_v(p):
            return p if p is not None and not math.isnan(p) and p > 0 else None

        bid = get_v(ticker.bid)
        ask = get_v(ticker.ask)
        model = get_v(ticker.modelGreeks.optPrice) if ticker.modelGreeks else None
        
        # If we have a tight spread (< 1.5 points for SPX), Mid is often fine
        if bid and ask:
            mid = (bid + ask) / 2.0
            spread = ask - bid
            if spread < 1.5:
                return mid
        
        # If spread is huge or bid=0, trust the Model Price (Theoretical Math)
        if model:
            return model
            
        # Last resort: whatever the IBKR 'marketPrice' helper says
        val = ticker.marketPrice()
        return val if not math.isnan(val) and val > 0 else 0.0

    async def _get_chain_data(self):
        """
        Get SPX price, 0DTE expiry, and available strikes.
        Returns (price, expiry_str, strikes_list) or raises on failure.
        """
        # Force delayed market data in case live data is not subscribed
        self.ib.reqMarketDataType(3)

        # Index quotes usually must be sourced explicitly from CBOE, SMART may fail
        spx = Index(self.symbol, 'CBOE')
        try:
            await asyncio.wait_for(self.ib.qualifyContractsAsync(spx), timeout=3.0)
        except Exception: pass

        try:
            ticker = self.ib.reqMktData(spx, '', False, False)
            await asyncio.sleep(0.5)
            price = ticker.marketPrice()
            # Intentionally NOT cancelling this subscription so background monitors
            # can instantly read the SPX spot price without Error 300 collisions.
        except Exception as e:
            print(f"WARNING: reqMktData for SPX failed ({e}), checking cached tickers...")
            cached = [t for t in self.ib.tickers() if t.contract.conId == spx.conId]
            price = cached[0].marketPrice() if cached else float('nan')
        
        if price != price or price <= 0:  # NaN or invalid
            print("WARNING: Real-time SMART ticket returned NaN. Fetching latest historical close from CBOE...")
            try:
                spx_cboe = Index('SPX', 'CBOE')
                await self.ib.qualifyContractsAsync(spx_cboe)
                bars = await self.ib.reqHistoricalDataAsync(spx_cboe, endDateTime='', durationStr='1 D', barSizeSetting='1 day', whatToShow='TRADES', useRTH=True)
                if bars and bars[-1].close > 0:
                    price = bars[-1].close
                    print(f"✅ Recovered true SPX price from historical data: {price:.2f}")
            except Exception as e:
                print(f"WARNING: CBOE historical recovery failed ({e}). Trying SPY fallback...")
        
        if price != price or price <= 0:
            try:
                from ib_async import Stock
                spy = Stock('SPY', 'SMART', 'USD')
                await self.ib.qualifyContractsAsync(spy)
                spy_ticker = self.ib.reqMktData(spy, '', False, False)
                await asyncio.sleep(0.3)
                if spy_ticker.marketPrice() > 0:
                    price = spy_ticker.marketPrice() * 10.0
                    print(f"✅ Recovered SPX price via SPY: {price:.2f}")
                self.ib.cancelMktData(spy)
            except:
                pass
        
        if price != price or price <= 0:
            price = 6890.00 # Ultra fallback
            print(f"❌ FAILED to recover SPX price. Using {price} fallback.")
        
        print(f"SPX Market Price: {price:.2f}")

        # Instead of reqSecDefOptParams (which fails on some index setups), 
        # we ask for all Option contracts expiring today directly.
        today = datetime.date.today().strftime('%Y%m%d')
        
        # We use a wildcard Option contract to search
        opt_search = Option(symbol=self.symbol, lastTradeDateOrContractMonth=today, exchange=self.exchange)
        
        print(f"Requesting Option Chain details for {today}...")
        try:
            details = await asyncio.wait_for(self.ib.reqContractDetailsAsync(opt_search), timeout=10.0)
            
            if not details:
                # Fallback: maybe SMART doesn't have it explicitly bound, try CBOE
                opt_search.exchange = 'CBOE'
                details = await asyncio.wait_for(self.ib.reqContractDetailsAsync(opt_search), timeout=10.0)
        except Exception as e:
            print(f"Timeout/Error fetching initial options chain: {e}")
            details = []
            
        if not details:
            raise RuntimeError(f"No option chains returned from IBKR for {today}.")
            
        # Extract unique strikes from the returned contracts
        strikes = sorted(list(set(d.contract.strike for d in details)))
        expiry = today

        print(f"0DTE Expiry: {expiry}, {len(strikes)} strikes available")
        return price, expiry, strikes, details

    @staticmethod
    def _estimate_time_to_expiry(expiry_str: str) -> float:
        """Estimate T for 0DTE (using NY Time to 16:00 ET)."""
        import datetime as dt
        # Try to use zoneinfo to accurately measure New York time
        try:
            from zoneinfo import ZoneInfo
            now_ny = dt.datetime.now(ZoneInfo("America/New_York"))
            hours_to_expiry = 16.0 - (now_ny.hour + now_ny.minute / 60.0)
            days_to_expiry = max(0.001, hours_to_expiry / 24.0)
        except ImportError:
            # Fallback if zoneinfo is somehow missing: Approx 0.25 days
            days_to_expiry = 0.25 
        
        # Extract date
        expiry_date = dt.datetime.strptime(expiry_str[:8], '%Y%m%d').date()
        today_date = dt.date.today()
        
        if expiry_date == today_date:
            return days_to_expiry / 365.25 # mathematically correct years
        else:
            days = (expiry_date - today_date).days
            return max(days / 365.25, 0.0001)

    @staticmethod
    def _bs_gamma(S, K, T, r, sigma):
        """Standard Black-Scholes Gamma used as a fallback when IBKR Greeks fail."""
        if sigma <= 0 or T <= 0:
            return 0.0
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        return norm.pdf(d1) / (S * sigma * np.sqrt(T))

    async def _get_multiexpiry_chain_data(self, expirations_count=4):
        """
        Get SPX price and Option contract details for the next N expirations.
        Returns (price, expirations_list, details_list).
        """
        self.ib.reqMarketDataType(3)

        # Pre-qualify SPX contract and cache it to avoid repeated network bottlenecks
        if not hasattr(self, '_cached_spx_contract'):
            spx = Index(self.symbol, 'CBOE')
            try:
                await asyncio.wait_for(self.ib.qualifyContractsAsync(spx), timeout=3.0)
                self._cached_spx_contract = spx
            except Exception as e:
                print(f"Warning: Failed to qualify SPX contract: {e}")
                # Use a dummy but known valid setup
                spx.conId = 416904 # Known SPX CBOE conId fallback
                self._cached_spx_contract = spx
        else:
            spx = self._cached_spx_contract

        try:
            ticker = self.ib.reqMktData(spx, '', False, False)
            await asyncio.sleep(0.5)
            price = ticker.marketPrice()
            # Intentionally NOT cancelling this subscription to keep background monitors alive.
            
            # Fallback for pre-market or illiquid periods
            if not price or math.isnan(price) or price <= 0:
                if ticker.last and ticker.last > 0:
                    price = ticker.last
                elif ticker.close and ticker.close > 0:
                    price = ticker.close
        except Exception as e:
            print(f"WARNING: reqMktData for SPX failed ({e}), checking cached tickers...")
            cached = [t for t in self.ib.tickers() if t.contract.conId == spx.conId]
            price = cached[0].marketPrice() if cached else float('nan')
        
        if price != price or price <= 0:  # NaN or invalid
            print("WARNING: Real-time SMART ticket returned NaN. Fetching latest historical close from CBOE...")
            spx_cboe = Index('SPX', 'CBOE')
            try:
                await asyncio.wait_for(self.ib.qualifyContractsAsync(spx_cboe), timeout=3.0)
                bars = await asyncio.wait_for(
                    self.ib.reqHistoricalDataAsync(spx_cboe, endDateTime='', durationStr='1 D', barSizeSetting='1 day', whatToShow='TRADES', useRTH=True),
                    timeout=5.0
                )
                if bars and bars[-1].close > 0:
                    price = bars[-1].close
                else:
                    price = 6890.00
            except Exception as e:
                print(f"Historical fallback failed/timed out: {e}")
                price = 6890.00
        
        print(f"SPX Market Price: {price:.2f}")

        import datetime
        today = datetime.date.today()

        # SPEED OPTIMIZATION: Cache option chains for the day since they don't change intraday
        if hasattr(self, 'chain_cache_date') and self.chain_cache_date == today and hasattr(self, 'chain_cache'):
            expiries, all_details = self.chain_cache
            print(f"Using cached Option Chains: {expiries}")
            return price, expiries, all_details

        all_details = []
        found_expiries = []
        
        print(f"Fetching Option Chains for the next {expirations_count} expirations...")
        
        import logging
        ib_logger = logging.getLogger('ib_async.wrapper')
        old_level = ib_logger.level
        ib_logger.setLevel(logging.FATAL) # Suppress "No definition found" Error 200 for weekends
        
        # Pre-compute the valid trading dates we need (skip weekends and US holidays)
        us_holidays = {
            datetime.date(2026, 5, 25),  # Memorial Day
            datetime.date(2026, 7, 3),   # Independence Day (observed)
            datetime.date(2026, 12, 25),
        }
        target_dates = []
        for i in range(21):
            if len(target_dates) >= expirations_count:
                break
            target_date_obj = today + datetime.timedelta(days=i)
            if target_date_obj.weekday() < 5 and target_date_obj not in us_holidays:
                target_dates.append(target_date_obj.strftime('%Y%m%d'))

        # Fetch all 4 expiry chains concurrently instead of sequentially
        opt_searches = [
            Option(symbol=self.symbol, lastTradeDateOrContractMonth=td, exchange=self.exchange)
            for td in target_dates
        ]

        async def fetch_single_expiry(opt_search, expiry_date):
            try:
                details = await asyncio.wait_for(
                    self.ib.reqContractDetailsAsync(opt_search), timeout=30.0
                )
                if not details:
                    opt_search.exchange = 'CBOE'
                    details = await asyncio.wait_for(
                        self.ib.reqContractDetailsAsync(opt_search), timeout=30.0
                    )
                return details
            except Exception as e:
                print(f"Timeout/Error fetching options chain for {expiry_date}: {e}")
                return []

        results = await asyncio.gather(*[
            fetch_single_expiry(opt_search, td)
            for opt_search, td in zip(opt_searches, target_dates)
        ])

        for expiry_date, details in zip(target_dates, results):
            if details:
                found_expiries.append(expiry_date)
                all_details.extend(details)
                print(f"  -> Found Expiry: {expiry_date} ({len(details)} contracts)")
                
        if not all_details:
            raise RuntimeError(f"No option chains returned from IBKR for {self.symbol}.")
            
        print(f"Loaded {len(found_expiries)} expiries: {found_expiries} ({len(all_details)} total contracts)")
        
        # Save to cache
        self.chain_cache_date = today
        self.chain_cache = (found_expiries, all_details)

        return price, found_expiries, all_details

    async def fetch_5min_bars(self) -> list[dict]:
        """
        Fetch today's 5-min bars for SPX from IBKR.

        IBKR rejects 5-min historical bars for the SPX index (CBOE), so we
        request 1-min bars and aggregate them into 5-min buckets in Python.
        Returns list of {date, open, high, low, close} for today's RTH session.
        Bars cover 9:30-16:00 ET.
        """
        from zoneinfo import ZoneInfo
        import datetime as dt

        today_et = dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
        spx = Index('SPX', 'CBOE')
        try:
            await self.ib.qualifyContractsAsync(spx)
            # Request 1-min bars (5-min rejected for SPX index). We aggregate below.
            bars = await self.ib.reqHistoricalDataAsync(
                spx,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=True,
            )
        except Exception as e:
            print(f"[Engine] fetch_5min_bars failed: {e}")
            return []

        et_zone = ZoneInfo('America/New_York')
        # First pass: filter to today's RTH 1-min bars and normalize timestamps.
        one_min: list[dict] = []
        for bar in (bars or []):
            bar_utc = bar.date
            if bar_utc.tzinfo is None:
                bar_utc = bar_utc.replace(tzinfo=dt.timezone.utc)
            bar_et = bar_utc.astimezone(et_zone)
            if bar_et.date() == today_et and 9 * 60 + 30 <= bar_et.hour * 60 + bar_et.minute < 16 * 60:
                one_min.append({
                    'date': bar_et,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'total_min': bar_et.hour * 60 + bar_et.minute,
                })

        # Second pass: aggregate 1-min bars into 5-min buckets keyed by
        # floor(total_min / 5). IBKR 1-min bars land on minute boundaries
        # (9:30, 9:31, ..., 15:59), so the bucket close is always the bar at
        # minute % 5 == 4 of its bucket.
        buckets: dict[int, dict] = {}
        for b in one_min:
            bucket_start = (b['total_min'] // 5) * 5  # 9:30 → 570, 9:35 → 575, ...
            cur = buckets.get(bucket_start)
            if cur is None:
                buckets[bucket_start] = {
                    'date': b['date'],          # open time of first 1-min bar
                    'open': b['open'],
                    'high': b['high'],
                    'low': b['low'],
                    'close': b['close'],
                }
            else:
                cur['high'] = max(cur['high'], b['high'])
                cur['low'] = min(cur['low'], b['low'])
                cur['close'] = b['close']      # last 1-min close wins

        # Return chronologically with total_min key the callers rely on.
        return [
            {**bucket, 'total_min': bucket_start}
            for bucket_start, bucket in sorted(buckets.items())
        ]

    async def fetch_daily_bars(self, days: int = 20) -> list[dict]:
        """
        Fetch daily bars for SPX for the last N days.
        Returns list of {date, open, high, low, close} sorted oldest→newest.
        """
        from zoneinfo import ZoneInfo
        import datetime as dt

        spx = Index('SPX', 'CBOE')
        try:
            # IBKR can hang indefinitely on these calls during pacing windows
            # or transient disconnects. Timeouts keep the calling strategy from
            # blocking forever.
            await asyncio.wait_for(self.ib.qualifyContractsAsync(spx), timeout=10.0)
            bars = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    spx,
                    endDateTime='',
                    durationStr=f'{days + 5} D',
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                ),
                timeout=15.0,
            )
        except (asyncio.TimeoutError, Exception) as e:
            print(f"[Engine] fetch_daily_bars failed: {e}")
            return []

        result = []
        et_zone = ZoneInfo('America/New_York')
        for bar in (bars or []):
            bar_utc = bar.date
            # ib_insync quirk: intraday bars return datetime.datetime (UTC),
            # daily bars return datetime.date (no time/tz component).
            if isinstance(bar_utc, dt.datetime):
                if bar_utc.tzinfo is None:
                    bar_utc = bar_utc.replace(tzinfo=dt.timezone.utc)
                result_date = bar_utc.astimezone(et_zone).date()
            else:
                # bar_utc is datetime.date — already a calendar date, no tz needed
                result_date = bar_utc
            result.append({
                'date': result_date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
            })
        # Return newest last
        result.reverse()
        return result

    async def _fetch_vix_async(self) -> float | None:
        """Fetch VIX via Yahoo Finance HTTP API in a thread pool (no IBKR event-loop conflicts)."""
        try:
            import urllib.request
            url = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=2d'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            result = data.get('chart', {}).get('result', [])
            if not result:
                print('[VIX] no chart result from Yahoo')
                return None
            meta = result[0].get('meta', {})
            vix = meta.get('regularMarketPrice') or meta.get('previousClose')
            if vix:
                print(f"[VIX] Yahoo close={vix}")
                return round(float(vix), 2)
            print(f"[VIX] no price in meta: {meta}")
            return None
        except Exception as exc:
            print(f"[VIX] Yahoo fetch error: {exc}")
            return None

    async def fetch_market_metrics(self) -> dict:
        """
        Fetch the 4 closest option chains and calculate:
        - Call Wall
        - Put Wall
        - Gamma Flip
        - Dark Gamma strikes
        - +/- 1, 2, 3 Sigma Levels
        """
        if not self.ib.isConnected():
            return {"error": "Not connected to IBKR."}

        # Fetch the 4 closest expirations as the user prefers to see overall institutional positioning
        price, expiries, all_details = await self._get_multiexpiry_chain_data(expirations_count=1)

        # Distribute exposure gathering across found expiries
        # User wants +/- 15 strikes for each day (~30 strikes * 2 = 60 contracts per expiry)
        contracts_by_expiry = {exp: {} for exp in expiries}
        for d in all_details:
            expiry = d.contract.lastTradeDateOrContractMonth
            # Filter matches for the 4 target expiries
            if expiry in contracts_by_expiry:
                c = d.contract
                key = (c.strike, c.right)
                # Deduplicate strikes (Prioritize 'SPXW' Weekly over 'SPX' Monthly)
                if key not in contracts_by_expiry[expiry]:
                    contracts_by_expiry[expiry][key] = c
                elif c.tradingClass == 'SPXW':
                    contracts_by_expiry[expiry][key] = c

        # We'll collect all tickers in batches to stay under IBKR's concurrent limit
        tickers = []
        ib_logger = logging.getLogger('ib_async.wrapper')
        old_level = ib_logger.level
        ib_logger.setLevel(logging.FATAL)

        all_contracts_to_fetch = []
        for exp in expiries:
            exp_list = list(contracts_by_expiry[exp].values())
            
            if exp == expiries[0]:
                # Expand 0DTE: Take ALL strikes for the whole chain structure
                all_contracts_to_fetch.extend(exp_list)
            else:
                # Other expirations: Take the 60 closest contracts to current spot price (+/- 15 strikes)
                closest_60 = sorted(exp_list, key=lambda c: abs(c.strike - price))[:60]
                if closest_60:
                    all_contracts_to_fetch.extend(closest_60)

        print(f"  -> Batching {len(all_contracts_to_fetch)} total contracts in safe chunks...")
        
        chunk_size = 50
        for i in range(0, len(all_contracts_to_fetch), chunk_size):
            chunk = all_contracts_to_fetch[i:(i + chunk_size)]
            try:
                # reqMktData returns immediately (Ticker object), data arrives async
                for c in chunk:
                    self.ib.reqMktData(c, '100,101,104,106', False, False)

                # Wait for IBKR to populate the ticker data
                await asyncio.sleep(0.3)
                tickers.extend([self.ib.ticker(c) for c in chunk])

                for c in chunk:
                    self.ib.cancelMktData(c)

                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"  [ERROR] Chunk {i} failed: {e}")

        ib_logger.setLevel(old_level) # Restore logger to previous state
        
        # Initialize data structures
        call_oi = {}
        put_oi = {}
        call_gex_per_strike = {}  # GEX from calls (positive)
        put_gex_per_strike = {}  # GEX from puts (negative)
        total_gex_per_strike = {}  # Aggregate GEX across all expiries
        net_gex_0dte = {}  # Net GEX for 0DTE only (for Gamma Flip)
        gex_by_expiry = {exp: {} for exp in expiries}  # GEX split by expiry date
        vol_by_expiry = {exp: {} for exp in expiries}  # Volume split by expiry date
        dark_gamma_candidates = []

        # --- NEW: raw OI and Volume profiles for GEX zone analysis ---
        # oi_profile: total OI (calls + puts) per strike across all expiries
        oi_profile = {}  # { strike: total_oi }
        # vol_profile: total intraday volume per strike across all expiries
        vol_profile = {}  # { strike: total_vol }
        # oi_by_expiry: OI split by expiry, keyed like gex_by_expiry
        oi_by_expiry = {exp: {} for exp in expiries}  # { expiry: { strike: oi } }

        # --- NEW: Gamma Hunter enrichment data ---
        # strike_ladder_raw: per-strike call/put market data for the live ladder
        strike_ladder_raw = {}  # { strike: {'C': {...}, 'P': {...}} }
        # iv_skew_raw: per-strike implied vol for calls and puts
        iv_skew_raw = {}  # { strike: {'C': iv, 'P': iv} }

        # --- NEW: Premium tracking for 0DTE Net Drift ---
        total_call_premium_0dte = 0.0
        total_put_premium_0dte = 0.0
        total_call_volume_0dte = 0
        total_put_volume_0dte = 0
        total_volume_0dte = 0

        atm_iv = None
        min_distance_to_atm = float('inf')

        # Pre-seed strikes near the spot price (+/- 2.5%) to ensure the HeatMap always renders structurally
        # even during pre-market when IBKR drops the Open Interest (nan) stream.
        target_strikes = set(c.strike for c in all_contracts_to_fetch)
        for s in target_strikes:
            if abs(s - price) / price <= 0.025:  # Within 2.5% of spot
                total_gex_per_strike[s] = 0.0
                for exp in expiries:
                    gex_by_expiry[exp][s] = 0.0

        for ticker in tickers:
            if not ticker or not ticker.contract:
                continue
                
            contract = ticker.contract
            strike = contract.strike
            right = contract.right
            expiry_key = contract.lastTradeDateOrContractMonth
            
            # Using get_valid pattern safely
            def get_valid(val):
                return val if val is not None and not math.isnan(val) and val >= 0 else 0

            # For Options, IBKR sometimes maps OI to callOpenInterest/putOpenInterest, 
            # sometimes openInterest, and sometimes it doesn't stream it immediately. We use volume as fallback if OI is 0
            # to make sure the app doesn't crash to "2800".
            oi = get_valid(getattr(ticker, 'callOpenInterest', 0) if right == 'C' else getattr(ticker, 'putOpenInterest', 0))
            if oi == 0:
                 oi = get_valid(getattr(ticker, 'openInterest', 0))
            
            volume = get_valid(getattr(ticker, 'volume', 0))
            
            # Actually apply the fallback to keep the heat map colored during Pre-Market
            if oi == 0 and volume > 0:
                oi = volume
            
            if expiry_key in vol_by_expiry:
                vol_by_expiry[expiry_key][strike] = vol_by_expiry[expiry_key].get(strike, 0) + volume

            # --- NEW: accumulate raw OI and volume into flat profiles ---
            oi_profile[strike] = oi_profile.get(strike, 0) + oi
            vol_profile[strike] = vol_profile.get(strike, 0) + volume
            if expiry_key in oi_by_expiry:
                oi_by_expiry[expiry_key][strike] = oi_by_expiry[expiry_key].get(strike, 0) + oi
            
            # Record OI for Call/Put Walls (0DTE ONLY)
            if expiry_key == expiries[0]:
                mid_px = self._get_robust_price(ticker)
                premium_dollars = volume * mid_px * 100
                total_volume_0dte += volume

                if right == 'C':
                    total_call_premium_0dte += premium_dollars
                    total_call_volume_0dte += volume
                    call_oi[strike] = call_oi.get(strike, 0) + oi
                    
                    # Dark Gamma Check (Volume > 5x OI)
                    # Typically checked on calls, but can be done for both.
                    if oi > 0: # Ensure some baseline OI exists to prevent noise
                        ratio = volume / (oi + 1)
                        if ratio > 5 and volume > 100: # Adding a volume threshold to filter illiquid noise
                            dark_gamma_candidates.append({
                                "strike": strike,
                                "type": "Call",
                                "volume": volume,
                                "oi": oi,
                                "ratio": round(ratio, 1)
                            })
                elif right == 'P':
                    total_put_premium_0dte += premium_dollars
                    total_put_volume_0dte += volume
                    put_oi[strike] = put_oi.get(strike, 0) + oi
                    
                    # Dark Gamma Check for Puts as well
                    if oi > 0:
                        ratio = volume / (oi + 1)
                        if ratio > 5 and volume > 100:
                            dark_gamma_candidates.append({
                                "strike": strike,
                                "type": "Put",
                                "volume": volume,
                                "oi": oi,
                                "ratio": round(ratio, 1)
                            })

            # Calculate GEX (Gamma Exposure) using Standard Hedging Mechanics
            # Market Standard: Dealer is Short Puts (+1) and Long Calls (-1)
            # Notional GEX approximates the effect of a 1% move in spot price.
            # Base formula: Sign * Spot * Gamma * OI * ContractSize(100) * 0.01  ==> Sign * Spot * Gamma * OI
            
            gamma = 0
            iv = 0.18 # Conservative default fallback
            
            if ticker.modelGreeks:
                gamma = ticker.modelGreeks.gamma if ticker.modelGreeks.gamma is not None else 0
                if ticker.modelGreeks.impliedVol and ticker.modelGreeks.impliedVol > 0:
                    iv = ticker.modelGreeks.impliedVol

            # Fallback to Math if IBKR Live Greeks are zero (common in pre/post market for 0DTE)
            if gamma == 0 and oi > 0:
                # Calculate Days to Expiry (T) with intraday 0DTE logic
                T = self._estimate_time_to_expiry(contract.lastTradeDateOrContractMonth)
                gamma = self._bs_gamma(price, strike, T, 0.05, iv)

            # --- NEW: populate Gamma Hunter ladder data after IV/Gamma are resolved ---
            # Read real Greeks from IBKR modelGreeks (already available, no new subscription needed)
            greeks = ticker.modelGreeks
            greeks_delta = greeks.delta if greeks and greeks.delta is not None else None
            greeks_gamma = gamma  # already resolved above
            greeks_theta = greeks.theta if greeks and greeks.theta is not None else None
            greeks_vega  = greeks.vega  if greeks and greeks.vega  is not None else None

            if strike not in strike_ladder_raw:
                strike_ladder_raw[strike] = {'C': {}, 'P': {}}
            side = 'C' if right == 'C' else 'P'
            strike_ladder_raw[strike][side] = {
                'bid': get_valid(getattr(ticker, 'bid', 0)),
                'ask': get_valid(getattr(ticker, 'ask', 0)),
                'last': get_valid(getattr(ticker, 'last', 0)),
                'volume': volume,
                'oi': oi,
                'iv': iv if iv > 0 else None,
                'delta': greeks_delta,
                'gamma': greeks_gamma,
                'theta': greeks_theta,
                'vega': greeks_vega,
            }
            if iv > 0:
                if strike not in iv_skew_raw:
                    iv_skew_raw[strike] = {}
                iv_skew_raw[strike][side] = iv

            if gamma > 0 and oi > 0:
                # 1% move Notional GEX calculation standard in Dollars
                # Market Standard: Dealers are typically modeled as Long Calls (+) and Short Puts (-)
                sign = 1.0 if right == 'C' else -1.0

                # Formula: Sign * Gamma * OI * ContractSize(100) * Spot * Spot * 1% Move (0.01)
                # The mathematical definition of dollar-gex. We divide by 1e6 to output in Millions.
                contribution_dollars = sign * gamma * oi * 100.0 * price * price * 0.01
                contribution_millions = contribution_dollars / 1e6

                # Accumulate in the aggregate profile
                total_gex_per_strike[strike] = total_gex_per_strike.get(strike, 0) + contribution_millions

                # Accumulate per-expiry (for heat map columns)
                if expiry_key in gex_by_expiry:
                    gex_by_expiry[expiry_key][strike] = gex_by_expiry[expiry_key].get(strike, 0) + contribution_millions

                # Track call and put GEX separately for wall calculation
                if right == 'C':
                    call_gex_per_strike[strike] = call_gex_per_strike.get(strike, 0) + contribution_millions
                elif right == 'P':
                    put_gex_per_strike[strike] = put_gex_per_strike.get(strike, 0) + contribution_millions

                # Track net GEX for 0DTE only (Call GEX + Put GEX)
                if expiry_key == expiries[0]:
                    net_gex_0dte[strike] = net_gex_0dte.get(strike, 0) + contribution_millions

            # Find ATM IV for Sigma calculation
            dist = abs(strike - price)
            if dist < min_distance_to_atm and iv > 0:
                min_distance_to_atm = dist
                atm_iv = iv

        # Calculate Walls using the same NET GEX shown in the GEX Heatmap (gex_by_expiry[expiries[0]])
        # Call Wall: strike with maximum positive NET GEX
        # Put Wall: strike with most negative NET GEX
        # Note: convert keys to float to avoid lexicographic comparison on string strikes
        zero_dte_gex = gex_by_expiry.get(expiries[0], {}) if expiries else {}
        valid_net_pos = {float(k): float(v) for k, v in zero_dte_gex.items() if v > 0}
        call_wall = max(valid_net_pos, key=valid_net_pos.get) if valid_net_pos else None

        valid_net_neg = {float(k): float(v) for k, v in zero_dte_gex.items() if v < 0}
        put_wall = min(valid_net_neg, key=valid_net_neg.get) if valid_net_neg else None

        # Calculate Gamma Flip (Zero GEX Level) - 0DTE only, all strikes
        # Gamma Flip is the strike where Net GEX crosses zero (Call GEX + Put GEX).
        gamma_flip = None
        if net_gex_0dte:
            # Use all strikes with non-zero GEX (convert keys to float for proper numeric comparison)
            valid_gex = {float(k): float(v) for k, v in net_gex_0dte.items() if v != 0}

            if len(valid_gex) > 1:
                flips = []
                sorted_strikes = sorted(valid_gex.keys())
                for i in range(len(sorted_strikes) - 1):
                    s1 = sorted_strikes[i]
                    s2 = sorted_strikes[i+1]
                    # If they have opposite signs, a zero-cross exists between them
                    if valid_gex[s1] * valid_gex[s2] < 0:
                        # Claim the strike whose exposure is already nearest to zero
                        flips.append(s1 if abs(valid_gex[s1]) < abs(valid_gex[s2]) else s2)
                
                if flips:
                    # If multiple flips exist in the chain, the true institutional Gamma Flip is the one nearest to Spotlight
                    gamma_flip = min(flips, key=lambda f: abs(f - price))
                else:
                    gamma_flip = "--" # No mathematical zero-cross exists in the local market cleanly
            else:
                gamma_flip = "--"

        # Calculate Max Change Gamma: strike with largest absolute GEX (biggest gamma P&L change for 1% move)
        max_change_gamma = None
        max_change_gamma_value = 0.0
        if net_gex_0dte:
            for strike, gex_val in net_gex_0dte.items():
                if abs(gex_val) > abs(max_change_gamma_value):
                    max_change_gamma_value = gex_val
                    max_change_gamma = strike

        # Calculate Sigma Levels
        # Sigma = Spot * ATM_IV * sqrt(1/365)
        # Note: For 0DTE, some use 1/252 or intra-day time. We use standard 1/365 daily var.
        daily_var = atm_iv * math.sqrt(1 / 365.0) if atm_iv else 0.01 # fallback to 1% daily move if IV missing
        sigma_1 = price * daily_var
        
        sigmas = {
            "+3": round(price + (sigma_1 * 3), 2),
            "+2": round(price + (sigma_1 * 2), 2),
            "+1": round(price + sigma_1, 2),
            "-1": round(price - sigma_1, 2),
            "-2": round(price - (sigma_1 * 2), 2),
            "-3": round(price - (sigma_1 * 3), 2),
        }

        # Format Dark Gamma
        # Sort by ratio descending
        dark_gamma_candidates.sort(key=lambda x: x['ratio'], reverse=True)
        # Top 3 candidates
        dg_top = dark_gamma_candidates[:3]

        # Log Intraday 0DTE data for the Interval Bubble Map
        if expiries:
            self._log_intraday_data(price, expiries[0], gex_by_expiry[expiries[0]], vol_by_expiry[expiries[0]])

        # --- NEW: classify GEX zones and build regime payload ---
        # Use 0DTE-only GEX for net_gex_total (user request: NET GEX = 0DTE chain)
        zero_dte_gex = gex_by_expiry.get(expiries[0], {}) if expiries else {}
        zone_data = self._classify_gex_zones(
            gex_profile=zero_dte_gex,
            oi_profile=oi_profile,
            vol_profile=vol_profile,
            price=price,
            call_wall=call_wall,
            put_wall=put_wall,
            gamma_flip=gamma_flip,
        )

        self._log_premium_drift_data(price, total_call_premium_0dte, total_put_premium_0dte,
                                     total_call_volume_0dte, total_put_volume_0dte,
                                     call_wall=call_wall, put_wall=put_wall, gamma_flip=gamma_flip)

        # --- NEW: build Gamma Hunter enrichment payload ---
        strike_ladder = []
        for strike in sorted(strike_ladder_raw.keys(), reverse=True):
            raw = strike_ladder_raw[strike]
            call = raw.get('C', {})
            put = raw.get('P', {})
            call_gex = call_gex_per_strike.get(strike, 0)
            put_gex = put_gex_per_strike.get(strike, 0)
            strike_ladder.append({
                "strike": strike,
                "call_bid": call.get('bid') or None,
                "call_ask": call.get('ask') or None,
                "call_last": call.get('last') or None,
                "call_volume": call.get('volume', 0),
                "call_oi": call.get('oi', 0),
                "call_gex": round(call_gex, 4),
                "call_delta": call.get('delta'),
                "call_gamma": call.get('gamma'),
                "call_theta": call.get('theta'),
                "call_vega": call.get('vega'),
                "put_bid": put.get('bid') or None,
                "put_ask": put.get('ask') or None,
                "put_last": put.get('last') or None,
                "put_volume": put.get('volume', 0),
                "put_oi": put.get('oi', 0),
                "put_gex": round(put_gex, 4),
                "put_delta": put.get('delta'),
                "put_gamma": put.get('gamma'),
                "put_theta": put.get('theta'),
                "put_vega": put.get('vega'),
            })

        call_gex_total = sum(call_gex_per_strike.values())
        put_gex_total = sum(put_gex_per_strike.values())
        gex_summary = {
            "call_gex_total": round(call_gex_total, 2),
            "put_gex_total": round(abs(put_gex_total), 2),
            "net_gex": round(call_gex_total + put_gex_total, 2),
            "max_abs_gex": round(
                max(
                    abs(call_gex_total),
                    abs(put_gex_total),
                    max((abs(v) for v in total_gex_per_strike.values()), default=0),
                ), 2),
        }

        iv_skew = []
        for strike in sorted(iv_skew_raw.keys()):
            raw = iv_skew_raw[strike]
            iv_skew.append({
                "strike": strike,
                "moneyness": round(strike / price, 4) if price else 0,
                "call_iv": raw.get('C'),
                "put_iv": raw.get('P'),
            })

        call_volume_total = sum(raw.get('C', {}).get('volume', 0) for raw in strike_ladder_raw.values())
        put_volume_total = sum(raw.get('P', {}).get('volume', 0) for raw in strike_ladder_raw.values())
        call_oi_total = sum(raw.get('C', {}).get('oi', 0) for raw in strike_ladder_raw.values())
        put_oi_total = sum(raw.get('P', {}).get('oi', 0) for raw in strike_ladder_raw.values())
        put_call_ratio = {
            "volume": round(put_volume_total / call_volume_total, 2) if call_volume_total > 0 else 0,
            "oi": round(put_oi_total / call_oi_total, 2) if call_oi_total > 0 else 0,
        }

        # VIX index for IRON_FLY strategy filter (best-effort, returns None if unavailable)
        # Fetched via Yahoo Finance HTTP API in a thread to avoid IBKR event-loop conflicts.
        vix_value = await self._fetch_vix_async()

        return {
            # --- Existing fields (unchanged, backward-compatible) ---
            "spot": price,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "gamma_flip": gamma_flip,
            "sigmas": sigmas,
            "dark_gamma": dg_top,
            "atm_iv": atm_iv,
            "gex_profile": total_gex_per_strike,
            "gex_by_expiry": gex_by_expiry,
            "expiries": expiries,
            "vix": vix_value,
            # --- NEW fields ---
            "oi_profile": oi_profile,
            "vol_profile": vol_profile,
            "oi_by_expiry": oi_by_expiry,
            "vol_by_expiry": vol_by_expiry,
            "max_change_gamma": max_change_gamma,
            # --- Gamma Hunter fields ---
            "strike_ladder": strike_ladder,
            "gex_summary": gex_summary,
            "iv_skew": iv_skew,
            "put_call_ratio": put_call_ratio,
            **zone_data,  # regime, bias, gex_zones, fade_setups, breakout_setups, etc.
        }

    def _append_csv(self, filename_suffix: str, headers: list, row: list):
        """Append a row to a daily CSV file in history/. Creates file with headers if new."""
        now = datetime.datetime.now()
        today_str = now.strftime('%Y%m%d')
        timestamp_str = now.strftime('%H:%M:%S')

        history_dir = os.path.join(os.path.dirname(__file__), 'history')
        os.makedirs(history_dir, exist_ok=True)

        filename = os.path.join(history_dir, f'{filename_suffix}_{today_str}.csv')
        file_exists = os.path.isfile(filename)

        try:
            with open(filename, 'a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(headers)
                writer.writerow([timestamp_str] + row)
        except Exception as e:
            print(f"Failed to log CSV data ({filename}): {e}")

    def _log_intraday_data(self, spot: float, expiry: str, gex_dict: dict, vol_dict: dict):
        """
        Append [Timestamp, Spot, Strike, NetGEX, Volume] to a daily CSV file.
        Used to draw the Intraday Bubble Map (GEX vs Time).
        Strike prices are normalized to the nearest multiple of 5.
        """
        import csv

        norm_gex = {}
        for k, v in gex_dict.items():
            ns = int(round(k / 5.0) * 5)
            norm_gex[ns] = norm_gex.get(ns, 0.0) + v

        norm_vol = {}
        for k, v in vol_dict.items():
            ns = int(round(k / 5.0) * 5)
            norm_vol[ns] = norm_vol.get(ns, 0) + v

        all_strikes = set(norm_gex.keys()).union(set(norm_vol.keys()))
        for strike in sorted(all_strikes):
            gex = norm_gex.get(strike, 0.0)
            vol = norm_vol.get(strike, 0)
            if abs(gex) > 1e-4 or vol > 0:
                self._append_csv(
                    f'gex_intraday_{expiry}',
                    ['Timestamp', 'Spot', 'Strike', 'NetGEX', 'Volume'],
                    [round(spot, 2), strike, round(gex, 4), vol]
                )

    def _log_premium_drift_data(self, spot: float, call_prem: float, put_prem: float,
                                 call_vol: int, put_vol: int,
                                 call_wall: float | None = None, put_wall: float | None = None,
                                 gamma_flip: float | None = None):
        self._append_csv(
            'premium_drift_0dte',
            ['Timestamp', 'Spot', 'CallPremium', 'PutPremium', 'CallVolume', 'PutVolume', 'CallWall', 'PutWall', 'GammaFlip'],
            [round(spot, 2), round(call_prem, 2), round(put_prem, 2), call_vol, put_vol,
             round(call_wall, 2) if call_wall is not None else '',
             round(put_wall, 2) if put_wall is not None else '',
             round(gamma_flip, 2) if gamma_flip is not None else '']
        )

    # ------------------------------------------------------------------
    # Position snapshot for the Gamma Hunter panel
    # ------------------------------------------------------------------

    def get_position_summary(self) -> dict | None:
        """
        Return the most relevant SPX/SPXW option position for the active position panel.
        Uses portfolio() first (includes market price and unrealized P&L), then positions().
        Returns None if no SPX/SPXW option position is found.
        """
        if not self.ib.isConnected():
            return None

        try:
            portfolio = self.ib.portfolio()
            positions = self.ib.positions()
        except Exception as e:
            print(f"[POSITION] Failed to fetch positions: {e}")
            return None

        target = None
        # Portfolio items include live marketPrice and unrealizedPNL
        for item in portfolio:
            contract = item.contract
            if contract.symbol in ('SPX', 'SPXW'):
                target = item
                break

        # Fallback to positions() if portfolio() has no SPX/SPXW option
        if target is None and positions:
            for pos in positions:
                contract = pos.contract
                if contract.symbol in ('SPX', 'SPXW'):
                    target = pos
                    break

        if target is None:
            return None

        contract = target.contract
        qty = int(target.position)
        avg_cost = getattr(target, 'averageCost', getattr(target, 'avgCost', 0))
        market_price = getattr(target, 'marketPrice', 0)

        # Default options multiplier is 100; read from contract if available.
        multiplier_raw = getattr(contract, 'multiplier', '100')
        try:
            multiplier = int(multiplier_raw)
        except (TypeError, ValueError):
            multiplier = 100

        if market_price and market_price > 0 and avg_cost and avg_cost > 0:
            cost = avg_cost * multiplier * abs(qty)
            current = market_price * multiplier * abs(qty)
            pnl = (current - cost) if qty > 0 else (cost - current)
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
        else:
            pnl = 0.0
            pnl_pct = 0.0

        return {
            "active": True,
            "symbol": contract.symbol,
            "right": contract.right,
            "strike": contract.strike,
            "expiry": getattr(contract, 'lastTradeDateOrContractMonth', None),
            "qty": abs(qty),
            "entry_price": round(avg_cost, 2) if avg_cost else None,
            "current_price": round(market_price, 2) if market_price else None,
            "unrealized_pnl": round(pnl, 2),
            "unrealized_pct": round(pnl_pct, 2),
            "opened_at": None,  # IBKR does not expose position open timestamp easily
        }

    @staticmethod
    def _classify_gex_zones(
        gex_profile: dict,
        oi_profile: dict,
        vol_profile: dict,
        price: float,
        call_wall,
        put_wall,
        gamma_flip,
    ) -> dict:
        """
        Classify GEX strikes into contiguous zones (clusters) and compute the market
        regime, bias, and actionable setups.

        Based on the Perplexity hilo strategy:
        - GEX positive cluster  → FADE zone (dealers stabilise / pin)
        - GEX negative cluster  → BREAKOUT zone (dealers amplify movement)
        - Confluence flag: volume > 0.5 * OI at the same strike (hot level)

        Returns a dict with keys: regime, regime_score, bias, net_gex_total,
        pinning_candidate, expected_range, breakout_risk, gex_zones,
        fade_setups, breakout_setups.
        """
        # ----------------------------------------------------------------
        # 1. Net GEX total (positive = dealers net long gamma = stabilising)
        # ----------------------------------------------------------------
        net_gex_total = sum(gex_profile.values()) if gex_profile else 0.0

        # ----------------------------------------------------------------
        # 2. Regime: spot vs gamma_flip
        # ----------------------------------------------------------------
        try:
            flip_val = float(gamma_flip)
        except (TypeError, ValueError):
            flip_val = None

        if flip_val is not None:
            regime_score = (price - flip_val) / price  # positive = above flip
            if regime_score > 0.0015:       # >0.15% above flip
                regime = "LONG_GAMMA"
            elif regime_score < -0.0015:    # >0.15% below flip
                regime = "SHORT_GAMMA"
            else:
                regime = "NEUTRAL"
        else:
            regime_score = 0.0
            regime = "NEUTRAL"

        # ----------------------------------------------------------------
        # 3. Directional bias from net GEX sign
        # ----------------------------------------------------------------
        if net_gex_total > 0:
            bias = "BULLISH"
        elif net_gex_total < 0:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        # ----------------------------------------------------------------
        # 4. Pinning candidate: GEX-positive strike nearest to spot
        # ----------------------------------------------------------------
        positive_strikes = [
            k for k, v in gex_profile.items()
            if v > 0 and abs(k - price) / price <= 0.03
        ]
        pinning_candidate = (
            min(positive_strikes, key=lambda k: abs(k - price))
            if positive_strikes else None
        )

        # ----------------------------------------------------------------
        # 5. Expected range
        # ----------------------------------------------------------------
        try:
            expected_range = [
                float(put_wall) if put_wall is not None else price * 0.975,
                float(call_wall) if call_wall is not None else price * 1.025,
            ]
        except (TypeError, ValueError):
            expected_range = [price * 0.975, price * 1.025]

        # ----------------------------------------------------------------
        # 6. Breakout risk: how close spot is to a Wall
        # ----------------------------------------------------------------
        try:
            dist_call = abs(price - float(call_wall)) / price if call_wall else 1.0
            dist_put = abs(price - float(put_wall)) / price if put_wall else 1.0
            min_dist = min(dist_call, dist_put)
        except (TypeError, ValueError):
            min_dist = 1.0

        if min_dist < 0.002:       # Within 0.2% of a wall
            breakout_risk = "HIGH"
        elif min_dist < 0.005:     # Within 0.5%
            breakout_risk = "MEDIUM"
        else:
            breakout_risk = "LOW"

        # ----------------------------------------------------------------
        # 7. Zone detection: cluster strikes by contiguous sign and proximity
        #    SPX strikes are in 5pt increments, so contiguous = gap <= 10pts
        # ----------------------------------------------------------------
        # Only consider strikes within ±5% of spot to avoid noise
        nearby = {
            k: v for k, v in gex_profile.items()
            if v != 0 and abs(k - price) / price <= 0.05
        }
        sorted_strikes = sorted(nearby.keys())

        zones = []
        if sorted_strikes:
            current_group = [sorted_strikes[0]]
            current_sign = 1 if nearby[sorted_strikes[0]] > 0 else -1

            for s in sorted_strikes[1:]:
                s_sign = 1 if nearby[s] > 0 else -1
                gap = s - current_group[-1]
                # Same sign AND close enough (≤10pt gap) → extend cluster
                if s_sign == current_sign and gap <= 10:
                    current_group.append(s)
                else:
                    # Commit current cluster
                    zones.append((current_group, current_sign))
                    current_group = [s]
                    current_sign = s_sign
            zones.append((current_group, current_sign))

        gex_zones = []
        for (group_strikes, sign) in zones:
            # Peak strike (highest |GEX| in the cluster)
            peak_strike = max(group_strikes, key=lambda k: abs(nearby[k]))
            peak_gex = nearby[peak_strike]

            # Average OI across the cluster (structural weight indicator)
            avg_oi = (
                sum(oi_profile.get(k, 0) for k in group_strikes) / len(group_strikes)
            )

            # Confluence: any strike in the cluster has vol > 0.5 * OI (hot activity)
            confluence = any(
                vol_profile.get(k, 0) > 0.5 * oi_profile.get(k, 1)
                for k in group_strikes
                if oi_profile.get(k, 0) > 0
            )

            zone_type = "FADE" if sign > 0 else "BREAKOUT"

            gex_zones.append({
                "strikes": group_strikes,
                "sign": "POSITIVE" if sign > 0 else "NEGATIVE",
                "type": zone_type,
                "peak_strike": peak_strike,
                "peak_gex": round(peak_gex, 4),
                "avg_oi": round(avg_oi, 0),
                "confluence": confluence,
            })

        # Sort by |peak_gex| descending so the most relevant zones are first
        gex_zones.sort(key=lambda z: abs(z["peak_gex"]), reverse=True)

        # ----------------------------------------------------------------
        # 8. Build actionable setups from the top zones
        # ----------------------------------------------------------------
        fade_setups = []
        breakout_setups = []

        # Helper: find the next GEX-positive zone beyond a given strike
        def _next_positive_wall(from_strike: float, direction: str) -> float | None:
            """Return the peak_strike of the nearest FADE zone beyond from_strike."""
            candidates = [
                z["peak_strike"] for z in gex_zones
                if z["type"] == "FADE" and z["peak_strike"] != from_strike
                and (
                    z["peak_strike"] > from_strike if direction == "UP"
                    else z["peak_strike"] < from_strike
                )
            ]
            if not candidates:
                return None
            return min(candidates, key=lambda k: abs(k - from_strike))

        for zone in gex_zones[:5]:  # Consider only top 5 zones
            anchor = zone["peak_strike"]
            proximity = abs(anchor - price) / price  # How close is spot

            if zone["type"] == "FADE":
                # Fade setup: spot approaching a positive GEX wall
                if proximity <= 0.005:  # Within 0.5% of the wall
                    direction_lbl = "CCS" if anchor > price else "PCS"
                    tp = _next_positive_wall(
                        anchor, "DOWN" if anchor > price else "UP"
                    )
                    fade_setups.append({
                        "type": direction_lbl,
                        "anchor": anchor,
                        "approach": "from_below" if anchor > price else "from_above",
                        "tp": tp,
                        "label": (
                            f"{direction_lbl} fade \u2264 {anchor} "
                            f"| TP \u2192 {tp}"
                            if tp else
                            f"{direction_lbl} fade \u2264 {anchor}"
                        ),
                        "confluence": zone["confluence"],
                    })

            elif zone["type"] == "BREAKOUT":
                # Breakout setup: spot inside or just crossed a negative GEX zone
                if proximity <= 0.003:  # Within 0.3% of the zone
                    direction_lbl = "CCS" if price > anchor else "PCS"
                    tp = _next_positive_wall(
                        anchor, "UP" if price > anchor else "DOWN"
                    )
                    breakout_setups.append({
                        "type": direction_lbl,
                        "anchor": anchor,
                        "tp": tp,
                        "label": (
                            f"{direction_lbl} breakout from {anchor} "
                            f"| TP \u2192 {tp}"
                            if tp else
                            f"{direction_lbl} breakout from {anchor}"
                        ),
                        "confluence": zone["confluence"],
                    })

        return {
            "regime": regime,
            "regime_score": round(regime_score * 100, 2),  # In % distance from flip
            "bias": bias,
            "net_gex_total": round(net_gex_total, 4),
            "pinning_candidate": pinning_candidate,
            "expected_range": expected_range,
            "breakout_risk": breakout_risk,
            "gex_zones": gex_zones,
            "fade_setups": fade_setups,
            "breakout_setups": breakout_setups,
        }

    async def _find_strike_by_delta(self, right: str, target_delta: float,
                                     expiry: str, strikes: list, price: float,
                                     details: list) -> float:
        """
        Scan nearby OTM strikes and return the one with delta closest to target.
        Falls back to a 40pt offset if greeks data is unavailable.
        """
        print(f"Scanning for {target_delta}Δ {right}...")

        if right == 'C':
            candidates = sorted([s for s in strikes if s > price])[:30]
        else:
            candidates = sorted([s for s in strikes if s < price], reverse=True)[:30]

        if not candidates:
            offset = 40
            return min(strikes, key=lambda x: abs(x - (price + offset if right == 'C' else price - offset)))

        # Find the exact, pre-qualified contract objects from the details we already fetched
        contracts = []
        for s in candidates:
            for d in details:
                if d.contract.strike == s and d.contract.right == right:
                    contracts.append(d.contract)
                    break
                    
        if not contracts:
            print("WARNING: Could not match candidates to retrieved details.")
            offset = 40
            return min(strikes, key=lambda x: abs(x - (price + offset if right == 'C' else price - offset)))

        # Use module-level Black-Scholes delta estimate to avoid IBKR network delays
        best_strike = None
        min_diff = float('inf')
        target_abs = abs(target_delta)

        for contract in contracts:
            current_delta = abs(calc_bs_delta(price, contract.strike, right))
            diff = abs(current_delta - target_abs)
            
            if diff < min_diff:
                min_diff = diff
                best_strike = contract.strike

        if best_strike is None:
            print("WARNING: Could not calculate greeks locally. Using 40pt offset fallback.")
            offset = 40
            best_strike = min(
                candidates,
                key=lambda x: abs(x - (price + offset if right == 'C' else price - offset))
            )

        print(f"Selected strike: {best_strike} ({right})")
        return best_strike

    async def _find_spread_by_rr(self, right: str, target_rr: float, width: int,
                                 strikes: list, price: float, details: list) -> float:
        """
        Sequential Directional Search: Start at ATM, move into ITM territory
        (Down for Calls, Up for Puts) until a spread paying the target credit is found.
        
        Uses 2-contract requests per step to stay well within IBKR market data limits.
        """
        import math
        import asyncio

        # Target Credit = Width - (Width / (1 + RR))
        min_credit = width - (width / (1.0 + target_rr))
        print(f"Sequential R:R Scan '{right}' | Target Credit >= {min_credit:.2f}")

        # Build a lookup table of SPXW contracts by strike
        spxw_by_strike = {}
        for d in details:
            if d.contract.right == right and d.contract.tradingClass == "SPXW":
                spxw_by_strike[d.contract.strike] = d.contract

        # ATM strike index
        atm = min(strikes, key=lambda x: abs(x - price))

        # Search direction:
        # - For Puts: ITM = HIGHER strike (> price). Sort descending from ATM upward.
        # - For Calls: ITM = LOWER strike (< price). Sort descending from ATM downward.
        if right == 'P':
            search_list = sorted([s for s in strikes if s >= atm], reverse=False)  # ATM -> UP ascending (ITM puts)
        else:
            search_list = sorted([s for s in strikes if s <= atm], reverse=True)   # ATM -> DOWN (ITM calls)


        async def price_pair(short_s, long_s):
            """Fetches live credit for a single short/long pair. Returns (credit, short_px, long_px)."""
            c_short = spxw_by_strike.get(short_s)
            c_long = spxw_by_strike.get(long_s)
            if not c_short or not c_long:
                return 0, 0, 0
            try:
                tickers = await asyncio.wait_for(
                    self.ib.reqTickersAsync(c_short, c_long), timeout=4.0
                )
                px = {t.contract.strike: self._get_robust_price(t) for t in tickers}
                s_px, l_px = px.get(short_s, 0), px.get(long_s, 0)
                return (s_px - l_px) if s_px > 0 and l_px > 0 else 0, s_px, l_px
            except Exception as e:
                print(f"  -> Error pricing {short_s}/{long_s}: {e}")
                return 0, 0, 0

        # -- Step 1: Sample ATM --
        atm_long = atm + width if right == 'C' else atm - width
        atm_credit, atm_s, atm_l = await price_pair(atm, atm_long)
        print(f"  -> ATM {atm}/{atm_long} short={atm_s:.2f} long={atm_l:.2f} credit={atm_credit:.2f}")

        if atm_credit >= min_credit:
            print(f"  -> TARGET MET immediately at ATM {atm}")
            return atm

        # -- Step 2: Sample one step further ITM to measure slope --
        step = 5  # SPX strikes are usually 5 pts apart
        probe_s = atm - step if right == 'C' else atm + step
        probe_long = probe_s + width if right == 'C' else probe_s - width
        probe_credit, p_s, p_l = await price_pair(probe_s, probe_long)
        credit_delta_per_step = max(probe_credit - atm_credit, 0.01)
        print(f"  -> Probe {probe_s}/{probe_long} credit={probe_credit:.2f} | Slope={credit_delta_per_step:.2f}/step")

        # -- Step 3: Predictive Jump --
        needed_extra = min_credit - probe_credit
        extra_steps = max(0, int(needed_extra / credit_delta_per_step) + 1)
        jump_s = probe_s - (extra_steps * step) if right == 'C' else probe_s + (extra_steps * step)
        # Snap to nearest valid strike
        jump_s = min(search_list, key=lambda x: abs(x - jump_s))
        jump_long = jump_s + width if right == 'C' else jump_s - width
        jump_credit, j_s, j_l = await price_pair(jump_s, jump_long)
        print(f"  -> Jump {jump_s}/{jump_long} credit={jump_credit:.2f} (target>={min_credit:.2f})")

        if jump_credit >= min_credit:
            # -- Step 4: Walk back OTM to find the most OTM strike that still meets target --
            best_s = jump_s
            walk_s = jump_s + step if right == 'C' else jump_s - step
            while walk_s in {s for s in search_list} and abs(walk_s - atm) <= abs(jump_s - atm):
                w_long = walk_s + width if right == 'C' else walk_s - width
                w_credit, _, _ = await price_pair(walk_s, w_long)
                print(f"  -> Walk-back {walk_s}/{w_long} credit={w_credit:.2f}")
                if w_credit >= min_credit:
                    best_s = walk_s
                    walk_s = walk_s + step if right == 'C' else walk_s - step
                else:
                    break
            print(f"  -> FINAL SELECTED: {best_s}")
            return best_s
        else:
            # Jump overshot (credit still too low), walk further ITM
            print("  -> Jump undershot, walking ITM...")
            walk_s = jump_s - step if right == 'C' else jump_s + step
            for _ in range(10):
                if walk_s not in {s for s in search_list}:
                    break
                w_long = walk_s + width if right == 'C' else walk_s - width
                w_credit, _, _ = await price_pair(walk_s, w_long)
                print(f"  -> Walk {walk_s}/{w_long} credit={w_credit:.2f}")
                if w_credit >= min_credit:
                    print(f"  -> TARGET MET at {walk_s}")
                    return walk_s
                walk_s = walk_s - step if right == 'C' else walk_s + step

        print("WARNING: Predictive Jump could not find R:R target. Using ATM fallback.")
        return atm



    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    async def execute_spread(self, spread_type: str, qty: int, target_mode: str, target_value: float,
                              width: int, tp_pct: float, sl_ratio: float,
                              transmit: bool = False,
                              entry_trigger_price: float | None = None,
                              tp_trigger_price: float | None = None,
                              sl_trigger_price: float | None = None,
                              bracket: bool = True,
                              delta_target_put: float | None = None,
                              delta_target_call: float | None = None):
        """
        Build and place a spread order (PCS, CCS, or IC) via IBKR API.

        Args:
            spread_type: 'PCS', 'CCS', or 'IC'
            qty: number of contracts
            target_mode: 'Delta', 'R:R', 'GEX', 'orb15', or 'iron_fly'
            target_value: numeric target for Delta/R:R modes (ignored for GEX/orb15/iron_fly)
            width: points between legs (e.g. 15)
            tp_pct: take-profit % of credit (e.g. 50)
            sl_ratio: stop-loss multiplier of credit (e.g. 2.5)
            transmit: True sends live; False stages in TWS for manual confirm
            entry_trigger_price: underlying price that triggers the entry order (IBKR PriceCondition)
            tp_trigger_price: underlying price that triggers the take-profit
            sl_trigger_price: underlying price that triggers the stop-loss
            bracket: True (default) places entry + TP + SL_LMT + SL_MKT as an OCA bracket.
                     False places only the entry combo (no TP/SL children) — parent transmits
                     directly when transmit=True. Useful for manual exit management or testing.
            delta_target_put: IC iron_fly mode — short put delta target (e.g. -0.50).
            delta_target_call: IC iron_fly mode — short call delta target (e.g. +0.40).
        """
        if not self.ib.isConnected():
            raise RuntimeError("Not connected to IBKR.")

        # Execute Spread - find strikes and build legs
        price, expiry, strikes, details = await self._get_chain_data()

        short_put_strike = None
        short_call_strike = None

        # --- NEW: GEX mode — anchor short legs to GEX Walls ---
        if target_mode.lower() == 'gex':
            # Require cached market metrics for Wall data.
            # If stale (>5 min) or absent, fetch fresh metrics first.
            metrics_stale = True
            if hasattr(self, '_last_metrics') and hasattr(self, '_last_metrics_time'):
                import time
                age = time.time() - self._last_metrics_time
                if age < 300:  # Less than 5 minutes old
                    metrics_stale = False

            if metrics_stale:
                print("[GEX mode] Fetching fresh market metrics for Wall data...")
                cached = await self.fetch_market_metrics()
                self._last_metrics = cached
                import time
                self._last_metrics_time = time.time()
            else:
                cached = self._last_metrics
                print("[GEX mode] Using cached Wall data.")

            put_wall = cached.get('put_wall')
            call_wall = cached.get('call_wall')

            if spread_type in ('PCS', 'IC'):
                # Short put anchored to Put Wall (the strongest support level)
                if put_wall and put_wall in strikes:
                    short_put_strike = put_wall
                else:
                    # Snap to nearest available strike if the Wall isn't exactly in the chain
                    short_put_strike = min(strikes, key=lambda x: abs(x - put_wall)) if put_wall else None
                print(f"[GEX mode] Short Put anchored to Put Wall: {short_put_strike}")

            if spread_type in ('CCS', 'IC'):
                # Short call anchored to Call Wall (the strongest resistance level)
                if call_wall and call_wall in strikes:
                    short_call_strike = call_wall
                else:
                    short_call_strike = min(strikes, key=lambda x: abs(x - call_wall)) if call_wall else None
                print(f"[GEX mode] Short Call anchored to Call Wall: {short_call_strike}")

        # --- ORB15 mode: short strike pre-computed by bot (anchored to ORB ± buffer) ---
        elif target_mode.lower() == 'orb15':
            # Snap to nearest available strike (SPX strikes are 5pt increments;
            # ORB buffer calc gives a continuous value that won't match a contract)
            short_strike = min(strikes, key=lambda x: abs(x - float(target_value)))
            if spread_type in ('PCS', 'IC'):
                short_put_strike = short_strike
            if spread_type in ('CCS', 'IC'):
                short_call_strike = short_strike

        # --- MILK_MAN mode: short strike pre-computed by bot (prev_week_close - ATR) ---
        elif target_mode.lower() == 'milk_man':
            short_strike = min(strikes, key=lambda x: abs(x - float(target_value)))
            if spread_type in ('PCS', 'IC'):
                short_put_strike = short_strike
            if spread_type in ('CCS', 'IC'):
                short_call_strike = short_strike

        # --- IRON_FLY mode: 4-leg IC with per-side delta targets (-0.50 put, +0.40 call) ---
        elif target_mode.lower() == 'iron_fly':
            if spread_type != 'IC':
                raise RuntimeError("IRON_FLY target_mode requires spread_type='IC' (4 legs)")
            put_delta = float(delta_target_put) if delta_target_put is not None else -0.50
            call_delta = float(delta_target_call) if delta_target_call is not None else 0.40
            short_put_strike = await self._find_strike_by_delta('P', put_delta, expiry, strikes, price, details)
            short_call_strike = await self._find_strike_by_delta('C', call_delta, expiry, strikes, price, details)

        # --- Existing Delta / R:R targeting (unchanged) ---
        elif spread_type in ('PCS', 'IC'):
            if target_mode.lower() == 'delta':
                short_put_strike = await self._find_strike_by_delta('P', target_value, expiry, strikes, price, details)
            else:
                short_put_strike = await self._find_spread_by_rr('P', target_value, width, strikes, price, details)

        if target_mode.lower() not in ('gex', 'orb15', 'iron_fly', 'milk_man') and spread_type in ('CCS', 'IC'):
            if target_mode.lower() == 'delta':
                short_call_strike = await self._find_strike_by_delta('C', target_value, expiry, strikes, price, details)
            else:
                short_call_strike = await self._find_spread_by_rr('C', target_value, width, strikes, price, details)

        print(f"Strikes → Put Short: {short_put_strike} | Call Short: {short_call_strike}")

        # Distribute into individual contracts using the actual, fully-qualified Contract objects
        contracts_to_trade = []
        
        def find_exact_contract(strike, right):
            # Prioritize SPXW (0DTE Weeklies) to avoid mixing with SPX (Monthlies)
            matches = [d.contract for d in details if d.contract.strike == strike and d.contract.right == right]
            if not matches: return None
            # Return SPXW if available, else first match
            for c in matches:
                if c.tradingClass == "SPXW":
                    return c
            return matches[0]
            
        def find_nearest_strike(target_strike):
            # Find the closest strike that actually exists in the chain
            return min(strikes, key=lambda x: abs(x - target_strike))

        if spread_type in ('PCS', 'IC') and short_put_strike:
            long_put_target = short_put_strike - width
            actual_long_put = find_nearest_strike(long_put_target)
            print(f"  PCS Legs -> Short: {short_put_strike}, Long target: {long_put_target} (Snapping to {actual_long_put})")
            
            short_p = find_exact_contract(short_put_strike, 'P')
            long_p = find_exact_contract(actual_long_put, 'P')
            if short_p and long_p:
                contracts_to_trade.append((short_p, 'SELL'))
                contracts_to_trade.append((long_p, 'BUY'))
            else:
                print(f"  ERROR: Could not qualify PCS legs (Short: {short_p is not None}, Long: {long_p is not None})")

        if spread_type in ('CCS', 'IC') and short_call_strike:
            long_call_target = short_call_strike + width
            actual_long_call = find_nearest_strike(long_call_target)
            print(f"  CCS Legs -> Short: {short_call_strike}, Long target: {long_call_target} (Snapping to {actual_long_call})")
            
            short_c = find_exact_contract(short_call_strike, 'C')
            long_c = find_exact_contract(actual_long_call, 'C')
            if short_c and long_c:
                contracts_to_trade.append((short_c, 'SELL'))
                contracts_to_trade.append((long_c, 'BUY'))
            else:
                print(f"  ERROR: Could not qualify CCS legs (Short: {short_c is not None}, Long: {long_c is not None})")

        if not contracts_to_trade:
            raise RuntimeError("No contracts were built — check chain data.")

        # Build BAG contract from the exact matched and sorted contracts
        combo_legs = []
        print("  [DEBUG] Final Sorted Combo Legs:")
        for contract, action in contracts_to_trade:
            print(f"    -> ConId: {contract.conId} | Action: {action} | Strike: {contract.strike} | Right: {contract.right}")
            leg = ComboLeg(
                conId=contract.conId,
                ratio=1,
                action=action,
                exchange="SMART" # Explicitly SMART for routing
            )
            combo_legs.append(leg)

        bag_contract = Contract()
        bag_contract.symbol = self.symbol
        bag_contract.secType = 'BAG'
        bag_contract.currency = 'USD'
        bag_contract.exchange = self.exchange
        
        # Explicit definitions to avoid Error 200 on multi-leg Index Combos
        if len(combo_legs) > 2:
            bag_contract.tradingClass = "SPXW"  # Highly specific for 0DTE Combos
            
        bag_contract.comboLegs = combo_legs

        print("\n[DEBUG STRICT] BAG Definition:")
        print(f"  Symbol: {bag_contract.symbol}")
        print(f"  SecType: {bag_contract.secType}")
        print(f"  Currency: {bag_contract.currency}")
        print(f"  Exchange: {bag_contract.exchange}")
        print(f"  TradingClass: {bag_contract.tradingClass}")
        print(f"  Legs count: {len(bag_contract.comboLegs)}")
        for i, l in enumerate(bag_contract.comboLegs):
            print(f"    L{i+1}: conid={l.conId} act={l.action} rto={l.ratio} exc={l.exchange}")

        # Fetch actual pricing for the final 2 or 4 legs to calculate Mid Price dynamically
        try:
            leg_contracts = [c for c, action in contracts_to_trade]
            try:
                leg_tickers = await asyncio.wait_for(self.ib.reqTickersAsync(*leg_contracts), timeout=2.5)
            except asyncio.TimeoutError:
                print("  [Price] WARNING: reqTickersAsync timed out, using cached tickers...")
                # Fallback to cached tickers to prevent the app from freezing on sequential clicks
                leg_tickers = [t for t in self.ib.tickers() if t.contract.conId in [c.conId for c in leg_contracts]]
                
            import math
            
            def get_valid(p):
                return p if p is not None and not math.isnan(p) and p >= 0 else None

            net_debit = 0.0
            for contract, action in contracts_to_trade:
                ticker = next((t for t in leg_tickers if t.contract.conId == contract.conId), None)
                mid_price = self._get_robust_price(ticker) if ticker else 0.0
                        
                print(f"  [Price] {action} {contract.localSymbol} -> Mid: {mid_price:.2f}")
                
                if action == 'BUY':
                    net_debit += mid_price
                elif action == 'SELL':
                    net_debit -= mid_price
                    
            # Round to nearest 0.05
            calculated_limit = round(net_debit / 0.05) * 0.05
            print(f"  [Price] Calculated Combo Mid Price (Net Debit): {calculated_limit:.2f}")

            # CRITICAL PRE-FLIGHT CHECK: For R:R mode, ensure credit satisfies the threshold
            if target_mode.lower() == 'r:r':
                # Target credit is Width / (1 + RR)
                min_credit_required = width - (width / (1.0 + target_value))
                actual_credit = -calculated_limit
                
                if actual_credit < min_credit_required - 0.20: # 0.20 grace for extreme volatility
                    raise RuntimeError(f"CREDIT VALIDATION FAILED: Target {min_credit_required:.2f}, Found {actual_credit:.2f}. Aborting to prevent bad fill.")
            
        except Exception as e:
            print(f"  [Price] ERROR: {e}")
            # Do not use fallbacks for R:R mode, safety first
            if target_mode.lower() == 'r:r':
                raise
            calculated_limit = -4.50 if spread_type == 'IC' else -2.50

        # CRITICAL: IBKR requires Credit Combo orders to be submitted as a 'BUY' order
        # with a NEGATIVE limit price. If you submit a 'SELL', it flips the legs into a Debit Spread.
        order = LimitOrder('BUY', qty, calculated_limit)
        order.tif = 'DAY'  # Explicitly prevent TWS 'Error 10349: Order TIF was set to DAY' auto-cancellation
        # CRITICAL: Parent MUST be False. If the parent transmits before the children are added 
        # to the same payload block, TWS throws Error 201 when the children finally arrive.
        # The final bracket leg triggers the transmission of the entire chain globally.
        order.transmit = False
        
        # CRITICAL: SPX SMART Combo routing requirements differ for 2-leg and 4-leg Combos.
        # 2-leg combos (PCS/CCS) require NonGuaranteed=1 or they throw Error 201 (Risk-Free Arb)
        # 4-leg combos (IC) require no routing parameters or they throw Error 10043 (Invalid Tag)
        routing_tags = [] if spread_type == 'IC' else [TagValue('NonGuaranteed', '1')]
        order.smartComboRoutingParams = routing_tags

        # CRITICAL: Do NOT place the parent order prematurely, or TWS will reject the subsequent children (Error 201).
        # We must pre-allocate the OrderID, build the entire bracket tree, and submit them sequentially in one payload.
        import traceback
        try:
            parent_id = self.ib.client.getReqId()
            order.orderId = parent_id
        except Exception as e:
            raise RuntimeError(f"IBKR Failed to allocate OrderId: {e}\n{traceback.format_exc()}")
        
        # 3-Component OCO Pattern (Take Profit Limit, Stop Limit, Stop Market)
        oca_group_name = f"OCA_SPX_{parent_id}"

        # 1. Take Profit (LMT)
        target_debit_tp = abs(calculated_limit) * (1.0 - tp_pct / 100.0)
        tp_limit = -abs(round(target_debit_tp / 0.05) * 0.05)
        
        tp_order = LimitOrder('SELL', qty, tp_limit)
        tp_order.tif = 'DAY'
        tp_order.parentId = parent_id
        tp_order.ocaGroup = oca_group_name
        tp_order.ocaType = 1  # 1 = Cancel all remaining orders on fill
        tp_order.transmit = False
        tp_order.smartComboRoutingParams = []

        # 2. Stop Limit (Primary SL)
        # Base credit value and stop loss buffer logic
        credit_base = abs(calculated_limit)
        # We calculate exact values using the pattern provided by the user
        trigger_val_sl = (credit_base * sl_ratio) - 0.07
        trigger_price_sl = -abs(round(trigger_val_sl / 0.05) * 0.05)
        
        # Stop limit is slightly less negative (worse) than trigger to ensure fill
        limit_price_sl = -abs(round((abs(trigger_price_sl) + 0.20) / 0.05) * 0.05)
        
        from ib_async import Order as IbOrder
        sl_limit = IbOrder()
        sl_limit.action = 'SELL'
        sl_limit.orderType = 'STP LMT'
        sl_limit.tif = 'DAY'
        sl_limit.totalQuantity = qty
        sl_limit.auxPrice = trigger_price_sl
        sl_limit.lmtPrice = limit_price_sl
        sl_limit.parentId = parent_id
        sl_limit.ocaGroup = oca_group_name
        sl_limit.ocaType = 1
        sl_limit.transmit = False
        sl_limit.smartComboRoutingParams = []

        # 3. Stop Market (Safety SL)
        # Safety trigger is even more negative (worse) than primary limit
        market_trigger_sl = -abs(round((abs(trigger_price_sl) + 0.35) / 0.05) * 0.05)
        
        sl_market = IbOrder()
        sl_market.action = 'SELL'
        sl_market.orderType = 'STP'
        sl_market.tif = 'DAY'
        sl_market.totalQuantity = qty
        sl_market.auxPrice = market_trigger_sl
        sl_market.parentId = parent_id
        sl_market.ocaGroup = oca_group_name
        sl_market.ocaType = 1
        sl_market.transmit = transmit # The LAST order specifies if the bracket is transmitted to the exchange
        sl_market.smartComboRoutingParams = []

        print(f"Placing {spread_type} Combo BAG | Credit: {calculated_limit} | TP: {tp_limit} | SL LMT: {trigger_price_sl}/{limit_price_sl} | SL MKT: {market_trigger_sl} | Transmit: {transmit}")

        # Attach PriceConditions for underlying price triggers (ORB levels)
        any_trigger = entry_trigger_price or tp_trigger_price or sl_trigger_price
        if any_trigger:
            try:
                # Qualify SPX underlying to get its conId
                under_contract = Contract()
                under_contract.symbol = 'SPX'
                under_contract.secType = 'IND'
                under_contract.exchange = 'CBOE'
                under_contract.currency = 'USD'
                qualified = self.ib.qualifyContract(under_contract)
                spx_conId = qualified.conId if qualified else 0
                if not spx_conId:
                    print("[execute_spread] WARNING: could not qualify SPX contract for PriceCondition")
                else:
                    def make_price_cond(price, is_above):
                        cond = PriceCondition()
                        cond.conId = spx_conId
                        cond.exchange = 'CBOE'
                        cond.isMore = is_above
                        cond.price = price
                        return cond

                    if entry_trigger_price:
                        order.conditions.append(make_price_cond(entry_trigger_price, True))
                        order.conditionsIgnoreRth = True
                        print(f"[execute_spread] Entry PriceCondition: SPX {'>' if True else '<'} {entry_trigger_price}")

                    if tp_trigger_price:
                        tp_order.conditions.append(make_price_cond(tp_trigger_price, True))
                        tp_order.conditionsIgnoreRth = True
                        print(f"[execute_spread] TP PriceCondition: SPX > {tp_trigger_price}")

                    if sl_trigger_price:
                        # SL triggers when price goes BELOW the level (isMore=False)
                        sl_limit.conditions.append(make_price_cond(sl_trigger_price, False))
                        sl_limit.conditionsIgnoreRth = True
                        sl_market.conditions.append(make_price_cond(sl_trigger_price, False))
                        sl_market.conditionsIgnoreRth = True
                        print(f"[execute_spread] SL PriceCondition: SPX < {sl_trigger_price}")
            except Exception as e:
                print(f"[execute_spread] WARNING: failed to attach PriceConditions: {e}")

        # No-bracket mode: parent transmits directly, no TP/SL children
        if not bracket:
            order.transmit = transmit
            print(f"Placing {spread_type} Combo BAG | NO BRACKET (TP/SL disabled) | Transmit: {transmit}")
            parent_trade = self.ib.placeOrder(bag_contract, order)
            for _ in range(20):
                await asyncio.sleep(0.1)
            print(f"✅ Combo PARENT ONLY (no bracket) | Status: {parent_trade.orderStatus.status} | Transmit: {transmit}")
            return parent_trade

        # Sequentially place the entire bundled package (Parent -> Children)
        parent_trade = self.ib.placeOrder(bag_contract, order)
        tp_trade = self.ib.placeOrder(bag_contract, tp_order)
        sl_limit_trade = self.ib.placeOrder(bag_contract, sl_limit)
        sl_market_trade = self.ib.placeOrder(bag_contract, sl_market)
        
        # CRITICAL: Force the event loop to flush the order queue to TWS before returning to GUI
        for _ in range(20):
            await asyncio.sleep(0.1)
            
        print(f"✅ Combo Bracket: PARENT {parent_trade.orderStatus.status} | TP {tp_trade.orderStatus.status} | SL_LMT {sl_limit_trade.orderStatus.status} | SL_MKT {sl_market_trade.orderStatus.status}")
        return parent_trade

    # ------------------------------------------------------------------
    # Single-leg option purchase (for ORB strategy)
    # ------------------------------------------------------------------

    async def execute_single_leg(
        self,
        right: Literal['CALL', 'PUT'],
        qty: int = 1,
        strike: float | None = None,
        orb_mid: float | None = None,
        limit_price: float | None = None,
        transmit: bool = False,
        entry_trigger_price: float | None = None,
        tp_trigger_price: float | None = None,
        sl_trigger_price: float | None = None,
    ):
        """
        Buy a single call or put with price-condition triggers on SPX underlying.

        This is used for ORB strategy: buy call (bullish) or put (bearish) at orb_mid,
        with TP and SL triggered when SPX crosses tp_trigger_price / sl_trigger_price.
        """
        if not self.ib.isConnected():
            raise RuntimeError("Not connected to IBKR.")

        price, expiry, strikes, details = await self._get_chain_data()

        right_upper = right.upper()

        # Strike selection: orb_mid ± 1 strike (SPX strikes are 5pt apart)
        if orb_mid is not None:
            if right_upper == 'CALL':
                target = orb_mid + 5   # 1 strike above orb_mid
            else:
                target = orb_mid - 5   # 1 strike below orb_mid
        else:
            target = strike if strike else price

        candidates = [s for s in strikes if
                      (right_upper == 'CALL' and s >= target) or
                      (right_upper == 'PUT' and s <= target)]
        if not candidates:
            candidates = strikes
        chosen_strike = min(candidates, key=lambda x: abs(x - target))

        # Find the exact contract
        def find_contract(strike, right):
            matches = [d.contract for d in details
                       if d.contract.strike == strike and d.contract.right == right]
            if not matches:
                return None
            for c in matches:
                if c.tradingClass == "SPXW":
                    return c
            return matches[0]

        contract = find_contract(chosen_strike, right_upper)
        if not contract:
            raise RuntimeError(f"No SPX contract found for strike={chosen_strike} right={right_upper}")

        # Use a mid-price estimate for the limit price if not provided
        if limit_price is None:
            limit_price = price * 0.01  # rough estimate; adjust as needed

        # Qualify SPX for PriceCondition
        spx_conId = 0
        try:
            under_contract = Contract()
            under_contract.symbol = 'SPX'
            under_contract.secType = 'IND'
            under_contract.exchange = 'CBOE'
            under_contract.currency = 'USD'
            qualified = self.ib.qualifyContract(under_contract)
            spx_conId = qualified.conId if qualified else 0
        except Exception as e:
            print(f"[execute_single_leg] WARNING: could not qualify SPX: {e}")

        def make_cond(p, is_above):
            cond = PriceCondition()
            cond.conId = spx_conId
            cond.exchange = 'CBOE'
            cond.isMore = is_above
            cond.price = p
            return cond

        # Estimate limit price for initial order
        estimated_price = limit_price if limit_price else 1.0

        # Parent: BUY LMT — wait for fill before attaching TP/SL
        parent_id = self.ib.client.getReqId()
        order = LimitOrder('BUY', qty, estimated_price)
        order.tif = 'DAY'
        order.transmit = False
        order.orderId = parent_id

        if entry_trigger_price and spx_conId:
            order.conditions.append(make_cond(entry_trigger_price, True))
            order.conditionsIgnoreRth = True
            print(f"[execute_single_leg] Entry trigger: SPX > {entry_trigger_price}")

        print(f"[execute_single_leg] Placing {right_upper} {qty}x@{chosen_strike} @ ~{estimated_price} | Entry: {entry_trigger_price}")

        parent_trade = self.ib.placeOrder(contract, order)

        # Wait up to 30s for fill
        filled = False
        for _ in range(60):
            await asyncio.sleep(0.5)
            if parent_trade.orderStatus.status == 'Filled':
                filled = True
                break

        if not filled:
            print(f"[execute_single_leg] Parent not filled after 30s, cancelling")
            self.ib.cancelOrder(parent_trade)
            return parent_trade

        fill_price = parent_trade.orderStatus.avgFillPrice or estimated_price
        print(f"[execute_single_leg] Filled at {fill_price}")

        # TP = +20% above fill; SL = -15% below fill
        tp_limit = round(fill_price * 1.20, 2)
        sl_limit = round(fill_price * 0.85, 2)

        # Time exit: 15 minutes from fill (GTD)
        from datetime import datetime, timedelta, timezone as dt_tz
        expire_dt = datetime.now(dt_tz.utc) + timedelta(minutes=15)
        expire_str = expire_dt.strftime('%Y%m%d %H:%M:%S')

        oca_group = f"OCA_ORB_{parent_id}"

        # TP child: SELL LMT to close at tp_limit
        tp_order = LimitOrder('SELL', qty, tp_limit)
        tp_order.tif = 'GTD'
        tp_order.goodTillDate = expire_str
        tp_order.parentId = parent_id
        tp_order.ocaGroup = oca_group
        tp_order.ocaType = 1
        tp_order.transmit = False
        if tp_trigger_price and spx_conId:
            tp_order.conditions.append(make_cond(tp_trigger_price, True))
            tp_order.conditionsIgnoreRth = True
            print(f"[execute_single_leg] TP limit: {tp_limit} (trigger SPX > {tp_trigger_price})")

        # SL child: SELL LMT to close at sl_limit
        sl_order = LimitOrder('SELL', qty, sl_limit)
        sl_order.tif = 'GTD'
        sl_order.goodTillDate = expire_str
        sl_order.parentId = parent_id
        sl_order.ocaGroup = oca_group
        sl_order.ocaType = 1
        sl_order.transmit = transmit
        if sl_trigger_price and spx_conId:
            sl_order.conditions.append(make_cond(sl_trigger_price, False))
            sl_order.conditionsIgnoreRth = True
            print(f"[execute_single_leg] SL limit: {sl_limit} (trigger SPX < {sl_trigger_price})")

        tp_trade = self.ib.placeOrder(contract, tp_order)
        sl_trade = self.ib.placeOrder(contract, sl_order)

        for _ in range(10):
            await asyncio.sleep(0.1)

        print(f"✅ {right_upper} {qty}x@{chosen_strike} filled @ {fill_price} | TP {tp_limit} | SL {sl_limit} | GTD {expire_str}")
        return parent_trade

    # ------------------------------------------------------------------
    # Arbitrary multi-leg combo (for Recommendation Engine one-click EXECUTE)
    # ------------------------------------------------------------------

    async def execute_combo(
        self,
        legs: list,
        expiry: str,
        qty: int = 1,
        tp_pct: float = 50.0,
        sl_ratio: float = 2.0,
        transmit: bool = True,
        bracket: bool = True,
        entry_trigger_price: float | None = None,
        tp_trigger_price: float | None = None,
        sl_trigger_price: float | None = None,
    ):
        """
        Place an arbitrary option combo (1-4 legs) via IBKR BAG contract.

        Args:
            legs: list of {right: 'C'|'P', strike: float, action: 'BUY'|'SELL'}
            expiry: YYYYMMDD format
            qty: number of contracts
            tp_pct: take-profit % of credit (e.g. 50)
            sl_ratio: stop-loss multiplier of credit (e.g. 2.0)
            transmit: True sends live; False stages in TWS for manual confirm
            bracket: True (default) places entry + TP + SL as OCA bracket.
                     False places only the entry combo.
            entry_trigger_price: SPX price that triggers entry
            tp_trigger_price: SPX price that triggers take-profit
            sl_trigger_price: SPX price that triggers stop-loss

        Used by the Recommendation Engine's one-click EXECUTE button.
        Single-leg combos route through execute_single_leg for proper
        fill-then-attach-TP/SL semantics.
        """
        if not self.ib.isConnected():
            raise RuntimeError("Not connected to IBKR.")

        if not legs or len(legs) > 4:
            raise ValueError(f"execute_combo requires 1-4 legs, got {len(legs) if legs else 0}")
        for leg in legs:
            if leg.get("right") not in ("C", "P"):
                raise ValueError(f"Invalid right: {leg.get('right')}")
            if leg.get("action") not in ("BUY", "SELL"):
                raise ValueError(f"Invalid action: {leg.get('action')}")

        symbol = self.symbol
        currency = self.currency
        exchange = "SMART"

        # Single-leg: route through execute_single_leg (handles fill-then-attach semantics)
        if len(legs) == 1 and bracket:
            leg = legs[0]
            right = "CALL" if leg["right"] == "C" else "PUT"
            print(f"[execute_combo] Routing single-leg to execute_single_leg")
            return await self.execute_single_leg(
                right=right,
                qty=qty,
                strike=leg["strike"],
                transmit=transmit,
                entry_trigger_price=entry_trigger_price,
                tp_trigger_price=tp_trigger_price,
                sl_trigger_price=sl_trigger_price,
            )

        # Multi-leg: build ComboLeg list and BAG contract
        combo_legs = []
        qualified_contracts = []
        for leg in legs:
            option_contract = Option(symbol, expiry, leg["strike"], leg["right"], exchange)
            qualified = None
            try:
                qualified_list = await self.ib.qualifyContractsAsync(option_contract)
                qualified = qualified_list[0] if qualified_list else None
            except Exception as e:
                print(f"[execute_combo] Qualify warning {leg['right']} {leg['strike']}: {e}")

            con_id = getattr(qualified, "conId", 0) if qualified else 0
            combo_legs.append(ComboLeg(
                conId=con_id,
                ratio=1,
                action=leg["action"],
                exchange=exchange,
            ))
            qualified_contracts.append(qualified)

        bag = Contract()
        bag.symbol = symbol
        bag.secType = "BAG"
        bag.currency = currency
        bag.exchange = exchange
        bag.comboLegs = combo_legs

        # Estimate net credit/debit: sum of (mid × sign) per leg, where sign is +1 for BUY, -1 for SELL
        estimated_legs = []
        for leg, qc in zip(legs, qualified_contracts):
            bid = getattr(qc, "bid", None) if qc else None
            ask = getattr(qc, "ask", None) if qc else None
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                mid = 1.0
            else:
                mid = (bid + ask) / 2.0
            sign = 1 if leg["action"] == "BUY" else -1
            estimated_legs.append(sign * mid)

        # credit > 0 means net credit received; credit < 0 means net debit paid
        net_value = sum(estimated_legs)
        # Limit price: in IBKR BAG convention, parent action='BUY' uses positive limit
        # representing the debit to pay. For credit combos, the limit should be a small
        # positive number (we accept any credit >= $0.01).
        if net_value <= 0:
            limit_price = round(abs(net_value), 2)
        else:
            limit_price = 0.05  # accept any credit >= $0.05

        parent_id = self.ib.client.getReqId()
        oca_group_name = f"OCA_REC_{parent_id}"

        # Parent: BUY limit at limit_price
        parent = LimitOrder('BUY', qty, limit_price)
        parent.tif = 'DAY'
        parent.orderId = parent_id
        parent.ocaGroup = oca_group_name
        parent.ocaType = 1
        parent.transmit = False

        # Attach entry trigger (underlying SPX price)
        spx_conId = 0
        if entry_trigger_price or tp_trigger_price or sl_trigger_price:
            try:
                under = Contract()
                under.symbol = 'SPX'
                under.secType = 'IND'
                under.exchange = 'CBOE'
                under.currency = 'USD'
                qualified_under = self.ib.qualifyContract(under)
                spx_conId = qualified_under.conId if qualified_under else 0
            except Exception as e:
                print(f"[execute_combo] WARNING: could not qualify SPX for triggers: {e}")

            if spx_conId and entry_trigger_price:
                cond = PriceCondition()
                cond.conId = spx_conId
                cond.exchange = 'CBOE'
                cond.isMore = True
                cond.price = entry_trigger_price
                parent.conditions.append(cond)
                parent.conditionsIgnoreRth = True

        # No bracket: just place parent
        if not bracket:
            parent.transmit = transmit
            print(f"[execute_combo] Placing {len(legs)}-leg combo @ {limit_price} | NO BRACKET | Transmit: {transmit}")
            return self.ib.placeOrder(bag, parent)

        # Compute TP/SL prices based on credit_base = abs(net_value)
        # For consistency with execute_spread: TP/SL are both SELL to close.
        credit_base = abs(net_value) if net_value != 0 else 1.0

        # TP limit price: lower than entry for credit, higher for debit
        if net_value > 0:
            tp_price = round(max(0.05, credit_base * (1.0 - tp_pct / 100.0)), 2)
        else:
            tp_price = round(credit_base * (1.0 + tp_pct / 100.0), 2)

        # SL: stop-limit and stop-market like execute_spread
        sl_trigger_price = -abs(round((credit_base * sl_ratio + 0.07) / 0.05) * 0.05)
        sl_limit_price = -abs(round((abs(sl_trigger_price) + 0.20) / 0.05) * 0.05)

        from ib_async import Order as IbOrder

        # TP: SELL limit at tp_price (close for profit)
        tp_order = LimitOrder('SELL', qty, tp_price)
        tp_order.tif = 'DAY'
        tp_order.parentId = parent_id
        tp_order.ocaGroup = oca_group_name
        tp_order.ocaType = 1
        tp_order.transmit = False

        # SL: STP LMT (primary)
        sl_limit = IbOrder()
        sl_limit.action = 'SELL'
        sl_limit.orderType = 'STP LMT'
        sl_limit.tif = 'DAY'
        sl_limit.totalQuantity = qty
        sl_limit.auxPrice = sl_trigger_price
        sl_limit.lmtPrice = sl_limit_price
        sl_limit.parentId = parent_id
        sl_limit.ocaGroup = oca_group_name
        sl_limit.ocaType = 1
        sl_limit.transmit = False

        # SL: STP (safety market order)
        sl_market_trigger = -abs(round((abs(sl_trigger_price) + 0.35) / 0.05) * 0.05)
        sl_market = IbOrder()
        sl_market.action = 'SELL'
        sl_market.orderType = 'STP'
        sl_market.tif = 'DAY'
        sl_market.totalQuantity = qty
        sl_market.auxPrice = sl_market_trigger
        sl_market.parentId = parent_id
        sl_market.ocaGroup = oca_group_name
        sl_market.ocaType = 1
        sl_market.transmit = transmit  # last in chain — controls transmission

        # Attach underlying triggers if provided
        if spx_conId:
            if tp_trigger_price:
                tp_cond = PriceCondition()
                tp_cond.conId = spx_conId
                tp_cond.exchange = 'CBOE'
                tp_cond.isMore = True
                tp_cond.price = tp_trigger_price
                tp_order.conditions.append(tp_cond)
                tp_order.conditionsIgnoreRth = True

            if sl_trigger_price is not None:
                sl_cond = PriceCondition()
                sl_cond.conId = spx_conId
                sl_cond.exchange = 'CBOE'
                sl_cond.isMore = False
                sl_cond.price = sl_trigger_price
                sl_limit.conditions.append(sl_cond)
                sl_limit.conditionsIgnoreRth = True
                sl_market.conditions.append(sl_cond)
                sl_market.conditionsIgnoreRth = True

        parent_trade = self.ib.placeOrder(bag, parent)
        tp_trade = self.ib.placeOrder(bag, tp_order)
        sl_limit_trade = self.ib.placeOrder(bag, sl_limit)
        sl_market_trade = self.ib.placeOrder(bag, sl_market)

        for _ in range(20):
            await asyncio.sleep(0.1)

        print(f"✅ Combo Bracket {len(legs)}-leg | Net: {net_value:+.2f} | TP: {tp_price} | SL LMT: {sl_trigger_price}/{sl_limit_price} | SL MKT: {sl_market_trigger} | Transmit: {transmit}")
        return parent_trade
