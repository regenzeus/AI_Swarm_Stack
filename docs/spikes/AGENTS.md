# docs/spikes/: the stage 0 spike reports

One report per spike of docs/PLATFORM-DESIGN.md's stage 0 (§11): a short trial of one risky choice that ends in "yes,
this choice holds" or "no, use this replacement". Each holds the question, what was built, how it was run, the measured
results (numbers seen, never guessed), the verdict, what stage 1 takes from it, and what was not tested. The code of a
spike lives under `spikes/<name>/`. Every report is listed in `docs/README.md`.

## Rules

- A report records a trial on a date; it is not edited after the fact. A new trial is a new section with its date.
- A number in a report comes from a run of the spike's own command, and the report says which command.
