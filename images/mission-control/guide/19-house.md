---
title: "The House: lights, plugs and Echos"
kicker: Home Assistant on the NAS, Hermes' hands in the flat
part: Everyday use
icon: house
minutes: 4
summary: Home Assistant on the NAS connects the stack to your Echos, the lights in the Alexa app and Tapo plugs. Hermes can switch them, speak on the Echos and answer when you say "Alexa, Hermes …".
views: [house]
---
**Home Assistant** runs on the NAS (always on, on your home network) and is the stack's hub for the flat. The stack
talks to it; it talks to your devices. Open **House** (Home → *Needs you* while it isn't set up, or the banner on
the Stack page).

## Setting it up (once)

1. **Create your Home Assistant account**: *Open Home Assistant* on your home Wi-Fi, pick a user name and password,
   set your location. Nothing is open to the internet; it is reached on the home network only.
2. **Connect it to the AI stack**: *Connect* sends you to Home Assistant's own sign-in and back. The stack keeps its
   own long-lived token, encrypted; it never sees your password.
3. **Sign in to Amazon**: *Add Alexa* opens Home Assistant's **Alexa Devices** integration. Enter your Amazon e-mail,
   password and the code from your authenticator app. Amazon must send its sign-in codes to an **authenticator app**
   (not SMS): Amazon → Your Account → Login & security → 2-step verification.
4. **Tapo plugs** (optional): Home Assistant usually finds them by itself under Settings → Devices; sign in with your
   TP-Link account there.

## What Hermes can do then

```try
label: Switch something
chat: Turn off all the lights.
note: Lights that live in the Alexa app are switched through an Echo (house_alexa); plugs and lights Home Assistant knows directly with house_switch.
```

- **house_status** lists every light, plug, switch and shutter Home Assistant knows, by room, and the Echos.
- **house_switch** switches one of them (on, off, dim, shutters up/down/position).
- **house_alexa** tells Alexa a command as if you said it ("schalte das Licht im Wohnzimmer aus"). That is how the
  stack reaches the lights you set up in the Alexa app.
- **house_say** speaks a message on one Echo, or on all of them with the announcement chime.

```try
label: Say something on the Echos
chat: Say on all Echos that dinner is ready.
note: Uses house_say with announce on every Echo.
```

## Home Assistant's menus

Whenever Home Assistant answers, the House page starts with its menus: Settings, Integrations, Voice assistants, People,
Devices and Logs, each opening that screen in a new tab (on your home Wi-Fi).

## Hermes on the AI phone

**Talk to Hermes on the AI phone** lists the steps that make the AI phone a speaker for Hermes, each with a button to
the exact screen: add the person "AI phone" (you choose its password), install the Home Assistant app and sign in,
then the app's Assist settings. The stack ticks a step off as soon as Home Assistant shows it done; the app's own
settings it cannot see, so those stay a plain instruction. Then say "Okay Nabu" and talk: the conversation is the
Voice chat.

## Talking to Hermes through an Echo

Say **"Alexa, Hermes, …"** or **"Alexa, frag Hermes …"**. Alexa first says it can't help (it doesn't know Hermes);
right after, the same Echo says "Einen Moment, Hermes kümmert sich darum", and then speaks Hermes' answer, within
about a minute. For bigger work ("schreib mir einen Newsletter über …") Hermes starts a one-off job and says where
the result will arrive. Only requests that start with "Hermes" are passed on; nothing else you say to Alexa is
kept. Switch the bridge off on the House page. For a real conversation without
Alexa in between, a Home Assistant Voice speaker is the better device.

## Safety

- **Protected things**: a plug or switch whose name says it powers the fridge, freezer, router, NAS, PC, server or
  similar is shown with *protected*, and so is everything the FRITZ!Box and NAS integrations offer (guest Wi-Fi, port
  forwards, a device's internet access, the NAS's restart), whatever it is called. Hermes can read it but never switch
  it, also not through an Alexa command. You can, on the House page. Name your plugs clearly in the Tapo app (e.g.
  "Fridge") so this works.
- **No shopping through Alexa**: commands that buy or order are refused.
- **Everything is logged**: *What happened* on the House page, the activity feed, and the run view (*house*).
- Upgrades and redeploys of Home Assistant: `make ha-deploy` (Operations).
