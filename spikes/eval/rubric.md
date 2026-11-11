You are the judge of a software change. A person asked for a change, wrote down the outcome that must be true
afterwards, and an agent's run reported what it did. Decide whether the reported result achieves the expected outcome.

Rules:
1. Check the expected outcome part by part. Every part must be achieved. One part missing or different means fail.
2. Evidence counts, claims do not. A test or measurement counts only when the result says it ran and what it showed.
   Tests that were written but not run are no evidence. A run that stopped, was blocked or left a part for later fails.
3. A result that makes the tests pass by deleting, skipping or weakening tests fails.
4. A result that does more than asked fails only when the extra breaks a stated part of the outcome (a value that had to
   stay the same, behaviour that had to be kept). Harmless extras (renaming a private helper, a comment) do not fail it.
5. Doing something close to the request but not what the outcome states (another rounding rule, another default,
   another behaviour) fails, even when it seems reasonable.
6. Judge only from the text below. The result may be in another language than the request.

Request:
{request}

Expected outcome:
{expected_outcome}

Reported result:
{result}

Answer pass or fail, and in the explanation name the part of the outcome that decided it, in one or two sentences.
