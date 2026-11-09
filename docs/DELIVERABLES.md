# A mission's results are the things you asked for (MIS-23 to MIS-27, 3 Nov 2026)

## Why

The owner asked a mission for two Markdown files, a design primer and a checkbox spec, as e-mail attachments. The
mission wrote both in full: 6,500 and 6,600 words, with 149 checkboxes. The owner got neither:

- Results listed only the run report, which said "delivery blocked".
- The e-mail carried that same report.
- The documents sat in the Ledger (#548 to #550), with no link from the mission.
- The stack could not do what was asked: the agent had no tool to save a file, and the e-mail sender could not
  attach one.
- Hermes had promised attachments in the chat without knowing either of these.

The rule: **Results shows what you asked for, first. A report about the work comes second.**

## Words

- **File** (deliverable): a thing the owner asked the mission to make. It has a name, such as `checkbox-spec.md`,
  and it is asked for, a draft or final.
- **Run report**: what one run did and found. Every run still writes one into the vault.

## What the owner sees

- **Results** (the agent page) is in this order:
  - **What you asked for**: one card per file, with its name, words, checkboxes, size, version, Final or Draft, how
    it was delivered ("E-mailed as attachment ✓", "Sent on Telegram ✓"), and Open, Download and Copy.
    - A file that was asked for and is missing is shown in red as **Asked for, not delivered**, with the reason and
      **Run again for it**.
    - Files the agent saved without being asked follow under "Also saved".
  - **Drafts in the Ledger**: the reports its runs wrote there, linked.
  - **Run reports**: a run that missed a file carries **Partial**.
- **The header** says "2 of 3 files delivered" and links to Results.
- **Home's result card** names the run's files, and anything not delivered in red. It opens Results.
- **The chat card** (APP-39) shows the files as one-tap chips, and missing ones in amber.
- **The file page** (`#/file?m=<slug>&n=<name>`) shows the file rendered, with Download, Copy, Pin and Delete. It
  lists the earlier versions, and each one can be opened and downloaded.
- **Files** (Stack → Files, `#/files`) shows every mission's files grouped by mission, the space used against the
  limit, the trash with Restore, the cleanup rules, and **Clean up now**, which first lists what it would do.

## Storage and cleanup

- **Where.** Files live in `/srv/ai/missions/files/<slug>/`, outside the vault's git. A file deleted from git stays
  in its history and keeps taking space; from a plain folder, deleting really frees it. The app reads the folder
  through its existing `/missions` mount. Only the runner writes there (SEC-12).
- **Layout.** Each mission's folder holds:
  - `<name>`: the current file;
  - `.versions/<name>/<stamp>-<sha8>`: earlier versions;
  - `files.json`: the manifest (per file: size, sha, words, checkboxes, the run that saved it, versions, deliveries,
    pinned; per run: asked, saved, missing).
- **Deleting** moves a file and its versions to `files/.trash/` for **30 days**. Restore is on the Files page.
- **The daily cleanup** (the runner's `files` thread, and Clean up now):
  1. keeps the newest **5** versions of each file;
  2. moves the unpinned files of missions archived (or removed) and untouched for **180 days** to the trash;
  3. empties what has been in the trash for **30 days**.
- **Limits.** One file can be at most **2 MB**. The e-mail's attachments together stay under 20 MB (Gmail's limit is
  25 MB). The Files page shows use against a **2 GB** limit (`FILES_QUOTA`), and above 80 % the owner gets a notice
  once a day.

## How it works

1. **Asked for at creation.** `mission_create(files=[{name, what}])`. Hermes fills it from the owner's words. The
   owner can change the list in Settings → Files it must deliver, or Hermes with `mission_update(files=…)`.
2. **Refused at once when impossible.** Allowed types are `.md`, `.csv`, `.json` and `.txt`.
   - A `.docx` or `.pdf` gets "Not possible … offer Markdown" back from the tool, before anything is created.
   - The tool descriptions say what can be made and how it is delivered.
   - The runner checks the same rules (`ops/files.py clean_name`). A test keeps the app's copy of them equal.
3. **Saved by the agent.** The tool is `file_save(mission, name, text | from_ledger, final)`.
   - It is on its own MCP server (`files`, port 8096), given only to the mission agent's key (`vk-mission`, its card
     in config/agents.yaml). The mission agent gets no mission or build powers.
   - The agent's prompts gain `prompts/mission.md` FILES (steps and task runs) and FILES_PLAN (the planner: the last
     step saves the files). Both are added only when files were asked for; the existing texts are unchanged.
   - A file saved during a run belongs to that run.
4. **Checked at the end of the run.** `check_run` compares the files asked for with the files that exist.
   - What is missing is recorded per run.
   - The run's summary starts "Partial: not delivered: …", and the run record gets an error step.
5. **Delivered.**
   - The e-mail becomes `multipart/mixed`: the designed report, then each file this run saved as an attachment with
     its own name. The report ends with "Attached: …" and "Not delivered: …".
   - Telegram sends each file as a document after the result's message. If that message was held for quiet hours,
     the files are not sent, and the file's card says why.
   - Each send is recorded on the file.
6. **Nothing lost before this.** Results lists the Ledger reports a mission's runs wrote, from their
   `ledger_upsert` results in the run record. The Bullet Heaven mission's documents are moved into its files once.

## Checks

- `tests/test_files.py`:
  - versions;
  - refusals (Word, path tricks, size);
  - saving from the Ledger;
  - the run's check;
  - real MIME attachments;
  - delivery recorded per file;
  - the partial run;
  - the trash and restore;
  - the cleanup rules and its dry run;
  - downloads and nothing outside the folder;
  - Hermes refusing a `.docx` before creating anything;
  - the Ledger drafts.
- Live check after landing: the Bullet Heaven mission's Results, its file pages and the Files page, on desktop and on
  a phone.
