"""Risk policy is independent of both the predictor and ledger writes."""
from dataclasses import dataclass


@dataclass
class Decision:
    approved: bool
    reason: str


def assess(*, side, quantity, price_cents, fee_cents, cash, equity, gross, held,
           strength, quote_age, signal_age, paused, max_position, max_gross, min_strength,
           drawdown, max_drawdown):
    checks = [
        (not paused, "Paper execution is paused."),
        (side in {"BUY", "SELL"}, "HOLD signals do not create orders."),
        (quantity > 0, "Order has no whole shares to execute."),
        (0 <= quote_age <= 900, "Price is missing, future-dated, or older than 15 minutes."),
        (0 <= signal_age <= 86400, "Signal is future-dated or older than 24 hours."),
        (strength >= min_strength, "Signal strength is below the configured threshold."),
    ]
    if side == "BUY":
        notional = quantity * price_cents
        checks += [(drawdown < max_drawdown, "Portfolio drawdown limit reached."),
                   (notional + fee_cents <= cash, "Insufficient paper cash."),
                   ((held + quantity) * price_cents <= equity * max_position, "Position concentration limit exceeded."),
                   (gross + notional <= equity * max_gross, "Gross exposure limit exceeded.")]
    if side == "SELL":
        checks.append((quantity <= held, "Insufficient shares; short selling is disabled."))
    for passed, reason in checks:
        if not passed:
            return Decision(False, reason)
    return Decision(True, "Approved: freshness, strength, cash, position and exposure checks passed.")
