# Development notes

Local-dev gotchas and traps that have already cost real time once. Read this
before touching `ColumnProfile`, `ProfileCard`, `prompts.py`, or the LLM
layer - most of what is here exists because one of those changes broke
something non-obvious.

This file replaces an earlier `docs/CONTEXT.md` handoff briefing. Everything
below was re-verified against the working tree, not carried over from memory.

---

## Running it day to day

```bash
# Backend - there is no bare `python` on PATH in a fresh venv; use .venv's
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```

Open **`http://localhost:5173`**, not `127.0.0.1`. The backend's default CORS
allowlist (`CORS_ORIGINS` in `.env`) contains only `http://localhost:5173`.
The mismatch is confusing to debug because the request actually succeeds
server-side and only the browser refuses the response - it looks like a
network failure, not a config mismatch.

Port 8000 is a popular default and collides with other local tooling often.
If it's taken, run the backend on another port and point the frontend at it
via `frontend/.env.local`:

```
VITE_API_BASE=http://localhost:8001/api
```

keeping `CORS_ORIGINS` in the backend's `.env` in step with wherever the
frontend actually serves from.

## The cassette trap

`backend/tests/cassettes/*.json` are three real recorded Gemini responses,
keyed by `sha256(system_prompt + "\n---\n" + user_message)[:16]`.

**Editing `ColumnProfile`, `ProfileCard`, or anything in `prompts.py` silently
invalidates all three.** The affected tests fail with a `FileNotFoundError`
naming a hash that no longer has a cassette. `test_prompts.py` independently
asserts prompt structure and fires first, as the intended tripwire, but it
does not prevent the cassette break - only makes the cause easier to find.

Re-recording costs real Gemini quota (`backend/tests/record_cassettes.py`).
Batch every prompt-affecting change into one PR and re-record once, not per
commit.

## Gemini quota specifics

- **Free-tier quota is per project, per model**
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, 20/day). Keys issued
  from the same Google Cloud project share one bucket, so configuring
  `GOOGLE_API_KEY1/2/3` buys 429 failover, not more requests per day.
- **Changing `LLM_MODEL` grants a fresh bucket.** The fastest way to unblock
  mid-session if the daily quota is exhausted.
- **`HttpOptions.timeout` is in milliseconds**, and Gemini enforces roughly a
  10-second floor below it - go under that and the request 400s immediately
  rather than timing out. A genuine deadline surfaces as
  `ServerError(504, DEADLINE_EXCEEDED)`, not an `httpx.TimeoutException`.
- Server errors from Gemini were routine in early testing, not an edge case -
  roughly one call in ten failed with a 5xx. That is why `LLM_UNAVAILABLE` is
  retryable and the frontend shows a retry button rather than treating it as
  exceptional.

## Traps that have already bitten

1. **`asyncio.create_task` without holding a reference can be garbage
   collected mid-run.** The event loop only holds a weak reference; a
   background task with nothing else pointing at it can vanish silently. The
   sweeper task in `main.py`'s lifespan is held in a local variable for
   exactly this reason. Relevant again if async job polling is ever built -
   see `docs/srs-status.md`.
2. **`shiki`'s top-level `codeToHtml` import pulls in every language grammar
   it ships** - several megabytes, untree-shakeable, for an app that only
   ever highlights Python. `CodeBlock.tsx` uses the fine-grained
   `shiki/core` API with static imports of only `python.mjs` and one theme.
3. **`react-dropzone`'s accessible tab stop is the outer
   `role="presentation"` div, not the hidden `<input type=file>`.** The
   accessible name belongs on the wrapper, not the input.
4. **A zero-argument function is assignable to a `(event) => void` handler,
   and TypeScript will not catch it.** Wiring `onClick={handler}` where
   `handler` takes an optional parameter passes the click's `MouseEvent` as
   that parameter. If the parameter reaches `JSON.stringify` unchecked, this
   surfaces as `Converting circular structure to JSON` pointing at a DOM
   element and its React fiber - a confusing crash a long way from its
   cause. Fix at both ends: wrap the handler at the call site
   (`onClick={() => handler()}`), and add a runtime type guard wherever a
   value crosses into `JSON.stringify` from a prop that could plausibly be
   miswired this way (see the guards in `frontend/src/api.ts`).
5. **The `datasets.state` column was, for a while, write-once, read-never** -
   asserted by a test, updated by nothing, which made a genuinely dead column
   look load-bearing. It is now written on insert and advanced on
   `/profile`, and read back by `GET /datasets/{id}`. Worth remembering as a
   pattern: a column or field that is only ever asserted in tests, never read
   by application code, is a smell worth checking directly against `grep`.
6. **A published state machine that never transitions is worse than none.**
   `JobState` originally had six members (`pending`, `profiling`,
   `generating`, `validating`, `complete`, `failed`); only two were ever
   actually constructed, because both API routes are synchronous. It has
   since been narrowed to the two real states. If async job polling is ever
   built (see `docs/srs-status.md`), the in-flight members should return
   together with the endpoint that actually writes them, not before.
7. **macOS's default filesystem is case-insensitive.** Renaming a file to fix
   only its casing (`ReadMe.md` -> `README.md`) needs an intermediate name in
   git (`git mv a.md tmp.md && git mv tmp.md a.md`, or `git mv --force`) -
   `git mv old new` where `old` and `new` differ only in case can no-op
   silently on a case-insensitive filesystem.
8. **A stale server on the same port serves stale code.** If a `uvicorn`
   process from a previous session is still holding the target port, a new
   one started against the same port exits nonzero on bind - but if that
   exit is not checked, requests keep hitting the old process, and a test
   run against it can produce a false pass. `lsof -ti:<port> | xargs kill`
   before starting a new one if behavior doesn't match the code you expect.

## Things that look unfinished but are deliberate

- **scikit-learn is not a backend dependency**, even though MVP-1.5 runs
  scikit-learn pipelines. Generated code runs under `RUNNER_PYTHON`, a
  separate venv built from `backend/runner-requirements.txt`. Installing
  scikit-learn into the API venv "to make execution work" would erase the
  boundary the phase-2 container is meant to replace.
- **`ErrorCode.VALIDATION_FAILED` is raised only by `/execute`**, never by
  `/generate`. A failing `ValidationReport` still ships alongside the code
  from `/generate`, on purpose, after one automatic repair round. The code is
  for refusing to *run* code that failed a safety check.

## Execution gotchas (MVP-1.5)

- **The execution tests start real processes.** They use the test venv's own
  interpreter as the runner, which has pandas but not scikit-learn, so test
  scripts there must stay pandas-only. They do not need `.venv-runner`.
- **`python -I` ignores every `PYTHON*` variable**, including
  `PYTHONIOENCODING`. That is why the runner is started with `-X utf8`:
  without it, a non-ASCII column name printed on Windows raises
  `UnicodeEncodeError` against the console code page.
- **On Windows, `taskkill /T` only walks the tree while the parent is alive.**
  It is called on timeout, when the parent always is. After a normal exit,
  multiprocessing and loky workers notice their parent is gone and exit.
- **A venv is not portable across operating systems.** A repo copied from a
  Mac carries a `.venv` with `bin/` and a `node_modules` with darwin-arm64
  binaries; both must be deleted and reinstalled on Windows or Linux.
- **The bundled pip in a fresh Python 3.13 venv (25.0.1) hung indefinitely
  on one Windows machine** during network resolution. Installing with a
  newer pip from another venv (`pip --python <abs path to target python>`)
  worked.
- **`recharts` is not in `package.json` as of this cleanup pass** - it was
  present as a dependency with zero imports anywhere in `frontend/src`
  (confirmed by grep and by an identical production bundle size before and
  after removal). Removed rather than left as unexplained dead weight.

## Frontend routing

`frontend/src/routes.ts` maps each `Screen` to a real path
(`/`, `/upload`, `/target`, `/profile`, `/strategy`, `/pipeline`) using the
History API directly - no router library. Rules worth knowing before editing
`App.tsx`'s routing effects:

- A URL may only select a screen the current app state can actually render
  (the same rule the sidebar nav already enforces). A deep link to a screen
  the session has no data for falls back to the furthest screen that does
  exist, not a blank panel.
- Boot-time corrections use `history.replaceState`; in-app navigation uses
  `history.pushState`. Getting this backwards means either the back button
  returns to a URL that never worked, or ordinary navigation stops
  contributing to browser history at all.
- The dataset id deliberately does **not** appear in any URL. There is no
  auth (see `docs/srs-status.md`), so the id is the only thing between a URL
  and the profile behind it - keeping it in `sessionStorage` instead of the
  path keeps it out of browser history, `Referer` headers, and anything that
  logs URLs.

## More traps that have bitten

- **`uvicorn --reload` did not pick up file changes on one Windows machine.**
  The server kept serving code from before a long editing session, with no
  reload line in its log; the symptom was the frontend calling a new route
  and getting 404. If behaviour does not match the code, restart the server
  rather than trusting the reloader - and check `/api/health` for a field
  you just added.
- **Docker Desktop is often started after the API.** That is why
  `execution.resolve_docker` checks the engine and the image on every
  `/execute` rather than once at boot, and why its error says which of the
  two is missing.
- **The live Docker tests skip silently without the engine.** `pytest -rs`
  shows the skip reason. CI builds the image so they always run there.
- **Rate-limit windows are per app instance** (`app.state.rate_limiter`), so
  each `TestClient` starts clean. A test that needs to exhaust a budget sets
  the `settings.rate_limit_*` value low with `monkeypatch` instead of making
  dozens of requests.
