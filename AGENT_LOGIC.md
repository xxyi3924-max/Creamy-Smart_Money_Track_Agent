# Smart Money Agent — Logic, Reasoning & Rationale

---

## Was the AI Actually Thinking?

**Short answer: No — not before the prompt rewrite.**

The original prompt said `ALWAYS call first`, `ALWAYS call second` six times in a numbered list. The LLM executes a fixed sequence with no choice in tool selection or ordering. The only real reasoning happened at the very end, when it saw all results and wrote the verdict.

The scoring table made it worse. By specifying exact point values (`+2 if unusual=true AND bullish...`), we replaced LLM judgment with arithmetic that a simple Python `if/else` could do. The model was a pipeline executor, not an analyst.

**What changed after the rewrite:**

The prompt now requires the LLM to write after **every single tool result** — all six:

> *"Hypothesis so far: [what I think is happening and why]"*

This forces genuine integration of each result before the next tool call. The hypothesis shapes which tool gets called next and what the LLM is looking to confirm or refute. The call order is now a recommendation the LLM can deviate from — not a rigid script.

**Evidence it's working:** In a live NVDA run, the LLM reordered its calls — it called `dark_pool_activity` second (instead of `social_buzz`) because its hypothesis after seeing bearish options was "this could be a hedge, not a directional bet — need dark pool to distinguish before checking 13F." That is reasoning, not sequencing.

**Remaining prompt enforcement:** The prompt includes an explicit 6-step numbered example showing the correct cadence — call → hypothesis → call → hypothesis — with "Do NOT batch multiple tool calls without reasoning between them." This was added after observing the LLM write only one hypothesis then batch the remaining 5 tool calls silently.

---

## How the Full System Works

### End-to-End Flow

```
User types ticker → FastAPI /analyze → SSE stream opens
                                            │
                                            ▼
                              LLM Orchestrator (Claude Sonnet / GPT-4o)
                              reads system prompt, forms null hypothesis
                                            │
                        ┌───────────────────┴───────────────────┐
                        │  Agentic tool-use loop (multi-round)  │
                        │                                       │
                        │  Round 1  → call tool                 │
                        │           → get result                │
                        │           → write hypothesis          │
                        │           → decide next tool          │
                        │                                       │
                        │  Rounds 2–6  → same pattern           │
                        │                                       │
                        │  Final round  → no more tool calls    │
                        │              → write verdict JSON     │
                        └───────────────────────────────────────┘
                                            │
                          SSE events stream to frontend in real time:
                          tool_call → tool_result → reasoning → verdict
                                            │
                                            ▼
                              Frontend renders skill steps,
                              reasoning stream, verdict card
```

### The Agentic Loop in Code

```python
while True:
    response = llm.call(messages, tools)       # LLM decides: call a tool or stop
    if response.finish_reason == "stop":
        return parse_verdict(response.content) # done — emit verdict
    for tool_call in response.tool_calls:
        result = execute_skill(tool_call.name) # run the actual data skill
        messages.append(tool_result)           # feed result back to LLM
                                               # loop — LLM sees result and decides next
```

The LLM controls the loop. It can call tools in any order and stops when it has enough to write the verdict. We do not force it through a fixed sequence.

### Verdict Parsing — Robustness

The LLM occasionally ends with reasoning text instead of a clean JSON block (especially after writing a final hypothesis). The `_parse_verdict` function handles this with three fallback layers:

1. Try ` ```json...``` ` code fence extraction
2. Try bare `{...}` block extraction
3. Return a complete `signal_type=noise, conviction=low` fallback with the raw LLM text as `explanation`

This ensures the frontend never receives an incomplete verdict dict. The frontend also applies its own validation layer — unknown `signal_type` or `conviction` values are normalised to safe defaults before rendering.

---

## The 6-Skill Pipeline — What Each Detects and Why

Institutions move in a predictable sequence:

```
Dark pool prints → Options sweeps → 13F filings → Retail awareness
(immediate)        (immediate)      (45d lag)      (too late)
```

Each skill fills a blind spot the others cannot:

### Skill 1 — Options Flow (`options_flow_scanner`)

**What it detects:** Unusual options activity — high vol/OI contracts at specific strikes, large premium sweeps.

**Why it matters:** When a fund buys 500 deep-ITM calls in a single sweep, they are making a large directional bet. This is the loudest, most visible institutional signal.

**Limitation:** Options can also be hedges. A fund holding 10M shares of NVDA buying puts is not bearish — it is protecting a long position. Options alone cannot tell you direction without corroboration.

**Pipeline rule:** `unusual=false` does **not** stop the pipeline. It scores the signal (weight input) but doesn't veto. Institutions frequently accumulate via dark pools without touching the options market. The old hard-stop was the most critical logic flaw in the original system.

---

### Skill 2 — Social Buzz (`social_buzz_scanner`)

**What it detects:** Whether the retail crowd has already noticed the stock.

**Why it matters:** The entire thesis of this project is finding the gap between institutional positioning and retail awareness. `crowd_aware=false` means that gap is still open. `crowd_aware=true` means the edge is shrinking or gone.

**Sources (5 total):**
- Reddit — public JSON API, no credentials needed
- StockTwits — `curl_cffi` with `impersonate="chrome110"` to bypass Cloudflare TLS fingerprinting
- Finviz — scraped headlines
- Yahoo Finance news — `yfinance` stock.news (replaced X/twscrape as the reliable fallback)
- X/Twitter — **Playwright** headless Chromium with session cookie injection (see below)

**X scraper redesign:** The original twscrape approach caused 15-minute account lockouts when cookies expired (it called the login API). The new approach uses Playwright to launch a real browser, inject `auth_token` + `ct0` cookies directly, navigate to the search page, and scrape tweet elements via DOM selectors. No login API calls — no lockout risk. Returns empty gracefully if cookies are not configured.

**Sentiment calibration:** BULLISH/BEARISH term lists were tightened after observing `yf_bull_ratio=1.0` for NVDA. Generic words (`record`, `strong`, `rise`, `gain`) fired on almost every AI/tech headline. Terms are now specific financial events only: `upgrade/downgrade`, `beat/miss`, `guidance raise/cut`, `raised/lowered target`.

**What "informed vs hype" means:**
- `informed` — posts discuss filings, earnings, institutional moves
- `hype` — price targets, moon emojis, meme language
- `none` — almost no activity (earliest possible window)

---

### Skill 3 — Insider Tracker (`insider_tracker`)

**What it detects:** SEC 13F institutional filings (quarterly long position disclosures) and Form 4 insider transactions.

**Why it matters:** 13F filings are ground truth — legally required disclosures of what funds actually own. When multiple funds increase their holdings in the same quarter, that is confirmed accumulation, not a guess.

**Form 4 (insider buys) are the strongest signal of all.** A CEO buying $5M of their own stock in the open market is putting their personal money where their mouth is.

**Known limitations:**
- 13F is long-only. A fund marked "accumulating" may simultaneously hold short positions via swaps.
- 45-day reporting lag. Filings show where funds *were* positioned at quarter end.
- `shares_delta=0` is expected — EDGAR archive XML rate-limits aggressively.

---

### Skill 4 — Price Action / SMC (`price_action_context`)

**What it detects:** Where institutions actually entered the stock, using Smart Money Concepts (SMC) primitives on 60 days of daily OHLCV.

**Why SMC over standard resistance levels:**

Generic resistance only tells you price is near a past level — not *why* it matters or *who* is positioned there. SMC replaces this with:

| Concept | What it is | Why it matters |
|---|---|---|
| **Order Block (OB)** | Last opposite-colour candle before a Break of Structure | Institutions built their position here — they will defend it as support |
| **Fair Value Gap (FVG)** | 3-candle price gap (candle[i+2].low > candle[i].high) | Price imbalances that statistically fill ~70% of the time |
| **AMD Phase** | Accumulation → Manipulation fakeout → Distribution | Which stage of the institutional cycle price is currently in |
| **Flow/Price Divergence** | Volume slope rising + price slope falling | The clearest behavioral signature of silent accumulation |

**Practical reading:**
- `amd_phase=accumulation` + `order_block=bullish` near current price = institutions defending their entry level
- `fvg=bullish` below current price = institutions will likely return to fill it before moving higher
- `flow_price_divergence=true` = someone is absorbing selling pressure without moving price — classic dark pool behavior

---

### Skill 5 — Institutional Positioning (`institutional_positioning`)

**What it detects:** Whether the institutional trade is already crowded.

**Why crowding matters:** Three signals agreeing can mean two completely different things:
1. We are **early** — institutions quietly building, crowd hasn't noticed, trade isn't crowded
2. We are **late** — institutions already heavily positioned, trade overcrowded, move mostly done

Without a crowding check, the system cannot distinguish these.

**The crowding inputs:**

| Input | What it measures | High reading means |
|---|---|---|
| `short_pct_float` | % of float currently sold short | >8% = significant short crowding |
| `short_covering` | Short interest fell >5% MoM | Shorts closing = potential squeeze setup |
| `institutional_bias` | Top 10 holder pctChange direction | Distributing = smart money exiting |
| `pc_ratio` | Full-chain put/call OI across 5 expirations | >1.2 = heavy hedging or directional puts |

**Crowding score (0–100):** `crowded=true` if score > 70 → **conviction hard-capped at "medium" regardless of other signals.** An overcrowded trade is a late trade.

**Why CFTC COT is not used:** All known CFTC download URLs return 404. The yfinance approach is more precise for individual stocks anyway — CFTC COT covers index futures (market-wide), not individual tickers.

---

### Skill 6 — Dark Pool Activity (`dark_pool_activity`)

**What it detects:** Off-exchange block accumulation inferred from behavioral signatures in OHLCV — without direct FINRA TRF access (behind Cloudflare).

**Why dark pool matters:** It answers the question options flow cannot: *is this a sustained institutional positioning pattern or a one-time event?* A single options sweep could be a hedge. Three days of volume absorption at the same price level is a pattern.

**The four detection methods:**

| Method | Signal | Interpretation |
|---|---|---|
| **Volume Absorption** | vol > 1.5x avg AND range < 60% of stock's avg range | Institution absorbing supply without moving price |
| **Block Trade Score** | 10-day rolling — vol > 2x avg AND move < 40% of avg range = +3pts | Sustained block activity |
| **Vol/Price Divergence** | Volume slope positive + price slope negative | The clearest silent accumulation signature |
| **ATM Options Spread** | Tight near-ATM spread | Market makers providing institutional liquidity |

**Critical fix — ATR-relative thresholds:** The original code used a hardcoded `range_pct < 1.0%` threshold. This caused dark pool signals to **always return 0** for volatile large-caps like NVDA, which has a typical daily range of 2–4%. The fix computes the stock's own average daily range over the 30-day window and uses 60% of that as the "narrow" threshold. This self-calibrates correctly across any ticker.

---

## The Core Signal — Silent Accumulation Window

This is the scenario the entire system is designed to surface:

```
price_action.trend          = "downtrend"    ← price is falling (retail selling)
dark_pool.vol_price_div     = true           ← volume rising while price falls
options_flow.unusual        = true           ← directional bet placed
options_flow.sentiment_lean = "bullish"      ← someone expects up
insider_tracker.direction   = "accumulating" ← confirmed in 13F filings
social_buzz.crowd_aware     = false          ← retail hasn't noticed yet
institutional.crowded       = false          ← we are early, not late
─────────────────────────────────────────────────────────────────────
VERDICT: signal_type=accumulation, conviction=HIGH
         bullish_divergence=true

Explanation: "While the price has been falling, smart money appears to be
quietly accumulating. [Fund names] have increased their positions while retail
attention remains low — the crowd hasn't noticed yet."
```

This fires rarely. When it does, every independent data layer is pointing the same direction — that is the actual definition of a high-conviction signal.

---

## Engineering Decisions & Why

| Decision | Why |
|---|---|
| twscrape → Playwright for X | twscrape called the login API on every run, causing 15-min account lockouts when cookies expired. Playwright injects cookies directly into a browser — no login calls, no lockout. |
| Removed `options_flow` pipeline veto | Institutions accumulate via dark pools without unusual options. The veto was causing the agent to return `noise` on legitimate accumulation setups. |
| ATR-relative dark pool thresholds | Fixed `range_pct < 1.0%` always returned 0 for volatile stocks. Thresholds now adapt to each stock's own volatility baseline. |
| Tightened BULLISH/BEARISH terms | Generic terms (`record`, `strong`, `rise`) caused `yf_bull_ratio=1.0` for every AI/tech stock. Terms now require specific financial events. |
| Removed scoring table from prompt | Explicit point arithmetic (`+2 if...`) made the LLM a calculator, not an analyst. Replaced with judgment guide: "use as inputs, not a formula." |
| `_parse_verdict` three-layer fallback | LLM occasionally outputs hypothesis text instead of JSON as its final message. Parser now tries code fence → bare JSON → complete error verdict. Frontend never receives an incomplete dict. |
| Skill logging cleanup | Skills 1–6 were each logging their own result summaries AND `agent.py` was logging them again. Every result line appeared twice. Skills now only log unique intermediate details; `agent.py` owns the result summary. |

---

## Known Weaknesses

| Weakness | Impact | Mitigation |
|---|---|---|
| 13F is 45-day lagging | Direction confirmed but not current | Dark pool divergence provides real-time corroboration |
| 13F long-only | "Accumulating" fund may be net short via derivatives | Skill 5 short interest cross-reference partially compensates |
| Dark pool is a proxy | No direct TRF data | Volume absorption catches the behavioral effect of block trades |
| X cookies expire | X scraper returns 0 until cookies refreshed | Other 4 social sources still work; cookie refresh is manual |
| LLM confidence ≠ accuracy | Model states verdicts confidently regardless of data quality | `conviction="low"` for thin data; no backtesting yet |
| yfinance rate limits | Repeated rapid requests throttled | MOCK_MODE for demos; fixture data for testing |

---

## Summary Table

| Layer | Skill | Data Source | Temporal | Key Output |
|---|---|---|---|---|
| Options | options_flow | yfinance | Real-time | unusual, sentiment_lean |
| Crowd | social_buzz | Reddit / StockTwits / Finviz / YF / X (Playwright) | Real-time | crowd_aware, informed_vs_hype |
| Filings | insider_tracker | SEC EDGAR | 45-day lag | direction, notable_funds |
| Structure | price_action | Twelve Data | Real-time | OB, FVG, AMD, divergence |
| Crowding | institutional_positioning | yfinance | Bi-monthly | crowding_score, crowded |
| Dark pool | dark_pool | yfinance OHLCV | Real-time | absorption, vol_price_divergence |
