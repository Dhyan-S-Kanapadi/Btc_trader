# News and Jev spike (throwaway)

This directory is isolated research for Issue #24.  It is not imported by
`src/trader`, does not ingest news, and does not call Jev automatically.

## What was run

On 2026-10-21, `fetch_bls_calendar.py` made three unauthenticated requests to
the BLS public iCalendar feed: one received HTTP 403 without a User-Agent and
two succeeded with an identifying tool User-Agent. It selected a small, public
schedule sample and wrote `tests/fixtures/news/bls_calendar_sample.json`. No
account, API key, article body, or user identifier is involved.

No Jev request was made.  The documented Vercel route charges from $0.04 per
million input tokens, so a live test needs an explicitly supplied environment
credential and must wait until the human labels `labeling_sheet.csv`.

## Re-run the one permitted news sample

```powershell
python spikes/news_jev/fetch_bls_calendar.py
```

The script uses `httpx`, already installed by this project.  It sends no
credentials, follows no links, has a 10-second timeout, and saves selected
schedule fields only.  It is not an ingestion service.

## Labeling hand-off

Fill `event_within_4h_label` with `yes`, `no`, or `ambiguous`; fill
`news_tone_label` with a number from -1 (negative) to 1 (positive), or leave it
blank when the headline does not support a tone judgment.  Do not alter IDs,
text, timestamps, or source markers.  Return the completed CSV for the
separate, post-label comparison step.  The test is deliberately not run before
then.

shortcut: The sample script reads a public iCalendar document as text rather than adding an ICS parser; replace it only if #25 needs production ingestion.
