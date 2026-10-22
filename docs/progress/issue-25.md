# Issue #25: BLS forward-test ingestion

Status: implemented for review. This is **PAPER TRADING ONLY** and has no path to
orders, worker routing, risk, broker, API, dashboard, models, sentiment, or Jev.

Only `https://www.bls.gov/schedule/news_release/bls.ics` is allowlisted. The
poller stores receipt time as `fetched_at` and `available_at`; an ICS schedule
time is nullable metadata and can never expose an item early. The BLS source is
forward-test only: it is not replay data and makes no predictive claim about BTC.

Defaults are operational assumptions: a five-minute poll interval, 10-second
total deadline, two retries, 30-second retry cap, three failure breaker, five
minute breaker cooldown, one MiB response cap, 100 items per poll, 15-minute
coverage staleness, one-day duplicate window, five-minute timestamp skew, and
one-year maximum timestamp age. They need operational review; none is BLS
guidance or a trading parameter.

`trader news poll --once`, `trader news run`, and `trader news show --as-of
<UTC ISO-8601>` require `DATABASE_URL`. Poll and heartbeat logs are JSON and
contain counts and stable error codes, never titles, response bodies, keys, or
credentials. `run` owns a separate PostgreSQL advisory lock and stops after the
current persistence operation when signalled.
