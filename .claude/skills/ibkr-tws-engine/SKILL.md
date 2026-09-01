---
name: ibkr-tws-engine
description: IBKR TWS/Gateway option-chain capture, combo formation, and order submission for 0DTE SPX/SPXW trading. Covers ib_async patterns, pacing limits, BAG sign convention, OCA brackets, and the TRADING-DECK engine architecture.
metadata:
  type: skill
  scope: project
  repo: TRADING-DECK
---

# IBKR TWS Engine — Option Chain, Combo Formation, Order Submission

This skill captures the institutional knowledge for working with the IBKR
TWS/Gateway API in the TRADING-DECK codebase. Three pillars:

1. **Option chain data capture** — fetching, caching, qualifying contracts
2. **Trade formation** — credit spreads, brackets, TP/SL math
3. **TWS submission** — BAG convention, OCA brackets, transmission sequencing

---

## 1. Option Chain Data Capture

### Strikes: SPX is 5-pt, SPXW is 1-pt

- SPX monthly: strikes at 5-pt increments (7600, 7605, 7610, …)
- SPXW 0DTE weekly: strikes at 1-pt increments (7600, 7601, 7602, …)
- **Always use SPX (monthly) for 0DTE orders.** GEX walls/anchors land on 5-pt
  boundaries. Raw SPXW 1-pt strikes cause contract qualification failures.
- If a raw wall/anchor is on a 1-pt boundary, snap to 5:
  ```python
  def _round5(x: float) -> float:
      return round(x / 5.0) * 5.0
  ```
  Pattern: snap upstream in the signal generator, not downstream in pricing
  (cleaner separation, downstream just trusts the value).

### Contract qualification — ib_async gotchas

```python
from ib_async import Option
qualified_list = await asyncio.wait_for(
    self.ib.qualifyContractsAsync(Option('SPX', expiry, strike, 'P', 'SMART')),
    timeout=10.0,
)
qualified = qualified_list[0] if qualified_list else None
con_id = getattr(qualified, 'conId', 0) if qualified else 0
if con_id == 0:
    raise RuntimeError(f"Could not qualify {strike}")
```

Gotchas:
- **`qualifyContractsAsync` returns a list, not a contract.** Always index `[0]`.
- **`conId == 0` means qualification failed.** Don't proceed — TWS will silently reject.
- **Wrap in `asyncio.wait_for(timeout=10.0)`.** ib_async can hang on disconnects.
- **Retry once after 15s on timeout** — pacing violations typically clear.

### Pacing limits

| API | Limit | Recovery |
|-----|-------|----------|
| `reqHistoricalData` | 60 req / 10 min | wait + retry with backoff |
| `reqContractDetails` | 60 req / 10 min | wait + retry |
| `reqMktData` / `reqTickers` | soft (snapshot) | cache aggressively |

Pacing violations return **empty lists, not exceptions**. If `_get_chain_data()`
returns `[]` after a refresh that should have data, you've been throttled.
Pattern: 3 attempts with exponential backoff before declaring failure.

### Cache pattern — strike_ladder

The engine maintains `_last_metrics["strike_ladder"]` (a list of dicts with
`strike / call_bid / call_ask / put_bid / put_ask / iv / oi / vol`). Refresh
happens on a 60s loop, but reads can happen at any time.

**Two-level cache freshness:**

```python
# 1. Fresh check (< 60s old): use as-is
# 2. Stale check (> 60s old): re-qualify just the strikes you need (cheap)
# 3. Missing strike: fall back to live reqTickersAsync on the qualified contract

ladder = self._last_metrics.get("strike_ladder", [])
ladder_lookup = {float(r["strike"]): r for r in ladder}

missing = [(i, leg) for i, leg in enumerate(legs)
           if float(leg["strike"]) not in ladder_lookup]
if missing:
    contracts = [qualified[i] for i, _ in missing]
    tickers = await asyncio.wait_for(
        self.ib.reqTickersAsync(*contracts), timeout=5.0
    )
```

**Why this matters:** a full chain re-fetch on every combo order burns your
pacing budget. Single-leg live ticker fallback costs ~1 req.

---

## 2. Trade Formation

### Sign convention for leg pricing

```python
# Mid-price model:
sign = 1 if leg["action"] == "BUY" else -1
estimated_legs.append(sign * mid)
# Net value: <0 = credit combo, >0 = debit combo
net_value = sum(estimated_legs)
```

This matches IBKR's convention:
- SELL higher-strike put + BUY lower-strike put (PCS) → credit (negative net)
- BUY lower-strike call + SELL higher-strike call (CCS) → credit (negative net)
- Long call spread (debit) → positive net

### TP / SL parameters

| Parameter | Meaning | Default | Example |
|-----------|---------|---------|---------|
| `tp_pct` | take-profit as % of credit captured | 50 | 50% = half the credit |
| `sl_ratio` | stop-loss multiplier of credit | 2.0 | 2x = lose 2× the credit |

### TP / SL math (matches IBKR BAG close-order semantics)

```python
credit_base = abs(net_value) if net_value != 0 else 1.0

# Take Profit — SELL to close
if net_value < 0:                                       # credit combo
    target_debit_tp = credit_base * (1.0 - tp_pct / 100.0)
    tp_price = -abs(round(target_debit_tp / 0.05) * 0.05)   # NEGATIVE
else:                                                   # debit combo
    tp_price = abs(round(credit_base * (1.0 + tp_pct / 100.0) / 0.05) * 0.05)  # POSITIVE

# Stop Loss — STP LMT (primary)
trigger_val_sl = (credit_base * sl_ratio) - 0.07
sl_trigger_price = -abs(round(trigger_val_sl / 0.05) * 0.05)     # NEGATIVE
sl_limit_price = -abs(round((abs(sl_trigger_price) + 0.20) / 0.05) * 0.05)  # slightly less negative (worse) than trigger

# Stop Market — STP (safety)
sl_market_trigger = -abs(round((abs(sl_trigger_price) + 0.35) / 0.05) * 0.05)  # even more negative
```

**Round all values to 0.05 boundary.** SPX options tick in 5-cent increments.

---

## 3. TWS Submission — The BAG Sign Convention

This is the **#1 source of bugs**. Memorize it:

### Entry (Parent)

| Combo type | IBKR order | Limit sign | Meaning |
|-----------|-----------|-----------|---------|
| Credit (PCS, CCS, IC, IronFly) | `BUY` | **NEGATIVE** | Receive ≥ \|limit\| |
| Debit (long call spread, etc.) | `BUY` | **POSITIVE** | Pay ≤ \|limit\| |

```python
# Match execute_spread's pattern EXACTLY:
limit_price = round(net_value / 0.05) * 0.05   # SIGNED, never abs()
parent = LimitOrder('BUY', qty, limit_price)
parent.transmit = False  # never transmit parent first
```

**Why negative limit on BUY = credit?** IBKR BAG convention: a negative
limit on the BAG parent inverts the role — instead of "pay up to X", it means
"receive at least |X|". Counterintuitive but correct per IBKR docs.

### Common bugs (and their fixes)

| Bug | Symptom | Fix |
|-----|---------|-----|
| `if net_value < 0: limit_price = -0.05` | Fills at $0.05 instead of true credit | Use signed `round(net_value/0.05)*0.05` |
| `tp_price = credit_base * (1 + tp_pct/100)` (no abs) | TP = positive (e.g., +22.72) — never fills | For credit, use `-abs(round(...))` |
| `sl_trigger = ... + 0.07` (positive) | SL triggered 10¢ too early | Use `(credit * ratio) - 0.07` |
| `parent.transmit = True` | TWS Error 201 — "Risk-Free Arb" | All but last bracket leg = `transmit=False` |

### 3-Component OCA Bracket Pattern

IBKR requires the entire bracket (parent + TP + SL) submitted as one OCA group.
Transmission is sequential: parent first, then TP, then SL_LMT, then SL_MKT
(the last leg's `transmit` flag actually fires the whole bracket).

```python
parent_id = self.ib.client.getReqId()          # allocate upfront!
oca_group_name = f"OCA_SPX_{parent_id}"

# Parent — transmit=False
parent = LimitOrder('BUY', qty, limit_price)
parent.orderId = parent_id
parent.ocaGroup = oca_group_name; parent.ocaType = 1  # 1 = cancel all on fill
parent.transmit = False

# TP — transmit=False
tp = LimitOrder('SELL', qty, tp_price)
tp.parentId = parent_id; tp.ocaGroup = oca_group_name; tp.ocaType = 1
tp.transmit = False

# SL Limit — transmit=False
sl_limit = IbOrder()
sl_limit.action = 'SELL'; sl_limit.orderType = 'STP LMT'
sl_limit.auxPrice = sl_trigger_price; sl_limit.lmtPrice = sl_limit_price
sl_limit.parentId = parent_id; sl_limit.ocaGroup = oca_group_name; sl_limit.ocaType = 1
sl_limit.transmit = False

# SL Market — transmit=<user's choice> (last leg fires the bracket)
sl_market = IbOrder()
sl_market.action = 'SELL'; sl_market.orderType = 'STP'
sl_market.auxPrice = sl_market_trigger
sl_market.parentId = parent_id; sl_market.ocaGroup = oca_group_name; sl_market.ocaType = 1
sl_market.transmit = transmit  # True = live, False = staged in TWS
```

**Critical: allocate `parent_id` with `self.ib.client.getReqId()` BEFORE
placing anything.** TWS rejects the chain (Error 201) if children arrive
without a parent pre-allocated.

### Combo routing — 2-leg vs 4-leg difference

```python
# 2-leg combos (PCS/CCS) — MUST have NonGuaranteed=1
#   else: TWS Error 201 (Risk-Free Arb)
# 4-leg combos (IC) — MUST NOT have routing params
#   else: TWS Error 10043 (Invalid Tag)
routing_tags = [] if spread_type == 'IC' else [TagValue('NonGuaranteed', '1')]
order.smartComboRoutingParams = routing_tags
```

### Underlying price triggers (PriceCondition)

For entry/TP/SL triggered by SPX crossing a level:

```python
under = Contract()
under.symbol = 'SPX'; under.secType = 'IND'; under.exchange = 'CBOE'
qualified_under = self.ib.qualifyContract(under)
spx_conId = qualified_under.conId if qualified_under else 0

if spx_conId and trigger_price:
    cond = PriceCondition()
    cond.conId = spx_conId; cond.exchange = 'CBOE'
    cond.isMore = True            # True = trigger when SPX ≥ price
    cond.price = trigger_price
    order.conditions.append(cond)
    order.conditionsIgnoreRth = True   # trigger outside RTH
```

`isMore=True` for entry/TP (long bias), `isMore=False` for SL (short bias).

---

## 4. Code Map (TRADING-DECK)

| Function | File:line | Purpose |
|----------|-----------|---------|
| `execute_spread` | engine.py:1880-2030 | Manual bot path, credit combos (canonical reference) |
| `execute_combo` | engine.py:2216-2535 | 1-4 leg generic BAG, used by recommendation engine |
| `execute_single_leg` | engine.py:2056-2200 | Single-leg with fill-then-attach semantics |
| `_get_chain_data` | engine.py:240-340 | Option chain fetch w/ 3-attempt pacing retry |
| `_find_strike_by_delta` | engine.py:900-980 | Delta-based strike picker, accepts empty details |
| `_last_metrics["strike_ladder"]` | engine.py:1200+ | Session-lifetime cache |
| `/api/trade_combo` | server.py:1018-1056 | FastAPI wrapper, validates → engine.execute_combo |
| `bot_engine.execute_signal` | bot_engine.py:1300+ | Calls execute_spread for FLIP/PINNING/TREND/etc. |

When changing TP/SL/limit math, **always diff against execute_spread's pattern
first.** It has been validated live. execute_combo was added later and
diverged in three places (commit d1964e9 fixed them).

---

## 5. Testing checklist for IBKR order changes

1. **Pre-flight validation** — does the math produce the expected sign?
   Credit → parent limit < 0. TP → < 0 for credit, > 0 for debit. SL → < 0.
2. **Syntax + import check** — `python3 -c "import ast; ast.parse(open('engine.py').read())"`
3. **Mock tests pass** — `test_recommendation_*.py` mock `execute_combo` so they're
   unaffected by internal logic changes.
4. **Paper account live test** — place a 1-lot PCS at minimum size, verify
   fill matches expected credit (not $0.05).
5. **TWS log inspection** — after fill, check `Reports → Activity` for the
   actual fill price vs. expected.
6. **Bracket cleanup** — TP or SL should cancel the other two via OCA group.

---

## 6. Anti-patterns (DON'T do this)

- ❌ `limit_price = abs(net_value)` — strips sign, sends credit as debit
- ❌ `if credit: limit_price = -0.05` — caps credit at floor, fills tiny
- ❌ `parent.transmit = True` for first bracket leg — Error 201
- ❌ `ocaType = 0` (None) — bracket doesn't cancel siblings
- ❌ Smart-routing tags on 4-leg IC — Error 10043
- ❌ Skipping `qualifyContractsAsync` (using raw contract) — TWS rejects
- ❌ Re-fetching the full chain per order — burns pacing budget
- ❌ Snapping strikes downstream in pricing — snap upstream in signal gen
- ❌ Mixing TP sign conventions (positive for credit) — never fills