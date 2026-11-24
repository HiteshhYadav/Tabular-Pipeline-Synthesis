# Agentic AutoML (AutoNexus)

Binding rules for any contributor, human or AI, working in this repository.
Read `IMPLEMENTATION_PLAN.md` for the build order and `docs/not-building.md`
before proposing a feature.

## Core rule
Python computes facts. The LLM reasons over facts. The LLM never sees raw data.
`llm.py` accepts a `ProfileCard`, never a DataFrame. Do not change that signature.

## Hard constraints
- No LangChain, LangGraph, Instructor, ydata-profiling, Redis, Celery,
  SQLAlchemy, pyarrow. Do not add dependencies without asking.
- Gemini SDK is `google-genai`. NOT `google-generativeai` (deprecated).
- All thresholds live in `backend/app/heuristics.py` as named constants, each
  with a comment defending the number. No magic numbers anywhere else.
- `GenResult` has no field that can hold a metric value. Never add one. The
  generated code is not executed by default, so any score in it would be
  fabricated. When MVP-1.5 execution is switched on, the only measured output
  is the raw stdout of a run on a small sample, stored in `RunResult` and
  labelled as such - never copied into `GenResult`.
- CSV reads use the pandas C engine everywhere, including in generated code
  and in the execution sample writer.
- pandas stays below 3.0 in both the API venv and the runner venv.
- No em dashes in any output, comments, or docs. Use hyphens.

## models.py has two audiences
`#` comments are for humans. Docstrings and `Field(description=...)` on any
class reachable from `GenResult` are prompt surface - google-genai sends them
to the model. Engineering rationale never goes in a docstring there.

## GenResult field order is load-bearing
Strategy fields must precede `code` so the model plans before it writes.
Do not reorder.

## The cassette trap
Any change to `ColumnProfile`, `ProfileCard`, or `prompts.py` changes the
prompt hash and invalidates every recorded cassette in
`backend/tests/cassettes/`. Re-recording costs real Gemini quota. Batch such
changes and re-record once. New prompt text for retry rounds lives in `llm.py`
and is appended only on a retry, so the first-round prompt hash is unchanged.

## Code execution (MVP-1.5)
- Off by default. `ENABLE_LOCAL_EXECUTION=true` is refused at boot unless
  `DEPLOYMENT_ENV=local`.
- Generated code runs only in a subprocess, using the separate runner venv
  (`backend/.venv-runner`), never in the API process and never with the API's
  environment variables.
- Only code the server itself generated and stored is executed. The client
  never sends code to run.
- The process group is killed on timeout and reaped in a `finally`; with the
  Docker backend the container is killed by name as well.
- Only `EXECUTION_BACKEND=docker` may execute outside `DEPLOYMENT_ENV=local`.
  Do not loosen that guard, and do not drop any `docker run` isolation flag
  in `DockerSandbox.command` without a test proving it is unnecessary.

## Data that must stay off the prompt
`distributions.py` exists so per-level counts and histograms reach the user
without reaching the model. Never add distribution data, or anything else
derived from raw values, to `ColumnProfile` or `ProfileCard`.

## Access control
- `API_TOKENS` is mandatory for `DEPLOYMENT_ENV=hosted` (boot guard).
- Every new `/datasets` route inherits the token check and the default rate
  budget from the router. Expensive routes add their own `security.limit(...)`.
- Never log, echo, or put a token in a URL.

## Testing
Profiler and validator changes require a fixture. Never assert on exact LLM
prose; assert structural invariants only. LLM tests run offline against
cassettes or `StubProvider`; the test suite never calls the network.
Frontend: `npm test` (Vitest); every fetch is stubbed. CI runs both suites
plus the live Docker sandbox tests.
