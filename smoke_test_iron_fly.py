"""Smoke test: IRON_FLY execution via TWS.

Goal: verify that a synthetic IRON_FLY signal routes through `execute_signal`
to `engine.execute_spread` with:
  - target_mode='iron_fly'
  - spread_type='IC' (4 legs)
  - bracket=False (forced override — hold-to-expiry)
  - delta_target_put=-0.50, delta_target_call=+0.40

By default the order is STAGED in TWS but NOT transmitted to the exchange
(safer). Pass --transmit to actually send it.

The smoke test bypasses the time-window / VIX / day-of-week gates in
_evaluate_iron_fly by constructing a synthetic BotSignal directly — the
goal is to verify execution plumbing, not the gate logic (covered by
unit tests).

Prereqs:
- TWS / IB Gateway running
- API connections enabled on the configured port

Usage:
    python3 smoke_test_iron_fly.py                  # paper (4002), staged only
    python3 smoke_test_iron_fly.py --port 4001      # live (4001)
    python3 smoke_test_iron_fly.py --transmit       # actually send entry only
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
    parser.add_argument('--client-id', type=int, default=98,
                        help='IBKR client ID (avoid clashing with smoke_test_orb15)')
    args = parser.parse_args()

    print(f"[smoke] Connecting to TWS on port {args.port} (clientId={args.client_id})...")
    engine = IBKREngine(port=args.port, client_id=args.client_id)
    success, err = await engine.connect_async()
    if not success:
        print(f"[smoke] ❌ Connection failed: {err}")
        return 1
    print(f"[smoke] ✅ Connected")

    bot = BotEngine(paper_engine=engine, metrics_cache=lambda: {}, capital=25000)
    print(f"[smoke] BotEngine ready (strategies: {bot.enabled_strategies})")

    # ── Construct a synthetic IRON_FLY signal — bypass _evaluate_iron_fly ──
    # Spot is needed for engine's delta lookup (not strictly required for
    # execution routing — engine fetches SPX live).
    sig = BotSignal(
        strategy='IRON_FLY',
        direction='IC',
        short_strike=0.0,    # not used by iron_fly mode (delta lookup overrides)
        long_strike=0.0,     # not used
        width=15,
        entry_credit=4.00,
        tp_credit=0.0,       # hold-to-expiry
        sl_credit=0.0,       # hold-to-expiry
        confidence=0.65,
        reason='SMOKE TEST — IRON_FLY delta routing + bracket=False',
        timestamp=time.time(),
        delta_target_put=-0.50,
        delta_target_call=0.40,
    )
    print(f"[smoke] Synthetic signal: {sig.strategy} {sig.direction} "
          f"width={sig.width} deltas=(put={sig.delta_target_put}, call={sig.delta_target_call})")

    # ── Spy on execute_spread to verify routing without polluting TWS logs ──
    captured = {}
    original_execute_spread = engine.execute_spread

    async def spy_execute_spread(*a, **kw):
        captured.update(kw)
        print(f"[smoke] >>> execute_spread called with: "
              f"target_mode={kw.get('target_mode')!r} "
              f"spread_type={kw.get('spread_type')!r} "
              f"bracket={kw.get('bracket', True)!r} "
              f"delta_target_put={kw.get('delta_target_put')!r} "
              f"delta_target_call={kw.get('delta_target_call')!r} "
              f"transmit={kw.get('transmit')!r}")
        if not args.transmit:
            print(f"[smoke] >>> STAGING ONLY (transmit=False). Skipping actual TWS order.")
            mock = type('M', (), {'orderStatus': type('S', (), {'status': 'PendingSubmit'})()})()
            return mock
        return await original_execute_spread(*a, **kw)

    engine.execute_spread = spy_execute_spread

    # ── Execute — pass bracket=True to verify the override forces it to False ──
    print(f"[smoke] Calling execute_signal(transmit={args.transmit}, bracket=True [should be forced to False])...")
    result = await bot.execute_signal(sig, execution_mode='MANUAL', transmit=args.transmit, bracket=True)

    if not result.get('ok'):
        print(f"[smoke] ❌ execute_signal failed: {result.get('error')}")
        engine.disconnect()
        return 1

    print(f"[smoke] ✅ execute_signal returned ok")
    print()
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # Assertions
    tm = captured.get('target_mode')
    st = captured.get('spread_type')
    br = captured.get('bracket', True)
    d_put = captured.get('delta_target_put')
    d_call = captured.get('delta_target_call')
    width = captured.get('width')

    print(f"target_mode        = {tm!r}      (expected 'iron_fly')")
    print(f"spread_type        = {st!r}      (expected 'IC')")
    print(f"bracket            = {br!r}      (expected False — forced override)")
    print(f"delta_target_put   = {d_put!r}      (expected -0.50)")
    print(f"delta_target_call  = {d_call!r}      (expected 0.40)")
    print(f"width              = {width!r}      (expected 15)")
    print()

    ok = True
    checks = [
        (tm == 'iron_fly', "target_mode is 'iron_fly' (routing correct)",
         f"target_mode should be 'iron_fly' (got {tm!r})"),
        (st == 'IC', "spread_type is 'IC' (4-leg structure)",
         f"spread_type should be 'IC' (got {st!r})"),
        (br is False, "bracket=False (hold-to-expiry forced)",
         f"bracket should be False — even when caller passes True (got {br!r})"),
        (d_put is not None and abs(d_put - (-0.50)) < 0.01,
         "delta_target_put=-0.50 propagated",
         f"delta_target_put should be -0.50 (got {d_put!r})"),
        (d_call is not None and abs(d_call - 0.40) < 0.01,
         "delta_target_call=+0.40 propagated",
         f"delta_target_call should be 0.40 (got {d_call!r})"),
        (width == 15, "width=15 ($15 wing)",
         f"width should be 15 (got {width!r})"),
    ]
    for passed, label, fail_msg in checks:
        if passed:
            print(f"✅ PASS: {label}")
        else:
            print(f"❌ FAIL: {fail_msg}")
            ok = False

    print()
    if args.transmit:
        print("[smoke] 📦  Entry-only order transmitted to TWS — no TP/SL (hold-to-expiry).")
        print("[smoke] Check TWS: should be ONE parent combo with 4 legs,")
        print("[smoke] NO OCA group, NO TP/SL exit orders.")
    else:
        print("[smoke] Order was NOT transmitted — only the routing was verified.")
        print("[smoke] To actually place the order, re-run with --transmit")

    engine.disconnect()
    print(f"[smoke] Disconnected from TWS")
    return 0 if ok else 2


if __name__ == '__main__':
    rc = asyncio.run(main())
    sys.exit(rc)
