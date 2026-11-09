# converters/: export conversion

`bulk_convert.py` turns mail (mbox, `.eml`) and chat exports (ChatGPT, Claude) into one markdown file per item for
the vault, fully offline (`make ingest-exports`, input from `C:\AI\exports`). qmd indexes the output.

Personal data passes through here: never print message contents to logs, and never send them anywhere. Output
file names are derived from dates and subjects, not from addresses.
