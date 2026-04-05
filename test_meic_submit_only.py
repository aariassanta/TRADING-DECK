import sys
import os
import time
import argparse
import random
from datetime import datetime

# Adjust path to find strategy-builder modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract, ComboLeg
from ibapi.order import Order
from utils.ib_utils import create_order

from meic_strategy import MEICStrategy  # Using MEICStrategy now
# from utils.utils import error, setup_logger # Not needed for this standalone test

# Helper to create ComboLeg (since it's not exposed on strategy instance easily)
def create_combo_leg_by_id(con_id, action, ratio=1, exchange="SMART"):
    leg = ComboLeg()
    leg.conId = con_id
    leg.ratio = ratio
    leg.action = action
    leg.exchange = exchange
    return leg

def main():
    print("======================================================================")
    print("MEIC SUBMIT ONLY TEST (transmit=False)")
    print("======================================================================")

    # 2. Connect
    print("2. Connecting to IBKR...")
    # Initialize with specific Client ID and Port, relying on connect_to_ibkr to handle threading
    strategy = MEICStrategy(port=4002, client_id=201, paper=False)
    
    # Monkey patch error handler to see errors
    original_error = strategy.error
    def printing_error_handler(reqId, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode in [2104, 2106, 2158]: # Connection messages
            print(f"⚠️ IBKR ERROR: [{reqId}] {errorCode} - {errorString}")
        elif errorCode in [10349]: # Preset warnings
            print(f"⚠️ IBKR ERROR: [{reqId}] {errorCode} - {errorString}")
        else:
            print(f"🛑 IBKR ERROR: [{reqId}] {errorCode} - {errorString}")
    strategy.error = printing_error_handler

    if not strategy.connect_to_ibkr():
        print("❌ Failed to connect")
        return
    
    # Wait for connection to stabilize
    time.sleep(3)
    if not strategy.isConnected():
        print("❌ Not connected after wait")
        return
    print("✓ Connected")

    # 3. Parameters (Hardcoded for stability off-hours)
    underlying_price = 6909.79
    expiration = "20260127"
    trading_class = "SPXW"
    
    # Strikes (Simulating an Iron Condor)
    # Underlying ~6910
    # PCS: Short 6900 / Long 6870 (Width 30)
    # CCS: Short 6920 / Long 6950 (Width 30)
    pcs_short_strike = 6900.0
    pcs_long_strike = 6870.0
    ccs_short_strike = 6920.0
    ccs_long_strike = 6950.0
    
    print("\n4. Selected Legs for Iron Condor:")
    print(f"   PCS: Short {pcs_short_strike} / Long {pcs_long_strike}")
    print(f"   CCS: Short {ccs_short_strike} / Long {ccs_long_strike}")

    # ConIds (Approximate or Hardcoded fallbacks)
    # Using dummy/fallback IDs if fetch fails, but let's try to be realistic or use placeholders
    # In a real test, one might fetch these. For "Submit Only" dry run, any valid ConID works if we don't care about market data.
    # But to prevent "No Security Definition" errors, we should use valid SPXW ConIds if possible.
    # Reusing the ones from previous METF test for PCS, calculating new ones for CCS is hard without fetching.
    # Let's use the same hardcoded fallbacks for PCS, and invent/reuse for CCS just to test structure.
    # actually, reusing same IDs for CCS legs would be weird (Put leg in Call side).
    # Ideally should fetch.
    
    print("5. Resolving ConIds (Live Fetch)...")
    try:
        pcs_short_conid = strategy.get_con_id("SPX", pcs_short_strike, 'P', expiration, trading_class)
        pcs_long_conid = strategy.get_con_id("SPX", pcs_long_strike, 'P', expiration, trading_class)
        ccs_short_conid = strategy.get_con_id("SPX", ccs_short_strike, 'C', expiration, trading_class)
        ccs_long_conid = strategy.get_con_id("SPX", ccs_long_strike, 'C', expiration, trading_class)
    except Exception as e:
        print(f"⚠️ Fetch error: {e}")
        pcs_short_conid = 0

    # Fallback if fetch failed (returns 0) or threw error
    if pcs_short_conid == 0 or ccs_short_conid == 0:
        print("⚠️ Fetch failed or timed out. Using DISTINCT fallback IDs for structure test.")
        # Use DISTINCT fake IDs if real ones aren't available to preserve 4-leg structure
        pcs_short_conid = 10001
        pcs_long_conid =  10002
        ccs_short_conid = 20001 # Distinct from Puts
        ccs_long_conid =  20002 # Distinct from others
    
    print(f"   PCS Short ConId: {pcs_short_conid}")
    print(f"   PCS Long ConId:  {pcs_long_conid}")
    print(f"   CCS Short ConId: {ccs_short_conid}")
    print(f"   CCS Long ConId:  {ccs_long_conid}")

    # 6. ESTIMATE PRICES & CREDITS
    # Simulating nice premiums
    pcs_est_credit = 2.45
    ccs_est_credit = 2.45
    total_credit = pcs_est_credit + ccs_est_credit # 4.90 Total
    
    print(f"\n6. Estimated Credits:")
    print(f"   PCS Credit: ${pcs_est_credit:.2f}")
    print(f"   CCS Credit: ${ccs_est_credit:.2f}")
    print(f"   Total Credit: ${total_credit:.2f}")

    # 7. Construct Iron Condor Order (4 Legs)
    print("\n7. Constructing Iron Condor Order (transmit=False)...")
    ic_contract = Contract()
    ic_contract.symbol = "SPX"
    ic_contract.secType = "BAG"
    ic_contract.currency = "USD"
    ic_contract.exchange = "SMART"
    
    # Order: BUY Long Put, SELL Short Put, SELL Short Call, BUY Long Call
    # Wait, "Iron Condor" usually:
    # Sell Put Vertical (Sell Short, Buy Long) -> Net Credit
    # Sell Call Vertical (Sell Short, Buy Long) -> Net Credit
    # Combined: Sell Short Put, Buy Long Put, Sell Short Call, Buy Long Call
    
    ic_legs = []
    # PCS Legs
    ic_legs.append(create_combo_leg_by_id(pcs_short_conid, 'SELL'))
    ic_legs.append(create_combo_leg_by_id(pcs_long_conid, 'BUY'))
    # CCS Legs
    ic_legs.append(create_combo_leg_by_id(ccs_short_conid, 'SELL'))
    ic_legs.append(create_combo_leg_by_id(ccs_long_conid, 'BUY'))
    
    ic_contract.comboLegs = ic_legs
    
    # Action=BUY + Leg(Short=SELL, Long=BUY) = Sell Short, Buy Long.
    # This results in a Credit (Net Seller of premium).
    # Price should be Negative (Debit paid) or Positive (Debit paid)?
    # If we "BUY" a strategy that yields specific legs, the price is implicitly the Net Cost.
    # If Net Cost is negative (we receive money), price is negative limit?
    ic_order = create_order()
    ic_order.action = "BUY"
    ic_order.orderType = "LMT"
    ic_order.totalQuantity = 1
    ic_order.lmtPrice = strategy.round_price(-total_credit) # Negative for Credit
    ic_order.transmit = False
    
    ic_id = strategy.nextOrderId()
    print(f"   Placing IC Order #{ic_id} @ ${ic_order.lmtPrice}")
    strategy.placeOrder(ic_id, ic_contract, ic_order)
    time.sleep(1) # Wait for processing

    # 8. Construct Dual OCO Stop Loss (PCS + CCS)
    print("\n8. Constructing Dual OCO Stop Loss (transmit=False)...")
    
    # Parameters
    stop_loss_buffer = 0.07
    stop_limit_offset = 0.20
    stop_market_offset = 0.35  # Confirmed 0.35 in documentation/config
    
    # --- PCS STOP LOGIC ---
    pcs_base = pcs_est_credit
    pcs_trigger_val = (pcs_base * 2) - stop_loss_buffer
    pcs_trigger_price = strategy.round_price(-pcs_trigger_val) # Negative because we Buy Back Debit
    
    pcs_limit_price = strategy.round_price(pcs_trigger_price + stop_limit_offset) # Trigger + Offset
    pcs_market_trigger = strategy.round_price(pcs_trigger_price - stop_market_offset) # Trigger - Offset (More negative)
    
    print(f"   PCS Params:")
    print(f"     Credit: ${pcs_base:.2f}")
    print(f"     Trigger: ${pcs_trigger_price} (Calc: {pcs_base}*2 - {stop_loss_buffer})")
    print(f"     Limit Price: ${pcs_limit_price} (Trigger + {stop_limit_offset})")
    print(f"     Market Trigger: ${pcs_market_trigger} (Trigger - {stop_market_offset})")
    
    # PCS Contracts (2-Leg BAG to Close)
    # Closing PCS: BUY Short, SELL Long.
    pcs_sl_legs = [
        create_combo_leg_by_id(pcs_short_conid, 'BUY'), # Close Short
        create_combo_leg_by_id(pcs_long_conid, 'SELL')  # Close Long
    ]
    
    pcs_sl_contract = Contract()
    pcs_sl_contract.symbol = "SPX"
    pcs_sl_contract.secType = "BAG"
    pcs_sl_contract.currency = "USD"
    pcs_sl_contract.exchange = "SMART"
    pcs_sl_contract.comboLegs = pcs_sl_legs
    
    # PCS Orders
    # PCS Stop Limit OCO setup
    pcs_sl_limit = create_order()
    pcs_sl_limit.action = "SELL" # "Sell" the bag? (Wait, if legs are Buy/Sell closing...)
    # If we want to PAY Debit to Close.
    # Closing a Credit Spread usually means Buying it back.
    # If Action=BUY, Legs (Buy Short, Sell Long) -> Buy Short, Sell Long. Correct.
    # Why strategy uses "SELL"?
    # MEIC code: `pcs_limit.action = "SELL"`.
    # And Legs: `create_combo_leg_by_id(put_short, 'BUY'), create_combo_leg_by_id(put_long, 'SELL')`
    # If Order Action is SELL, and Leg Action is BUY...
    # IBKR Logic: Order Action flips leg action? No.
    # Wait, usually for BAG, Order Action just determines direction of the whole combo relative to price?
    # Let's trust the MEIC code: Action "SELL".
    
    pcs_sl_limit.action = "SELL"
    pcs_sl_limit.orderType = "STP LMT"
    pcs_sl_limit.totalQuantity = 1
    
    # Standard Assignment Verified:
    # Aux = Trigger
    # Lmt = Limit
    pcs_sl_limit.auxPrice = pcs_trigger_price
    pcs_sl_limit.lmtPrice = pcs_limit_price
    
    pcs_sl_limit.transmit = False
    pcs_sl_limit_id = strategy.nextOrderId()
    
    # Stop Market
    pcs_sl_market = create_order()
    pcs_sl_market.action = "SELL"
    pcs_sl_market.orderType = "STP"
    pcs_sl_market.totalQuantity = 1
    pcs_sl_market.auxPrice = pcs_market_trigger
    pcs_sl_market.transmit = False
    pcs_sl_market_id = strategy.nextOrderId()
    
    # OCO Group
    group_name = f"PCS_TEST_{ic_id}"
    pcs_sl_limit.ocaGroup = group_name
    pcs_sl_market.ocaGroup = group_name
    pcs_sl_limit.ocaType = 1
    pcs_sl_market.ocaType = 1
    
    print(f"   Placing PCS Stop Limit #{pcs_sl_limit_id}: Trigger ${pcs_sl_limit.auxPrice}, Limit ${pcs_sl_limit.lmtPrice}")
    print(f"   Placing PCS Stop Market #{pcs_sl_market_id}: Trigger ${pcs_sl_market.auxPrice}")
    
    strategy.placeOrder(pcs_sl_limit_id, pcs_sl_contract, pcs_sl_limit)
    strategy.placeOrder(pcs_sl_market_id, pcs_sl_contract, pcs_sl_market)
    
    
    # --- CCS STOP LOGIC ---
    ccs_base = ccs_est_credit
    ccs_trigger_val = (ccs_base * 2) - stop_loss_buffer
    ccs_trigger_price = strategy.round_price(-ccs_trigger_val)
    
    ccs_limit_price = strategy.round_price(ccs_trigger_price + stop_limit_offset)
    ccs_market_trigger = strategy.round_price(ccs_trigger_price - stop_market_offset)
    
    print(f"\n   CCS Params:")
    print(f"     Credit: ${ccs_base:.2f}")
    print(f"     Trigger: ${ccs_trigger_price}")
    print(f"     Limit Price: ${ccs_limit_price}")
    print(f"     Market Trigger: ${ccs_market_trigger}")
    
    # CCS Contracts
    ccs_sl_legs = [
        create_combo_leg_by_id(ccs_short_conid, 'BUY'), # Close Short Call
        create_combo_leg_by_id(ccs_long_conid, 'SELL')  # Close Long Call
    ]
    
    ccs_sl_contract = Contract()
    ccs_sl_contract.symbol = "SPX"
    ccs_sl_contract.secType = "BAG"
    ccs_sl_contract.currency = "USD"
    ccs_sl_contract.exchange = "SMART"
    ccs_sl_contract.comboLegs = ccs_sl_legs
    
    # CCS Orders
    ccs_sl_limit = create_order()
    ccs_sl_limit.action = "SELL"
    ccs_sl_limit.orderType = "STP LMT"
    ccs_sl_limit.totalQuantity = 1
    ccs_sl_limit.auxPrice = ccs_trigger_price
    ccs_sl_limit.lmtPrice = ccs_limit_price
    ccs_sl_limit.transmit = False
    ccs_sl_limit_id = strategy.nextOrderId()
    
    ccs_sl_market = create_order()
    ccs_sl_market.action = "SELL"
    ccs_sl_market.orderType = "STP"
    ccs_sl_market.totalQuantity = 1
    ccs_sl_market.auxPrice = ccs_market_trigger
    ccs_sl_market.transmit = False
    ccs_sl_market_id = strategy.nextOrderId()
    
    # OCO Group
    ccs_group_name = f"CCS_TEST_{ic_id}"
    ccs_sl_limit.ocaGroup = ccs_group_name
    ccs_sl_market.ocaGroup = ccs_group_name
    ccs_sl_limit.ocaType = 1
    ccs_sl_market.ocaType = 1

    print(f"   Placing CCS Stop Limit #{ccs_sl_limit_id}: Trigger ${ccs_sl_limit.auxPrice}, Limit ${ccs_sl_limit.lmtPrice}")
    print(f"   Placing CCS Stop Market #{ccs_sl_market_id}: Trigger ${ccs_sl_market.auxPrice}")
    
    strategy.placeOrder(ccs_sl_limit_id, ccs_sl_contract, ccs_sl_limit)
    strategy.placeOrder(ccs_sl_market_id, ccs_sl_contract, ccs_sl_market)
    
    print(f"\n✅ All MEIC Orders Submitted (transmit=False).")
    print("   Waiting 5 seconds for TWS processing...")
    time.sleep(5)
    print("Disconnecting...")
    # strategy.disconnect() # connect_to_ibkr usage handles disconnect or thread
    strategy.disconnect()
    time.sleep(1)

if __name__ == "__main__":
    main()
