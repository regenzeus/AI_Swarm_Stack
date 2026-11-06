# Hermes at home: one running conversation, by voice, in every room

Design, 1 November 2026. Status: V0 done (the measurements below; speech to text and the voice run on the NAS,
`nas/voice/compose.yaml`). V1 in progress: the voice gateway, the *Voice* chat, "let me check" and the voice prompt
are built (VOI-03 to VOI-05); Home Assistant's pipeline and the AI phone's satellite app are next. The NAS cannot reach
the PC by itself (the PC's WSL sits behind NAT, and the NAS has SSH tunnels off): Windows passes port 11434 on to the
gateway (11435 on the PC, because the owner's Ollama app holds Windows' own 11434) from the NAS's address only, two commands the owner runs as administrator. It builds on the House service (`ops/house.py`,
requirements HSE-01 to HSE-08), Hermes' chat and mission tools ([MISSION-CONTROL.md](MISSION-CONTROL.md)).

## What the owner wants

Read from the request of 1 November, not only its words:

1. **Say "Hermes" and talk.** No "Alexa, frag Hermes": Hermes has a wake word of its own, and Alexa keeps
   "Alexa". Each
   answers only to its own name.
2. **A conversation, not a command.** Follow-up questions without the wake word again, long answers when asked for,
   interruptions, "what did we say earlier": the voice is one always-running chat with the stack.
3. **In English**, while Alexa stays German.
4. **Anywhere in the flat**, with the stack's whole reach: start any mission, ask about results, switch the house.
5. **Without talking to Alexa.** Alexa may stay for what it does today; it is not the way to Hermes.

## What is possible, and what is not

**An Echo cannot listen for "Hermes".** Its wake word is one of Amazon's fixed list (Alexa, Amazon, Echo, Computer,
Ziggy), and what its microphones hear goes only to Alexa. A third party reaches an Echo's microphone only through an
Alexa skill ("Alexa, open Hermes"), which also needs an endpoint reachable from the internet. Today's bridge reads
Alexa's transcript after Alexa has answered (HSE-07): one question at a time, Alexa's "Ich weiß nicht" first.

So the microphone has to be a device of our own in each room. The Echos keep doing Alexa's work, side by side.

| Way | "Hermes" alone | Conversation | Hermes' voice, English | Public exposure | Verdict |
|---|---|---|---|---|---|
| Today's bridge (Alexa Devices transcripts) | no ("Alexa, frag Hermes") | no, one shot | Alexa's voice | none | keep as the fallback |
| Alexa custom skill | no ("Alexa, open Hermes") | yes, until 8 s of silence | Alexa's voice; language follows the Echo | an internet-facing endpoint | no |
| **Voice satellites of Home Assistant, Hermes as their agent** | **yes** | **yes** | **own English voice** | **none: all on the home network** | **proposed** |
| The phone (the app's chat by voice) | push-to-talk | yes | yes | none (Tailscale) | a complement: the same conversation outside the flat |

## The proposal

A small voice speaker in each room where you want Hermes (a satellite), running Home Assistant's voice pipeline in
English with Hermes as the conversation agent. Recommended device: the **Home Assistant Voice Preview Edition** (around
60 €, open firmware, the wake word runs on the device, a good microphone array, a jack for a better speaker). Start
with one, in the room you talk most in.

```
 room                          NAS (Home Assistant + two small services)        PC (the stack)
 ┌────────────────────┐        ┌─────────────────────────────────────┐        ┌───────────────────────────────┐
 │ satellite          │ audio  │ Assist pipeline "Hermes (English)"  │  text  │ voice gateway (runner)        │
 │ wake word "Hermes" ├───────►│  speech to text: Parakeet, local    ├───────►│  one session per house,       │
 │ on the device      │        │  conversation agent: Hermes ───────────────► │  the "Voice" chat, run record,│
 │ LED ring, speaker  │◄───────┤  text to speech: Piper, local       │◄───────┤  voice rules, background work │
 └────────────────────┘ speech └─────────────────────────────────────┘ stream └──────────────┬────────────────┘
                                                                                               │ Hermes (chat API),
 Echo Dots: Alexa as today ("Alexa, …"); Hermes may still announce on them                     │ its tools, missions
```

### The pieces

1. **Wake word "Hermes" on the satellite.** A custom microWakeWord model, trained once from synthetic voices and
   flashed with ESPHome. Short wake words wake by mistake more often: "Hermes" (two syllables) is tested against
   "Hey Hermes" (three) for 24 hours with the TV on; the owner picks with the numbers.
2. **Speech to text on the NAS.** NVIDIA's Parakeet (English, int8, through sherpa-onnx) behind Home Assistant's
   Wyoming protocol: the fastest and most accurate of the three measured in V0 (below). Audio never leaves the flat
   and is never stored.
3. **Text to speech on the NAS.** Piper, an English voice the owner picks (British or American), about 0.1 GB, and
   it speaks sentence by sentence while Hermes is still writing.
4. **Hermes as the conversation agent.** Home Assistant hands each utterance to the stack's voice gateway and streams
   its reply back. The gateway answers like an Ollama server, so Home Assistant's own **Ollama** integration connects to
   it (a URL and an API key, streaming): no code of ours inside Home Assistant, which holds the NAS admin password.
   Each room is one agent of that integration with its own model name (`hermes:kitchen`), so the gateway knows the
   room. Home Assistant's "control Home Assistant" option stays off: Hermes switches the house with its own tools.
5. **The voice gateway in the runner.** The one place that knows a voice turn: it keeps the session, writes every turn
   into the "Voice" chat, applies the voice rules below, records the run, starts background work and speaks its
   result later.

### The conversation

- **One running chat.** Every voice turn lands in a chat called *Voice* in Mission Control, tagged with its room. It
  is the same Hermes session in every room and on the phone: start in the kitchen, continue in the office, read it
  back on the phone, answer there in writing. "Hermes, new topic" starts a fresh thread; older turns are summarised
  into Hermes' memory as in any chat.
- **Follow-ups without the wake word.** Home Assistant keeps the satellite listening when the reply ends with a question
  mark (measured in its code, V0). So Hermes ends a turn with a question when it expects an answer, and while a
  conversation is going ("Hermes, let's talk" … "thanks, that's all") every turn ends with one; the LED ring shows it
  listens. Silence ends it.
- **Interrupting.** "Hermes, stop" while Hermes talks stops the answer; a new question replaces the old.
- **Long form when asked.** By default two or three spoken sentences; "tell me more", "go into detail", "read me the
  report" give the long answer, spoken in parts with "shall I go on?" between them.
- **Spoken style.** A voice prompt of its own (prompts/main.md, VOICE): English, no lists or links, numbers and dates
  said the way people say them, a question back when the request is unclear.

### Speed

Measured on the bridge's question of 1 Nov: Hermes decided in 2 s, then the research scout took 51 s. The rule:
**nothing slow happens while you wait.**

| Step | Budget | Measured in V0 (1 Nov) | How |
|---|---|---|---|
| Wake word | instant | (V1: on the device) | on the device |
| Speech to text | under 1.5 s | **0.82 s** median, 1.47 s slowest | Parakeet on the NAS |
| Hermes' first word | under 2 s | **1.3 to 1.6 s** for a plain answer; 5.5 to 6.8 s when a tool is needed | streaming through the chat API |
| Voice starts | under 1 s | **0.82 s** median for the first audio | Piper, sentence by sentence |
| First word heard | under 4 s in all | about **3.2 s** plain; about 8 s with a tool | |
| Anything slower (research, a mission, a long text) | in the background | the bridge's research took 51 s | "On it, I'll tell you when it's ready"; the conversation goes on |

A turn that needs a tool would leave 6 s of silence: the gateway says "Let me check" the moment Hermes calls a tool,
and V1 trims Hermes' voice context (the bridge's turn carried 180,000 input tokens) to bring the tool answers down.

### V0: what was measured

Run on the NAS with `ops/voice_bench.py`: 20 sentences one says to Hermes at home, spoken by three Piper voices other
than Hermes' own with white noise added, through each speech-to-text model; five of Hermes' typical answers through
three candidate voices; five harmless questions through Hermes' chat API, streamed. Synthetic speech is cleaner than
a person across a room: V1 repeats the speech test with the owner's voice.

| Speech to text (noise 20 dB below speech) | Word errors | Sentences exactly right | Time per sentence (median, slowest) | Memory |
|---|---|---|---|---|
| Whisper small (English, int8) | 3.7 % | 17 of 20 | 7.0 s, 7.9 s | 0.79 GB |
| Whisper base (English, int8) | 4.4 % | 16 of 20 | 2.0 s, 2.2 s | 0.38 GB |
| **Parakeet TDT 0.6B v2 (int8)** | **2.5 %** | **17 of 20** | **0.82 s, 1.24 s** | 1.1 GB loaded, 0.83 GB settled |
| Parakeet, noise 10 dB below speech | 3.1 % | 17 of 20 | 0.82 s, 1.47 s | |

Most "errors" are style: "6" for "six", "30%" for "thirty percent". The real ones: Whisper base heard "NES" for NAS;
all three stumbled on "Hermes what is on" once (the wake word is cut off before speech to text on a real satellite).

| Hermes' voice (Piper, medium) | First audio (median, slowest) | Time to speak / length of speech |
|---|---|---|
| en_GB alba | 0.82 s, 2.3 s | 0.24 |
| en_US lessac | 1.1 s, 2.1 s | 0.26 |
| en_GB cori | 1.1 s, 2.4 s | 0.26 |

The NAS keeps 1.2 GB free with both services running (Home Assistant 0.43 GB, Parakeet 0.83 GB, Piper 0.04 GB).

When background work is done, the gateway says so in the room you last spoke in (if you are home, from the router
presence, and not in quiet hours), otherwise a push to the phone as today.

### Missions by voice

Hermes' existing tools do the work: start a mission ("research X and send me the result", a one-off), run one now,
pause it, ask for its last result, start a task. What changes by voice:

- **Say back before acting.** "I'll start a one-off research on mesh repeaters for your router and send the result
  to Telegram. Shall I?" A yes starts it. Reading and answering need no confirmation.
- **Approvals stay in the app.** A purchase, a deploy, e-mail to anyone but the owner, deleting, the NAS and the network
  are never done by voice: Hermes says where to approve it. Voice is a shared channel: a guest, a child or the TV can be
  heard.
- **Private things aloud** (mail contents, calendar details, money) are the owner's decision: never, always, or only
  when the presence says the owner is home alone.

### Observability

Every voice turn is a run in the record: the room, wake to transcript, the transcript, Hermes' first sentence, the
tool calls, speech start and end, the whole time; what started in the background and when it reported back. A
*Voice* page shows the turns per room, the time to first word (median and slowest), false wakes per day, misheard
turns (a correction right after), and a health line when speech to text or the voices are down. A nightly journey
sends a text into the pipeline and checks the answer arrives.

### Privacy and security

- No audio is stored; the wake word and the speech recognition run in the flat. Only text goes to the model, as with
  every chat.
- Nothing is exposed to the internet: no Alexa skill, no port forward. The phone reaches the same chat through
  Tailscale as today.
- The satellites and Home Assistant only carry speech and text; the gateway decides what Hermes may do by voice.
- A false wake costs nothing but an "I didn't catch that": no action runs without being said back first.

## The AI phone as a speaker

The owner asked (1 Nov) whether the AI phone can be the speaker. It can, as the first satellite, at no cost, with
limits.

**How.** An Android app that makes a phone a Home Assistant voice satellite: the wake word on the phone, the speech to
the same pipeline as a Voice Preview Edition, the answer from the phone's speaker. It has to run as a background
service, because the agents use the AI phone's screen (purchases, clean-ups) and a page in the foreground would fight
them. Candidates are checked in V1 (an open-source satellite app, or the Home Assistant app's own Assist); the stack
installs it only with the owner's OK, like every app on the AI phone.

**What changes on the AI phone.**
- The agents may never stop, open or reconfigure the satellite app (it goes on the phone's protected list), and their
  phone tools get no microphone access: the microphone belongs to the satellite alone.
- It listens only for the wake word on the phone; nothing is sent before it.
- It stays plugged in (it is today); its battery protection (charge to 80 %) is switched on.

**Its limits, against a Voice Preview Edition.**

| | AI phone | Voice Preview Edition |
|---|---|---|
| Microphone | one, for a person near the phone (about 2 to 3 m, a quiet room) | an array built for across the room, with echo cancelling |
| Speaker | small | small, with a jack for a better one |
| Shared with | the agents' purchases and clean-ups | nothing |
| Cost | none | about 60 € |

**Proposal.** V1 starts on the AI phone where it stands: everything behind the microphone (gateway, *Voice* chat,
conversation, missions) is built and tested without buying anything. A Voice Preview Edition follows for the room you
talk most in, once V1 works; a spare old phone or tablet would serve as well as the AI phone, without sharing it.

## V1: what the owner does

Two steps only the owner can take; everything else is set up by `ops/voice_setup.py` (VOI-06).

**1. On the PC, once, in PowerShell as administrator** (Home Assistant on the NAS reaches the voice gateway; nothing else
on the network can):

```
netsh interface portproxy add v4tov4 listenaddress=192.168.1.20 listenport=11434 connectaddress=127.0.0.1 connectport=11435
New-NetFirewallRule -DisplayName "Hermes voice gateway (NAS only)" -Direction Inbound -Action Allow -Protocol TCP -LocalAddress 192.168.1.20 -LocalPort 11434 -RemoteAddress 192.168.1.10
```

The PC's address should stay 192.168.1.20: in the router, Heimnetz → Netzwerk → the PC → "Diesem Netzwerkgerät
immer die gleiche IPv4-Adresse zuweisen".

**2. On the AI phone** (the Galaxy AI phone): in Home Assistant, Settings → People, add a person "AI phone" who may log in
and is not an administrator; on the phone, install the Home Assistant app from the Play Store and sign in as that
person; in the app, Settings → Companion app → Assist: make Home Assistant the default assistant, switch the wake word
on, and pick the pipeline "Hermes". The agents can never open that app (VOI-07).

## The phases

| Phase | What | Done when |
|---|---|---|
| V0 Prove | speech to text and voices on the NAS, measured on 20 spoken samples (time, RAM, mistakes); Hermes' first word measured; which built-in integration the gateway can speak | done 1 Nov: the numbers above; Parakeet, Piper and the Ollama integration chosen |
| V1 One room | the gateway (Ollama-compatible), the pipeline in English with a stock wake word on the AI phone, Hermes through the gateway, the *Voice* chat, "let me check", run records; the speech test with the owner's voice | a spoken question is answered in under 4 s on a quiet evening |
| V2 "Hermes" | the wake word trained and flashed; 24 h with the TV on for "Hermes" and "Hey Hermes" | false wakes below one a day; the owner picks |
| V3 Conversation | follow-ups without the wake word, interrupting, long form in parts, the same session on the phone | a ten-minute conversation without repeating the wake word |
| V4 Missions | say-back, background work, the result spoken in the room you are in, quiet hours | "research X" by voice ends with the result spoken or pushed |
| V5 Every room | more satellites, the *Voice* page, the nightly journey | each room answers; the page shows a week |

Requirements live in requirements/voice.yaml: VOI-01 and VOI-02 came with V0 (the services on the NAS, the
measurement); each later phase adds its own in the same commit as the code, as for every area.

## Decisions for the owner

| # | Decision | Proposal |
|---|---|---|
| 1 | The first satellite | the AI phone for V1 (no cost); then one Voice Preview Edition, in the room you talk most in |
| 2 | Wake word | test both, decide by the false-wake count |
| 3 | Speech recognition | decided by V0: Parakeet on the NAS (free, 0.8 s); Home Assistant Cloud is not needed |
| 4 | Private things aloud | only when you are home alone |
| 5 | Hermes' voice | pick from three Piper voices in V1 |
| 6 | The Echos | stay as they are: Alexa for Alexa; Hermes may announce on them |
