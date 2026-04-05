import sys
import os
import time
from datetime import datetime

# Adjust path to find strategy-builder modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ibapi.contract import Contract, ComboLeg
from utils.ib_utils import create_order
from metf_strategy import METFStrategy

# Helper to create ComboLeg
def create_combo_leg_by_id(con_id, action, ratio=1, exchange="SMART"):
    leg = ComboLeg()
    leg.conId = con_id
    leg.ratio = ratio
    leg.action = action
    leg.exchange = exchange
    return leg

def main():
    print("======================================================================")
    print("METF OCO TEST (TP + SL) - transmit=False")
    print("======================================================================")

    # 1. Connect
    print("1. Connecting to IBKR...")
    # Port 4002 (Paper), Client ID 202
    strategy = METFStrategy(port=4002, client_id=202, paper=False)
    
    # Monkey patch error handler
    def printing_error_handler(reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode in [2104, 2106, 2158]: # Info messages
            print(f"⚠️ IBKR INFO: [{reqId}] {errorCode} - {errorString}")
    strategy.error = printing_error_handler

    if not strategy.connect_to_ibkr():
        print("❌ Failed to connect")
        return
    
    time.sleep(3)
    if not strategy.isConnected():
        print("❌ Not connected after wait")
        return
    print("✓ Connected")

    # 2. Parameters (0DTE for today)
    expiration = datetime.now().strftime("%Y%m%d")  # Today's date
    trading_class = "SPXW"
    short_strike = 6000.0
    long_strike = 5975.0  # SPX strikes go in 5-point increments
    side = 'P' # Put Credit Spread
    
    print(f"\n2. Test Parameters (PCS):")
    print(f"   Short {short_strike} / Long {long_strike} @ {expiration}")

    # 3. Resolve ConIds
    print("3. Resolving ConIds...")
    try:
        short_conid = strategy.get_con_id("SPX", short_strike, 'P', expiration, trading_class)
        long_conid = strategy.get_con_id("SPX", long_strike, 'P', expiration, trading_class)
    except Exception as e:
        print(f"⚠️ Fetch error: {e}")
        short_conid = 0

    if short_conid == 0 or long_conid == 0:
        print("⚠️ Fetch failed. Using fallback IDs.")
        short_conid = 10001
        long_conid = 10002
    
    print(f"   Short ConId: {short_conid}")
    print(f"   Long ConId:  {long_conid}")

    # 4. Entry Order
    print("\n4. Constructing METF Entry Order (transmit=False)...")
    credit = 2.50
    contract = Contract()
    contract.symbol = "SPX"
    contract.secType = "BAG"
    contract.currency = "USD"
    contract.exchange = "SMART"
    
    contract.comboLegs = [
        create_combo_leg_by_id(short_conid, 'SELL'),
        create_combo_leg_by_id(long_conid, 'BUY')
    ]
    
    order = create_order()
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = 1
    order.lmtPrice = strategy.round_price(-credit)
    order.transmit = False
    
    oid = strategy.nextOrderId()
    print(f"   Placing METF Order #{oid} @ ${order.lmtPrice}")
    strategy.placeOrder(oid, contract, order)
    time.sleep(1)

    # 5. OCO Group: Take Profit + Stop Loss
    print("\n5. Constructing OCO Group (TP + SL) (transmit=False)...")
    trigger_val = (credit * 2) - 0.07
    trigger_price = strategy.round_price(-trigger_val)
    limit_price = strategy.round_price(trigger_price + 0.20)
    market_trigger = strategy.round_price(trigger_price - 0.35)
    
    sl_contract = Contract()
    sl_contract.symbol = "SPX"
    sl_contract.secType = "BAG"
    sl_contract.currency = "USD"
    sl_contract.exchange = "SMART"
    sl_contract.comboLegs = [
        create_combo_leg_by_id(short_conid, 'BUY'),
        create_combo_leg_by_id(long_conid, 'SELL')
    ]
    
    # OCO Group Name
    group_name = f"METF_TEST_{oid}"
    
    # Take Profit (NEW: mitad del premium)
    tp_order = create_order()
    tp_order.action = "SELL"
    tp_order.orderType = "LMT"
    tp_order.totalQuantity = 1
    tp_order.lmtPrice = strategy.round_price(-(credit / 2))
    tp_order.transmit = False
    tp_order.ocaGroup = group_name
    tp_order.ocaType = 1
    tp_id = strategy.nextOrderId()
    
    # Stop Limit
    sl_limit = create_order()
    sl_limit.action = "SELL"
    sl_limit.orderType = "STP LMT"
    sl_limit.totalQuantity = 1
    sl_limit.auxPrice = trigger_price
    sl_limit.lmtPrice = limit_price
    sl_limit.transmit = False
    sl_limit.ocaGroup = group_name
    sl_limit.ocaType = 1
    sl_limit_id = strategy.nextOrderId()
    
    # Stop Market
    sl_market = create_order()
    sl_market.action = "SELL"
    sl_market.orderType = "STP"
    sl_market.totalQuantity = 1
    sl_market.auxPrice = market_trigger
    sl_market.transmit = False
    sl_market_id = strategy.nextOrderId()
    
    # Set OCO group for all
    for o in [tp_order, sl_limit, sl_market]:
        o.ocaGroup = group_name
        o.ocaType = 1
    
    print(f"   Placing Take Profit  #{tp_id}: Limit {tp_order.lmtPrice}")
    print(f"   Placing Stop Limit   #{sl_limit_id}: Trigger {sl_limit.auxPrice}, Limit {sl_limit.lmtPrice}")
    print(f"   Placing Stop Market  #{sl_market_id}: Trigger {sl_market.auxPrice}")
    
    strategy.placeOrder(tp_id, sl_contract, tp_order)
    strategy.placeOrder(sl_limit_id, sl_contract, sl_limit)
    strategy.placeOrder(sl_market_id, sl_contract, sl_market)
    
    print(f"\n✅ OCO Orders Submitted (transmit=False).")
    time.sleep(5)
    print("Disconnecting...")
    strategy.disconnect()
    time.sleep(1)

if __name__ == "__main__":
    main()
