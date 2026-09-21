"""Transparent, deliberately simple baseline and point-in-time feature extraction."""
import math
import re
import statistics

FEATURES = ["sentiment", "importance", "momentum", "volatility", "volume_ratio"]
NAMES = {"AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon",
         "GOOGL": "Alphabet", "META": "Meta", "TSLA": "Tesla", "SPY": "S&P 500 ETF"}
RULES = [("guidance", ["guidance", "outlook"]), ("earnings", ["earnings", "quarterly results"]),
         ("acquisition", ["acquisition", "merger", "acquire"]), ("regulation", ["regulator", "regulation"]),
         ("lawsuit", ["lawsuit", "litigation"]), ("analyst", ["upgrade", "downgrade"]),
         ("product_launch", ["launch", "unveil"]), ("macro", ["inflation", "interest rate"])]
POSITIVE = ["beats", "record revenue", "raises guidance", "upgrade", "surges", "growth", "approval"]
NEGATIVE = ["misses", "cuts guidance", "downgrade", "lawsuit", "decline", "recall", "loss"]


def classify(title, body):
    text = (title + " " + body).lower()
    event = next((kind for kind, words in RULES if any(w in text for w in words)), "other")
    pos = sum(bool(re.search(r"\b" + re.escape(w) + r"\b", text)) for w in POSITIVE)
    neg = sum(bool(re.search(r"\b" + re.escape(w) + r"\b", text)) for w in NEGATIVE)
    sentiment = max(-1, min(1, (pos - neg) / 2))
    return event, sentiment, 0.85 if event in {"earnings", "guidance", "acquisition"} else 0.55


def extract(db, scope, ticker, received, sentiment, importance):
    rows = db.execute("SELECT price,volume FROM bars WHERE scope=? AND ticker=? AND ts<=? ORDER BY ts DESC LIMIT 25",
                      (scope, ticker, received)).fetchall()[::-1]
    prices = [r[0] for r in rows]
    returns = [prices[i] / prices[i-1] - 1 for i in range(1, len(prices))]
    momentum = prices[-1] / prices[0] - 1 if len(prices) > 1 else 0
    volumes = [r[1] for r in rows[:-1]]
    return [sentiment, importance, momentum, statistics.pstdev(returns) if returns else 0,
            rows[-1][1] / statistics.mean(volumes) if volumes and statistics.mean(volumes) else 1]


def predict(features, model=None):
    if model:
        scaled = [(x-m)/s for x,m,s in zip(features, model['mean'], model['scale'])]
        z = model['intercept'] + sum(c*x for c,x in zip(model['coef'], scaled))
        p = 1 / (1 + math.exp(-max(-50, min(50, z))))
        action = "BUY" if p >= .60 else "SELL" if p <= .40 else "HOLD"
        return action, max(p, 1-p), f"Logistic model upward estimate {p:.1%}; uncalibrated research probability."
    sentiment = features[0]
    action = "BUY" if sentiment >= .5 else "SELL" if sentiment <= -.5 else "HOLD"
    strength = min(.90, .45 + abs(sentiment) * .4)
    return action, strength, f"Keyword baseline sentiment {sentiment:+.2f}. Strength is a rule score, not a probability."
