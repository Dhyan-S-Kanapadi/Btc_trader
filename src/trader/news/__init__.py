"""Forward-test-only, untrusted BLS schedule ingestion.

Nothing in this package participates in a trading decision.  #26 may consume
only the frozen types exported here.
"""

from trader.news.types import NewsView, SanitizedHeadline

__all__ = ["NewsView", "SanitizedHeadline"]
