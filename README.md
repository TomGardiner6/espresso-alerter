# Espresso-Gear Bargain Alerter

Periodically sweeps UK secondhand listings (eBay UK via the official Browse
API; Gumtree UK via scraping — stage 3) for specific espresso machines and
grinders, filters aggressively for genuine bargains, and sends a rare Telegram
digest when one appears.

## Setup

```sh
uv sync
cp .env.example .env   # then fill in real credentials
```

Everything is tuned in `config.yaml` (targets, prices, location, sweep
interval, rate cap) — no code changes needed.

## Running

```sh
uv run espresso-alerter --once --dry-run   # one sweep, print what WOULD be sent
uv run espresso-alerter --once             # one sweep, send for real
uv run espresso-alerter                    # scheduled loop (every sweep_interval_minutes)
```

`--verbose` enables debug logging. Logs go to `logs/alerter.log`; state lives
in `alerter.db` (SQLite). Both are gitignored generated data — never commit
them.

## Credentials

### eBay Browse API app token

1. Register at <https://developer.ebay.com> and create an application.
2. Under **Application Keys** (<https://developer.ebay.com/my/keys>), use the
   **Production** keyset: the *App ID (Client ID)* is `EBAY_CLIENT_ID`, the
   *Cert ID (Client Secret)* is `EBAY_CLIENT_SECRET`. Put both in `.env`.
3. The tool mints and refreshes its own OAuth app token (client-credentials
   grant) — you never handle tokens by hand.

### Telegram bot

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, follow the
   prompts. The token it gives you is `TELEGRAM_BOT_TOKEN`.
2. Find your chat ID: message [@userinfobot](https://t.me/userinfobot), or
   send your new bot any message then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and read
   `message.chat.id`. That's `TELEGRAM_CHAT_ID`.

**Never commit secrets.** `.env` is gitignored; `.env.example` documents the
required keys with dummy values. If a real token is ever committed by
accident, revoke and regenerate it immediately — deleting the file does not
remove it from git history.

## How the bargain gate works

A listing only becomes an alert if **all** of these hold:

1. **Title match** — the title contains one of the target's keywords, and no
   exclusion phrase (`spares`, `broken`, `not working`, `descaler`, …; see
   `exclude_keywords` in `config.yaml`). This keeps parts/accessory listings
   out.
2. **Strict price** — price ≤ the target's `bargain_price` (not merely
   `max_price`).
3. **Below recent median** — price is under the rolling median of the last
   `history_window` (default 20) genuine sightings of that target across all
   sources. With fewer sightings than that, `bargain_price` alone decides and
   the alert notes "insufficient history".
4. **Scam/accessory sanity check** — listings priced below the target's
   `min_price` floor (a £3 "Barista Express storage accessory" is not a
   Barista Express), below `scam_median_fraction` (default 25%) of the
   running median, or with no location, are suppressed with a log line and
   never alerted.

Qualifying listings are batched into a single digest message, and
`min_hours_between_messages` (default 3) rate-caps sends globally — held
alerts are persisted in SQLite (`pending_alerts`) and included in the next
allowed message, surviving restarts, notifier outages, and dry runs.
`--dry-run` still records listings as seen and queues qualifiers as pending
(so nothing is lost), but sends nothing and never starts the rate-cap clock.

Every listing ever seen is stored keyed by `(source, listing_id)`, so nothing
is alerted twice.

## Gumtree scraping notes

Gumtree has no API, so `sources/gumtree.py` scrapes the public search pages.
Two failure modes to know about (both isolated to that one module, and a
Gumtree outage never blocks the eBay sweep):

- **Markup changes** break the selectors. The module docstring documents the
  update procedure; the selectors target Gumtree's own `data-q` test hooks,
  which are far more stable than its auto-generated CSS classes.
- **Bot protection** (Radware). Burst traffic gets served a JavaScript
  challenge (HTTP 247) instead of results. The scraper paces requests ~10s
  apart, detects the challenge page, and backs off for 30 minutes rather
  than hammering. Expect occasionally intermittent Gumtree coverage — eBay
  is the reliable backbone.

## Future additions (not yet implemented)

- **LLM deal verification before alerting** — once a listing passes the
  bargain gate, hand its details *and photos* to a multimodal LLM to judge
  whether it's genuinely a good deal (condition from the pictures, stock-photo
  scams, wrong/incomplete model, missing accessories) before it reaches
  Telegram. Candidate: Gemini Pro (API key already available). Would slot in
  as a post-gate/pre-notify step in the pipeline, with the key loaded from
  `.env` (e.g. `GEMINI_API_KEY`) like the other credentials. The LLM should
  also tag the **model variant** (e.g. pre-2015 Gaggia Classic vs Classic
  Pro), enabling per-variant price history — variants sell at very different
  prices, so one blended median is muddier than it should be.
- **Observe-then-pounce thresholding (optimal stopping)** — with a whole
  summer to shop, treat it like the secretary problem: spend the first ~2–3
  weeks in observation mode (build price history, alert only on screaming
  outliers), then alert on anything better than the best price seen during
  observation, relaxing the threshold as September approaches so the summer
  never ends empty-handed. Percentile-based gating (bottom X% of history)
  instead of a fixed `bargain_price`.
- **Price-drop re-evaluation** — dedupe currently ignores a listing forever
  once seen, but sellers cut prices; re-check seen listings whose price has
  dropped materially (>10%) and let them re-enter the gate at the new price.
- **Shipping-inclusive pricing** — the Browse API returns shipping options;
  gate on effective price (item + postage) since £85 + £15 P&P is worse than
  £95 collected locally.
- **Seller-trust signals** — eBay returns seller feedback score/percentage;
  a zero-feedback seller with a great price is a scam tell that should feed
  the suppression logic.
- **Weekly market report** — one scheduled Sunday message with per-target
  medians, sighting counts, and near-misses: proves the alerter is alive
  (rare alerts are indistinguishable from a broken cron otherwise) and helps
  recalibrate `config.yaml` prices as the market moves.
- **Vinted as a source** — there's prior art in `Programming Projects/`
  (`Vinted_Scraper`); Vinted has espresso gear listed and an unofficial but
  well-understood API surface.

## Build stages

1. ✅ eBay source + normaliser + SQLite + dry-run printing
2. ✅ Telegram notifier + rate cap (persistent pending queue)
3. ✅ Gumtree source (scraper isolated in one module; selectors will break
   when Gumtree changes layout)
4. ✅ Rolling-median bargain logic (built alongside stage 1, verified in stage 4)
5. ⬜ Scheduler (APScheduler loop)
