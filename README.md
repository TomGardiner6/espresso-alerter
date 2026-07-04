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
4. **Scam sanity check** — listings priced below `scam_median_fraction`
   (default 25%) of the running median, or with no location, are suppressed
   with a log line and never alerted.

Qualifying listings are batched into a single digest message, and
`min_hours_between_messages` (default 3) rate-caps sends globally — held
alerts are persisted and included in the next allowed message.

Every listing ever seen is stored keyed by `(source, listing_id)`, so nothing
is alerted twice.

## Build stages

1. ✅ eBay source + normaliser + SQLite + dry-run printing
2. ⬜ Telegram notifier + rate cap
3. ⬜ Gumtree source (scraper isolated in one module; selectors will break
   when Gumtree changes layout)
4. ✅ Rolling-median bargain logic (built alongside stage 1, verified in stage 4)
5. ⬜ Scheduler (APScheduler loop)
