# ADR 0002: Generated code is not executed by default; MVP-1.5 runs it in a separate local process

**Status:** Accepted. MVP-1.5 (stage 6) implemented, off by default.

## Context

Running the generated pipeline answers the question users care about most:
does this code actually work on my file? It also means executing code a
language model wrote, from a prompt that contains user-controlled column
names, on the machine serving the API.

MVP-1 shipped with no execution at all. Every screen says so, and `GenResult`
has no field for a score, because a number that was never measured would look
exactly like one that was.

## Decision

1. **Off by default.** `ENABLE_LOCAL_EXECUTION=false`. With it off, the
   product is MVP-1 exactly: static checks only, and the "not executed" notice
   above the code.
2. **Local only.** `config.py` refuses to boot with execution on unless
   `DEPLOYMENT_ENV=local`. A hosted deployment cannot be started in a state
   that runs generated code without a container boundary.
3. **A separate interpreter.** Code runs under `RUNNER_PYTHON`, a dedicated
   venv (`backend/.venv-runner`) holding pandas, numpy and scikit-learn. The
   API's environment never imports scikit-learn. The API depends on a
   `Sandbox` protocol, so the phase-2 container runner is a new
   implementation of one method, not a rewrite.
4. **Only stored code runs.** `/execute` takes no body. It runs the pipeline
   this server generated and stored for the dataset's current profile.
   Re-profiling deletes that pipeline and its runs.
5. **Screened before running.** The three safety checks from the static
   report (syntax, import allowlist, dangerous calls) must pass, plus an
   execution-only preflight that refuses `open()`, dunder access, OS-reaching
   attributes, URLs and absolute paths. Correctness checks such as a near-miss
   column name do not block a run; running the code is how the user finds out
   what that mistake does.
6. **Contained run.** A fresh temp directory holding only `pipeline.py` and
   `data.csv`; an environment built from nothing, so no API key reaches the
   script; `python -I -X utf8`; stdin closed; output to files capped at
   `EXECUTION_OUTPUT_MAX_CHARS`; thread count capped; a hard timeout after
   which the whole process group is killed (`killpg` on POSIX, `taskkill /T`
   on Windows) and reaped in a `finally`.
7. **A sample, labelled as one.** The run sees `EXECUTION_SAMPLE_ROWS` rows
   (500 by default), drawn with a fixed seed, with every class guaranteed up
   to `EXECUTION_MIN_ROWS_PER_CLASS` rows. Output is shown verbatim under
   "Executed on a N-row sample", never parsed into a score field. `GenResult`
   still has no metric field; the run lives in a separate `RunResult`.

## Consequences

- This is a convenience on a developer's own machine, not a security sandbox.
  A determined script can still read files the user can read. The boot guard
  and the documentation say so plainly.
- A crash or timeout is a successful request (200) whose `RunResult` reports
  the failure. Refusals before starting use the error envelope:
  `EXECUTION_DISABLED`, `EXECUTION_UNAVAILABLE`, `PIPELINE_NOT_FOUND`,
  `VALIDATION_FAILED`, `EXECUTION_IN_PROGRESS`.
- Before execution can run anywhere but localhost, it needs the phase-2
  container boundary and authentication.

## Update: phase 2 landed

Both preconditions now exist, and the decision above is extended rather than
replaced:

- `DockerSandbox` implements the same `Sandbox` protocol, selected with
  `EXECUTION_BACKEND=docker`. Each run is a fresh container from
  `backend/runner.Dockerfile` (the same `runner-requirements.txt` as the local
  runner) with `--network none`, `--read-only`, a 64 MB `/tmp`, the inputs
  bind-mounted read-only, `--user 65534`, `--cap-drop ALL`,
  `no-new-privileges`, and memory, CPU and PID limits. On timeout the
  container is killed by name, because killing the `docker` CLI process
  alone would leave it running.
- The boot guard now reads: execution outside `DEPLOYMENT_ENV=local` requires
  `EXECUTION_BACKEND=docker`. A separate guard requires `API_TOKENS` for
  `DEPLOYMENT_ENV=hosted`, and every dataset route is rate limited per client.
- Container isolation shares the host kernel. It is the right boundary for
  running model-written data-science scripts with no network; it is not a VM.
