# The AI phone on any internet

Design, 4 Nov 2026. The owner's requirement: *"AI Phone will boot up after restart into AI controllable state as long as it
has internet"*, on the home Wi-Fi, on the hotspot of the other phone, anywhere.

## Where it stands

The stack reaches the phone through Tailscale (`100.64.0.10`), which works from any network, and nothing in the stack
depends on the home Wi-Fi. What ties the phone down is the door it comes in by: **Wireless debugging**.

| What gets in the way | Home Wi-Fi | Hotspot | Mobile data only |
|---|---|---|---|
| Tailscale reaches the phone | yes | yes | yes |
| Wireless debugging runs | yes | should (a hotspot is Wi-Fi to the AI phone); **not tested** | **no: Android runs it on Wi-Fi only** |
| Android may ask once per new Wi-Fi ("Always allow on this network") | answered | **one tap on the AI phone, to be seen** | n/a |
| Its port changes when it restarts | scan finds it | scan finds it (slower through a relay) | n/a |
| The pairing lapses after 7 days (FND-120) | **yes, today** | yes | yes |
| Back after a phone restart | yes (KeepADB, always-on Tailscale) | on a known Wi-Fi | **no: needs Wi-Fi or USB once** |

The last column is the hard one. Without root, Android only lets a program get ADB rights through Wireless debugging (Wi-Fi) or
USB. So "any internet, even right after a restart" can't be met through ADB alone.

## The way there

### Stage 0: the pairing stops lapsing (built; needs the owner once)

The owner pairs again on the Phone page, then taps **Set it up** under *Starts in AI mode*: a fourth Allow sets
`adb_allowed_connection_time` to 0, which is what Developer options calls *Disable adb authorization timeout*. Check: the
Phone page shows the ✓, and the phone still connects on day 8.

### Stage 1: any Wi-Fi, the hotspot included (small; needs one test with the owner)

1. **Test first.** The AI phone joins the main phone's hotspot. Measure: does Wireless debugging stay on or come back, does Android ask, how long
   until the stack reconnects, and does it survive a restart of the AI phone on the hotspot.
2. **Reconnect faster.** Try the last known port before scanning 20,000 ports, and retry as soon as Tailscale sees the phone on a new
   network, not on the backoff of up to 10 minutes.
3. **Say which network.** The Phone page shows the Wi-Fi name, direct or relayed, and how the last restart went.
4. **Rehearse it** as a probe in `docs/PROBES.md`, like P8 for the PC.

A hotspot's address can change between sessions, and "always allow" may be tied to it. If Android asks every time, Stage 1 alone
doesn't meet the requirement on the hotspot, and Stage 2 becomes the answer there too.

### Stage 2: any internet, even after a restart with no Wi-Fi (not built: DEC-42; kept in case that changes)

A small **agent app on the AI phone** that needs no ADB:

- It runs as an Android accessibility service, which can read the screen, tap, swipe, type and take screenshots (Android 11+), and it
  starts by itself after a restart.
- It **dials out** to the stack over Tailscale, so it doesn't matter which network the phone is on, and no port has to be found.
- The stack's `phone` service gets a second driver behind the same tools. Every guard stays where it is, in the stack: Stop, block
  list, money always asks, approvals. The app holds no credentials beyond a token for that one connection.
- ADB remains the stronger tool when it is there. Uninstalling apps and deleting files need it (or a confirmation on the phone), so
  those steps run or wait for Wi-Fi. Everything a finger can do works anywhere.

Options for the app: **DroidRun Portal**, an existing accessibility app with HTTP and WebSocket control (check its licence, whether it
can dial out, and pin the build), or **our own small app**. Its one-time setup, granting the accessibility permission, can run over ADB
at home on the owner's Allow. Known risk: some phones switch accessibility off after a restart, so that needs its own test on the AI phone.

**A bridge between the stages:** after each connection the stack can run `adb tcpip 5555`. ADB then listens on a fixed port on every network,
mobile data included, until the next restart. It needs no new app, but it opens ADB on all the phone's networks (still only for the paired key),
and it doesn't help after a restart. It is worth having only if Stage 2 is not built.

Not considered: rooting the AI phone. It wipes the phone, trips Knox and removes a safeguard.

## Decision

The owner, 4 Nov 2026: the AI phone will always be on Wi-Fi ("No, always Wi-Fi", DEC-42). So the requirement reads "on any Wi-Fi", and
**Stage 2 and the `adb tcpip` bridge are not built**. Stage 0 is done. Stage 1 is next and starts with the hotspot test, with the owner.
If Android turns out to ask on the hotspot every time, that goes back to the owner, since Stage 2 was the answer to that case.

## What would prove it done

From the Phone page, with the AI phone restarted: on home Wi-Fi and on the hotspot, the phone reports back by itself and carries out one
approved action, with no tap on the AI phone.
