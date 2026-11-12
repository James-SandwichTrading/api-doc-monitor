# Exchange API change review — monitor run of 2026-11-12

## Your task

You have access to our exchange integrations (connectors, order entry, market data, account/wallet code, symbol/instrument configuration, error handling, rate limiters). Below is everything our API documentation monitor picked up in its run on **2026-11-12 (≈08:10–08:42 UTC)**, compared against the previous run on 2026-11-11 (≈08:21–08:57 UTC).

For each item, check our integration code and configuration and tell us whether we are affected and whether anything needs to be done or watched. Specifically:

1. Search the integrations for every endpoint, channel, field, error/reject code, symbol, URL and rate-limit assumption named below.
2. For each item, classify it as one of:
   - **ACTION REQUIRED** — we use the affected thing and current behaviour will break or become wrong. Say what, where (file and line), and by when.
   - **WATCH** — we use something adjacent, or the impact depends on runtime/account configuration you cannot see from code. Say exactly what to monitor and what the symptom would look like.
   - **NOT AFFECTED** — say what you searched for and that nothing was found, so the conclusion can be checked.
3. Do not assume we use, or do not use, a feature. Verify it in the code. If you cannot determine something from the code (for example, which account-level limits are configured at the exchange, or which symbols are traded live), say so explicitly and list it as an open question instead of guessing.
4. Do not change any code. This is a read-only review; report findings only.
5. Pay attention to the deadlines. Several items take effect on 2026-11-13.

The text quoted under "Before" and "After" is copied verbatim from the exchange documentation. Everything else is our summary. Where the two disagree, trust the quoted text.

## Time-ordered deadlines in this run

| When (UTC) | Exchange | Event |
|---|---|---|
| 2026-11-11 11:00 (already live) | Bybit | DANGOTEUSDT Pre-IPO TradFi perpetual listed |
| 2026-11-12 (today) | Deribit | Starbase order-entry reject reason change for open order size limits |
| 2026-11-12 (today) | OKX | SBE order entry / private data services launch in **demo trading** (moved from 2026-11-11) |
| 2026-11-13 09:00 | Bybit | 4STOCKUSDT, AGIUSDT, HAJIMIUSDT perpetuals delisted |
| 2026-11-13 12:00 | Deribit | GRAM, QNT, ZRO, GRASS, PEARL USDC-settled perpetuals launch |
| Early December 2026 | OKX | SBE order entry / private data services launch in production |
| Effective date not stated | Hyperliquid | Congestion block-space allowance halved (see below) |

---

## 1. Deribit

### 1.1 Starbase (SBE order entry): reject reason changes for open order size limits — NEW, dated 12.11.2026

Source: `https://docs.deribit.com/changelogs/starbase#starbase-update-12-11-2026` (new changelog entry). This is the highest-priority item in this run because it changes a reject code on live order entry with no schema change, so nothing will fail to decode — behaviour just silently differs.

Full text of the new entry:

> Starbase Update 12.11.2026
> API Changes — Order Entry
> Reject reason for open order size limits. A new order or a replace that would breach a Portfolio Margin open order size limit is now rejected with `ORDER_SIZE_LIMIT_EXCEEDED` (`28`) instead of `POSITION_LIMIT_EXCEEDED` (`27`). These limits cap the total size of resting orders, not position size. This applies to:
> - `pm_max_future_open_order_size`: maximum total size of future open orders per side
> - `pm_max_option_open_contracts`: maximum total size of option open contracts per side
>
> Position size limits (such as `sm_max_future_position_size`) still reject with `POSITION_LIMIT_EXCEEDED`. Open order count limits are unchanged. The SBE order entry schema is unchanged: both reason codes already exist. Clients that handle `POSITION_LIMIT_EXCEEDED` for these limits should also handle `ORDER_SIZE_LIMIT_EXCEEDED`.
> See Rejection Reason Codes and Position Limits.

The same change is reflected on the "Get Starbase Risk Limits" reference page (`https://docs.deribit.com/api-reference/portfolio-management/get-starbase-risk-limits`). For both `pm_max_future_open_order_size` ("Portfolio Margin: maximum total size of future open orders per side. USD notional for inverse contracts, quantity for linear contracts. Omitted when unset. -1 means unlimited.") and `pm_max_option_open_contracts` ("Portfolio Margin: maximum total size of option open contracts per side, in contracts. Omitted when unset. -1 means unlimited."), this sentence was added:

> An order or replace that would breach it is rejected with `ORDER_SIZE_LIMIT_EXCEEDED` (`28`).

What to check:
- Do we connect to Deribit Starbase (SBE order entry) at all? If not, say so and mark not affected.
- Where do we map Starbase rejection reason codes? Is `28` / `ORDER_SIZE_LIMIT_EXCEEDED` mapped, or does it fall into an "unknown reject" path?
- Is there any logic keyed specifically on `27` / `POSITION_LIMIT_EXCEEDED` — for example backing off, reducing quote size, pausing a strategy, alerting, treating it as a risk-limit breach, or deciding whether to retry? Any such logic will stop firing for open-order-size breaches, on both new orders and replaces, and needs to handle `28` as well.
- Conversely, is there existing handling for `28` that assumes it means a single order was too large (and, for example, splits or shrinks that one order)? It can now also mean the aggregate resting size per side is too large, where shrinking one order and resending may loop.
- Does any monitoring, alert rule or dashboard count rejects by reason code? Counts will shift from 27 to 28.
- Open question to raise if not answerable from code: are `pm_max_future_open_order_size` or `pm_max_option_open_contracts` actually set on our accounts? If both are unset or `-1`, the practical exposure is nil.

### 1.2 New perpetuals: GRAM, QNT, ZRO, GRASS, PEARL — launching 2026-11-13 12:00 UTC

Source: Deribit announcement dated 2026-11-11 (via `public/get_announcements`).

> 🚨GRAM, QNT, ZRO, GRASS and PEARL perpetuals are coming to Deribit. Launching Friday, November 13, 2026, at 12 PM UTC: 5 new USDC-settled perpetual contracts will be available on Deribit. GRAM · QNT · ZRO · GRASS · PEARL

The announcement does not give instrument names or contract multipliers. The previous batch (ENA_USDC, AAVE_USDC, HBAR_USDC, August 2026) used the `<COIN>_USDC` perpetual naming and per-contract multipliers that differed by coin (1 ENA, 0.01 AAVE, 1 HBAR), so do not assume a multiplier of 1.

What to check:
- How do we discover Deribit instruments — dynamically from `public/get_instruments`, or from a static list/whitelist? Will five new USDC-settled linear perpetuals appearing mid-session cause problems (unknown-instrument errors, failed symbol mapping, an instrument-count assertion, subscription wildcards such as `*.any.any` suddenly delivering unknown instruments)?
- Do we have mappings from Deribit base currencies to our internal asset identifiers? Are GRAM, QNT, ZRO, GRASS and PEARL present, and could any of them collide with an existing internal symbol?
- Do we read contract size / multiplier / tick size from the instrument definition, or hard-code them per currency?
- Any per-currency configuration (index names, fee tables, margin parameters, settlement-currency handling) that needs an entry before a new underlying appears.

### 1.3 Terminology clean-up: "Deribit Block Trades" versus "Block RFQ trades" (documentation wording, with a few clarifications of scope)

Fourteen Deribit pages changed, and almost all of it is a consistent rewording that now distinguishes two things that were previously both called "block trades":
- **Block Trades** / "Deribit Block Trades" — bilateral, signature-based trades via `private/verify_block_trade` / `private/execute_block_trade`, including Voice Broker trades.
- **Block RFQ trades** — trades produced when a Block RFQ is filled.

No endpoint, parameter, field or error code was added, removed or renamed. However, the rewording makes several behaviours explicit that were ambiguous before. These are the ones with any semantic content:

a) **Scope `block_trade:read`** (page: Access Scope)
- Before: "Read-only access to block trading information."
- After: "Read-only access to information on Block Trades and Block RFQ trades."
- `block_trade:read_write` — Before: "Full access to create and manage block trades." After: "Full access to create and manage Block Trades."
- Creating API key page — `block_rfq:read`: "view RFQs" → "view Block RFQs"; `block_trade:read`: "view existing block trades and trade history" → "view existing Block Trades and Block RFQ trades, and trade history".

b) **`private/get_block_trade` and `private/get_block_trades` return both kinds** (Block Trading page, Related Methods)
- "Get information about a specific block trade" → "Get information about a specific Block Trade or Block RFQ trade"
- "List block trades" → "List Block Trades and Block RFQ trades"
- JSON-RPC changelog entry for Release 01.07.2025 reworded: when `private/get_block_trades` is called without a currency "it will return Block Trades and Block RFQ trades for all available currencies" (previously "block trades for all available currencies").

c) **`block_trade_id` identifies both kinds** (Block Trading page)
- Before: "Block trades can be distinguished from other trades in the API via the `block_trade_id` field"
- After: "Block Trades and Block RFQ trades can be distinguished from other trades in the API via the `block_trade_id` field"
- Block RFQ walkthrough: "Each result entry is one block trade. Its `id` is the `block_trade_id`" → "Each result entry is one Block RFQ trade"; "`block_trade_id` — The executed block trade produced when the RFQ is filled" → "The executed Block RFQ trade produced when the RFQ is filled".

d) **Delayed publication applies to Block RFQ trades only** (JSON-RPC Release 10.11.2026, FIX Release 10.11.2026, Starbase Update 10.11.2026 — these releases themselves went live on 10 November and were reported in an earlier run; only the wording changed today)
- JSON-RPC: heading "Delayed publication of large Block RFQ trades" → "Delayed publication of large Deribit Block RFQ trades".
- JSON-RPC: "This applies only to qualifying Block RFQ trades. On-screen trades, liquidation trades and block trades executed outside Block RFQ are unchanged." → "…On-screen trades, liquidation trades and Deribit Block Trades are unchanged."
- JSON-RPC chart data: "Block trades, including Block RFQ trades, no longer add to volume in `public/get_tradingview_chart_data` or on `chart.trades.{instrument_name}.{resolution}`" → "Block Trades and Block RFQ trades no longer add to volume in…" (same meaning, restated).
- FIX: "Qualifying Block RFQ trades with delayed publication are omitted from FIX market data until they are published" → "Qualifying Deribit Block RFQ trades…".
- Starbase market data: "Delayed block trade publication." → "Delayed Deribit Block RFQ trade publication."; "On all other block trades `wasDelayed` is `0`" → "On all other Block Trades and Block RFQ trades `wasDelayed` is `0`"; "Delayed block trades are not published on the incremental channel at execution" → "Delayed Block RFQ trades are not published…"; link text "Delayed block trades" → "Delayed Block RFQ trades".

e) **Block Trade Approval feature applies to Deribit Block Trades** (Asymmetric API Keys, Creating new API key, Block Trading pages) — "Requires additional approval from a different API key before executing block trades" → "…before executing Deribit Block Trades".

f) Pure capitalisation / wording with no semantic content: Error Codes page descriptions for 13905 `too_many_quotes_per_block_rfq`, 13906 `too_many_quotes_per_block_rfq_side`, 13907 `not_fully_filled`, 13907 `too_many_open_block_rfqs`, 13917 `account_quote_limit_crossed`, 13918 `inverse_future_cross_trading` ("block rfq" → "Block RFQ"; codes and identifiers unchanged); Notifications page (`block_trade_confirmations`, `block_trade_confirmations.{currency}` descriptions capitalised); Spot Trading Venues page; Voice Broker Trading API page ("block trades" → "Block Trades" / "Deribit Block Trades" throughout, `min_block_trade_limit` description capitalised).

What to check:
- Anywhere we consume `private/get_block_trades` / `private/get_block_trade`, or classify trades by the presence of `block_trade_id` (trade tape, user trades, reconciliation, volume statistics, fair-value or signal inputs that exclude block prints): does the code assume a `block_trade_id` means a bilateral Block Trade? It can equally be a Block RFQ trade, and only Block RFQ trades can be delayed-published.
- If we filter or flag delayed prints (`wasDelayed` on Starbase market data, or the equivalent JSON-RPC/FIX fields from the 10.11.2026 release), confirm the logic does not assume every block print can be delayed, or that delayed implies bilateral.
- If any of our Deribit API keys are provisioned with `block_trade:read` for the purpose of seeing only bilateral block trades, note that the scope is documented as covering Block RFQ trades too.
- If we do none of the above, mark not affected and say what you searched for.

### 1.4 Not a real change (ignore)

- Forty Deribit API-reference and subscription pages show content differences that are purely how the documentation site rendered code samples on the day (JSON and cURL examples split one token per line versus pretty-printed). After whitespace normalisation they are identical to yesterday. Pages include `private/cancel`, `private/edit_by_label`, `private/mass_quote`, `private/get_user_trades_by_currency`, `public/subscribe`, `user.orders.*`, `user.trades.*`, `book.*` and others. None has a content change.
- One old announcement (2026-08-15, ENA_USDC / AAVE_USDC / HBAR_USDC perpetuals) rolled out of the monitored window.

---

## 2. Hyperliquid

Two documentation pages changed. No effective date is given for either; treat both as potentially already in force.

### 2.1 Rate limits and user limits — congestion block-space allowance halved

Source: `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits`

- Before: "During high congestion, addresses are limited to use **2x their previous day maker share percentage** of the block space. The maker share is scaled by the same factor as the volume contribution of that asset towards fee tiers. …"
- After: "During high congestion, addresses are limited to use **their previous day maker share percentage** of the block space. **Block space has a constant cost per signature, so batched actions are strictly cheaper to send.** The maker share is scaled by the same factor as the volume contribution of that asset towards fee tiers. …"

The rest of the paragraph is unchanged: HIP-3 assets under growth mode count less towards this limit; the maker share is computed once per UTC date; "it can therefore be helpful to not resend cancels whose results have already been returned via the API"; "During congestion, the weight of a batched action is proportional both to its batch size and a constant per-action weight. Therefore, batching cancels or orders together will strictly decrease their weighting and reduce rate limit usage."

Net effect: under congestion, each address gets half the block space it used to (1x rather than 2x the previous day's maker share), and there is now an explicit statement that cost is per signature, so one signed batch of N orders/cancels is cheaper than N separately signed actions.

What to check:
- Do we send orders, cancels and modifies individually signed, or batched into a single signed action? Where we send individually, how much could be batched (including cancels)?
- Do we resend cancels (or orders) whose result has already come back through the API? Any retry/duplicate-cancel logic burns allowance that is now scarcer.
- Is there any internal model, constant or comment that encodes the "2x maker share" allowance (throttles, congestion back-off, capacity estimates)? It is now wrong by a factor of two.
- How do we behave when actions are rejected or dropped for exceeding the congestion limit — is that surfaced, retried, or silently lost? Expect this to happen more often for a given flow, especially on days following low maker share and on HIP-3 growth-mode assets.
- Maker share is per address per UTC day: note any addresses/sub-accounts that take more than they make, since they will have the least headroom.

### 2.2 Optimizing latency — scope of mempool deprioritisation clarified

Source: `https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/optimizing-latency`

Existing text (unchanged): "Actions other than `noop, scheduledCancel, cancel, cancelByCloid, order, modify, batchModify` sent on HyperCore will cause all actions to be deprioritized while that action has not yet been committed. This holds across sub-accounts associated with and vaults led by the same master user which originate the non-trading action sent."

Sentence added immediately after:

> "It does not affect other subaccounts of vaults of the same master account."

The added sentence is quoted exactly as published; its grammar is ambiguous ("subaccounts of vaults" is probably intended as "subaccounts or vaults"). Read with the preceding sentence, the likely meaning is that deprioritisation applies to the account that originated the non-trading action and not to the master's other sub-accounts and vaults — but that is our interpretation and is not confirmed by the text.

Surrounding context on the same page, unchanged but relevant: mempool prioritisation only works for users in Standard abstraction (latency-sensitive users should not use Unified Account or Portfolio Margin); users who have ever directly sent CoreWriter actions are deprioritised; IOC and ALO priority fees require a minimum delegatable balance of 10 HYPE.

What to check:
- Which non-trading actions do we send from accounts that also trade (for example `usdClassTransfer`, `updateLeverage`, `updateIsolatedMargin`, sub-account transfers, `vaultTransfer`, `approveAgent`, `setReferrer`, staking/delegation, spot sends, withdrawals, TWAP actions), from which account, and how often? Each one deprioritises that account's order flow until it commits.
- Are such actions sent from the same address/sub-account that carries latency-sensitive order flow, or from a separate one? If the new sentence means what we think, isolating housekeeping actions on a different sub-account avoids the penalty; do not restructure anything on the strength of this sentence alone — flag it for confirmation.
- Any periodic job (leverage refresh, margin top-up, balance sweep) that fires during active trading.

### 2.3 Not a real change (ignore)

Seven other Hyperliquid pages (Exchange endpoint, HIP-3 deployer actions, Priority fees, Websocket, Funding, Order types, Sub-accounts) differ only in their "Last updated N days ago" footer.

---

## 3. OKX

### 3.1 SBE order entry and private data — demo launch date moved, new connection rate limit

Source: `https://www.okx.com/docs-v5/log_en#upcoming-changes-sbe-order-entry-and-private-data` ("Last update" changed from October 28, 2026 to November 10, 2026).

Two changes:

a) Demo launch date slipped by one day.
- Before: "expected to launch in the demo trading environment on **November 11, 2026** and in the production environment in early December 2026."
- After: "expected to launch in the demo trading environment on **November 12, 2026** and in the production environment in early December 2026."

b) New sentence added under "New SBE services":

> "The `/ws/v5/trade-sbe` and `/ws/v5/private-sbe` WebSocket services share a connection rate limit of 500 connection requests per 5 minutes per IP."

Context that did not change today but defines what this service is:
- Order entry: production `wss://ws.okx.com/ws/v5/trade-sbe`, demo `wss://wspap.okx.com/ws/v5/trade-sbe`, schema `okx_sbe_trade_2_0.xml`.
- Private data: production `wss://ws.okx.com/ws/v5/private-sbe`, demo `wss://wspap.okx.com/ws/v5/private-sbe`, schema `okx_sbe_private_1_1.xml`.
- "Existing REST and JSON WebSocket APIs will remain unaffected."
- Authentication happens during the WebSocket HTTP Upgrade request (API key and signature in request headers), the same as the existing SBE Market Data service. JSON control messages use text frames (opcode 1); SBE messages use binary frames (opcode 2).
- Order entry supports place / amend / cancel, single and batch (up to 20), in CASH and CROSS trading modes only; other modes must stay on the JSON WebSocket trading API.
- Private data supports `orders` and `fills` (fills is VIP4 and above); neither publishes an initial snapshot; subscription requests/responses stay JSON, channel data is SBE.
- Schema notes already published: trade schema id 1 → 2 (`semanticVersion` 2.0.0), `expTime` → `expTimeUs`, `ts` → `tsUs`, place-order responses drop `instIdCode`, batch responses rename `data` group to `results` and add `sMsgDetails`; private schema version 0 → 1 (`semanticVersion` 1.1.0), `orders` adds `reduceOnly` and `avgPxMantissa`, `fillTime`/`uTime`/`cTime` → `fillTimeUs`/`uTimeUs`/`cTimeUs`, `fills` `ts` → `tsUs`.

What to check:
- Do we have, or are we building, an integration against `/ws/v5/trade-sbe` or `/ws/v5/private-sbe`? If neither, this is not affected for now — say so. Existing REST and JSON WebSocket integrations are explicitly unaffected.
- If we are building one: confirm any demo-environment test plan accounts for the 12 November date; confirm encoders/decoders are generated from `okx_sbe_trade_2_0.xml` and `okx_sbe_private_1_1.xml` rather than earlier schema versions.
- For the new limit: it is shared across both SBE services and counted per IP, on connection requests. Check our reconnect logic (back-off, jitter, maximum attempts) and how many processes/connections share one egress IP. A reconnect storm across several sessions behind one NAT address could exhaust 500 per 5 minutes and lock out both order entry and private data together.
- Check whether any existing OKX WebSocket reconnect loop could behave the same way against similar per-IP connection limits on the JSON endpoints.

### 3.2 Unchanged today but imminent (for awareness only — not part of today's diff)

The OKX "WebSocket port 8443 discontinuation" notice (last updated 2026-10-22, unchanged in this run) has its second cut-off four days out: public-internet connections on port 8443 stopped being accepted on 2026-10-31, and **Colo connections on port 8443 stop on 2026-11-16**. If any OKX WebSocket URL in our configuration still contains `:8443` — especially Colo endpoints — it will fail from that date. Until then such connections receive `event = notice` with code `64010`. A quick grep for `8443` in OKX configuration is worthwhile while you are in the code.

---

## 4. Bybit

Announcements added since yesterday's run (all dated 2026-11-11):

### 4.1 Perpetual delistings — 2026-11-13 09:00 UTC

> "Bybit will be delisting the 4STOCKUSDT Perpetual Contract at Nov 13, 2026, 9:00AM UTC."
> "Bybit will be delisting the AGIUSDT Perpetual Contract at Nov 13, 2026, 9:00AM UTC."
> "Bybit will be delisting the HAJIMIUSDT Perpetual Contract at Nov 13, 2026, 9:00AM UTC."

Sources:
- `https://announcements.bybit.com/en-US/article/delisting-of-4stockusdt-perpetual-contract--art52c4cf790adc/`
- `https://announcements.bybit.com/en-US/article/delisting-of-agiusdt-perpetual-contract--art7816e6629a54/`
- `https://announcements.bybit.com/en-US/article/delisting-of-hajimiusdt-perpetual-contract--art7266681607d5/`

The monitor only captures the headline sentence. The full articles normally specify when new position opening is restricted before the delisting time, and that remaining positions are settled at an average index price at delisting; read the articles if any of these symbols are relevant.

What to check:
- Are `4STOCKUSDT`, `AGIUSDT` or `HAJIMIUSDT` (linear perpetuals) present in any symbol list, strategy configuration, hedging map, market-data subscription list or risk configuration?
- If so: are there open positions or resting orders, and what closes or cancels them before 09:00 UTC on 13 November? Forced settlement at delisting is at an exchange-determined price.
- How does our code behave when an instrument disappears or changes status mid-session — instrument status moving to settling/closed, order rejections for a closed symbol, WebSocket topics going silent or being rejected on resubscribe, instruments-info responses no longer listing it? Look for startup failures caused by a configured symbol that no longer exists.
- If these symbols are hedges or legs for something on another venue, flag the other leg.

### 4.2 New listing — DANGOTEUSDT Pre-IPO TradFi perpetual (already live since 2026-11-11 11:00 UTC)

> "New listing: Listing of DANGOTEUSDT on Bybit Pre-IPO Tradfi Perpetual on Nov 11, 2026, 11:00AM UTC"

Source: `https://announcements.bybit.com/en-US/article/new-listing-listing-of-dangoteusdt-on-bybit-pre-ipo-tradfi-perpetual-on-nov-11-2026-11-00am-utc--art6ad921fb4a95/`

What to check:
- This is a "Pre-IPO TradFi Perpetual", not a standard crypto perpetual. If we enumerate all linear USDT perpetuals dynamically, check whether this instrument gets picked up automatically and whether anything assumes all such instruments trade 24/7, share standard funding intervals, price-limit rules, leverage tiers or have a crypto spot/index reference. Pre-IPO and TradFi products commonly have different trading sessions, funding and risk parameters.
- Check for any universe filter (by contract type, category or symbol pattern) that should exclude it, and whether an unmapped base asset ("DANGOTE") causes errors in symbol normalisation.

### 4.3 Network upgrades (deposit/withdrawal suspensions)

> "Bybit to Support HYPEREVM (HYPE) nb-20261110 Network Upgrade"
> "Bybit to Support Injective (INJ) v1.20.4 Network Upgrade"

Sources:
- `https://announcements.bybit.com/en-US/article/bybit-to-support-hyperevm-hype-nb-20261110-network-upgrade--art7a2162c994b9/`
- `https://announcements.bybit.com/en-US/article/bybit-to-support-injective-inj-v1-20-4-network-upgrade--art892f11cb8f65/`

Only the titles were captured — the suspension windows are in the articles. Such upgrades normally suspend deposits and withdrawals on the affected network while trading continues.

What to check:
- Do we move HYPE (HyperEVM network) or INJ (Injective network) to or from Bybit, either manually or through automated rebalancing/treasury transfers? If so, the transfer path will be unavailable during the window; check how a suspended-chain response from the withdrawal or deposit-address endpoints is handled (retry storm, alert, silent failure). Given we also integrate Hyperliquid, pay particular attention to any HYPE flow between Hyperliquid/HyperEVM and Bybit.

### 4.4 Not a real change (ignore)

Six older announcements (dated 2026-11-02 to 2026-11-04: Bybit City Edition 13, interest-free institutional loan applications, KOR spot listing, Zigchain v6.0.0 network upgrade, a MENA VIP promotion, short-dated options fee discount extension) rolled out of the monitored window. Nothing was retracted.

---

## 5. Lighter

No API change.

- The draft page "Guild field updates — review preview" (`https://docs.lighter.xyz/api/guild-field-updates-review`) was removed from the documentation. It was explicitly a review copy of *proposed* updates ("The existing API Reference pages, URLs and published OpenAPI are unchanged… merging this page alone will not update the shared API definition") and described proposed `pnlLeaderboard` filters `guild_id`, `l1_addresses` (comma-separated, maximum 150 addresses) and `integrator_account_index`, plus pagination/sorting notes. None of the actual reference pages changed in this run, so the proposal has not been applied to the published API reference as of today.
- The WebSocket page (`https://docs.lighter.xyz/api/websocket`) changed only because its "Next" navigation link to that draft page disappeared.
- The other 147 Lighter pages differ only in "Last updated N days ago" footers and code-sample rendering.

What to check: nothing required. Only if we use Lighter's `pnlLeaderboard` endpoint or guild-related fields is it worth noting that changes to them have been drafted and may land later.

---

## 6. Exchanges with no changes in this run

Binance (spot, derivatives and margin changelogs), Bitget, HTX, Coinbase (Exchange, International Exchange and Derivatives changelogs/upcoming changes) and Kraken were all checked on 2026-11-12 and returned content identical to 2026-11-11. BitMEX is not monitored (exchange shut down). No action for any of these.

---

## What to send back

A single report, ordered by urgency, containing:

1. A one-paragraph headline: is there anything we must do before 2026-11-13 09:00 UTC (Bybit delistings) or 12:00 UTC (Deribit listings), and is the Deribit reject-code change (already in effect) handled?
2. For every numbered item above (1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.3, 5): the classification (ACTION REQUIRED / WATCH / NOT AFFECTED), the evidence (file paths and line numbers, configuration keys, or the search terms that returned nothing), and for anything that is not NOT AFFECTED, the concrete recommended change or the specific thing to monitor and its symptom.
3. A list of open questions you could not resolve from the code (for example, exchange-side account limits, which symbols are live in production, which egress IPs are shared), each phrased so a person can answer it in one line.
4. Anything you noticed in the integrations while checking that is related to these items but not listed here.

State plainly where you verified something versus where you are inferring it.
