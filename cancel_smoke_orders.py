"""Cancel smoke-test orders staged in TWS before market open.

Reconnects with each clientId used by smoke tests (98=IRON_FLY, 99=ORB15)
to recover the session ownership of those orders, then cancels any
non-final-state orders.

Run before 08:30 US/Central (= 09:30 ET) to prevent pre-market orders
from filling at the open.

Usage:
    python3 cancel_smoke_orders.py                  # paper (4002)
    python3 cancel_smoke_orders.py --port 4001      # live (4001, dangerous)
"""
import argparse
import asyncio
import sys

sys.path.insert(0, '.')

from ib_async import IB


SMOKE_CLIENT_IDS = [99, 98]  # ORB15, IRON_FLY


async def cancel_for_client(port: int, client_id: int) -> int:
    """Reconnect with a given clientId and cancel its open orders."""
    ib = IB()
    try:
        await ib.connectAsync('127.0.0.1', port, clientId=client_id)
    except Exception as e:
        print(f"  connect(clientId={client_id}) failed: {e}")
        return 0

    # Probe orders from all clients (async variants needed; sync _run() can't re-enter the loop)
    try:
        await ib.reqAllOpenOrdersAsync()
    except Exception as e:
        print(f"  reqAllOpenOrders failed ({e}); using reqOpenOrders only")
        ib.reqOpenOrders()
    await asyncio.sleep(3)

    all_trades = list(ib.openTrades())
    print(f"  clientId={client_id} sees {len(all_trades)} open trades total")

    cancelled = 0
    seen_perms: set[int] = set()
    for t in all_trades:
        # Cancel orders that match smoke-test fingerprint:
        # - clientId in {98, 99} (active session), or 0 (session ended - TWS reset)
        # - SPX/BAG/OPT (combo legs from these specific smoke tests)
        # - status pending or live (not already filled/cancelled)
        order_client = t.order.clientId or 0
        if order_client not in SMOKE_CLIENT_IDS and order_client != 0:
            continue
        if t.contract.symbol != 'SPX':
            continue
        if t.contract.secType not in ('BAG', 'OPT'):
            continue
        if t.orderStatus.status not in ('PendingSubmit', 'PreSubmitted', 'Submitted'):
            continue
        # Dedupe by permId (TWS orderId often 0 after disconnect; permId is permanent)
        if t.order.permId in seen_perms:
            print(f"    SKIP dup permId={t.order.permId}")
            continue
        seen_perms.add(t.order.permId)

        # Build fresh Order with just permId (TWS will match by permId, not orderId)
        from ib_async import Order
        cancel = Order()
        cancel.permId = t.order.permId
        cancel.action = 'CANCEL'
        # Send via IB API (uses TWS permId matching internally)
        try:
            # ib.cancelOrder(reqId-based) wants a Trade; for permId-based we use placeOrder
            # Actually simplest: use ib.cancelOrder with a constructed Order having permId
            ib.cancelOrder(cancel)
            cancelled += 1
            print(f"    CANCEL request sent: oid={t.order.orderId} permId={t.order.permId} "
                  f"client={order_client} status={t.orderStatus.status} "
                  f"symbol={t.contract.symbol}/{t.contract.secType}")
        except Exception as e:
            print(f"    CANCEL failed for permId={t.order.permId}: {e}")

    if cancelled:
        await asyncio.sleep(2)  # let cancellations flush

    ib.disconnect()
    return cancelled


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4002,
                        help='TWS port (4002=paper, 4001=live)')
    args = parser.parse_args()

    print(f"[cancel] Cancelling smoke-test orders on port {args.port}...")
    total = 0
    for cid in SMOKE_CLIENT_IDS:
        print(f"[cancel] Reconnecting with clientId={cid}...")
        cancelled = await cancel_for_client(args.port, cid)
        print(f"[cancel]   → cancelled {cancelled} order(s)")
        total += cancelled

    print(f"[cancel] Done. Total cancelled: {total}")
    return 0 if total > 0 else 1


if __name__ == '__main__':
    rc = asyncio.run(main())
    sys.exit(rc)
