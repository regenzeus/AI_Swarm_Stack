---
title: "Measures: records, links and numbers from your tracker"
kicker: The tracker of record
part: Everyday use
icon: target
minutes: 4
summary: The stack keeps a read-only copy of the tracker your work is recorded in, checks each record against what its type needs, and computes the measures your pack declares, each number with the records behind it.
views: [measures]
---
Where your work is recorded in a tracker (an issue tracker such as Jira), the stack can keep a **copy of it to read**:
every record with its type, status, the fields that matter and its links. It never writes to that tracker: the
copy goes one way, and a tracker set to read-only takes no comment, label or status change from the stack at all.

## What a record is

Your deployment's **pack** says what the tracker's items are: which issue type or label makes a change request, a
problem, an analysis, a review record, a test report or release notes; which fields each type needs; which records
it needs linked as its work products (a change request needs a test report linked as "verified by", for example); and
which links it must have. The stack names none of these itself.

A link counts from both ends: "DEMO-1 is tested by DEMO-5" on one ticket and "DEMO-5 tests DEMO-1" on the other are one
link, shown on both records.

## The Measures page

**Stack → Packs and trackers → Measures** on the tracker. At the top are the pack's measures, for example the share of
change requests with every work product, or the hours from a problem's report to the work on it. **Tap a number** to
see the records behind it: the ones counted and the ones not.

Below them:

- **Missing a work product**: records whose type needs a linked record they do not have, and which one.
- **Missing a link**: pick a link type and see the records without it.
- **Missing a required field**.
- **Record types**: how many of each, what each needs, and its template.

Each record has its own page: its fields, what it lacks, its links both ways, its status changes, and a link to it in
the tracker.

```try
label: Open the Measures page
open: "#/measures"
note: With a tracker that names its pack's records, the measures and the two lists show after the tracker poller's next pass.
```

## Approvals only you can give

A pack may say that a record reaching a status (a change request becoming Approved, say) needs a person in a role. Then
the stack does not make that change on its own: it waits until the person holding the role taps the approving choice.
Words, a standing rule, a default or a deadline never approve it. The record's page shows who approved and when.

## Where the numbers come from

The tracker poller reads the tracker every few minutes, only what changed since its last pass, and computes every
measure again. Nothing on this page is typed in by anyone, so a number changes when the tracker does.
