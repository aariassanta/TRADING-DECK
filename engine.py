"""
engine.py - IBKR trading engine using ib_insync async API.

The IB object must be used exclusively within the event loop it was created on.
All public coroutines (async methods) must be dispatched via run_coroutine_threadsafe
from the GUI thread, targeting the single persistent 'ib_loop' stored in app.py.
"""

import asyncio
import datetime
from ib_insync import IB, Index, Option, LimitOrder, Order, Contract, ComboLeg, TagValue


class IBKREngine:
    """
    Manages a single persistent IBKR connection and exposes async methods
    for order building and placement. Everything runs on one shared event loop.
    """

    def __init__(self, host='127.0.0.1', port=4002, client_id=1):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
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

    async def _get_chain_data(self):
        """
        Get SPX price, 0DTE expiry, and available strikes.
        Returns (price, expiry_str, strikes_list) or raises on failure.
        """
        # Force delayed market data in case live data is not subscribed
        self.ib.reqMarketDataType(3)

        spx = Index(self.symbol, self.exchange)
        await self.ib.qualifyContractsAsync(spx)

        [ticker] = await self.ib.reqTickersAsync(spx)
        price = ticker.marketPrice()
        
        if price != price or price <= 0:  # NaN or invalid
            print("WARNING: Real-time SMART ticket returned NaN. Fetching latest historical close from CBOE...")
            
            spx_cboe = Index('SPX', 'CBOE')
            await self.ib.qualifyContractsAsync(spx_cboe)
            
            bars = await self.ib.reqHistoricalDataAsync(
                spx_cboe,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True
            )
            
            if bars and bars[-1].close > 0:
                price = bars[-1].close
                print(f"✅ Recovered true SPX price from historical data: {price:.2f}")
            else:
                print("❌ FAILED to recover SPX price. Using 6890.00 fallback.")
                price = 6890.00
        
        print(f"SPX Market Price: {price:.2f}")

        # Instead of reqSecDefOptParams (which fails on some index setups), 
        # we ask for all Option contracts expiring today directly.
        today = datetime.date.today().strftime('%Y%m%d')
        
        # We use a wildcard Option contract to search
        opt_search = Option(symbol=self.symbol, lastTradeDateOrContractMonth=today, exchange=self.exchange)
        
        print(f"Requesting Option Chain details for {today}...")
        details = await self.ib.reqContractDetailsAsync(opt_search)
        
        if not details:
            # Fallback: maybe SMART doesn't have it explicitly bound, try CBOE
            opt_search.exchange = 'CBOE'
            details = await self.ib.reqContractDetailsAsync(opt_search)
            
        if not details:
            raise RuntimeError(f"No option chains returned from IBKR for {today}.")
            
        # Extract unique strikes from the returned contracts
        strikes = sorted(list(set(d.contract.strike for d in details)))
        expiry = today

        print(f"0DTE Expiry: {expiry}, {len(strikes)} strikes available")
        return price, expiry, strikes, details

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

        # Use local Black-Scholes estimate to avoid massive IBKR network delays
        import math
        def calc_bs_delta(S, K, right_str, dte=0.2):
            t = dte / 365.0
            if t <= 0: t = 0.0001
            vol = 0.15  # SPX 0DTE baseline IV
            r = 0.053   # Approx Risk Free Rate
            d1 = (math.log(S / K) + (r + 0.5 * vol**2) * t) / (vol * math.sqrt(t))
            cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
            return cdf if right_str == 'C' else cdf - 1.0

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

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    async def execute_spread(self, spread_type: str, qty: int, target_delta: float,
                              width: int, tp_pct: float, sl_ratio: float,
                              transmit: bool = False):
        """
        Build and place a spread order (PCS, CCS, or IC) via IBKR API.

        Args:
            spread_type: 'PCS', 'CCS', or 'IC'
            qty: number of contracts
            target_delta: short leg delta target (e.g. 20 -> 0.20)
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

        if spread_type in ('PCS', 'IC'):
            short_put_strike = await self._find_strike_by_delta(
                'P', target_delta, expiry, strikes, price, details
            )
        if spread_type in ('CCS', 'IC'):
            short_call_strike = await self._find_strike_by_delta(
                'C', target_delta, expiry, strikes, price, details
            )

        print(f"Strikes → Put Short: {short_put_strike} | Call Short: {short_call_strike}")

        # Distribute into individual contracts using the actual, fully-qualified Contract objects
        contracts_to_trade = []
        
        def find_exact_contract(strike, right):
            for d in details:
                if d.contract.strike == strike and d.contract.right == right:
                    return d.contract
            return None
            
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

        # Build BAG contract from the exact matched contracts
        combo_legs = []
        for contract, action in contracts_to_trade:
            leg = ComboLeg(
                conId=contract.conId,
                ratio=1,
                action=action,
                exchange=contract.exchange or self.exchange
            )
            combo_legs.append(leg)

        bag_contract = Contract()
        bag_contract.symbol = self.symbol
        bag_contract.secType = 'BAG'
        bag_contract.currency = 'USD'
        bag_contract.exchange = self.exchange
        bag_contract.comboLegs = combo_legs

        # Fetch actual pricing for the final 2 or 4 legs to calculate Mid Price dynamically
        try:
            leg_contracts = [c for c, action in contracts_to_trade]
            leg_tickers = await self.ib.reqTickersAsync(*leg_contracts)
            import math
            
            def get_valid(p):
                return p if p is not None and not math.isnan(p) and p >= 0 else None

            net_debit = 0.0
            for contract, action in contracts_to_trade:
                ticker = next((t for t in leg_tickers if t.contract.conId == contract.conId), None)
                mid_price = 0.0
                if ticker:
                    bid = get_valid(ticker.bid)
                    ask = get_valid(ticker.ask)
                    close = get_valid(ticker.close)
                    model = get_valid(ticker.modelGreeks.optPrice) if ticker.modelGreeks else None
                    
                    if bid is not None and ask is not None:
                        mid_price = (bid + ask) / 2.0
                    elif model is not None:
                        mid_price = model
                    elif close is not None:
                        mid_price = close
                    elif bid is not None:
                        mid_price = bid
                    elif ask is not None:
                        mid_price = ask
                        
                print(f"  [Price] {action} {contract.localSymbol} -> Mid: {mid_price:.2f}")
                
                if action == 'BUY':
                    net_debit += mid_price
                elif action == 'SELL':
                    net_debit -= mid_price
                    
            # Round to nearest 0.05
            calculated_limit = round(net_debit / 0.05) * 0.05
            print(f"  [Price] Calculated Combo Mid Price (Net Debit): {calculated_limit:.2f}")
            
            if abs(calculated_limit) < 0.01:
                print("  [Price] WARNING: Calculated limit near 0, using fallback.")
                calculated_limit = -4.50 if spread_type == 'IC' else -2.50
                
        except Exception as e:
            print(f"  [Price] ERROR fetching leg prices: {e}")
            calculated_limit = -4.50 if spread_type == 'IC' else -2.50

        # CRITICAL: IBKR requires Credit Combo orders to be submitted as a 'BUY' order
        # with a NEGATIVE limit price. If you submit a 'SELL', it flips the legs into a Debit Spread.
        order = LimitOrder('BUY', qty, calculated_limit)
        order.transmit = transmit
        
        # CRITICAL: SPX SMART Combo routing requires NonGuaranteed=1 to prevent Risk-Free Arbitrage rejection (Error 201)
        order.smartComboRoutingParams = [TagValue('NonGuaranteed', '1')]

        print(f"Placing {spread_type} Combo BAG | Credit limit: {calculated_limit} | Transmit: {transmit}")
        trade = self.ib.placeOrder(bag_contract, order)
        
        await asyncio.sleep(1)  # Give IB a moment
        print(f"✅ Combo Order dispatched: {trade.orderStatus.status}")
        return trade
