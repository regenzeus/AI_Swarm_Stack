---
title: "Your taxes: papers from your mail, a draft per year"
kicker: The tax desk
part: Everyday use
icon: coin
minutes: 4
summary: The tax desk finds your German income tax papers in the copy of your mail, files a copy of each in Steuern on the NAS, and prepares a draft per year from your earlier returns. Only ChatGPT reads them; nothing is submitted.
views: [tax]
---
The **tax desk** prepares your German income tax return, as a draft for you to enter in ELSTER yourself. It is not tax
advice, and it never submits anything anywhere.

## What it does

Once a month while a year is open, and whenever you start it:

1. It looks through the **copy of your mail on the NAS** by subject and sender only: Lohnsteuerbescheinigung,
   Beitragsbescheinigung, Spendenquittung, Jahressteuerbescheinigung, invoices from tradesmen and doctors, and more.
2. **Hermes with ChatGPT** reads each of those mails with its PDFs, one at a time: which year, which form and line,
   which amounts. No other model reads your tax papers, and Hermes has no tools while it does.
3. It **copies** each paper into `Steuern/<year>/<form>/` on the NAS, with the mail next to it, and keeps
   `Belege.csv`, a draft workbook `Steuer-<year>.md` and its questions in that year's folder.

A paper counts for the year it concerns: a Lohnsteuerbescheinigung for 2025 that came in February 2026 is filed under 2025.
Your Gmail and the mail copy never change; nothing is deleted.

## Where to find it all

- **Tasks → Your taxes** is the desk's one task. Its page shows **Your tax drafts** per year: the papers found per
  form, the sums per form line, what is missing, the questions for you, your earlier return as read, and the files.
  **Run now** on it starts the desk; each run shows there with its three steps.
- **The workbook**, **Belege** and **your return as read** open as pages from the year's Files. Each shows where the
  file lies on the NAS (`\\NAS\Shared_Data\Steuern\<year>\...`), copied with one tap for the Explorer.
- **The Tax reader** is the desk's agent (Tasks → Team): ChatGPT only, no tools.
- The figures show only on your own devices, signed in: never on the AI phone.

```try
label: Open Your taxes
open: "#/workflows"
note: Your taxes is under Needs you while it has a question for you, then Running now, Recent results or Scheduled; tap Taxes to see only it.
```

## Your earlier returns are its base

Your own returns for 2023 and 2024 (the ELSTER protocols in `Steuern/2023/` and `Steuern/2024/`) are read the same way.
The desk writes what it understood next to them (`Erklaerung-<year>.md`, check it once), and prepares 2025 and 2026 from
them: each recurring item is expected again, and the workbook says whether this year's paper came, is missing, is new,
or moved a lot against the year before.

## Correct it, answer it

- **Belege.csv** in each year's folder lists every paper. Change a form or an amount, or write `yes` under checked, and
  the desk keeps your change on every run; delete a row and it stays out.
- **Needs you** shows what only you know, under **Your taxes**: whether you are assessed alone or jointly, church tax,
  your commute in km and days, days at home, and the mails it could not sort. A tap or a number answers; the next run
  uses it. The questions never show an amount.

```try
label: See what the desk asks
open: "#/decide"
note: Questions from the tax desk are under Your taxes. Each answer is used on its next run.
```

> [!note] The workbook compares your figures with what the law sets for the year: the Arbeitnehmer-Pauschbetrag, the
> Homeoffice-Pauschale, the Entfernungspauschale (0.38 EUR from the first km since 2026), the Sonderausgaben- and
> Sparer-Pauschbetrag, the zumutbare Belastung and the 20 % for tradesmen and household services. Check every figure
> against its paper before you enter it.
