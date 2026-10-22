# 0002. News sources and Jev access spike

- **Status:** proposed; stop after labeling hand-off
- **Date read:** 2026-10-21
- **Scope:** Issue #24 only. PAPER TRADING ONLY; no worker, trading, risk,
  snapshot, schema, or ingestion changes.

## Decision

**Defer Jev from v1.** Use the official BLS calendar only as a narrow,
forward-test event-schedule candidate after #25 adds a guarded ingestion design;
there is **no approved news source for historical replay**. Therefore Account C
is defined but disabled and is **forward-test only**. Its Jev snapshot fields
remain null; no price-prediction test was done (that belongs to #26/#29).

## Evidence convention

Every source below was read on 2026-10-21. **VERIFIED** means the linked
publisher documentation or a small live BLS request supports the statement.
**UNVERIFIED** means the source did not publish enough contractual or technical
detail for this spike. “Publication timestamp” is not an observation-time
timestamp: replay needs an independently retained `fetched_at` or provider
availability time as well.

## A. Candidate sources

| Candidate | Free tier / rate limit | Licence, storage and public display | Format / latency | History and as-of reliability | Verdict |
| --- | --- | --- | --- | --- | --- |
| **BLS release calendar and RSS** ([calendar](https://www.bls.gov/schedule/news_release/), [terms](https://www.bls.gov/developers/termsOfService.htm)) | **VERIFIED:** public; BLS may limit abusive API use. No numeric calendar rate stated. | **VERIFIED:** BLS says retrieved data have no end-use controls, requires attribution/disclaimer, and prohibits false representation. Schedule headlines/metadata may be stored and displayed with attribution; do not use logo. | **VERIFIED:** HTML, ICS and RSS. Calendar gives scheduled ET times; live ICS sample retrieved. Latency to publication is not stated. | **VERIFIED:** prior-year calendar pages exist, but **UNVERIFIED** whether an old calendar reflects what was known on that date. Current ICS `DTSTART` had no zone; the HTML says ET. Backfills/revisions are a look-ahead trap. | **Forward-test candidate only** for scheduled US releases; not a crypto headline feed and not replay-safe. |
| **Federal Reserve RSS / FOMC calendar** ([RSS](https://www.federalreserve.gov/feeds/feeds.htm), [policy calendar](https://www.federalreserve.gov/monetarypolicy.htm)) | **VERIFIED:** public RSS; numeric rate limit not published. | **UNVERIFIED:** RSS page documents subscription/display but no explicit licence for retaining headlines in a public dashboard. Ask counsel/source owner before public storage/display. | **VERIFIED:** RSS XML has headline/summary links; calendar lists upcoming and recent FOMC documents. Latency not stated. | **UNVERIFIED:** no published observation-time history or immutable revision trail found. RSS may update; publication dates alone do not prove availability. | **Reject for now:** authoritative event discovery, but public-display and replay terms/as-of evidence are insufficient. |
| **NewsAPI** ([pricing](https://newsapi.org/pricing), [terms](https://newsapi.org/terms), [cache docs](https://newsapi.org/docs/caching)) | **VERIFIED:** Developer is $0, 100 requests/day, 24-hour delay, one-month search. | **VERIFIED:** Developer use is development/testing only, not staging or production (even internal). It cannot support this dashboard. | **VERIFIED:** JSON article metadata; its own response cache is five minutes. Developer data is delayed 24 hours. | **VERIFIED:** one month only on free tier; `publishedAt` is not provider availability. Caching and source edits make replay unsafe. | **Reject.** |
| **GDELT 2.0 / DOC API** ([data page](https://www.gdeltproject.org/data.html), [DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)) | **VERIFIED:** public data/API; numeric limit and commercial terms were not located. | **UNVERIFIED:** no clear licence was found permitting a public dashboard to retain/show third-party headline text. Store URLs/derived flags only until clarified. | **VERIFIED:** JSON/JSONP; GDELT says 2.0 updates every 15 minutes. | **VERIFIED:** event data is historical and DOC searches a rolling three-month window; **UNVERIFIED** that any timestamp is first availability. Later collection, translation, tag/tone enrichment and corrected records can leak future information. | **Reject for replay and v1 dashboard pending rights/as-of contract.** |
| **CryptoPanic API** ([site](https://cryptopanic.com/developers/api/)) | **UNVERIFIED:** an API/developer page exists, but current free quota/rate/price could not be verified without a credentialed account. | **UNVERIFIED:** no reviewed terms established whether stored/displayed headline text is allowed. | **UNVERIFIED:** expected JSON metadata but exact documented fields/latency were not verified. | **UNVERIFIED:** no evidence of an immutable first-seen time or replay-grade archive. | **Reject; do not sign up or call.** |
| **CoinDesk RSS** ([RSS landing page](https://www.coindesk.com/arc/outboundfeeds/rss/), [terms](https://www.coindesk.com/terms-of-use/)) | **UNVERIFIED:** no official numeric limit found. | **UNVERIFIED:** headline/article rights for storage and public display were not established in this spike; do not store text. | **UNVERIFIED:** RSS exists, but current field contract and latency were not verified. | **UNVERIFIED:** no documented immutable availability archive; edited headlines and feeds can backfill. | **Reject.** |

### Live source sample

**VERIFIED:** `spikes/news_jev/fetch_bls_calendar.py` made three small public
requests on 2026-10-21 (one 403 without a User-Agent, two successful), and
saved five scrubbed schedule records at
`tests/fixtures/news/bls_calendar_sample.json`. It retains only a scheduled
time and headline, with retrieval time and source URL. The returned ICS values
have no timezone marker, so the fixture must not be replayed as UTC. BLS's web
calendar explicitly labels its scheduled times Eastern Time. No other candidate
passed the rights and as-of gates, so none was fetched.

### Replay conclusion and traps

No candidate demonstrated a trustworthy first-availability timestamp, an
immutable revision history, and clear rights for the intended public display.
Consequently the answer is **no news source for historical replay**. Account C
must be forward-test only. A future forward collector must store a UTC
`fetched_at`, raw-source identifier/URL, provider publication time and its
declared zone, content hash, and revision/supersession state before it lets an
item influence a snapshot. It must reject naïve time values. Never infer
availability from a later archive: old feeds can be backfilled, headlines can
be edited, zones omitted/local, and sentiment/tags added retroactively.

## B. Jev access and contract

### Route, auth, price and data handling

**VERIFIED:** Vercel's Jev model page lists `typesafe-ai/jev` (and versioned
`typesafe-ai/jev-1.14.0`), a 32K context, and $0.04 per one million input
tokens. Its integration guide documents an HTTP route through Vercel AI Gateway
at `POST https://ai-gateway.vercel.sh/v1/evaluate`, authenticated with an AI
Gateway API key or Vercel OIDC token; it also documents a TypeSafe-compatible
base path and an OpenAI-compatible decisions route. This is the simplest
documented gateway route for a small Python worker, but it still requires a
secret supplied only via a local ignored environment variable.

**Update, 2026-10-22:** The operator explicitly accepted the TypeSafe/Vercel terms for this narrow
purpose: sending sanitized, bounded BLS schedule headlines to Vercel AI Gateway. Issue #26 may use
the pinned Gateway route with an environment-only key. This changes neither the BLS-only forward-test
limit nor the requirement to keep Jev a typed snapshot sensor; it does not approve raw headlines,
article bodies, credentials, replay use, or any predictive claim.

**UNVERIFIED:** direct `api.typesafe.ai/v1/systemone`, Cloudflare Workers AI,
OpenRouter, Netlify, current gateway rate limits, regions, retention/training,
zero-data-retention, provider subprocessor path, timeout/error envelope, and
whether each gateway offers Jev today. The Vercel model page says use is subject
to TypeSafe terms/privacy but does not establish the required data-handling
guarantees. Do not send headline content there until those are contractually
acceptable.

No paid sign-up or Jev call was made. The checked-in
`tests/fixtures/jev/not_called.json` is explicitly status metadata, **not** a
fake model response.

### Schema needed by this design

**VERIFIED at documentation level:** Vercel documents a shared text `state`
and questions keyed by ID, with Boolean questions returning a `probability`;
it says Jev returns typed Choice, Score, and Boolean answers with probabilities.
The requested two-question shape is therefore:

```json
{
  "model": "typesafe-ai/jev-1.14.0",
  "state": "<guarded, timestamped headlines and calendar facts>",
  "questions": {
    "major_event_within_4h": {
      "type": "boolean",
      "instructions": "Is a major event scheduled or reported within four hours of the as-of time?"
    },
    "news_tone": {
      "type": "score",
      "instructions": "Score BTC-relevant tone from -1 to 1."
    }
  }
}
```

**UNVERIFIED:** the exact HTTP JSON request/response field names for `score`,
the score range/enforcement, Boolean response envelope, error bodies, retryable
status codes, timeout behavior, and whether identical calls are deterministic.
The prompt supplied an earlier `api.typesafe.ai/v1/systemone` claim; this spike
did not confirm it. The only honest “real example” before labels and a credential
is the documented Boolean example linked above, not a fabricated response.

The required three identical live calls were **not made**: they would incur
usage and need a credential, and the evaluation may not run before labels
return. Thus latency is **not measured** (sample size 0), determinism is
**UNVERIFIED**, and model-output fixture count is zero.

### Cost estimate

At the documented $0.04/M input tokens, cost is `$0.00000004 × input_tokens`.
With one shared call per hourly cycle, no output-token charge stated by the
model page, and no gateway/platform fee assumed:

| Case | Assumption | Calls/month | Input tokens/call | Estimated Jev model cost/month |
| --- | --- | ---: | ---: | ---: |
| Low | 1 shared call every 4 hours | 180 | 500 | $0.0036 |
| Expected | 1 shared hourly call | 720 | 1,000 | $0.0288 |
| High | 1 call per candidate, 10 candidates/hour | 7,200 | 2,000 | $0.5760 |

**UNVERIFIED:** gateway credits, taxes, minimums, output charges, retries,
fallback charges, and current price/rate limits. Choose the shared-state call,
not per-candidate calls, only after #25 proves the state has a single strict
as-of timestamp; otherwise abstain.

### Limits and hostile input

**VERIFIED:** Vercel describes Jev as typed decisions rather than generated
text, and its model page says it returns typed choices/scores/Boolean
probabilities. **UNVERIFIED:** vendor documentation reviewed here does not
promise input-injection resistance, tool isolation, a reasoning trace, model
architecture, training corpus, determinism, or market-data calibration. Typed
output restricts a hostile headline to influencing the fixed Boolean/score; it
cannot directly select a tool, set risk/sizing, execute a trade, or write state
when Jev remains a sensor. It can still bias those fields, so #25 must enforce
length/source/age/charset controls, delimiter/role neutralization, provenance,
dedupe, UTC as-of filtering, a fixed question template, null-on-error/low
confidence, and audit hashes. Do not treat vendor speed/cost claims as market
performance evidence.

## C. Human-label test status

`spikes/news_jev/labeling_sheet.csv` has 20 items: five real BLS schedule
headlines with real timestamps, and fifteen explicitly marked synthetic cases
covering clear events, non-events, ambiguous/stale items, mixed tone prompts,
and injection-style text. No labels were filled by this spike; no Jev run was
performed. The human should fill only `event_within_4h_label` (`yes`, `no`, or
`ambiguous`) and `news_tone_label` (`-1` through `1`, blank if unsupported).

After labels return, a separate continuation may call Jev, compare event
agreement and false positives/negatives, calculate tone rank/correlation where
labels support it, and check calibration if probabilities are actually returned.
Twenty items are far too few to establish accuracy; they only detect gross
failure. This spike does **not** test whether news or Jev predicts BTC returns.

## D. Verdicts and backlog edits (do not apply here)

- **Jev in v1:** **defer** — credentialed, paid live validation and data terms
  remain unverified; keep nullable Jev fields and Account C disabled.
- **News for forward test:** **conditional BLS schedule only** — no general
  BTC-news feed is approved; build only after rights/as-of guardrails exist.
- **News for replay:** **no**.
- **Account C forward-test only:** **yes**.

## E. Controlled forward-test update (2026-10-22)

The operator accepted the narrow TypeSafe/Vercel data-sharing route recorded above and
Issue #26 provides the bounded sensor implementation. Account C may therefore be
configured as an `agent_veto` **forward-test-only** variant after Issue #27, but only
when the global agent and Jev switches, C's account agent and Jev switches, and the
environment-only Jev configuration are all enabled. The defaults remain off. This
supersedes the earlier operational instruction to leave C on `skip_all`; it does not
supersede the no-historical-replay verdict. C's replay evidence remains null with
`coverage_not_ok`, and neither BLS schedules nor Jev output make a BTC prediction.

Suggested backlog edits for review, not applied:

1. **#25:** Define a BLS-only schedule adapter first; capture UTC receipt time,
   source URL, source time plus zone, content hash and revision state; reject
   naïve times and unlicensed third-party headline storage.
2. **#26:** Keep Jev disabled by default; require a reviewed data-processing
   route, environment-only key, fixed typed contract, timeout/error-to-null,
   output validation, audit hashes, injection test corpus and human labels.
3. **#27:** Treat absent Jev fields as unavailable evidence, never a default
   vote; agent remains a veto only and cannot change risk/execution.
4. **#29:** Do not claim replay for Account C; any forward comparison needs
   prospectively captured source availability and an explicit no-look-ahead
   protocol.
5. **#37 README claims:** say “BLS schedule event research is conditional and
   forward-test only; Jev is deferred,” not that Jev/news improves returns or
   that historical news replay exists.

## Sources read

All accessed 2026-10-21: [BLS calendar](https://www.bls.gov/schedule/news_release/),
[BLS terms](https://www.bls.gov/developers/termsOfService.htm),
[Federal Reserve RSS](https://www.federalreserve.gov/feeds/feeds.htm),
[Federal Reserve policy calendar](https://www.federalreserve.gov/monetarypolicy.htm),
[NewsAPI pricing](https://newsapi.org/pricing), [NewsAPI terms](https://newsapi.org/terms),
[GDELT data](https://www.gdeltproject.org/data.html), [CryptoPanic API](https://cryptopanic.com/developers/api/),
[CoinDesk RSS](https://www.coindesk.com/arc/outboundfeeds/rss/),
[CoinDesk terms](https://www.coindesk.com/terms-of-use/),
[Vercel Jev model](https://vercel.com/ai-gateway/models/jev), and
[Vercel Jev integrations](https://vercel.com/i/jev-integrations).
