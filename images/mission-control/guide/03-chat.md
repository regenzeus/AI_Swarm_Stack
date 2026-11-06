---
title: Chat with Hermes
kicker: Your assistant
part: Everyday use
icon: chat
minutes: 6
summary: Talk to Hermes like you'd talk to ChatGPT, except it knows your world and can use every tool in the stack.
views: [chat]
---
Hermes is the assistant at the center of the stack. The **Chat** tab is a full chat app: history, search, pinning,
attachments, model choice. What makes it different from ChatGPT is what Hermes can *do*. It searches your
vault, runs research on the web, starts and changes missions, e-mails you, files notes and assigns coding work.

## What Hermes can do here

These are the tools Hermes has in Mission Control right now. The list is live: when a new tool is added, it
shows up here.

```live
tools
```

On top of these, Hermes searches your vault and reports (qmd), asks the research agent to look things up on the
web, uses the code graph, and remembers facts about you across conversations.

```try
label: Search your own knowledge
chat: What do my notes and reports say about Acme Mining? Cite the files.
note: Hermes searches the vault and answers with links to the reports and wiki pages it used.
```

```try
label: Web research in one sentence
chat: Look up the latest news on Beta Materials and tell me what matters for an investor.
note: Hermes hands the question to the scout (the only agent allowed on the web), which reads the pages in an isolated reader and reports back.
```

## Models and effort

Pick the model and the reasoning effort under the message box. Both are remembered on each device.

```live
models
```

**Effort** controls how long the model thinks before answering: *low* for quick questions, *medium* for most
things, *high* or *extra high* for hard analysis. Higher effort is slower but costs nothing extra.

## Pictures and documents

Tap the **clip** to attach images or documents (PDF, Word, Excel, CSV, text, code). Images go to the model as images. For a
screenshot on a phone, **Screenshot or photo** sits above the keyboard; **Paste** adds a copied picture, and on a computer you
can paste or drop one in. You can also share a screenshot to Mission Control from the phone's own share menu.

In a chat, Hermes can also ask **Claude Code on your Windows PC** about your files there. It can only read, only in the folders
listed in `C:\\AI\\ops\\desk-folders.txt`, and never key or password files. It cannot run or change anything. Its tools are
`windows_status`, `windows_ask` and `windows_result`.
Documents are turned into text in the app, so even a long annual report works.

```try
label: Ask about a document
chat: I'll attach a PDF. Summarise it in five bullet points and list anything I should act on.
note: Attach any PDF with the clip before sending.
```

## Working with messages

- **Copy**: the icon under any message; code blocks have their own Copy button.
- **Edit**: change one of your messages and resend. The conversation continues from there.
- **Regenerate**: ask for a new answer to the same question.
- **Stop**: the send button turns into a stop button while Hermes works.
- **Rename, pin, search, delete**: tap the title to rename; use the chat list (the clock icon on a phone) for the rest.

You can close the app while Hermes is working. The answer is saved and appears on every device.

## What the chat made

When Hermes starts a mission, a build or a Claude task, adds a note to the vault or sends you an e-mail, the item
appears as a card under that answer. The card shows the item's state now (Being created, Queued, Running, Done,
Waits for you, Failed) and the headline of its latest result. One tap opens the item's page. A change, such as a
mission paused or triggers set, is one small line.

- **Made here · N** in the chat's header lists everything this chat made, newest first.
- The chat list shows small icons for what each chat made, so you can find the chat that started something.
- The item's page says **From a chat** under its title. Tap it to open the chat at the answer that made it.
- When a one-off mission or a Claude task ends, or a build waits for your review, the chat gets a line that says so,
  with a link. Daily briefings and other recurring missions don't write into the chat.

## Focus chats for a mission

Every mission has a **Tune** button that opens a chat about just that mission. Say what to track more or less,
add questions, or change the schedule. Hermes changes the mission for you.

```try
label: Tune one of your missions
open: "#/chat?mission={mission}"
note: A focus chat opens with the mission's goal and brief as context. Try "Focus more on regulatory news".
```

## How it saves tokens

Hermes keeps each conversation on its side, so the app only sends your new message, not the whole history again.
Long chats stay fast, and Hermes can condense older parts of a long conversation.
