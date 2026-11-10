# The tax desk

Built 10 Nov 2026 (TAX-01 to TAX-08). The owner, 10 Nov 2026: "Could you make an agent that prepares my taxes by looking
through my email for last year and this year and searching for tax relevant stuff and filing it somewhere as a copy and
preparing my tax? German income tax." The owner's answers: the reader is **Hermes with ChatGPT** and no other model
reads tax content; the copies go to the NAS share **Shared_Data/Steuern**; the owner's own returns for 2023 and 2024
(ELSTER transmission protocols) are the base from which 2025 and 2026 are prepared.

The desk prepares a **draft** for the owner's own ELSTER return. It is not tax advice, and it submits nothing anywhere.

## What runs

One n8n workflow, **Tax desk** (`n8n/workflows/tax-desk.json`, made by `ops/n8n_gen.py chain`, listed in
`deployments/home/workflows.yaml`): Run now, and on the 3rd of each month at 07:00 once switched on
(`ops/n8n_switch.py n8n/workflows/tax-desk.json on`). Three steps through the step service, in this order:

| Step | What | Model |
|---|---|---|
| **Find tax papers** (crew job `tax-find`, `ops/tax.py find`) | The mail copy's index on the NAS (`index.sqlite`, opened read-only) from `window_from` on, by subject and sender only, against `config/tax.yaml` and the owner's own `/srv/ai/tax/rules.yaml` (keep, ignore). Each new candidate's text and its attachments' text (pdftotext on the NAS; a PDF without text is "needs OCR") come to `/srv/ai/tax/work/` (owner-only). The owner's earlier returns in `Steuern/<year>/` (HTML or PDF at the year's top level) too. | none |
| **Read them (Hermes, ChatGPT)** (agent `tax`, step kind `tax-read`, `ops/tax.py run_read`) | Each mail and each earlier return is one turn of the Hermes profile `tax` through the Conductor's Hermes adapter, marked as data. The answer per document is JSON: relevant, tax year, form and line, kind, role, amounts, date, issuer, § 35a labour share, reason, confidence. | ChatGPT through Hermes, nothing else |
| **File copies and prepare the drafts** (crew job `tax-file`, `ops/tax.py file`) | Copies on the NAS, Belege, the workbook per year, the questions. | none |

`ops/tax_nas.py` is what runs on the NAS: it travels with each ssh call (python3 there, standard library), reads the
mail copy only, and writes only under the Steuern share, never over a file.

## Only ChatGPT reads tax content (TAX-02)

The card `tax` in `config/agents.yaml`: harness `hermes`, model `gpt-sub` (the ChatGPT engine in
`ops/swarm_client.py` `ENGINE`), key `vk-tax` with no MCP grant, `step_kind: tax-read`. Its Hermes profile
(`config/hermes/configure-tax.sh`) uses gpt-sub for the model and every auxiliary task, and has every toolset off and no
MCP server, so it cannot hand a paper to Claude, the web or memory. `ops/tax.py guard` refuses to read through any
other card, profile or engine. The prompts are `prompts/tax.md` (SOUL, READ, PRIOR).

An answer that is no such JSON, a refusal, or a relevant paper read with a confidence under 0.5 is a question for the
owner, never a guess. A usage limit is waited out by the Conductor (the step goes back to pending); every answer read
before it is kept, and the next attempt reads only what is left. Between two papers the reader waits 2 s.

What the run itself keeps on the PC: the extracted texts and answers under `/srv/ai/tax` (mode 700), Hermes' own
session store of the `tax` profile, and the runtime record of each Hermes turn. Log lines, Home lines and the steps'
answers (which n8n keeps) name counts and forms only.

## The share (TAX-03, TAX-04)

```
Steuern/<year>/<form folder>/<date>_<issuer>_<kind>.<ext>   each relevant attachment, a copy
Steuern/<year>/<form folder>/<date>_<issuer>_<kind>.eml     the mail it came with
Steuern/<year>/Belege.csv, Belege.md                         the year's papers; edit Belege.csv
Steuern/<year>/Steuer-<year>.md, Steuer-<year>-<form>.csv    the draft workbook (years being prepared)
Steuern/<year>/Fragen.md                                     the open questions, with the subjects of unclear mails
Steuern/<year>/Erklaerung-<year>.json, .md                   an earlier return as the reader extracted it
```

The year is the year a paper concerns (a Lohnsteuerbescheinigung for 2025 mailed in February 2026 is filed under 2025).
A paper of 2024 or earlier is filed under its year and never summed into 2025 or 2026. Form folders: Mantelbogen,
Anlage-N, Vorsorgeaufwand, Sonderausgaben, Anlage-KAP, Haushaltsnahe-Aufwendungen, Aussergewoehnliche-Belastungen,
Anlage-Kind, Sonstiges.

The owner's corrections win: a value changed in Belege.csv (form, kind, amount, date, issuer, checked) is kept on every
run and used in the workbook; a row removed stays out. Any other desk file the owner changed stays as it is, and the
desk's new version goes next to it under a numbered name. Nothing is ever deleted, and Gmail and the mail copy are never
changed.

## The workbook (TAX-05, TAX-06)

Per form its lines with sums and papers; then the comparisons with the year's figures; then what the earlier returns
lead to expect (each recurring item found, missing, none this year by the owner's word, or **moved a lot**: more than half
and more than 100 EUR against the last return), the items **new this year**, the open questions, and the table of
figures with their sources.

## The figures the law sets (ops/tax_law.py)

Checked on 10 Nov 2026. One table in `ops/tax_law.py`; a year missing from it is said, never guessed.

| Figure | 2025 | 2026 | Where |
|---|---|---|---|
| Arbeitnehmer-Pauschbetrag | 1,230 EUR | 1,230 EUR | § 9a Satz 1 Nr. 1a EStG |
| Homeoffice-Pauschale | 6 EUR a day, at most 1,260 EUR | the same | § 4 Abs. 5 Satz 1 Nr. 6c EStG |
| Entfernungspauschale | 0.30 EUR for km 1 to 20, 0.38 EUR from km 21 | 0.38 EUR from the first km | § 9 Abs. 1 Satz 3 Nr. 4 EStG; Steueränderungsgesetz 2025 |
| Cap without one's own car | 4,500 EUR | 4,500 EUR | § 9 Abs. 1 Satz 3 Nr. 4 EStG |
| Sonderausgaben-Pauschbetrag | 36 / 72 EUR | 36 / 72 EUR | § 10c EStG |
| Sparer-Pauschbetrag | 1,000 / 2,000 EUR | 1,000 / 2,000 EUR | § 20 Abs. 9 EStG |
| Altersvorsorge, highest amount | 29,344 / 58,688 EUR | 30,826 / 61,652 EUR | § 10 Abs. 3 EStG |
| Other Vorsorge, highest amount | 1,900 / 2,800 EUR | 1,900 / 2,800 EUR | § 10 Abs. 4 EStG |
| § 35a household services | 20 %, at most 4,000 EUR | the same | § 35a Abs. 2 EStG |
| § 35a tradesmen | 20 %, at most 1,200 EUR | the same | § 35a Abs. 3 EStG |
| Grundfreibetrag | 12,096 / 24,192 EUR | 12,348 / 24,696 EUR | § 32a Abs. 1 EStG |
| Arbeitsmittel at once (GWG) | 800 EUR net | 800 EUR net | § 6 Abs. 2 EStG |
| Zumutbare Belastung | 5/6/7 % (single), 4/5/6 % (joint), 2/3/4 % (1 or 2 children), 1/1/2 % (3 or more) of the Gesamtbetrag der Einkünfte up to 15,340 / to 51,130 / above, computed in steps | the same | § 33 Abs. 3 EStG; BFH VI R 75/14 |

2023 and 2024 are in the table for comparisons with the earlier returns only (2024's Grundfreibetrag 11,784 EUR after
its raise of December 2024).

Sources:
- EStG on gesetze-im-internet.de: https://www.gesetze-im-internet.de/estg/ (§ 4: https://www.gesetze-im-internet.de/estg/__4.html,
  § 33: https://www.gesetze-im-internet.de/estg/__33.html)
- the yearly table of Pauschbeträge, Freibeträge and Höchstbeträge for 2025 and 2026:
  https://www.steuertipps.de/finanzamt-formalitaeten/pauschbetraege-freibetraege-und-hoechstbetraege-fuer-die-steuererklaerung
- the Steueränderungsgesetz 2025 (Bundestag 4 Dec 2025, Bundesrat 19 Dec 2025):
  https://www.bundestag.de/dokumente/textarchiv/2025/kw49-de-steueraenderungsgesetz-1128142
- BFH, Urteil vom 19.01.2017, VI R 75/14: the zumutbare Belastung in steps

## Questions (TAX-07)

Each open question is a Needs you item of the class **Your taxes**: assessed alone or jointly, church tax, the commute's
km and days and the home-office days (from December of the year on), children, a mail it could not sort (Keep / Not a
tax paper), and an expected paper that never came (asked from 1 June of the next year on: I will add it to the folder /
None this year). A number is typed; a choice is a button. The texts name dates, forms and kinds, never an amount; the
subject of an unclear mail is in `Steuern/<year>/Fragen.md`. The runner refuses an answer that is not offered, not a
number of 0 or more, or over 200 characters (action `tax_answer`), and the next run uses it.

## Years

`config/tax.yaml`: prepare 2025 and 2026, earlier returns 2023 and 2024, mail from 1 Oct 2024 on (a year's papers come
from three months before it to the end of the year after it). A prepared year is open until the end of the next year;
a run with no open year finds nothing.

## Not done yet

- Papers the owner drops into a form folder by hand are not read (only the earlier returns at a year's top level).
- Scanned PDFs are named "needs OCR", not read.
- The first live run on real mail is the lead's (see the landing notes in the branch's report).
