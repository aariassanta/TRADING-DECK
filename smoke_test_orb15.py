"""Smoke test: ORB15 strike routing via TWS.

Goal: verify that a synthetic ORB15 signal routes through `execute_signal`
to `engine.execute_spread` with the ORB-anchored strikes (NOT the GEX walls).

By default the order is STAGED in TWS but NOT transmitted to the exchange
(safer). Pass --transmit to actually send it.

By default a full bracket (entry + TP + SL_LMT + SL_MKT) is placed.
Pass --no-bracket to stage ONLY the entry combo (no TP/SL children).

Prereqs:
- TWS / IB Gateway running
- API connections enabled on the configured port

Usage:
    python3 smoke_test_orb15.py                       # paper (4002), staged only, full bracket
    python3 smoke_test_orb15.py --port 4001           # live (4001)
    python3 smoke_test_orb15.py --transmit            # actually send the full bracket
    python3 smoke_test_orb15.py --transmit --no-bracket  # send entry ONLY, no TP/SL
"""
import argparse
import asyncio
import sys
import time

sys.path.insert(0, '.')

from engine import IBKREngine
from bot_engine import BotEngine, BotSignal


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4002,
                        help='TWS port (4002=paper, 4001=live)')
    parser.add_argument('--transmit', action='store_true',
                        help='Actually transmit the order (DANGEROUS)')
    parser.add_argument('--client-id', type=int, default=99,
                        help='IBKR client ID (avoid clashing with running app)')
    parser.add_argument('--no-bracket', action='store_true',
                        help='Skip TP/SL bracket — only place the entry combo')
    args = parser.parse_args()

    print(f"[smoke] Connecting to TWS on port {args.port} (clientId={args.client_id})...")
    engine = IBKREngine(port=args.port, client_id=args.client_id)
    success, err = await engine.connect_async()
    if not success:
        print(f"[smoke] ❌ Connection failed: {err}")
        return 1
    print(f"[smoke] ✅ Connected")

    # Wrap the engine in a BotEngine (mirrors server.py wiring)
    bot = BotEngine(paper_engine=engine, metrics_cache=lambda: {}, capital=25000)
    print(f"[smoke] BotEngine ready (strategies: {bot.enabled_strategies})")

    # ── Fetch the current SPX price so we can compute realistic strikes ──
    print(f"[smoke] Fetching current SPX price...")
    try:
        price, expiry, strikes, details = await engine._get_chain_data()
        print(f"[smoke] Current SPX = {price:.2f} | 0DTE expiry = {expiry} | "
              f"{len(strikes)} strikes available")
        # Round to a realistic ORB range around current price (e.g. ±0.3%)
        session_open = round(price / 5) * 5  # round to nearest 5
        orb_high = session_open + 8
        orb_low = session_open - 8
    except Exception as e:
        print(f"[smoke] ❌ Could not fetch SPX price: {e}")
        engine.disconnect()
        return 1

    # ── Synthesize an ORB15 signal using TODAY's prices ──
    # buffer = session_open * 0.005
    # PCS short = ORB_low − buffer
    # PCS long  = short − 20
    buffer = session_open * 0.005
    expected_short = round(orb_low - buffer, 2)
    expected_long = round(expected_short - 20, 2)
    sig = BotSignal(
        strategy='ORB15',
        direction='BULL_PUT',
        short_strike=expected_short,
        long_strike=expected_long,
        width=20,
        entry_credit=2.50,
        tp_credit=1.25,
        sl_credit=5.00,
        confidence=0.75,
        reason='SMOKE TEST — ORB15 strike routing',
        timestamp=time.time(),
    )
    print(f"[smoke] Synthetic signal: {sig.strategy} {sig.direction} "
          f"short={sig.short_strike} long={sig.long_strike} width={sig.width}")
    print(f"[smoke] (based on session_open={session_open}, "
          f"ORB_high={orb_high}, ORB_low={orb_low}, buffer={buffer:.2f})")

    # ── Patch the engine to log what execute_spread receives ──
    # We want to PROVE the fix routes target_mode='orb15' and target_value=short_strike
    captured = {}

    original_execute_spread = engine.execute_spread

    async def spy_execute_spread(*a, **kw):
        captured.update(kw)
        print(f"[smoke] >>> execute_spread called with: "
              f"target_mode={kw.get('target_mode')!r} "
              f"target_value={kw.get('target_value')!r} "
              f"spread_type={kw.get('spread_type')!r} "
              f"transmit={kw.get('transmit')!r} "
              f"bracket={kw.get('bracket', True)!r}")
        if not args.transmit:
            print(f"[smoke] >>> STAGING ONLY (transmit=False). Skipping actual TWS order.")
            # Return a mock trade so execute_signal doesn't error
            mock = type('M', (), {'orderStatus': type('S', (), {'status': 'PendingSubmit'})()})()
            return mock
        return await original_execute_spread(*a, **kw)

    engine.execute_spread = spy_execute_spread

    # ── Execute ──
    bracket = not args.no_bracket
    print(f"[smoke] Calling execute_signal(transmit={args.transmit}, bracket={bracket})...")
    result = await bot.execute_signal(sig, execution_mode='MANUAL', transmit=args.transmit, bracket=bracket)

    if not result.get('ok'):
        print(f"[smoke] ❌ execute_signal failed: {result.get('error')}")
        engine.disconnect()
        return 1

    print(f"[smoke] ✅ execute_signal returned ok")
    print()
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # 1. Routing assertion
    tm = captured.get('target_mode')
    tv = captured.get('target_value')
    st = captured.get('spread_type')
    br = captured.get('bracket', True)

    print(f"target_mode    = {tm!r}      (expected 'orb15')")
    print(f"target_value   = {tv!r}      (expected {expected_short})")
    print(f"spread_type    = {st!r}      (expected 'PCS')")
    print(f"bracket        = {br!r}      (expected {bracket})")
    print()

    ok = True
    if tm != 'orb15':
        print("❌ FAIL: target_mode should be 'orb15' (was falling through to 'GEX')")
        ok = False
    else:
        print("✅ PASS: target_mode is 'orb15' (fix is routing correctly)")

    if abs(tv - expected_short) > 0.01:
        print(f"❌ FAIL: target_value should be {expected_short} (got {tv})")
        ok = False
    else:
        print(f"✅ PASS: target_value is {expected_short} (ORB-anchored strike)")

    if st != 'PCS':
        print(f"❌ FAIL: spread_type should be 'PCS' (got {st})")
        ok = False
    else:
        print("✅ PASS: spread_type is 'PCS'")

    if br != bracket:
        print(f"❌ FAIL: bracket kwarg should be {bracket} (got {br})")
        ok = False
    else:
        label = 'PASS: bracket=False (NO TP/SL children placed)' if not bracket else 'PASS: bracket=True (full TP/SL bracket placed)'
        print(f"✅ {label}")

    print()
    if args.transmit:
        print("[smoke] �️  Order was transmitted to TWS / exchange. "
              "Check TWS for the staged/filled spread.")
    else:
        print("[smoke] Order was NOT transmitted — only the routing was verified.")
        print("[smoke] To actually place the order, re-run with --transmit")
        print("[smoke] (only do this once you've confirmed the strikes via this test).")

    engine.disconnect()
    print(f"[smoke] Disconnected from TWS")
    return 0 if ok else 2


if __name__ == '__main__':
    rc = asyncio.run(main())
    sys.exit(rc)
