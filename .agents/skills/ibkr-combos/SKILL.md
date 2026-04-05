---
name: ibkr-combos
description: Patterns for IBKR Combo (BAG) orders and OCO (One-Cancels-Other) bracket orders.
---

# IBKR Combo and OCO Order Patterns

This skill provides validated patterns for creating complex option orders using the Interactive Brokers TWS API. It covers multi-leg combos (vertical spreads, Iron Condors) and safety brackets (Take Profit + Stop Loss) using OCO groups.

## Core Concepts

- **BAG Contract**: A "Basket" or "Combo" security type used to trade multiple legs as a single instrument.
- **Credit vs Debit**: In combo orders (BAG), prices are often expressed as Net Cost. A negative price usually indicates a Net Credit (receiving money).
- **OCO (One-Cancels-Other)**: A group of orders linked such that if one fills, the others are automatically cancelled.

## Validated Patterns

### 1. Creating a Combo Contract (BAG)

Always use the `BAG` secType and specify `comboLegs`.

```python
from ibapi.contract import Contract, ComboLeg

def create_combo_contract(symbol, legs, exchange="SMART"):
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "BAG"
    contract.currency = "USD"
    contract.exchange = exchange
    
    contract.comboLegs = []
    for con_id, action, ratio in legs:
        leg = ComboLeg()
        leg.conId = con_id
        leg.ratio = ratio
        leg.action = action # 'BUY' or 'SELL'
        leg.exchange = exchange
        contract.comboLegs.append(leg)
    return contract
```

### 2. Entry Order (Credit Spread)

For a Credit Spread (vertical), we "BUY" the BAG with a negative limit price.

```python
def create_entry_order(credit, quantity=1):
    order = Order()
    order.action = "BUY"
    order.orderType = "LMT"
    order.totalQuantity = quantity
    order.lmtPrice = -credit # Negative price = Receive Credit
    order.transmit = False # Set to True to active
    return order
```

### 3. OCO Protection Brackets (TP + SL)

An OCO group typically contains a Limit order (Take Profit) and one or more Stop orders.

#### METF Pattern (3-component OCO)

- **Take Profit**: LMT order to close at profit.
- **Stop Limit**: STP LMT for controlled exit.
- **Stop Market**: STP as a "safety net" if price gaps.

```python
def create_oco_bracket(entry_id, con_ids, credit, quantity=1):
    group_name = f"OCO_{entry_id}"
    
    # 1. Take Profit (LMT)
    tp = Order()
    tp.action = "SELL" # Closing the credit spread
    tp.orderType = "LMT"
    tp.lmtPrice = -(credit / 2) # Close at 50% profit
    
    # 2. Stop Limit (Primary SL)
    sl_lmt = Order()
    sl_lmt.action = "SELL"
    sl_lmt.orderType = "STP LMT"
    sl_lmt.auxPrice = -((credit * 2) - 0.07) # Trigger
    sl_lmt.lmtPrice = sl_lmt.auxPrice + 0.20 # Limit (less negative)
    
    # 3. Stop Market (Safety SL)
    sl_mkt = Order()
    sl_mkt.action = "SELL"
    sl_mkt.orderType = "STP"
    sl_mkt.auxPrice = sl_lmt.auxPrice - 0.35 # More negative trigger
    
    for o in [tp, sl_lmt, sl_mkt]:
        o.ocaGroup = group_name
        o.ocaType = 1 # Cancel others on fill
        o.totalQuantity = quantity
        o.transmit = False
        
    return tp, sl_lmt, sl_mkt
```

### 4. Iron Condor (4-leg) Strategy

For an Iron Condor, use two separate OCO groups (one for the Put side, one for the Call side) to allow partial exits or independent protection.

- **Entry**: 4-leg BAG.
- **Protection**: Group A (PCS Legs) + Group B (CCS Legs).

### 5. Critical TagValue Routing Rules (Error 10043 & Error 201)

When routing complex Combo Orders (especially SPX) through the `SMART` exchange, Interactive Brokers enforces strict risk-free arbitrage rules that dictate whether the order should be "Guaranteed" or "NonGuaranteed". 

- **2-Leg Combos (Vertical Spreads, Straddles)**: MUST include `TagValue('NonGuaranteed', '1')` in their `smartComboRoutingParams` or TWS will reject the order with **Error 201 (Risk-Free Arbitrage)**.
- **4-Leg Combos (Iron Condors)**: MUST NOT include *any* tags in their `smartComboRoutingParams`. If you attach the `NonGuaranteed` tag to a 4-leg combo that contains OCO bracket orders, TWS will instantly auto-cancel the order natively with **Error 10043 (NonGuaranteed is missing or invalid for REL+MKT limits)**.

```python
# Best practice pattern for dynamic routing assignment
routing_tags = [] if spread_type == 'IC' else [TagValue('NonGuaranteed', '1')]

parent_order.smartComboRoutingParams = routing_tags
tp_order.smartComboRoutingParams = routing_tags
sl_order.smartComboRoutingParams = routing_tags
```

### 6. Order Transmission Sequence (Error 201)

When combining 2-Leg Combos with OCO Bracket safety nets, **you must never transmit the parent order before the child orders are built and dispatched.** If TWS receives the Parent `BUY` instruction before the Child `SELL` instructions are packaged alongside it, it will immediately reject the incoming Child brackets with **Error 201 (Risk-Free Arbitrage - Cannot be on both sides of the market)**.

To solve this, follow the Pre-Allocated Batching pattern:
1. Fetch a valid ID upfront: `parent_id = ib.client.getReqId()`.
2. Construct the Parent and all Child orders offline within python.
3. Make sure every order uses `transmit = False` EXCEPT the final child order in the chain (`transmit = True`).
4. Dispatch all `placeOrder` commands back-to-back at the end of the function block.

```python
parent_id = ib.client.getReqId()
parent_order.orderId = parent_id
parent_order.transmit = False

tp_order.parentId = parent_id
tp_order.transmit = False

sl_order.parentId = parent_id
sl_order.transmit = True # ONLY the last order triggers the TWS API transmission

# Batch dispatch
ib.placeOrder(combo_contract, parent_order)
ib.placeOrder(combo_contract, tp_order)
ib.placeOrder(combo_contract, sl_order)
```


## Critical Rules for Combos

1. **Negative Prices**: Always verify if a negative limit price is needed. In IBKR BAGs, negative prices are standard for receiving credits.
2. **Rounding**: Use `round_price()` (typically to 2 decimal places or nearest 0.05 for SPX) to avoid "Invalid Price" errors.
3. **Wait for Fills**: Safety brackets should ideally be submitted *after* the entry order fills, or with `transmit=False` for manual oversight.
4. **Time In Force (TIF)**: Always explicitly declare `order.tif = "DAY"` on **every** leg of your order (parent and all OCO brackets). If omitted on automated API orders, strict user TWS presets will intercept the order natively, assign it a TIF, and instantly auto-cancel the entire bracket chain with **Error 10349: Order TIF was set to DAY based on order preset**.
5. **Event Loop Flushing**: When using `ib_insync`, submitting native OCO brackets with complex legs requires allowing the TCP socket time to flush the payload queue sequentially. Failing to `await asyncio.sleep(0.1)` x 10 times at the end of a bracket submission function might result in TWS dropping the child orders silently.

## Usage in Scripts

Refer to the primary test scripts in the workspace for complete implementations:

- `test_metf_oco_tp_sl.py`: Vertical spread TP/SL logic.
- `test_meic_submit_only.py`: Iron Condor multi-group OCO logic.
