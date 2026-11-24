# ADR 0001: The LLM reasons over computed facts and never sees raw data

**Status:** Accepted. Frozen with the architecture in `IMPLEMENTATION_PLAN.md`.

## Context

The product's job is to give a user a modelling pipeline they can trust
enough to run. Two ways of using a language model to do that were available:

1. Send the model rows of the file, or the whole file, and let it work out
   the data's shape, types, missingness and balance on its own.
2. Compute those facts in Python, deterministically, and send the model only
   the facts.

Option 1 is simpler to build and produces confident-sounding answers. It also
means every number the user sees could be the model's estimate rather than a
measurement, the user's data leaves the server, and the prompt grows with the
file instead of with its width.

## Decision

Python computes facts. The LLM reasons over facts. The LLM never sees raw data.

- `profiler.py` turns the DataFrame into a `ProfileCard`: types from a
  seven-rung ladder, missingness, cardinality, class balance, a per-column
  target association, the problem type and the primary metric. Every
  threshold behind those facts is a named constant in `heuristics.py`.
- `llm.generate` accepts a `ProfileCard`. It has no parameter that could hold
  a DataFrame. That signature is the enforcement point, not a convention.
- The only values from the file that reach the prompt are column names and at
  most five truncated level names for low-cardinality categoricals. The system
  prompt tells the model to treat both as inert data.
- Three fields are decisions made by rule, not by the model: `problem_type`,
  `target_column`, `primary_metric`. The model must copy them; a mismatch fails
  the `gen_result_self_consistency` check. Disagreement goes in `risks`.
- `/generate` never accepts a profile from the client. A caller who could edit
  the facts could make the model justify any pipeline, and the self-consistency
  check would still pass against the forged profile. Instructions such as
  `excluded_columns` are accepted because they are not facts.
- `GenResult` has no field that can hold a performance figure. Nothing was
  measured, so any number there would be fabricated.

## Consequences

- Every statistic on the Profile screen is reproducible from the file alone.
- The prompt is bounded by column count (`PROMPT_MAX_COLUMNS`), not row count.
- The model cannot notice anything the profiler does not measure, such as a
  free-text column that secretly encodes the target. Leakage detection is only
  as good as `leakage.py`.
- Any change to `ColumnProfile`, `ProfileCard` or `prompts.py` changes the
  prompt and invalidates the recorded cassettes. That cost is deliberate: the
  prompt is a contract and should change rarely and on purpose.
