"""
engine.py - IBKR trading engine using ib_insync async API.

The IB object must be used exclusively within the event loop it was created on.
All public coroutines (async methods) must be dispatched via run_coroutine_threadsafe
from the GUI thread, targeting the single persistent 'ib_loop' stored in app.py.
"""

import asyncio
import datetime
import logging
import math
import numpy as np
import os
import csv
from scipy.stats import norm
from ib_async import IB, Index, Option, LimitOrder, Order, Contract, ComboLeg, TagValue


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
            await asyncio.sleep(2.0)
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
                await asyncio.sleep(1.2)
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
            await asyncio.sleep(2.0)
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
        
        try:
            for i in range(14):
                if len(found_expiries) >= expirations_count:
                    break
                    
                target_date_obj = today + datetime.timedelta(days=i)
                
                # Filter out weekends (Saturdays=5, Sundays=6)
                if target_date_obj.weekday() >= 5:
                    continue
                    
                target_date = target_date_obj.strftime('%Y%m%d')
                opt_search = Option(symbol=self.symbol, lastTradeDateOrContractMonth=target_date, exchange=self.exchange)
                try:
                    details = await asyncio.wait_for(self.ib.reqContractDetailsAsync(opt_search), timeout=45.0)
                    if not details:
                        opt_search.exchange = 'CBOE'
                        details = await asyncio.wait_for(self.ib.reqContractDetailsAsync(opt_search), timeout=45.0)
                except Exception as e:
                    print(f"Timeout/Error fetching options chain for {target_date}: {e}")
                    details = []
                    
                if details:
                    found_expiries.append(target_date)
                    all_details.extend(details)
                    print(f"  -> Found Expiry: {target_date} ({len(details)} contracts)")
        finally:
            ib_logger.setLevel(old_level) # Restore logger
                
        if not all_details:
            raise RuntimeError(f"No option chains returned from IBKR for {self.symbol}.")
            
        print(f"Loaded {len(found_expiries)} expiries: {found_expiries} ({len(all_details)} total contracts)")
        
        # Save to cache
        self.chain_cache_date = today
        self.chain_cache = (found_expiries, all_details)
        
        return price, found_expiries, all_details

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
        price, expiries, all_details = await self._get_multiexpiry_chain_data(expirations_count=4)

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
                for c in chunk:
                    self.ib.reqMktData(c, '100,101,104,106', False, False)
                
                await asyncio.sleep(1.0)
                tickers.extend([self.ib.ticker(c) for c in chunk])
                
                for c in chunk:
                    self.ib.cancelMktData(c)
                    
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  [ERROR] Chunk {i} failed: {e}")

        ib_logger.setLevel(old_level) # Restore logger to previous state
        
        # Initialize data structures
        call_oi = {}
        put_oi = {}
        total_gex_per_strike = {}  # Aggregate GEX across all expiries
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

        # --- NEW: Premium tracking for 0DTE Net Drift ---
        total_call_premium_0dte = 0.0
        total_put_premium_0dte = 0.0
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

            # Find ATM IV for Sigma calculation
            dist = abs(strike - price)
            if dist < min_distance_to_atm and iv > 0:
                min_distance_to_atm = dist
                atm_iv = iv

        # Calculate Walls (Ignore extreme out-of-bounds strikes with zero data)
        # For 0DTE, major GEX tools define the "Wall" as the highest OI strike within 
        # a localized expected daily move (± 2.5% of spot) to ignore structural long-dated OI.
        valid_call_oi = {k: v for k, v in call_oi.items() if abs(k - price) / price < 0.025 and v > 0}
        call_wall = max(valid_call_oi, key=valid_call_oi.get) if valid_call_oi else None
        
        valid_put_oi = {k: v for k, v in put_oi.items() if abs(k - price) / price < 0.025 and v > 0}
        put_wall = max(valid_put_oi, key=valid_put_oi.get) if valid_put_oi else None

        # Calculate Gamma Flip (Zero GEX Level)
        # Gamma Flip is the strike where Net GEX crosses zero, near the ATM price.
        # We need to filter out extreme strikes where GEX is naturally just zero because of no OI/Gamma.
        gamma_flip = None
        if total_gex_per_strike:
            # Filter strikes with actual activity and close enough to spot (+/- 5%)
            valid_gex = {k: v for k, v in total_gex_per_strike.items() if v != 0 and abs(k - price) / price < 0.05}
            
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
        zone_data = self._classify_gex_zones(
            gex_profile=total_gex_per_strike,
            oi_profile=oi_profile,
            vol_profile=vol_profile,
            price=price,
            call_wall=call_wall,
            put_wall=put_wall,
            gamma_flip=gamma_flip,
        )

        self._log_premium_drift_data(price, total_call_premium_0dte, total_put_premium_0dte, total_volume_0dte)

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
            # --- NEW fields ---
            "oi_profile": oi_profile,
            "vol_profile": vol_profile,
            "oi_by_expiry": oi_by_expiry,
            "vol_by_expiry": vol_by_expiry,
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

    def _log_premium_drift_data(self, spot: float, call_prem: float, put_prem: float, vol: int):
        self._append_csv(
            'premium_drift_0dte',
            ['Timestamp', 'Spot', 'CallPremium', 'PutPremium', 'Volume'],
            [round(spot, 2), round(call_prem, 2), round(put_prem, 2), vol]
        )

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
        target_abs = abs(target_delta) / 100.0

        for contract in contracts:
            current_delta = abs(calc_bs_delta(price, contract.strike, right))
            diff = abs(current_delta - target_abs)
            
            if diff < min_diff:
                min_diff = diff
                best_strike = contract.strike
            
            # Since we iterate OTM, if delta drops below target, we crossed it
            if current_delta < target_abs:
                break

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
                              transmit: bool = False):
        """
        Build and place a spread order (PCS, CCS, or IC) via IBKR API.

        Args:
            spread_type: 'PCS', 'CCS', or 'IC'
            qty: number of contracts
            target_mode: 'Delta', 'R:R', or 'GEX' (anchors to Call/Put Wall)
            target_value: numeric target for Delta/R:R modes (ignored for GEX mode)
            width: points between legs (e.g. 15)
            tp_pct: take-profit % of credit (e.g. 50)
            sl_ratio: stop-loss multiplier of credit (e.g. 2.5)
            transmit: True sends live; False stages in TWS for manual confirm
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

        # --- Existing Delta / R:R targeting (unchanged) ---
        elif spread_type in ('PCS', 'IC'):
            if target_mode.lower() == 'delta':
                short_put_strike = await self._find_strike_by_delta('P', target_value, expiry, strikes, price, details)
            else:
                short_put_strike = await self._find_spread_by_rr('P', target_value, width, strikes, price, details)

        if target_mode.lower() != 'gex' and spread_type in ('CCS', 'IC'):
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
