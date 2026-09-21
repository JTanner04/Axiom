"""Deterministic demo classification; not an investment prediction."""
import re
from app.schemas.news import Analysis, ArticleInput

EVENT_KEYWORDS = (
    ("earnings", ("earnings", "quarterly results")),
    ("guidance", ("guidance", "outlook")),
    ("acquisition", ("acquisition", "merger", "acquire")),
    ("regulation", ("regulation", "regulator")),
    ("lawsuit", ("lawsuit", "litigation")),
    ("product_launch", ("launch", "unveil")),
)


def analyze(article: ArticleInput) -> Analysis:
    text = f"{article.title} {article.body}".lower()
    event_type = next((event for event, words in EVENT_KEYWORDS
                       if any(re.search(r"\b" + re.escape(word) + r"\b", text)
                              for word in words)), "other")
    # Sentiment and probability estimation remain neutral/unavailable until evaluated.
    return Analysis(event_type=event_type, sentiment="neutral")
