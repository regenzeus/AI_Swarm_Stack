# tests/fixtures/jira: a stand-in Jira project

`five.json`: five made-up tickets of a project DEMO in Jira's own REST shapes (issue types, labels, custom fields,
issue links with their outward and inward phrases, the status changelog). `tests/test_domain_records.py` serves them
through its `StandInJira` client, asked as atlassian-python-api asks, to the real Jira adapter and the records cache;
the toy pack's `records.yaml` maps them (REC-01 to REC-08). No real system's names.
