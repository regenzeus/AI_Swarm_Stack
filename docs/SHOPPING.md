# Shopping agents: from a wish to the door

Code: `ops/shopping.py` (the agent's runs, proposals, limits, buying and tracking), `ops/pricewatch.py` (the
changedetection.io client), `images/pricewatch/` (the sealed price watch), `images/phone/phone.py` (purchase mode and
the final-screen check), `images/mission-control/server.py` (`/api/shop/decide`, `/api/shop/limits`),
`images/mission-control/web/static/shop.js` (the cards). Guide chapter: `images/mission-control/guide/18-shopping.md`.

## Flow

```
wish (chat/Telegram) ─ Hermes asks budget + deadline only ─ mission_create(kind=shopping)
  run: read facts → agent research (scout browser) → [AI phone: read-only app search, run parked] → proposal
  proposal ─ buy_now ─ card: Approve purchase / Not now / Change     (Mission Control + Home + Telegram)
           ─ wait    ─ watching: changedetection.io + next runs, propose again at ≤ target or on the date
           ─ over a cap or another shop ─ "buy it yourself" link only
  Approve (owner, own device) → /srv/ai/phone/purchases/<id>.json (45 min, one tap) + a buy run
  buy run: Hermes (main profile, phone tools) → cart → checkout → phone.py final_check → one tap, or stop + ask
  bought → order number from the screen → tracking runs (Gmail read grant) until delivered
```

## Safety design

- **Approval is a human act in one place.** `shop_decide` / `shop_limits` reach the runner only from the two
  Mission Control endpoints, which set `source: "owner"` and refuse the AI phone's Tailscale IP (`from_ai_phone`).
  The generic `/api/request` refuses `shop_*`, MCP tools submit with `source: "chat"`, and the runner refuses
  anything but `"owner"`. Proposals and limits live in `/srv/ai/missions/shopping`, outside the vault Hermes can write.
- **The approval is narrow.** The purchase file names the item words, variant words, seller words, the ceiling
  (proposal total × 1.03 + €1, never over the per-purchase cap), the owner's address words, the shop app, and
  expires after 45 minutes. The buy run deletes it afterwards; `phone.py` marks it used before the final tap.
- **The last step is deterministic.** `final_check()` in `phone.py` reads the whole screen (no model): blockers
  (secret fields, sign-in, one-time code, captcha, 3-D Secure, CVC) stop; no order total = not the review screen
  (refused, not stopped); item, variant, seller and address words must all be present and the parsed total ≤ ceiling.
  Only then the one tap, logged as "purchase <id> approved by <owner> stands in for this money tap". Any other money
  tap still needs its own approval, as before.
- **Purchase mode is tighter, not looser.** While an approval is open, only steps inside that shop's app run
  without asking; typing is refused; taps on change/edit/address/payment/voucher labels are refused.
- **No secrets.** No payment data, passwords or codes are ever typed; the address and payment method are the shop
  account's defaults, never changed. The owner signs in to the shop app himself.
- **The price watch is sealed.** changedetection.io (Apache-2.0, pinned by digest in `versions.env`) runs on its
  own network with an egress firewall against private ranges, no capabilities and no notifications configured; the
  runner reads its API on 127.0.0.1 and reports. It uses the plain HTTP fetcher (no browser): shops with bot checks
  give no reading, and the agent's next run covers them.

## Reuse check: anthropics/commerce-agents

[anthropics/commerce-agents](https://github.com/anthropics/commerce-agents) (Apache-2.0, a reference
implementation, marked as not maintained) shows agents that work on a shop's behalf: they **propose**, changes are
**staged until a human approves**, and the agents never place orders or charge cards themselves. We borrowed that
pattern (proposal → human approval → a narrow step that acts) and its separation of "the agent's suggestion" from
"the state a human committed". We did not borrow code: its agents hand checkout to the host application, while ours
ends in a buyer's shop app on a phone, so the deterministic final-screen check (ours) takes the place of that hand-off.

## Tests

`tests/test_shopping.py` (proposals, verdicts, limits, owner-only decisions, buy and stop results),
`tests/test_phone.py` (final-screen check against simulated Amazon review screens: match, dearer, other item, other
address, blockers, product page; the single tap; refusals during a purchase), `tests/test_server.py` (the endpoints
refuse the AI phone and the generic request route).
