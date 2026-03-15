# Smart Money Agent — User Guide

> Personal reference guide covering setup, operation, signal interpretation, API, and architecture.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites](#2-prerequisites)
3. [Installation & Setup](#3-installation--setup)
4. [Environment Configuration](#4-environment-configuration)
5. [Running the App](#5-running-the-app)
6. [Mock Mode vs Live Mode](#6-mock-mode-vs-live-mode)
7. [Switching LLM Providers](#7-switching-llm-providers)
8. [How to Interpret Signals](#8-how-to-interpret-signals)
9. [The 6 Skills Explained](#9-the-6-skills-explained)
10. [Console Log Reference](#10-console-log-reference)
11. [API Reference](#11-api-reference)
12. [Network Sharing](#12-network-sharing)
13. [File Structure Reference](#13-file-structure-reference)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Project Overview

Smart Money Agent detects institutional investor activity for a given stock ticker by correlating six data sources:

- **Options flow** — unusual options sweeps (yfinance)
- **Social buzz** — Reddit, StockTwits, Finviz, Yahoo Finance news, X/Twitter (Playwright)
- **Insider tracker** — SEC EDGAR 13F institutional filings + Form 4 insider transactions
- **Price action** — Smart Money Concepts: Order Blocks, Fair Value Gaps, AMD phase, flow/price divergence (Twelve Data)
- **Institutional positioning** — short interest, put/call ratio, holder changes → crowding score
- **Dark pool activity** — volume absorption, block trade score, vol/price divergence (yfinance OHLCV)

An LLM orchestrator (Claude / OpenAI / Gemini) calls these tools, writes a hypothesis after each result, and outputs a plain-English verdict.

**Core thesis:** Institutions move first — dark pool accumulation and options sweeps appear before SEC filings, and filings appear before retail attention. The system finds the gap.

---

## 2. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.13 | 3.14 not supported (PyO3/pydantic-core issue) |
| Node.js | 18+ | For the React frontend |
| npm | 9+ | Comes with Node |

---

## 3. Installation & Setup

### Backend

```bash
cd "/path/to/Dev"

# Create virtual environment (Python 3.13)
python3.13 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Install Playwright browser (for X scraper)
playwright install chromium

# Copy and fill in environment variables
cp backend/.env.example backend/.env
```

### Frontend

```bash
cd frontend
npm install
```

---

## 4. Environment Configuration

### `backend/.env`

Copy from `backend/.env.example` and fill in your keys:

```env
# ── LLM Provider ───────────────────────────────────────────────
LLM_PROVIDER=claude              # claude | openai | gemini

# ── LLM API Keys (only the chosen provider needs a real key) ───
ANTHROPIC_API_KEY=sk-ant-...     # console.anthropic.com
OPENAI_API_KEY=sk-...            # platform.openai.com
GEMINI_API_KEY=...               # aistudio.google.com

# ── Data APIs ──────────────────────────────────────────────────
TWELVE_DATA_API_KEY=...          # twelvedata.com — free, 800 calls/day

# ── X (Twitter) — Playwright + cookie injection ────────────────
# No username/password needed. Get cookies from:
# Browser DevTools → Application → Cookies → https://x.com
X_AUTH_TOKEN=                    # auth_token cookie value (required)
X_CT0=                           # ct0 cookie value (required)
X_GUEST_ID=                      # guest_id cookie (optional, helps avoid login redirect)

# ── Dev ────────────────────────────────────────────────────────
MOCK_MODE=false                  # true = use fixture files, skip real API calls
API_KEY=your_secret_key          # protects /analyze endpoint (optional)
```

> **Note:** `POLYGON_API_KEY` and `REDDIT_USER_AGENT` are no longer needed. Options data now comes from yfinance. Reddit uses the public JSON API with no credentials.

> **Note:** `X_USERNAME`, `X_PASSWORD`, `X_EMAIL` are removed. X scraping now uses Playwright with cookie injection instead of twscrape — no account lockout risk.

### How to get X cookies

1. Open [x.com](https://x.com) in Chrome and log in
2. Open DevTools (`F12`) → **Application** tab → **Cookies** → `https://x.com`
3. Copy the value of `auth_token` → paste into `X_AUTH_TOKEN`
4. Copy the value of `ct0` → paste into `X_CT0`
5. Optionally copy `guest_id` → paste into `X_GUEST_ID`

Cookies expire periodically. If X scraper returns 0 posts, refresh the cookies.

### `frontend/.env`

```env
VITE_BACKEND_URL=http://YOUR_LOCAL_IP:8000
VITE_API_KEY=your_secret_key     # must match backend API_KEY
```

Find your local IP: `ipconfig getifaddr en0`

---

## 5. Running the App

### Start the backend

```bash
cd backend

# Local only
../.venv/bin/uvicorn main:app --port 8000 --reload

# Exposed to local network (for sharing with others on same WiFi)
../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Start the frontend

```bash
cd frontend
npm run dev
```

`host: true` is already set in `vite.config.ts` — the frontend is accessible on the network automatically.

### Access

| Interface | URL |
|---|---|
| Frontend UI | `http://localhost:5173` |
| Backend API | `http://localhost:8000` |
| Health check | `http://localhost:8000/health` |
| Network (others on same WiFi) | `http://{YOUR_IP}:5173` |

---

## 6. Mock Mode vs Live Mode

| | Mock Mode (`MOCK_MODE=true`) | Live Mode (`MOCK_MODE=false`) |
|---|---|---|
| Data source | `backend/fixtures/{ticker}.json` | Real APIs |
| LLM | Still runs live | Runs live |
| API keys needed | Only LLM key | Twelve Data + LLM |
| Supported tickers | NVDA, TSLA, AAPL only | Any ticker |
| Speed | Fast (~5s) | 20–40 seconds |

### Mock fixtures

| Ticker | Signal | What it tests |
|---|---|---|
| `NVDA` | Accumulation (high conviction) | All 6 skills fire, crowd unaware |
| `TSLA` | Distribution (medium conviction) | Bearish options + institutional selling |
| `AAPL` | Noise | Conflicting signals, low conviction |

---

## 7. Switching LLM Providers

Change one line in `backend/.env`:

```env
LLM_PROVIDER=claude    # Sonnet 4 orchestrator + Haiku sub-agent
LLM_PROVIDER=openai    # gpt-4o orchestrator + gpt-4o-mini sub-agent
LLM_PROVIDER=gemini    # gemini-2.0-flash for both
```

Restart the backend. No other changes needed.

### Model mapping

| Role | Claude | OpenAI | Gemini |
|---|---|---|---|
| Orchestrator | claude-sonnet-4-20250514 | gpt-4o | gemini-2.0-flash |
| Social sub-agent | claude-haiku-4-5-20251001 | gpt-4o-mini | gemini-2.0-flash |

The sub-agent interprets raw Reddit/StockTwits/X/YF data into a structured signal before the orchestrator sees it.

---

## 8. How to Interpret Signals

### Signal types

| Signal | Meaning |
|---|---|
| `accumulation` | Institutions quietly building long exposure across multiple layers |
| `distribution` | Institutions reducing or exiting positions |
| `hedge` | Bearish options but 13F shows accumulation — protecting longs, not exiting |
| `noise` | Signals contradict without a coherent explanation, or data too thin |

### Conviction levels

| Conviction | Condition |
|---|---|
| `high` | 4+ signals agree AND `crowded=false` AND `crowd_aware=false` |
| `medium` | 2–3 signals agree OR `crowded=true` (hard cap) OR crowd already aware |
| `low` | Signals conflict, or only 1 signal, or insufficient data |

> **Hard rule:** `institutional_positioning.crowded=true` caps conviction at `medium` regardless of how many other signals agree. An overcrowded trade is a late trade.

### The core signal — silent accumulation window

```
price_action.trend          = "downtrend"    ← price falling (retail selling)
dark_pool.vol_price_div     = true           ← volume rising while price falls
options_flow.unusual        = true           ← directional bet placed
options_flow.sentiment_lean = "bullish"      ← someone expects up
insider_tracker.direction   = "accumulating" ← confirmed in 13F filings
social_buzz.crowd_aware     = false          ← retail hasn't noticed yet
institutional.crowded       = false          ← we are early, not late
─────────────────────────────────────────────────────────────────────
VERDICT: signal_type=accumulation, conviction=HIGH
```

---

## 9. The 6 Skills Explained

### Skill 1 — Options Flow (`options_flow_scanner`)

**Source:** yfinance
**What it does:** Fetches option chains for the nearest 3 expiry dates. Flags contracts with vol/OI > 1.5 and volume > 100 as unusual. Computes total unusual premium and sentiment lean.

**Key outputs:** `unusual`, `sentiment_lean`, `sweep_detected`, `total_unusual_premium`, `top_contracts`

**Note:** `unusual=false` no longer stops the pipeline. The agent continues — institutions often build via dark pools without touching options.

---

### Skill 2 — Social Buzz (`social_buzz_scanner`)

**Sources:** Reddit (public JSON), StockTwits (curl_cffi Chrome impersonation), Finviz (scrape), Yahoo Finance news (yfinance), X/Twitter (Playwright)

**What it does:** Collects raw social metrics from all 5 sources, then passes them to a cheap LLM sub-agent that interprets them into a structured signal.

**Key outputs:** `crowd_aware`, `informed_vs_hype`, `interpretation`, raw metrics per source

**X scraper:** Uses Playwright to launch a headless Chromium browser with your session cookies injected. Scrapes up to 30 posts, scores bullish/bearish sentiment. Returns empty if `X_AUTH_TOKEN` / `X_CT0` are not set — other sources still work.

---

### Skill 3 — Insider Tracker (`insider_tracker`)

**Source:** SEC EDGAR (no API key needed)
**What it does:** Looks up the company CIK, fetches Form 4 filings for insider buys (last 90 days), searches EFTS for recent 13F-HR institutional filings.

**Key outputs:** `net_institutional_direction`, `recent_13f_changes`, `insider_buys`, `notable_funds`

**Known limitation:** `shares_delta` is always 0 — EDGAR archive XML rate-limits aggressively. Fund names and filing recency are the real signal.

---

### Skill 4 — Price Action (`price_action_context`)

**Source:** Twelve Data
**What it does:** Fetches 60 days of daily OHLCV and computes Smart Money Concepts (SMC) primitives.

| Concept | What it detects |
|---|---|
| **Order Block** | Last opposite-colour candle before a Break of Structure — institutional entry level |
| **Fair Value Gap** | 3-candle price gap — price imbalances that statistically fill ~70% of the time |
| **AMD Phase** | Accumulation / Manipulation / Distribution — which stage of the institutional cycle |
| **Flow/Price Divergence** | Volume slope rising + price slope falling — silent accumulation signature |

**Key outputs:** `trend`, `volume_ratio`, `pct_from_52w_high`, `order_block`, `fvg`, `amd_phase`, `flow_price_divergence`

---

### Skill 5 — Institutional Positioning (`institutional_positioning`)

**Source:** yfinance
**What it does:** Computes a crowding score (0–100) from three inputs.

| Input | High reading means |
|---|---|
| `short_pct_float` | >8% = significant short crowding |
| `institutional_bias` | Top 10 holder pctChange direction — distributing or accumulating |
| `pc_ratio` | Full-chain put/call OI across 5 expirations — >1.2 = heavy hedging |

`crowded=true` (score > 70) → `conviction_modifier=downgrade` — this is a hard cap regardless of other signals.

**Key outputs:** `short_pct_float`, `short_covering`, `institutional_bias`, `pc_ratio`, `crowding_score`, `crowded`, `conviction_modifier`

---

### Skill 6 — Dark Pool Activity (`dark_pool_activity`)

**Source:** yfinance OHLCV
**What it does:** Infers off-exchange block activity from behavioral signatures — FINRA TRF files are behind Cloudflare and inaccessible directly.

| Method | Signal |
|---|---|
| **Volume Absorption** | vol > 1.5x avg AND range < 60% of stock's own avg range = institution absorbing supply |
| **Block Trade Score** | 10-day rolling score — high vol + small price impact = probable block print |
| **Vol/Price Divergence** | Volume slope positive + price slope negative = silent accumulation |
| **ATM Options Spread** | Tight spread = market makers providing institutional liquidity |

**Key outputs:** `absorption_detected`, `block_trade_score`, `vol_price_divergence`, `estimated_direction`, `high_dark_pool_activity`

---

## 10. Console Log Reference

```
════════════════════════════════════════════════════════════
  Smart Money Agent  |  ticker=NVDA  |  llm=claude
════════════════════════════════════════════════════════════
[HH:MM:SS]  ▶  Calling skill: {name}        ← LLM requested this tool
[HH:MM:SS]     🌐 Fetching from {source}    ← data being pulled
[HH:MM:SS]     ✔  {label}: {value}          ← key data point
[HH:MM:SS]     ⚠  {message}                 ← warning (non-fatal)
[HH:MM:SS]  ◀  [{tool}] {summary}           ← skill finished
[HH:MM:SS]  🧠 Hypothesis so far: ...       ← LLM reasoning after each skill
────────────────────────────────────────────────────────────
════════════════════════════════════════════════════════════
  VERDICT
  Signal type : ACCUMULATION
  Conviction  : HIGH
  Explanation : ...
════════════════════════════════════════════════════════════
```

The LLM writes a hypothesis after **every** tool result — the call order adapts based on what it finds.

---

## 11. API Reference

### `GET /health`

```json
{ "status": "ok", "llm_provider": "claude", "mock_mode": "false" }
```

### `GET /analyze?ticker={TICKER}&api_key={KEY}`

Streams SSE. `api_key` required if `API_KEY` is set in `.env`.

```
event: tool_call     data: {"tool": "options_flow_scanner", "ticker": "NVDA", "status": "calling"}
event: tool_result   data: {"tool": "options_flow_scanner", "result": {...}, "status": "complete"}
event: reasoning     data: {"text": "Hypothesis so far: ..."}
event: verdict       data: {"signal_type": "accumulation", "conviction": "high", "explanation": "...", ...}
event: error         data: {"message": "..."}
event: done          data: {}
```

### `GET /logs`

Streams backend terminal logs in real time (used by the Terminal tab in the UI).

---

## 12. Network Sharing

Backend and frontend are both configured for network access by default:

- `vite.config.ts` has `host: true`
- Run backend with `--host 0.0.0.0`

Others on the same WiFi connect to `http://{YOUR_IP}:5173`.

Find your IP: `ipconfig getifaddr en0`

---

## 13. File Structure Reference

```
Dev/
├── USER_GUIDE.md
├── CLAUDE.md                      ← project context for Claude Code
├── AGENT_LOGIC.md                 ← why the AI reasons the way it does
├── .gitignore                     ← protects .env files from being committed
├── railway.toml                   ← Railway deployment config
├── backend/
│   ├── main.py                    ← FastAPI app, /health + /analyze + /logs SSE
│   ├── agent.py                   ← async agent loop, streams events
│   ├── prompts.py                 ← orchestrator + social sub-agent prompts
│   ├── tools.py                   ← 6 tool schemas (Claude format)
│   ├── logger.py                  ← structured terminal logger
│   ├── requirements.txt
│   ├── .env                       ← your secrets (git-ignored)
│   ├── .env.example               ← template (safe to commit)
│   ├── x_scraper.py               ← standalone Playwright scraper (CLI tool)
│   ├── llm/
│   │   ├── __init__.py            ← get_llm() factory
│   │   ├── base.py                ← abstract interface
│   │   ├── claude.py              ← Anthropic adapter
│   │   ├── openai.py              ← OpenAI adapter
│   │   └── gemini.py              ← Gemini adapter
│   ├── skills/
│   │   ├── __init__.py            ← execute_skill() dispatcher
│   │   ├── options_flow.py        ← Skill 1: yfinance options chain
│   │   ├── social_buzz.py         ← Skill 2: Reddit + StockTwits + Finviz + YF + X
│   │   ├── insider_tracker.py     ← Skill 3: SEC EDGAR Form 4 + 13F
│   │   ├── price_action.py        ← Skill 4: Twelve Data + SMC primitives
│   │   ├── institutional_positioning.py  ← Skill 5: short interest + P/C + crowding
│   │   ├── dark_pool.py           ← Skill 6: volume absorption + block score
│   │   └── x_scraper.py           ← Playwright X scraper (used by social_buzz)
│   └── fixtures/
│       ├── nvda.json
│       ├── tsla.json
│       └── aapl.json
└── frontend/
    ├── index.html
    ├── src/
    │   ├── App.tsx
    │   ├── types.ts
    │   ├── hooks/
    │   │   └── useAgentStream.ts
    │   └── components/
    │       ├── SkillStep.tsx
    │       ├── ReasoningStream.tsx
    │       ├── VerdictCard.tsx
    │       └── Terminal.tsx
    ├── .env                       ← VITE_BACKEND_URL + VITE_API_KEY (git-ignored)
    └── vite.config.ts
```

---

## 14. Troubleshooting

### `pydantic-core` build fails on install
Use Python 3.13, not 3.14.
```bash
python3.13 -m venv .venv
```

### `Address already in use` on port 8000
```bash
pkill -f "uvicorn main:app"
```

### X scraper returns 0 posts
- `X_AUTH_TOKEN` and `X_CT0` are not set in `.env`, or the cookies have expired
- Re-copy cookies from DevTools → Application → Cookies → `https://x.com`
- Other social sources (Reddit, StockTwits, Finviz, YF) still work without X

### X scraper times out
- Cookies are valid but Playwright is slow to launch — increase `_TIMEOUT` in `skills/x_scraper.py`
- On a server: run `playwright install-deps chromium` to install system dependencies

### All 6 skills always run (pipeline never stops early)
This is correct behaviour. `options_flow.unusual=false` no longer vetoes the pipeline — institutions can accumulate via dark pools without unusual options activity.

### `conviction` is always `medium` even with many agreeing signals
Check `institutional_positioning.crowded` in the logs. If `crowded=true` (score > 70), conviction is hard-capped at `medium` by design — an overcrowded trade is a late trade.

### Dark pool absorption always 0
The thresholds are ATR-relative (60% of the stock's own average daily range). Check the log line `Avg daily range (ATR proxy): X.XX%` — if the stock is highly volatile, absorption events require a day with range below 60% of that average.

### EDGAR `insider_buys` always empty
Only outright open-market purchases (Form 4 code "A") are shown. Grants, option exercises, and disposals are filtered out. Most large-cap insiders don't buy in the open market frequently.

### `503` errors on EDGAR
EDGAR rate-limits archive XML requests. `shares_delta` stays 0. Fund names and filing dates still return via EFTS search.

### Twelve Data returns no values
Free tier: 800 calls/day. Check usage at `twelvedata.com`. The skill returns a neutral fallback and the agent continues.

### Frontend shows "Connection lost"
Backend is not running, or `VITE_BACKEND_URL` points to the wrong IP.
```bash
cd backend && ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

### Verdict shows `?` for signal type / conviction
The LLM returned reasoning text instead of a JSON verdict. The parser now falls back to `signal_type=noise, conviction=low` with the raw text as the explanation — the frontend will not crash.

---

*Last updated: 2026-03-14*
