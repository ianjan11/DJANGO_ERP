# Tax Engine Notes — `TaxCalculatorService`

Internal reference for `core/services/tax_engine.py`. Covers what the engine does, why it's built this way, and the edge cases that have already burned us once.

## What it does

Given a line's subtotal, quantity, and an ordered list of taxes, computes:
- `base` — the untaxed base amount
- `total_tax` — sum of all tax lines (rounded)
- `lines` — per-tax breakdown (`raw` and `rounded` amounts)
- `total_with_tax` — final amount the customer pays

Each `Tax` has:

| Field | Meaning |
|---|---|
| `rate` | Percentage (e.g. `10` = 10%) or, for FIXED taxes, a flat currency amount |
| `computation` | `'PERCENT'` or `'FIXED'` |
| `price_include` | `True` if the tax is already baked into the price (e.g. price tag includes VAT); `False` if it's added on top |
| `include_base_amount` | `True` if this tax **compounds** — later taxes in the sequence are calculated on a base that already includes this tax's amount |

## The core problem: solving for the untaxed base

If any tax is `price_include=True`, the `subtotal` you're given is the **final, tax-inclusive** price — you don't know the untaxed base up front, you have to back it out.

For a single non-compounding percent tax this is simple: `base = price / (1 + rate)`. It gets harder with multiple inclusive taxes, some compounding and some not, some FIXED and some PERCENT, in arbitrary order.

**Approach:** treat `base_untaxed` as an unknown `X`. Walk the tax list once, expressing each inclusive tax's amount as a linear function `coef * X + const`:

- **PERCENT, non-compounding:** `amount = rate * X` → contributes `coef = rate` to the total
- **PERCENT, compounding:** `amount = rate * running_base`, where `running_base` itself is `coef*X + const` from prior compounding taxes → contributes `rate * running_coef` and `rate * running_const`
- **FIXED (either):** `amount = rate * quantity` → a pure constant, contributes `0` to `coef`, `rate*quantity` to `const`

Sum all inclusive taxes' contributions into `total_coef` and `total_const`. Since `subtotal = X + total_tax(X)`:

```
subtotal = X * (1 + total_coef) + total_const
X = (subtotal - total_const) / (1 + total_coef)
```

This is solved once in `solve_untaxed_base`, then a second forward pass (`calculate_line_taxes`) computes the real per-line amounts using the now-known `base_untaxed`.

**Why two passes:** you can't compute real per-line tax amounts until you know `base_untaxed`, but you can't solve for `base_untaxed` without knowing how the taxes relate to each other. The symbolic (coef/const) pass solves that chicken-and-egg problem without guessing or iterating.

## Compounding (`include_base_amount`)

When `True`, this tax's amount is added into `running_base` before the *next* tax in sequence is calculated — regardless of whether the current tax is inclusive or exclusive. This lets you model things like "tax B is calculated on (price + tax A)".

Compounding and `price_include` are independent flags — all four combinations are valid and handled:

| price_include | include_base_amount | Meaning |
|---|---|---|
| `False`, `False` | Simple exclusive tax, added on top, doesn't affect later taxes |
| `False`, `True` | Exclusive tax that cascades — later taxes calculate on the inflated base |
| `True`, `False` | Simple inclusive tax, extracted from price, doesn't affect other inclusive taxes' extraction |
| `True`, `True` | Inclusive tax that compounds with other inclusive taxes during extraction |

## Worked examples

**Two independent 5% inclusive taxes on a price of 110** (neither compounds):
```
base = 110 / (1 + 0.05 + 0.05) = 100
tax A = 5, tax B = 5, total = 10
```
Do **not** unwind sequentially (`110/1.05/1.05 ≈ 99.77`) — that implicitly compounds taxes that were configured as independent. This was a real bug (see "Known bugs fixed" below).

**Two compounding 10% inclusive taxes on a price of 121:**
```
base = 121 / (1.10 * 1.10) = 100
tax A = 10 (on 100), tax B = 11 (on 110), total = 21
```

**Flat 500 inclusive fee baked into a price of 1500:**
```
base = 1500 - 500 = 1000
```
Not `1500 / (1 + 5.00)` — FIXED taxes are constants, never multiplied by a rate fraction.

## Rounding rules

- Each tax line's amount is rounded to 2dp (`ROUND_HALF_UP`) independently and stored as `amount` (raw unrounded value kept as `amount_raw` for audit).
- `total_tax` is the **sum of the rounded line amounts**, not a separately-rounded sum of raw amounts. This avoids the line items not adding up to the displayed total tax (a real bug in an earlier version).
- `total_with_tax` = `base` (rounded) + `total_tax` (already rounded). For pure-inclusive configurations this should reconcile back to the original subtotal to the cent — see `test_pure_inclusive_rounding_does_not_drift_from_subtotal`.

## Known bugs already fixed (don't reintroduce)

1. **FIXED inclusive taxes treated as percentages.** An earlier version always did `base * (rate/100)` for inclusive taxes regardless of `computation`. A FIXED inclusive tax of `500` was computed as if `500` were a 500% rate. Fixed by branching on `computation` in both the solve step and the forward pass.
2. **Non-compounding inclusive taxes divided out sequentially.** Earlier versions unwound each inclusive tax one at a time (`price / (1+r1) / (1+r2)`), which implicitly compounds taxes that were never flagged as compounding. Fixed by the symbolic coef/const solve, which sums non-compounding taxes additively into one shared divisor.
3. **Inclusive-tax extraction depended on sequence order.** An earlier version only looked for inclusive taxes at the *start* of the tax list and stopped at the first exclusive tax, silently skipping inclusive taxes that appeared later in the sequence. Fixed by walking the full list regardless of order.
4. **Rounding drift between line items and total.** `total_tax` was computed from the unrounded accumulator while each line was rounded independently, so summing the displayed line amounts could differ from the displayed total by ±0.01. Fixed by defining `total_tax` as the sum of rounded lines.

## Test coverage

See `core/tests/test_tax_engine.py`. Notable regression tests:
- `test_fixed_inclusive_is_not_treated_as_percent`
- `test_multiple_non_compounding_inclusive_taxes_combine_additively`
- `test_mixed_inclusive_and_exclusive_any_order`
- `test_pure_inclusive_rounding_does_not_drift_from_subtotal`
- `test_fixed_inclusive_that_also_compounds`

Run with:
```powershell
cd C:\Users\IAN\SHOP PROJECT\SM_SYSTEM
python manage.py test core.tests.test_tax_engine
```

## Open questions / things to verify against real config data

- Does any tax config actually combine `computation='FIXED'` with `include_base_amount=True`? The engine handles it, but it's an unusual combination worth confirming is meaningful in your business logic (a flat fee "compounding" into a later percentage tax's base).
- Confirm `denom <= 0` (raised as `ValueError`) can't realistically occur in your data — it would require inclusive tax rates summing to ≤ -100%, which shouldn't happen with normal positive rates, but worth knowing it's a hard failure rather than a silent fallback if it ever does.
