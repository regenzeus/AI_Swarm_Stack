---
title: "The AI phone: Hermes' hands"
kicker: Your old phone, operated for you
part: Everyday use
icon: bolt
minutes: 4
summary: Hermes can use apps on your old Android phone (look, tap, type, scroll, open apps), and it asks your OK once per job, unless you let it work for a while.
views: [phone]
---
Your old phone (the AI phone) is the **AI phone**. Ask Hermes in chat to do something on it, and it looks at the screen,
then taps, types, scrolls and opens apps the way you would. It works on that one phone only, never on your main phone.

```try
label: Try it
chat: On the AI phone, open Chrome and look up the weather in Berlin, then tell me what it says.
note: Your phone buzzes once for the whole job. Tap Allow this job and it works it through.
```

## You stay in control

- **Where it is**: tap the **AI phone** card on Home, or the AI phone line at the top of Agents and of Stack. If it stays disconnected,
  Home tells you under what needs you.
- **You approve whole jobs, not steps**: before it starts, Hermes asks once: what the job is, which apps, the exact texts it will
  type, and for how long (at most an hour). After your *Allow this job* it works through it in those apps without asking. A step
  outside the job isn't done: Hermes asks again for the wider job. It waits up to 15 minutes; no answer means no. The Phone page shows
  the job with *End task*; when it's done you get a summary with how many actions ran under your OK.
- **Fastest way to answer**: the Telegram message has *Allow this job* and *Decline* buttons. One tap records your answer. The Phone
  page shows the same request as a card with a screenshot.
- **Let it use the phone freely**: pick a time on the Phone page: *10 min*, *1 hour*, *8 hours*, your own number of
  minutes, or *Until I stop it*. Taps, swipes, opening apps and typing then run without asking; a step that was already
  waiting goes ahead too. Everything is still logged, blocked apps stay blocked, and Stop ends it at once.
- **Money always asks.** Anything that would buy, pay, order or subscribe needs its own OK every time, marked
  ↗ *Typing or a web address that holds an e-mail address, phone number, IBAN or key asks you*, even in free mode: it
  could send your data off the phone. (Inside a purchase you approved, its own steps don't ask again.)
  💳 *This would spend money*, even while it works on its own. That OK never opens a time window. Password, card and bank
  fields are never typed into: you type those yourself.
- **Some apps are never touched**: banking, investment, payment, wallet, password and authenticator apps, the
  Play Store and Settings. If one comes up anyway, the phone goes straight to the home screen.
- **It can't approve itself.** Mission Control refuses approvals and time windows that come from the AI phone, even if
  it opens this app in its own browser. It may only press Stop.
- **Stop** on the Phone page switches it off at once and disconnects. *Switch on* brings it back.
- **Everything is logged** on the Phone page: what it did, why, and what you decided.
- **The screen sleeps** after 30 seconds like any phone's, so the battery lasts; before each step the phone wakes it.
- **The network is sealed.** The service that drives the phone can reach that one phone and nothing else: no
  internet, no home network.

## Shopping on the AI phone

Sign in to your shops on the AI phone yourself (Amazon, eBay, a computer shop's app), once. Then ask Hermes, e.g.
*"On the AI phone, find 2×16 GB DDR4-3200 on Amazon, compare three offers and put the best in the cart."* It searches,
compares and fills the cart, then **stops before paying** and sends you a summary on Telegram with what is in the cart
and what is left to do. You check the cart and pay on that phone yourself. (Researching offers across many shops
without the phone is the job of a shopping agent; when you approve one of its proposals, the AI phone buys exactly
that item and checks the final screen itself before its one tap: see the Shopping chapter.)

```try
label: Shop-assist
chat: On the AI phone, open Amazon, search for 32 GB DDR4-3200 RAM (2x16 GB), and tell me the three best offers with prices. Don't put anything in the cart.
note: Read-only shopping; allow a few minutes on the Phone page first so it doesn't ask at every step.
```

## Mission Control on the AI phone

You can install Mission Control on the AI phone too (Chrome → ⋮ → *Add to home screen*), for example to watch it work.
It shows everything, but approvals and time windows from that phone are refused: only your main phone can say yes.

## Where to find it

**Home** shows an **AI phone** card: connected or not, what is on its screen, requests waiting for you, and one-tap
buttons to let it work without asking (*10 min*, *1 hour*, *Until I stop it*) or to *Stop* it. *Open* goes to the
Phone page with the full log, pairing and the block list. Then simply tell Hermes in Chat what to do on the AI phone.

## Cleaning it up

The AI phone was your own phone, so it is full of old apps and media you no longer need. A **cleanup analysis**
mission (Agents → New) reports what takes the space: the biggest apps you haven't used, the biggest files by name,
size and date, and per area (camera, WhatsApp media, downloads, old backups) how much is how old. Every step it
took and everything it found is in the run's **Log**.

Then tell Hermes what should go: **"uninstall …"**, **"trim the app caches"**, **"delete WhatsApp Media files older
than 365 days"** or **"delete /sdcard/SdCardBackUp"** (the report has the exact words). Each of these shows you what
and how much (files, size, dates) and waits for your tap, **also inside an allowance**. Blocked apps and system apps
are never touched; the analysis itself never deletes anything.

## Keep it ready

A sleeping phone gets woken up before each step. A swipe lock is dismissed, but **a PIN, pattern or password lock
stops it**: the AI phone never enters one. On the test phone, set the screen lock to *Swipe* or *None*, and leave
*Stay awake* off: the phone wakes the screen itself.

## Pairing (once)

The phone needs **Wireless debugging** on (Settings → Developer options). On the Phone page, follow the two steps:
on the phone, tap *Pair device with pairing code*, then enter the code and port. Later, if Wireless debugging was
switched off (it turns off when the phone changes Wi-Fi), switch it on again and tap *Connect*.

```try
label: Open the Phone page
open: "#/phone"
note: Shows whether it is connected, what is in front, waiting approvals and the log.
```

> [!warning] Don't sign the AI phone into anything sensitive. It is a test phone: keep banking, e-mail with
> important accounts and password managers off it, even though they are on the block list.

## Watching it work

While the agents act on the AI phone its screen stays on, until two minutes after the last action and while an action
waits for your OK, so you can see what it does. Idle, the screen goes off at once to save the battery. The Phone page
shows the screen's state: **Watch 10 min** keeps it on to look, **Turn off now** ends that.

