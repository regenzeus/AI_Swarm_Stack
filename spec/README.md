# Spec comprehension and code checking

Goal: give the stack large specifications (target: ~100 PDFs, ~100,000 requirements), let it understand them, chat
with them, and check code against them, with measured accuracy. Pilot: the MQTT 5.0 standard (OASIS PDF, 137 pages)
against the mochi-mqtt broker (Go), whose code carries 186 requirement IDs that serve as the answer key.

## Pipeline

| Step | Script | Model | What it does |
|---|---|---|---|
| 1 ingest | `ingest.py` | none | PDF -> sections (headings, pages), requirements with IDs; drops page headers/footers; one page per section for search (qmd collection `specs`) |
| 1b extract | `extract.py` | gpt-sub-fast | specs without IDs: atomic requirements per section, incl. implicit ones; combined with MUST/SHALL sentences (`pilot/extract_baseline.py`) |
| chat | Hermes + qmd `specs` | gpt-sub | "what does the spec say about X", answers with section and requirement IDs |
| 2 link | `link.py` | gpt-sub-fast | requirement -> functions: keyword search over all functions of the code graph (top 40), optional model query expansion, model picks <= 3 |
| 3 judge | `judge.py` | gpt-sub or cheap | verdict per requirement: implemented / contradicted / partial / missing / not_here / not_applicable, with lines as evidence; sees linked functions plus their callers/callees |

## Results (pilot, 2026-10-26)

- Ingest: 289 sections, 252/252 numbered requirements found, no empty texts.
- Extraction without IDs, chapters 3.1-3.3 (105 numbered requirements): keyword sentences 104, model 97, combined 105/105.
  The spec has 460 MUST/SHALL sentences; only 252 are numbered.
- Linking, 91 requirements with ground truth: keyword stage 86% (right function among 40), model 73% exact,
  77% exact-or-caller/callee (v1 was 68%; showing the best-matching passage of each function did most of it).
- Judging, 7 planted one-line deviations (+2 requirements they also break) and 11 untouched controls:
  - subscription model, pipeline links: 6/9 as deviation, 1 as needs-review, 2 missed (both: linking found no code)
  - cheap model (gpt-oss-20b): 5/9 deviation, 2 needs-review, 2 missed; $0.003 for 20 judgments
  - false deviations on untouched requirements: 0 in the pipeline runs; on the original code the judge also
    reported MQTT-3.2.2-20 (user properties size check ignores other properties already encoded), which reading
    the code confirms as a real edge-case deviation in mochi-mqtt, and 3.3.2-5 (< vs <= on expiry, pedantic).
  - "contradicted" is reliable; "partial/missing" is mostly missing context (v2 cut that noise from 4-7 to 0-1).

### Linking iterations (same 91 requirements with ground truth)

| Version | Change | Right function among candidates | Model picked it (exact) |
|---|---|---|---|
| v1 | first 40 lines per candidate | 86% (top 25-40) | 68% (31 req.) |
| v2 | best-matching passage per candidate | 86% | 73% |
| v3 | + model query expansion (3.1 only) | 88% (3.1) | 71% (3.1) |
| v4 | + adjacent words joined ("Keep Alive" -> keepalive), 60 candidates | 93% | 70% |

Finding is now good (93%); choosing among 60 candidates is the bottleneck. Next: two-stage choice (signatures ->
shortlist of 10 -> full bodies -> pick), or the stronger model for the pick. Judge v4 on the deviated copy: 6/9 as
deviation (Keep Alive now found, 3.1.2-24 lost to a receive-side link), 1 needs-review, 2 missed; run-to-run noise ~1.

## Lessons

1. Deterministic first, model second: keyword extraction and search do most of the work cheaply; the model splits,
   catches implicit rules, picks and judges.
2. Linking is the bottleneck: every missed deviation was a linking miss. Measure it separately (oracle runs).
3. Planted deviations must be checked to be effective (the first wildcard change was masked by a second check).
4. Two verdict tiers: deviation (act on it) vs needs-review (a human looks).

## Scale-up estimate (100,000 requirements)

- ingest + keyword extraction: offline, minutes per PDF
- model extraction: ~1 call per section (~20,000 sections)
- link: 1-2 calls per checkable requirement; judge: 1 call per linked requirement
- on the cheap model about $15 per 100k judgments (measured) plus similar for linking: roughly $30-40 per full
  pass; afterwards only changed requirements/code are re-run. On the ChatGPT subscription: free but weeks.
- confidentiality: company specifications should not go through a personal ChatGPT subscription.
