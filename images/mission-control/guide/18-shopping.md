---
title: "Shopping: from a wish to your door"
kicker: An agent that proposes, you approve
part: Everyday use
icon: coin
minutes: 5
summary: Say what you want; a shopping agent finds what fits, compares offers, tells you when to buy, and buys only after your own tap.
views: [new]
---
A **shopping agent** turns a wish ("I need more RAM", "a bigger SSD would be nice") into a delivered order, and you
decide at exactly one point: the proposal.

## 1. Tell Hermes what you want

Just say it in Chat or on Telegram. Hermes starts a shopping agent and asks only what it can't find out: **your budget
and your deadline**. It never asks about your PC (it reads the mainboard, memory slots and modules, graphics card and
disks from Windows itself) or which shop (it compares several).

```try
label: Find RAM for this PC
chat: I'd like to upgrade this PC to 32 GB RAM.
note: Hermes asks for budget and deadline if you didn't say them, then the agent's first run takes a few minutes.
```

Or give it as a task on **Home** ("Buy a 32 GB kit for this PC when it is cheap"): the task gets its shopping agent, and
each of its checks is a run of the task (Tasks); the proposals, your approval and the purchase are the same as here.

## 2. What it does

1. **What fits**: from your PC's own facts plus the manufacturer's specs and the board's memory support list, with
   the pitfalls (mixing kits, speeds, settings like XMP).
2. **Market research**: current offers in several German shops, in euros **including shipping**, with the seller, its
   rating and the delivery date, read with the isolated browser. If the AI phone is connected it also looks the top
   pick up in the shop's app there (read-only; it asks you first unless you let the phone work without asking).
3. **When to buy**: the price history where a page shows it, the category's trend, the sales ahead (Black Friday is
   **27 November 2026**) and its own price watch (below). The verdict is **buy now**, or **wait until ≤ €X or a
   date**, always with the reason.

Every step shows up in the agent's log (Agents → the shopping agent → Runs), including waits: while it waits for the
AI phone it steps aside, so other agents run meanwhile.

## 3. The proposal card

It appears on the agent's page, on **Home** ("needs you") and on Telegram: the item and exact variant, shop, seller,
price incl. shipping, delivery date, the delivery address (always your shop account's **default address**, never
changed), why this one and why now. Three buttons:

- **Approve purchase**: the AI phone buys exactly this (next section).
- **Not now**: it keeps watching and proposes again when the price drops about 5 % (or in two weeks).
- **Change**: say what should be different ("white", "cheaper", "by Friday"); it looks again.

If the verdict is "wait", the card says what it waits for, and the agent keeps watching and proposes again when the
target price or the date is reached. Approving works only in Mission Control on your own device: it is refused from
the AI phone, and no agent or chat tool can approve, change your limits or buy.

## 4. Buying, after your tap

The AI phone opens the product in the shop's app (Amazon on the S22: sign in there yourself once), puts exactly that
item in the cart and goes to checkout. On the final screen the phone itself checks, without any AI: the item and
variant, the seller, a total at most the proposed price (+3 % and €1 for small changes, never over your cap) and your
postcode in the delivery address. Only if all of that matches does it tap the final buy button, **once**; the log
says "approved by purchase proposal p-…".

It **stops and asks you** (with a screenshot, nothing bought) on any mismatch, a sign-in, a one-time code, a captcha
or a 3-D Secure / card check, or if the cart holds anything else. It never types payment data or passwords and never
changes the address or payment method; while it buys, typing and "change" buttons are refused.

## 5. Until it's at your door

After the order it shows the order number from the confirmation screen, then follows the **confirmation and
shipping mails** (it needs Gmail read access: grant it on the card) and updates the card until it is delivered.

## Limits

Under the shopping agent's **Settings → Limits** (for all shopping agents):

| Limit | Default |
|---|---|
| Per purchase | €150 |
| Per month | €300 |
| Shops it buys from | amazon.de |
| Address check | your postcode (nothing can be bought until you set it) |

Over a cap, or in a shop not on the list, you only get a **Buy it yourself** link.

> [!note] Shops with bot checks (Geizhals, idealo, Caseking, often Amazon's website) can't be read by the price watch
> or the browser; the agent re-checks those prices in its next run and in the shop's app on the AI phone.
