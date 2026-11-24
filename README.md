# AutoNexus

Upload a CSV, get back a machine-learning pipeline written for it, plus an
honest account of why, and what was checked.

## What is AutoNexus?

**Upload a spreadsheet, get back a machine-learning pipeline written for it -
plus an honest account of why, and what we checked.**

You upload a tabular CSV, pick the column you want to predict, and the app
walks it through five stages:

```
Upload  ->  Pick target  ->  Profile  ->  Strategy  ->  Pipeline
 CSV        the column       Python       the plan      the code
            to predict       measures     + reasons     + checks
```

The first two stages after upload - **Profile** and the metric selection
behind it - are pure deterministic Python: pandas and hand-written rules, no
model call. Only at **Strategy** does an LLM (Google Gemini) get involved, and
what it receives is never the dataset itself - it is a JSON summary of
statistics Python already computed: column types, missingness, cardinality,
class balance, and a leakage association score per column. The LLM reasons
over those facts and returns a structured strategy (what to drop, how to
preprocess, which models to try, how to validate) followed by the Python code
that implements exactly that strategy. Before you see it, that code is
statically checked - never executed - against a dozen rules: does it parse,
does it import only approved libraries, does it reference real columns, does
it match the strategy it just described.

**By default the generated code is never run, and no score is ever shown for
it.** That is a deliberate design decision, not a missing feature - see
[Why AutoNexus?](#why-autonexus) below. On your own machine you can switch on
optional local execution (MVP-1.5), which runs the pipeline on a 500-row
sample in a separate process and shows its raw output, labelled as a sample -
see [Local execution](#local-execution-mvp-15).

## Why AutoNexus?

Most "AutoML" tools train a model behind the scenes and hand you a number:
"94% accurate." That number is only trustworthy if you trust everything that
happened upstream of it, invisibly. This project takes the opposite bet:

- **Facts are computed, never guessed.** Every statistic on the Profile screen
  came from pandas running on your actual file, not from the LLM estimating
  anything.
- **Raw rows never leave the server.** The LLM sees a JSON profile - dtypes,
  percentages, counts, a handful of category level names - never your data.
  See [LLM Architecture](#llm-architecture) for exactly what crosses that
  boundary and why.
- **Generated code is auditable, not a black box.** It is ordinary
  scikit-learn code you can read top to bottom before running it yourself,
  and it comes with the checklist that was run against it.
- **The reasoning is visible.** The strategy - which columns get dropped and
  why, which models are worth trying, how the result should be validated - is
  shown as a plan before you see a single line of code, and the code's field
  order is arranged so the model has to commit to that plan before writing.
- **Validation happens before you see the result, not instead of showing it.**
  A failing check does not hide the code; it is shown alongside it, so you
  decide what to do about it.

We never run the generated code unless you switch local execution on, and we
never show a model score anywhere in the product. `GenResult`, the data
structure that carries the AI's answer, has no field capable of holding a
score, by design. When you do run a pipeline locally, its printed output is
shown verbatim under "Executed on a N-row sample" and is never parsed into a
headline number - see [Known Limitations](#known-limitations).

## Current Status

This repository has no standalone SRS or design PDF committed to it. The
closest artifacts to a requirements document are
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (the frozen architecture
and an eight-stage build order) and [`docs/not-building.md`](docs/not-building.md)
(an explicit list of what is deliberately out of scope, with reasons). The
status below is measured against those two documents plus the code itself,
not against an external file that does not exist in this repo.

### Implemented

- CSV upload with streaming size limits and structural validation (empty,
  header-only, single-column, too-many-columns, duplicate column names)
- Target column selection, with a coherence-checked override for the one
  genuinely ambiguous case (a discrete numeric target read as either
  classification or regression)
- Per-column feature exclusion (keep a column out of the generated pipeline
  entirely, independent of what the model would have chosen)
- Full deterministic profiling: dtypes, missingness, cardinality, duplicate
  rows, class balance, per-column target-association / leakage score
- Deterministic metric selection (accuracy / F1 / PR-AUC by balance band for
  binary classification; F1-macro for multiclass; RMSE for regression)
- LLM strategy and pipeline generation via Gemini structured output, with API
  key rotation across a 429 and one automatic repair attempt on malformed
  output
- Twelve static validation checks against the generated code (see
  [Validation](#validation)), plus **one automatic repair round** when an
  error-severity check fails: the model is told exactly which checks failed
  and why, and the better of the two results is shown with its real report
- The full five-screen frontend workflow, with real per-screen URLs, back/
  forward navigation, and session recovery on refresh - including the
  generated pipeline, its checklist, and its latest run
- A usage endpoint reporting real token/latency counts per dataset
- **MVP-1.5 local execution** (off by default): `LocalSubprocessSandbox`, a
  separate `.venv-runner` with scikit-learn, a fixed-seed sample with every
  class represented, a hard timeout that kills the whole process group, and
  the run's stdout/stderr shown on the Pipeline screen. See
  [Local execution](#local-execution-mvp-15)
- **Docker execution sandbox** (`EXECUTION_BACKEND=docker`): the same pipeline
  run in a container with no network, a read-only filesystem, no
  capabilities, a non-root user, and memory/CPU/PID limits. The only backend
  allowed to execute outside `DEPLOYMENT_ENV=local`
- Large-dataset sampling above `SAMPLE_THRESHOLD` (200,000 rows) for the
  leakage step, with `profiled_on_sample` set honestly, tested at full scale
- **Distribution charts** on the Profile screen: a histogram or level-count
  chart per column, with hover counts and a values table, from a separate
  `/distributions` endpoint that never feeds the model prompt
- **Access tokens and rate limiting**: bearer tokens (`API_TOKENS`, mandatory
  for `DEPLOYMENT_ENV=hosted`), per-client budgets on uploads, generations,
  runs and general requests, and a token prompt in the frontend
- SQLite persistence with WAL mode and an hourly TTL sweep (24h default) that
  removes a dataset's generations, pipeline and runs along with it
- 321 backend tests (pytest, `ruff check` clean) and 27 frontend tests
  (Vitest + Testing Library), run in CI on every push and pull request

### Not implemented

- **Model training scores, comparison, or feature importance as product
  features.** A local run prints whatever the pipeline prints; nothing parses
  that into a score, a leaderboard, or a "best model" claim. `GenResult` has
  no field that could hold a number like this.
- **Async jobs / progress polling.** `JobState` was deliberately narrowed to
  `pending | complete` after a prior six-state version was found to never
  transition through its other four members. `/profile` and `/generate` are
  synchronous HTTP calls; there is no jobs table and no `GET /jobs/{id}`.
- **User-chosen algorithms, hyperparameters, or preprocessing steps.**
  Deliberate - see [`docs/not-building.md`](docs/not-building.md) item 4-5.
- **Metric override.** The task type is overridable; the evaluation metric is
  always re-derived from the (possibly overridden) task, never chosen by the
  caller.
- **Multi-target prediction, unsupervised learning.** One target column, one
  supervised pipeline. See [`docs/not-building.md`](docs/not-building.md)
  items 2-3.
- **File formats other than CSV.** No Excel, Parquet, JSON, or database
  connections.
- **User accounts and per-user data isolation.** Access is by shared bearer
  token: anyone holding a valid token can reach any dataset id they learn.
  Datasets are anonymous UUIDs with a 24-hour TTL. See
  [Security Notes](#security-notes).
- **Multi-worker deployment.** Rate-limit windows and the one-generation-per-
  dataset guard live in process memory, which is correct for the single
  worker this app runs as. Several workers would each keep their own.
- **Deployment packaging for the API itself.** There is a Docker image for
  the *execution sandbox*, not for the API or frontend, and no
  docker-compose file.
- **BigQuery, WebSockets.** No reference to either anywhere in the codebase;
  not part of this architecture.

The full reasoning behind each "not building" decision, and what would have
to change for any of them to come back into scope, is in
[`docs/not-building.md`](docs/not-building.md). A more detailed status table
and the remaining backlog, ranked, is in
[`docs/srs-status.md`](docs/srs-status.md).

## Architecture

```
  React / Vite (TypeScript)
          |
          v  fetch, JSON over HTTP
  FastAPI  (backend/app/main.py)
          |
          v
  CSV ingestion            backend/app/ingest.py
  (stream size check, duplicate-header check, parse, shape check, memory check)
          |
          v
  Profiler                 backend/app/profiler.py, dtypes.py, leakage.py, metrics.py
  (per-column stats, task inference, metric selection - all deterministic)
          |
          v
  ProfileCard               backend/app/models.py
  (the ONLY object the LLM layer ever sees - never a DataFrame)
          |
          v
  LLM provider               backend/app/llm.py, prompts.py
  (Gemini, structured output, key rotation, one repair attempt)
          |
          v
  GenResult                 backend/app/models.py
  (strategy fields, THEN code - field order is load-bearing)
          |
          v
  Static validation          backend/app/validation.py
  (AST-only: parses, checks, never executes; one repair round on an error)
          |
          v  (optional, ENABLE_LOCAL_EXECUTION=true, DEPLOYMENT_ENV=local only)
  Local execution            backend/app/execution.py
  (safety preflight -> 500-row sample -> separate .venv-runner process)
          |
          v
  React screens               frontend/src/screens/
  (Upload -> Target -> Profile -> Strategy -> Pipeline)
```

The core rule that shapes every layer above: **Python computes facts, the LLM
reasons over facts, the LLM never sees raw data.** `llm.py`'s entry point
accepts a `ProfileCard`, never a `DataFrame` - that function signature is the
literal enforcement point for the rule, not just a description of it.

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python (`requires-python >=3.12`), FastAPI `>=0.115`, Pydantic v2 `>=2.9`, pydantic-settings `>=2.6` | Verified running on Python 3.14.2 in this environment |
| Data | pandas `>=2.2,<3`, numpy `>=2.1` | pandas capped below 3.0: pandas 3 defaults string columns to a real `str` dtype rather than `object`, which breaks the dtype-classification ladder |
| LLM | `google-genai>=1.0`, model `gemini-3.1-flash-lite` (configurable) | The unified SDK - **not** the deprecated `google-generativeai` |
| Storage | `sqlite3` (Python stdlib), WAL mode | No ORM; one table for datasets, one for generation attempts |
| Frontend | React 18.3, Vite 5.4, TypeScript 5.6 (strict), Tailwind CSS v4 | Tailwind is configured through an `@theme` block in `src/index.css`, not a `tailwind.config.js` file. No React Router - a small hand-written History API wrapper (`src/routes.ts`) does URL routing |
| Frontend deps | `react-dropzone`, `shiki` (syntax highlighting, fine-grained core API only), `framer-motion`, `lucide-react` | No component library, no shadcn, no `@/` alias |
| Backend dev tooling | pytest `>=8.3`, pytest-asyncio, httpx, ruff `>=0.7` | `ruff check app tests` is clean |
| Frontend dev tooling | `tsc -b` (strict, `noUnusedLocals`, `noUnusedParameters`), Vitest 2 + Testing Library + jsdom | `npm test` |

Explicitly **not** used anywhere in this codebase, by rule in
[`CLAUDE.md`](CLAUDE.md): LangChain, LangGraph, Instructor, ydata-profiling,
Redis, Celery, SQLAlchemy, pyarrow.

## Project Structure

```
backend/
  app/
    main.py           FastAPI app factory, CORS, the one error-envelope handler
    api/datasets.py   The dataset HTTP routes (see API below)
    config.py         Settings from environment, the local-execution boot guard
    models.py         Every Pydantic schema - the contract between every layer
    errors.py         ErrorCode enum + status/retryability table, one place
    ingest.py         CSV streaming, validation, and rejection rules
    dtypes.py         The 7-rung dtype classification ladder
    profiler.py       Builds a ProfileCard from a DataFrame
    leakage.py        The three target-association formulas (spearman/eta/purity)
    metrics.py        Deterministic metric selection from class balance
    heuristics.py     Every threshold in the app, as a named constant with a reason
    heuristics.md     Cross-cutting relationships between heuristics constants
    prompts.py        System prompt + ProfileCard -> LLM prompt serialization
    llm.py            LLMProvider protocol, GeminiProvider, key rotation, both repair rounds
    storage.py        SQLite persistence and the TTL sweeper
    validation.py      Twelve static checks on generated code
    execution.py       MVP-1.5: safety preflight, sampling, Sandbox protocol, LocalSubprocessSandbox, DockerSandbox
    distributions.py   Histogram / level-count chart data (never part of ProfileCard or the prompt)
    security.py        Bearer-token check and per-client rate limits
  tests/               321 tests: fixture-corpus-driven, cassette-backed LLM tests, real-subprocess and container sandbox tests
  pyproject.toml
  runner-requirements.txt  What the separate .venv-runner and the sandbox image get (pandas<3, numpy, scikit-learn)
  runner.Dockerfile        The Docker execution sandbox image
  .env.example

frontend/
  src/
    App.tsx            The one useReducer holding all app state; also routing
    routes.ts           URL <-> screen mapping (hand-rolled, no router library)
    state.ts             The reducer - a failed generation never clears the profile
    api.ts               fetch wrapper, unwraps the backend's error envelope
    types.ts              Hand-written mirror of backend/app/models.py
    index.css              Tailwind v4 @theme block - every design token
    screens/               UploadScreen, TargetScreen, ProfileScreen, StrategyScreen, CodeScreen, LandingScreen
    components/
      layout/             WorkflowShell (sidebar + stage nav), ActivityDialog, StageIntro
      upload/              Dropzone
      target/              ColumnTable, ColumnRow
      profile/            StatTile, MetricPanel, ClassBalanceChart, DistributionChart, QualityChip, QualityInsights, SystemWarnings, TaskConfidenceToggle
      strategy/            PreprocessingStep, DroppedColumnsTable, CandidateModelCard
      pipeline/            CodeBlock, ValidationChecklist, ValidationCheckRow, UnexecutedNotice, ExecutionPanel
      shared/              Button, Card, StatusBadge, ErrorPanel, RetryButton, AccessTokenPanel, icons
    *.test.ts(x), test/  Vitest suites and typed fixtures
  package.json
  .env.example

docs/
  not-building.md                              Explicit scope boundary, with reasons
  srs-status.md                                Full status table + ranked remaining backlog
  development.md                                Local-dev gotchas, cassette rules, traps that have already bitten
  spike-01-gemini-structured-output.md          Why field order / nested schemas behave the way they do on Gemini
  adr/0001-llm-reasons-over-computed-facts.md   Why the LLM only ever sees a ProfileCard
  adr/0002-execution-boundary.md                Why execution is off by default, and how MVP-1.5 contains it
  Agentic_AutoML_Apple_HIG_Design_System.md     The frontend's governing design spec

.github/workflows/ci.yml  Backend, Docker-sandbox and frontend jobs
IMPLEMENTATION_PLAN.md   Frozen architecture + the eight-stage build order this project followed
CLAUDE.md                 Binding rules for any contributor (human or AI) working in this repo
```

## Requirements

- **Python 3.12 or newer** (`backend/pyproject.toml` declares
  `requires-python = ">=3.12"`; this environment runs 3.14.2 and every
  dependency installs clean on it)
- **Node.js 18 or newer** (Vite 5's minimum; this environment runs Node 21)
- **npm** (the repo ships a `package-lock.json`; no pnpm/yarn lockfile exists)
- **A Google Gemini API key** - free tier is enough to run the app; get one
  at [Google AI Studio](https://aistudio.google.com/). Without a key, every
  route works except `POST /api/datasets/{id}/generate`, which needs one.
- macOS, Linux, or Windows. The full test suite, the build, and local
  execution have been run on Windows 11; the commands below give both forms
  where they differ. A venv is not portable between operating systems - if
  you copy the repo from another machine, delete `backend/.venv`,
  `backend/.venv-runner` and `frontend/node_modules` and reinstall.

## Installation

```bash
git clone <this-repository-url>
cd Tabular-Pipeline-Synthesis
```

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

On Windows (PowerShell), the venv layout is `Scripts\` instead of `bin/`:

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
```

Open `.env` and set at least `GOOGLE_API_KEY` to a real key. Every other
value in `.env.example` has a working default.

### Runner venv (only for local execution)

Skip this unless you want to switch on [local execution](#local-execution-mvp-15).
It is a second, separate environment on purpose - the API itself never
imports scikit-learn.

```bash
cd backend
python3 -m venv .venv-runner
.venv-runner/bin/python -m pip install -r runner-requirements.txt
```

```powershell
cd backend
py -3.13 -m venv .venv-runner
.venv-runner\Scripts\python -m pip install -r runner-requirements.txt
```

`RUNNER_PYTHON=.venv-runner/bin/python` (the default) works on both; on
Windows it is translated to `.venv-runner\Scripts\python.exe` automatically.

### Frontend

```bash
cd frontend
npm install
```

If port 8000 is already taken on your machine (common - it collides with
several other local dev tools), create `frontend/.env.local`:

```bash
echo "VITE_API_BASE=http://localhost:8001/api" > frontend/.env.local
```

and run the backend on the matching port in the next section, keeping
`CORS_ORIGINS` in the backend's `.env` in step with whatever origin the
frontend actually serves from.

## Environment Variables

### Backend (`backend/.env`, copied from `backend/.env.example`)

| Variable | Required | Description | Example |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes, for generation | Gemini API key. Every other route works without one. | `AIza...` |
| `GOOGLE_API_KEY1` / `GOOGLE_API_KEY2` / `GOOGLE_API_KEY3` | No | Extra keys. When more than one key is set, requests round-robin across them and a 429 fails over to the next. Keys from the *same* Google Cloud project share one daily quota bucket - this buys failover, not extra headroom. | `AIza...` |
| `LLM_MODEL` | No | Gemini model name. | `gemini-3.1-flash-lite` |
| `LLM_TIMEOUT_S` | No | Request timeout in seconds (converted to ms for the SDK; Gemini enforces roughly a 10s floor below which it 400s instead of timing out). | `60` |
| `DEPLOYMENT_ENV` | No | `local` or `hosted`. Governs the boot guard below. | `local` |
| `ENABLE_LOCAL_EXECUTION` | No | Turns on MVP-1.5 execution (`POST /datasets/{id}/execute` and the Run button). Outside `DEPLOYMENT_ENV=local` the app refuses to start unless `EXECUTION_BACKEND=docker`. | `false` |
| `EXECUTION_BACKEND` | No | `subprocess` (runner venv on this machine) or `docker` (locked-down container, image built from `backend/runner.Dockerfile`). | `subprocess` |
| `EXECUTION_DOCKER_IMAGE` | No | Image the Docker sandbox runs. | `autonexus-runner:latest` |
| `EXECUTION_TIMEOUT_S` | No | Hard wall-clock limit per run; the whole process group is killed when it expires. | `60` |
| `EXECUTION_SAMPLE_ROWS` | No | Rows in the sample a run sees. | `500` |
| `RUNNER_PYTHON` | No | Interpreter of the separate runner venv. The POSIX path is translated to `Scripts\python.exe` on Windows. | `.venv-runner/bin/python` |
| `UPLOAD_DIR` | No | Where uploaded CSVs are stored on disk. | `./data/uploads` |
| `DB_PATH` | No | SQLite file path. | `./data/app.db` |
| `DATASET_TTL_HOURS` | No | How long a dataset and its profile are kept before the hourly sweep deletes them. | `24` |
| `MAX_FILE_MB` | No | Upload size limit, enforced while streaming. | `50` |
| `MAX_COLS` | No | Maximum column count accepted at ingest. | `1000` |
| `CORS_ORIGINS` | No | Comma-separated list of allowed origins. | `http://localhost:5173` |
| `API_TOKENS` | Yes, for `hosted` | Comma-separated bearer tokens. When set, every dataset route requires `Authorization: Bearer <token>`. Empty means no auth, permitted only for `DEPLOYMENT_ENV=local`. | `team-a-token,team-b-token` |
| `RATE_LIMIT_GENERATIONS_PER_HOUR` | No | Per-client budget for `/generate` (protects the model quota). | `10` |
| `RATE_LIMIT_UPLOADS_PER_HOUR` | No | Per-client budget for uploads. | `30` |
| `RATE_LIMIT_EXECUTIONS_PER_HOUR` | No | Per-client budget for `/execute`. | `30` |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | No | Per-client budget for every other dataset route. | `120` |

### Frontend (`frontend/.env.local`, not checked in - see `frontend/.env.example`)

| Variable | Required | Description | Example |
|---|---|---|---|
| `VITE_API_BASE` | No | Base URL the frontend calls. Defaults to `http://localhost:8000/api` in code. | `http://localhost:8001/api` |

`.env.example` files in this repository hold variable *names* only, never a
real value - that rule is enforced by hand, not by tooling, so do not commit a
real key into either example file. Real values live in `backend/.env` and
`frontend/.env.local`, both gitignored.

## Running Locally

Two terminals.

**Backend** (from `backend/`):

```bash
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

On Windows: `.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000`

If port 8000 is taken, run on another port (e.g. `--port 8001`) and set
`VITE_API_BASE` accordingly, as described above.

**Frontend** (from `frontend/`):

```bash
npm run dev
```

Open **`http://localhost:5173`**. Use `localhost`, not `127.0.0.1` - the
backend's default CORS allowlist contains only `http://localhost:5173`, and a
mismatch surfaces in the browser as a CORS error even though the request
succeeded on the server.

Health check: `curl http://localhost:8000/api/health` should return
`{"status": "ok", "version": "...", "execution_enabled": false, ...}`.

## How to Use

1. **Upload a CSV.** Drag a file onto the dropzone, or click to browse. The
   backend rejects it up front, with a specific reason, if it is empty,
   header-only, has duplicate column names, has only one column, exceeds
   1000 columns, or exceeds 50MB.
2. **Pick the target column.** The one column you want to predict.
3. **Confirm, and review the profile.** Python computes every statistic on
   this screen: row/column counts, duplicate rows, missingness, the inferred
   task (classification or regression) and its confidence, the chosen
   evaluation metric and why, per-column flags (constant, high-cardinality,
   ID-like, potential leakage, and so on). If the target is a discrete
   number - a 1-5 rating, a count - the task is genuinely ambiguous and the
   screen offers an override. You can also exclude any feature column from
   the pipeline entirely before generating.
4. **Generate the strategy.** This is the one step that calls Gemini. You get
   back a plan: which columns get dropped and why, what preprocessing each
   retained column needs, two to four candidate models ranked by fit for
   this dataset, and how the result should be validated - all grounded in
   the profile, never in a number that was never measured.
5. **Review the pipeline code.** The strategy's code, with the twelve-check
   validation report shown above it, not below it. A banner states plainly
   that the pipeline has not been executed. Copy or download the code and
   run it yourself in your own environment - or, with local execution on,
   press **Run on sample** to see it run on a 500-row sample right there.

## API

Base path: `/api`. Every non-2xx response has the shape
`{"error": {"code": str, "message": str, "retryable": bool, "details": {}}}`.

**Access and limits, on every `/datasets` route:** when `API_TOKENS` is set,
requests need `Authorization: Bearer <token>`, or get `UNAUTHORIZED` (401).
Every client (its token, or its IP without auth) has budgets: uploads,
generations and runs per hour, and other requests per minute. Exceeding one
returns `RATE_LIMITED` (429, retryable, `details.retry_after_s` says when).
`/health` is always open.

### `GET /health`

Liveness check. Returns `{"status": "ok", "version": "<app version>",
"execution_enabled": bool, "execution_sample_rows": int | null,
"auth_required": bool}`. The frontend reads it once at boot to decide whether
to offer a Run button and whether to ask for an access token.

### `POST /datasets`

Upload a CSV (`multipart/form-data`, field name `file`).

**Response** `201` `DatasetUploadResponse`:
```json
{"dataset_id": "uuid", "filename": "sales.csv", "n_rows": 1000,
 "n_columns": 12, "columns": ["id", "amount", "..."], "state": "pending"}
```

**Errors:** `FILE_TOO_LARGE` (413), `DATASET_TOO_LARGE_IN_MEMORY` (413),
`UNPARSEABLE_CSV` (422), `EMPTY_DATASET` (422), `HEADER_ONLY` (422),
`SINGLE_COLUMN` (422), `TOO_MANY_COLUMNS` (422), `DUPLICATE_COLUMNS` (422).

### `GET /datasets/{id}`

Everything on record for a dataset, including its stored profile if one
exists. The recovery path for a browser refresh - the other three POST
routes leave nothing a `GET` could otherwise reach.

**Response** `200` `DatasetDetail`: `dataset_id`, `filename`, `n_rows`,
`n_columns`, `columns`, `created_at`, `state` (`pending`|`complete`),
`task_was_overridden`, `profile` (`ProfileCard | null` - `null` before
`/profile` has run, which is a normal state, not an error), and `pipeline`
(`StoredPipeline | null`: the `result` shown to the user, its `validation`
report recomputed on read, the `excluded_columns` it was generated against,
`generated_at`, and `latest_run`). Re-profiling discards the pipeline and its
runs, since code written for one target is wrong for another.

**Errors:** `DATASET_EXPIRED` (410) - covers both an unknown id and one whose
24-hour TTL has passed; the two are deliberately indistinguishable to avoid
leaking whether a given UUID ever existed.

### `POST /datasets/{id}/profile`

**Request** `ProfileRequest`:
```json
{"target_column": "churned", "problem_type_override": null}
```
`problem_type_override` is optional and only accepted when it resolves a
genuine ambiguity (a discrete-numeric target); an override incoherent with
the target's actual type is refused.

**Response** `200` `ProfileResponse`: `{"state": "complete", "profile": ProfileCard}`.
Persists the profile server-side so `/generate` can read it back.

**Errors:** `DATASET_EXPIRED` (410), `TARGET_NOT_FOUND` (422),
`TARGET_ALL_NULL` (422), `TARGET_SINGLE_VALUE` (422),
`TARGET_TYPE_UNSUPPORTED` (422) - the target's dtype (text, datetime, or a
column with no usable values) has no corresponding problem type, or the
requested override is incoherent with it.

### `POST /datasets/{id}/generate`

**Request** `GenerateRequest`:
```json
{"excluded_columns": ["notes", "internal_id"]}
```
Deliberately carries no profile data - the server always reads back what
`/profile` already stored, never a client-supplied one. `excluded_columns`
is an instruction ("do not offer this column to the model"), not a fact
claim, so it does not violate that rule; every name is validated against the
stored profile and the target column cannot be excluded.

**Response** `200` `GenerateResponse`: `{"state": "complete", "result": GenResult, "validation": ValidationReport}`.
If the first result fails an error-severity check, one repair round runs
automatically (one extra model request); the result with fewer failing errors
is returned. A failing validation report is still returned alongside the
code - never suppressed. The result is stored as the dataset's current
pipeline.

**Errors:** `DATASET_EXPIRED` (410, dataset not profiled yet or aged out),
`TARGET_NOT_FOUND` (422, an excluded-column name does not exist),
`TARGET_SINGLE_VALUE` (422, an attempt to exclude the target column),
`LLM_RATE_LIMITED` (429, all configured keys exhausted, or a generation is
already in flight for this dataset), `LLM_TIMEOUT` (504),
`LLM_UNAVAILABLE` (503), `LLM_INVALID_OUTPUT` (502, the model's output could
not be parsed even after one repair attempt).

### `GET /datasets/{id}/usage`

Every recorded provider attempt for a dataset - successes, failures, and the
repair round - with real measured tokens and latency. Not a quality metric
for the generated pipeline; there is no such metric anywhere in this API.

**Response** `200` `UsageResponse`: `dataset_id`, `attempts: GenerationAttempt[]`,
`total_attempts`, `total_input_tokens`, `total_output_tokens`.

**Errors:** `DATASET_EXPIRED` (410).

### `GET /datasets/{id}/distributions`

Chart data for the Profile screen, one entry per column: `kind` is
`histogram` (20 equal-width `bins` of `lower`/`upper`/`count`, for continuous
numeric columns), `levels` (up to 12 `levels` of `value`/`count` plus an
`other_count`, for categorical, boolean and discrete columns), or `none` with
a `reason` (free text, datetimes, identifiers, empty columns). Every entry
carries `missing_count`.

This is for the user's own eyes. It is deliberately not part of
`ProfileCard`, so none of it ever reaches the model prompt. Computed on
request from the stored file and profile.

**Errors:** `DATASET_EXPIRED` (410, including not profiled yet).

### `POST /datasets/{id}/execute`

MVP-1.5. Runs the stored pipeline on a sample of the stored dataset. Takes no
body: only code this server generated and stored is ever run.

**Response** `200` `ExecuteResponse`: `{"run": RunResult}` with `run_id`,
`executed_at`, `sample_rows`, `exit_code` (`null` when killed), `timed_out`,
`duration_ms`, `stdout`, `stderr`, `stdout_truncated`, `stderr_truncated`,
`succeeded`. A pipeline that crashes or times out is still a 200 - the run
happened, and its `RunResult` says how it went.

**Errors:** `EXECUTION_DISABLED` (403, the flag is off),
`EXECUTION_UNAVAILABLE` (503, the runner venv is missing, or with the Docker
backend: the engine is down or the image is not built - the message says
which),
`DATASET_EXPIRED` (410), `PIPELINE_NOT_FOUND` (409, nothing generated for the
current profile), `VALIDATION_FAILED` (422, a safety check or the execution
preflight failed - the code is not run), `EXECUTION_IN_PROGRESS` (409).

## Profiling

Everything on the Profile screen is computed by `backend/app/profiler.py` and
its supporting modules - no model call is involved anywhere in this stage.
Every named threshold below lives in `heuristics.py` as a constant with a
written justification; nothing here is a number chosen ad hoc in the code
that uses it.

**Per column:** inferred type (via a seven-rung classification ladder -
boolean vocabulary, native numeric dtype, datetime parse rate, numeric-string
coercion, near-unique text, categorical fallback, unknown), missing
count/percentage, unique count/percentage, the share held by the single most
common value, up to five sample level names (low-cardinality categoricals
and booleans only, capped and truncated - the one place file content reaches
the LLM prompt, treated as metadata rather than data; booleans are included
so generated code maps `"yes"`/`"no"` with the file's real spelling rather
than guessing `"Yes"`), min/max/mean/std/median for
numeric columns, and flags: `all_missing`, `high_missing` (>50% null),
`constant`, `quasi_constant` (one value holds ≥99% of rows, never applied to
the target), `id_like` (≥99% unique), `high_cardinality` (>50 distinct
values, or >50% of row count, whichever fires first, categorical columns
only), `numeric_as_string`, `potential_leakage`.

**Target association / leakage:** every feature column gets a single
association score against the target, using whichever of three formulas fits
its type and the task - Spearman rank correlation (numeric feature,
regression target), a correlation ratio / eta statistic (numeric-categorical
or categorical-numeric pairs), or a hand-defined level-purity score
(categorical feature, classification target). All three return an absolute
value in `[0, 1]`; a score above `0.98` sets the `potential_leakage` flag.
Free text, datetime, and unknown-type columns are skipped entirely - "no
meaningful test applies" is recorded as `association_method: "none"`, the
same value used when a test was attempted but too little paired data
survived.

**Task inference:** deterministic from the target column's inferred type.
Boolean or two-level categorical -> binary classification; categorical with
more levels -> multiclass; continuous numeric -> regression; **discrete**
numeric (a rating, a small count) is the one genuinely ambiguous case, and
gets a lower confidence score plus a UI offer to override it explicitly.

**Metric selection:** regression always uses RMSE (secondary: MAE, R²);
multiclass always uses F1-macro (secondary: accuracy); binary classification
picks accuracy, F1, or PR-AUC by the majority:minority class ratio -
`≤1.5:1` accuracy, `≤10:1` F1, above that PR-AUC - with ROC-AUC always listed
as a secondary and never selectable as the primary metric under imbalance.

**Sampling:** every per-column statistic above is always computed on the full
file. The one exception is the leakage-association pass, an O(rows ×
columns) operation - above 200,000 rows it runs on one shared random sample
(same rows for every column, fixed seed), and `profiled_on_sample` /
`sample_rows` are set honestly and shown on the profile screen whenever it
happens. Cardinality-related flags are never computed on a sample, because
sampling systematically distorts unique-value counts.

## LLM Architecture

**Provider:** Google Gemini, via the `google-genai` SDK, default model
`gemini-3.1-flash-lite` (configurable via `LLM_MODEL`).

**What crosses the boundary to the model - and nothing else:** the serialized
`ProfileCard` - filename, row/column counts, the target column name, the
inferred task and its confidence, the primary and secondary metrics, class
balance, duplicate row count, and the per-column statistics listed under
[Profiling](#profiling) above. **Raw dataset rows are never sent.** The only
values from the actual file that reach the prompt at all are column names and
the capped low-cardinality sample level names described above - and the
prompt explicitly instructs the model to treat both as inert data, never as
instructions, as a prompt-injection defence.

**Structured output:** the response is constrained to the `GenResult` Pydantic
schema via Gemini's `response_schema` parameter, not parsed out of free text.
`GenResult`'s field order is declared deliberately - every strategy decision
(problem type, target, metric, drops, preprocessing, candidate models,
validation approach, summary, risks) precedes the `code` field, so the model
commits to a plan before writing the pipeline that implements it. See
[`docs/spike-01-gemini-structured-output.md`](docs/spike-01-gemini-structured-output.md)
for the empirical verification that Gemini actually preserves this ordering.

**Reliability:** requests round-robin across up to four configured API keys;
a 429 fails over to the next key, other provider errors (timeout,
unavailable) do not rotate and fail immediately. If the model's JSON response
fails schema validation, exactly one automated repair attempt is made, with
the validation error appended to the prompt asking for a complete corrected
response. A provider-level failure (rate limit, timeout, unavailable) is
never retried automatically - it surfaces to the user with a retry button
where the error code says it is safe to press. Every attempt, successful or
not, is logged with real token counts and latency to a `generations` table,
readable via `GET /datasets/{id}/usage`.

## Validation

Twelve checks run against every generated result, all static - none of them
execute the code. If the code fails to parse, only the two checks that read
`GenResult`/`ProfileCard` directly still run; every AST-based check is
skipped rather than reported as passing.

| Check | Severity | Catches |
|---|---|---|
| `syntax_compile` | Error | The code fails to `compile()` - a syntax error |
| `ast_import_allowlist` | Error | Any import outside pandas, numpy, or scikit-learn |
| `dangerous_calls` | Error | Calls to `eval`, `exec`, `compile`, `__import__`, `os.system`, or anything rooted at `subprocess`, `socket`, `requests`, `urllib` |
| `hallucinated_columns` | Error | A string used as a column reference that is not a real profile column, not self-defined by the code, and close enough to a real name (fuzzy-match ratio ≥0.85) to be a plausible typo rather than an engineered feature name |
| `target_column_referenced` | Error | The target column name never appears anywhere in the code |
| `gen_result_self_consistency` | Error | The strategy's stated problem type, target column, or primary metric does not match what the profiler computed |
| `pipeline_or_column_transformer` | Warning | No `Pipeline` or `ColumnTransformer` used anywhere |
| `random_state_set` | Warning | No `random_state` keyword argument appears anywhere in the code |
| `split_or_cross_validation` | Warning | No train/test split or cross-validation call of any kind |
| `primary_metric_computed` | Warning | The chosen primary metric's keyword never appears in the code |
| `declared_columns_exist` | Warning | A column named in the strategy's drop list or preprocessing steps does not exist in the profile |
| `dropped_columns_not_referenced` | Warning | A column the strategy (or the user, via `excluded_columns`) declared dropped is still used as a feature in the code |

A report `passed` only when every **error**-severity check passed; warnings
never fail the overall report. The report is returned alongside the code
regardless of outcome - a failing check is never used to hide the code from
the user, only to inform the decision about whether to trust it.

**Self-correction.** When an error-severity check fails, `llm.generate_validated`
spends exactly one more model request (`CHECK_REPAIR_ROUNDS = 1`), appending
the failing checks, by title and reason, to the original prompt. The result
with fewer failing errors is kept, preferring the first on a tie. A provider
failure during the repair round keeps the first result rather than losing it.
Warnings never trigger a repair. The first-round prompt is byte-identical to
before, so recorded cassettes stay valid.

## Local execution (MVP-1.5)

Off by default. To switch it on, on your own machine:

1. Create the runner venv (see [Installation](#runner-venv-only-for-local-execution)).
2. In `backend/.env` set `ENABLE_LOCAL_EXECUTION=true` (with
   `DEPLOYMENT_ENV=local`, the default) and restart the backend.
3. The Pipeline screen now has a **Run on sample** button.

What a run does, in order (`backend/app/execution.py`):

- **Refuses** unless the stored pipeline passes the three safety checks
  (`syntax_compile`, `ast_import_allowlist`, `dangerous_calls`) and an
  execution-only preflight that rejects `open()`, `globals()` and friends,
  dunder attribute access, OS-reaching attributes such as `pd.io.common.os`,
  URL literals and absolute paths. Correctness failures such as a near-miss
  column name do not block a run - running it is how you see what it does.
- **Samples** `EXECUTION_SAMPLE_ROWS` rows with a fixed seed, guaranteeing
  every class up to `EXECUTION_MIN_ROWS_PER_CLASS` rows so stratified CV does
  not crash on an imbalanced file, then restores the original row order.
- **Runs** `python -I -X utf8 pipeline.py` under the runner venv in a fresh
  temp directory holding only the script and `data.csv`, with stdin closed, an
  environment built from scratch (no `GOOGLE_API_KEY` or any other API
  variable reaches it), and numerical-library threads capped.
- **Kills** the whole process group when `EXECUTION_TIMEOUT_S` expires
  (`killpg` on POSIX, `taskkill /T` on Windows), and reaps it in a `finally`.
- **Shows** stdout and stderr verbatim, capped at 20,000 characters each and
  flagged when cut, under a banner reading "Executed on a N-row sample".

The subprocess backend is a convenience for a developer's own machine, **not
a security sandbox** - see [ADR 0002](docs/adr/0002-execution-boundary.md)
and [Security Notes](#security-notes).

### Docker backend

For a real isolation boundary, run the same pipeline in a container:

```bash
cd backend
docker build -f runner.Dockerfile -t autonexus-runner:latest .
```

then set `EXECUTION_BACKEND=docker` in `backend/.env` and restart. Each run
gets a fresh container with `--network none`, a read-only root filesystem and
read-only inputs, a small writable `/tmp`, user `65534` (nobody), all Linux
capabilities dropped, `no-new-privileges`, and memory, CPU and PID limits
(`EXECUTION_DOCKER_*` in `heuristics.py`). On timeout the container is killed
by name, so it cannot outlive the request. The image carries only the runner
packages - no API code and no keys. If the engine is down or the image is
missing, `/execute` says which, rather than failing obscurely.

This is the only backend allowed to execute outside `DEPLOYMENT_ENV=local`.

## SRS Implementation Status

No standalone SRS exists in this repository - see
[Current Status](#current-status) above for what that means for this table.
Grouped by the phase each item was planned in
([`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) stages 0-5 = MVP-1;
stage 6 = MVP-1.5; unplanned items from
[`docs/srs-status.md`](docs/srs-status.md)'s backlog are marked Phase 2).

### MVP-1

| Feature | Status | Notes |
|---|---|---|
| CSV upload + validation | ✅ Complete | `ingest.py`, 7 rejection codes |
| Target selection | ✅ Complete | |
| Target/task override | ✅ Complete | Discrete-numeric ambiguity only |
| Feature exclusion | ✅ Complete | `excluded_columns` |
| Task inference | ✅ Complete | `dtypes.py` + `profiler.py` |
| Deterministic profiling | ✅ Complete | See [Profiling](#profiling) |
| Metric selection | ✅ Complete | `metrics.py` |
| Metric override | ❌ Not implemented | Only task type is overridable |
| LLM strategy + code generation | ✅ Complete | Structured output, `GenResult` |
| Static validation (12 checks) | ✅ Complete | See [Validation](#validation) |
| 5-screen frontend | ✅ Complete | Incl. real URLs, session recovery |
| Dataset/profile/pipeline recovery (`GET`) | ✅ Complete | Pipeline, report and latest run survive a refresh |
| Usage/quota visibility | ✅ Complete | |
| Repair-on-schema-failure | ✅ Complete | One automatic retry |
| Repair-on-failed-check loop | ✅ Complete | One round, `CHECK_REPAIR_ROUNDS` |
| Large-dataset sampling | ✅ Complete | Tested above 200,000 rows |
| Distribution charts | ✅ Complete | `GET /distributions`, never in the prompt |
| Frontend test suite | ✅ Complete | Vitest + Testing Library, 27 tests |

### MVP-1.5

| Feature | Status | Notes |
|---|---|---|
| Local subprocess execution | ✅ Complete | `LocalSubprocessSandbox`, off by default |
| `.venv-runner` + scikit-learn runner | ✅ Complete | `runner-requirements.txt`, separate from the API venv |
| Executed-on-a-sample result display | ✅ Complete | `ExecutionPanel`, `ExecutedNotice` |
| Docker execution sandbox | ✅ Complete | `DockerSandbox`, `runner.Dockerfile`, `EXECUTION_BACKEND=docker` |

### Phase 2 / explicitly deferred

| Feature | Status | Notes |
|---|---|---|
| Async jobs + polling | ❌ Not implemented (decided against for now) | `JobState` narrowed to 2 members after the 6-member version was found to never transition |
| Access tokens + rate limiting | ✅ Complete | `security.py`; tokens mandatory for `hosted` |
| CI | ✅ Complete | `.github/workflows/ci.yml`: backend, Docker sandbox, frontend |
| User accounts / per-user isolation | ❌ Not implemented | Shared bearer tokens only |
| Multi-target prediction | ❌ Not building | See `docs/not-building.md` #2 |
| Unsupervised learning | ❌ Not building | See `docs/not-building.md` #3 |
| User-chosen algorithms/preprocessing | ❌ Not building | See `docs/not-building.md` #4-5 |
| Formats other than CSV | ❌ Not building | See `docs/not-building.md` #11 |

Full reasoning and a ranked recommendation order for the still-open items is
in [`docs/srs-status.md`](docs/srs-status.md).

## Known Limitations

Stated plainly, not as a footnote:

- **CSV only.** No Excel, Parquet, JSON, or database connections.
- **One target column at a time.** No multi-output or multi-label prediction.
- **Supervised learning only.** No clustering, no anomaly detection.
- **The generated code is not executed by this app unless you switch local
  execution on**, and then only on a 500-row sample. A sample run shows the
  code works; it does not show how well it will perform on your full file.
  There is no accuracy figure, no leaderboard, and no "best model" claim
  anywhere in the product - by design, not by omission.
- **Access control is shared tokens, not accounts.** `API_TOKENS` keeps
  strangers out and rate limits stop one client draining the model quota,
  but anyone holding a token can reach any dataset id they learn. Serve it
  behind TLS (a reverse proxy) if it leaves localhost.
- **No accounts, no history.** Datasets are anonymous UUIDs, deleted after
  `DATASET_TTL_HOURS` (24h default).
- **Gemini's free tier caps generation at 20 requests/day, per project, per
  model.** Configuring multiple `GOOGLE_API_KEY*` values from the *same*
  Google Cloud project buys failover on a 429, not extra quota. Switching
  `LLM_MODEL` grants a fresh bucket if one is exhausted mid-session.
- **Single worker.** Rate-limit windows live in process memory; run one
  uvicorn worker.
- **A dev-only dependency vulnerability is currently present and
  unaddressed:** `npm audit` reports a moderate esbuild advisory
  (GHSA-67mh-4wv8-2f99) via Vite 5's bundled esbuild - it allows a malicious
  website to read responses from the Vite dev server while it is running.
  Fixing it requires an unreleased-as-tested Vite 8 major upgrade
  (`npm audit fix --force`), which this cleanup pass deliberately did not
  attempt. It affects `npm run dev` only, not the production build.

## Roadmap

Ranked by the order recommended in
[`docs/srs-status.md`](docs/srs-status.md), grouped so a cassette
re-recording (see [Testing](#testing)) only has to happen once per phase:

Everything on the previous version of this list is done: large-dataset
sampling tests, the repair-on-failed-check loop, MVP-1.5 local execution,
distribution charts, the Docker sandbox, access tokens and rate limiting,
frontend tests and CI. What would come next, if the scope grows:

1. **User accounts and per-user dataset ownership** - replacing shared tokens,
   so a token holder can only see their own uploads.
2. **A shared store for rate limits** - only needed for more than one worker.
3. **Deployment packaging for the API** - an image and compose file for the
   API and frontend themselves, alongside the existing sandbox image.

## Testing

**Backend:**

```bash
cd backend
.venv/bin/python -m pytest        # 326 passed with Docker up (321 + 5 skipped without it)
.venv/bin/ruff check app tests    # clean, as of this writing
```

(On Windows, `.venv\Scripts\python -m pytest` and `.venv\Scripts\ruff check app tests`.)

The execution tests start real subprocesses using the test venv's own
interpreter as the runner, so the timeout kill, environment scrubbing and
output cap are exercised for real. They do not need `.venv-runner`.

The five live Docker tests (no network inside the container, read-only
inputs, timeout kill, and the recorded Gemini pipelines run in the image)
skip themselves unless the engine is running and `autonexus-runner:latest`
is built. CI builds the image and runs them on every push.

To re-record cassettes after a prompt-affecting change (costs one Gemini
request per changed cassette; stale ones are pruned):
`.venv/bin/python -m tests.record_cassettes`.

Tests are fixture-corpus-driven: profiler and validator changes require a
named fixture CSV (`tests/fixtures/`) or a code-string fixture
(`tests/fixtures/validation_corpus.py`) demonstrating the specific behaviour,
and assertions check structural invariants, never exact LLM prose.

**LLM tests run offline.** `backend/tests/cassettes/*.json` holds three real
recorded Gemini responses, keyed by a hash of the exact prompt text. Any
change to `ColumnProfile`, `ProfileCard`, or `prompts.py` invalidates all
three and the affected tests fail with `FileNotFoundError` - `test_prompts.py`
asserts the prompt's structure independently and is the intended tripwire,
firing before a cassette miss would. Re-recording costs real Gemini quota, so
it should be a deliberate, batched action, not incidental to unrelated work.

**Frontend:**

```bash
cd frontend
npm test          # Vitest: 27 tests, jsdom, every fetch stubbed
npx tsc -b        # strict typecheck
npm run build     # runs tsc, then the production Vite build
```

The frontend tests cover the reducer's invariants (a failed generation keeps
the profile, a re-profile discards the pipeline and its run, session
restore), the API client (error envelope, bearer header, the click-event
guard, execute sending no body), and the rendering contracts that matter
most: the "not executed" notice versus the sample label, run output shown
only verbatim, chart text alternatives, and the token prompt.

**CI** (`.github/workflows/ci.yml`) runs on every push and pull request:
backend lint and tests, a Docker job that builds the runner image and runs
the live container tests, and frontend tests plus build. No secrets needed.

## Security Notes

- **Generated code is not executed by default.** The twelve checks in
  [Validation](#validation) are static analysis only - they reduce the
  chance that code you choose to run yourself does something obviously
  unsafe, but they are not a sandbox and were never designed as one.
- **The subprocess backend is not a security sandbox.** With
  `ENABLE_LOCAL_EXECUTION=true` and `EXECUTION_BACKEND=subprocess` the server
  runs model-written code in a subprocess on your machine. It is screened,
  isolated from the API's environment variables, confined to a temp
  directory as its working directory, and killed on timeout - but there is no
  container, so a determined script could still read files your user account
  can read. The boot guard refuses this backend outside `DEPLOYMENT_ENV=local`.
- **The Docker backend is the isolation boundary.** No network, read-only
  filesystem and inputs, non-root, no capabilities, resource limits, killed
  by name on timeout. Container isolation shares the host kernel; it is a
  strong boundary for this purpose, not a virtual machine. Either way, only
  code the server generated is ever run - the endpoint accepts no code.
- **Access tokens, not accounts.** With `API_TOKENS` set, every dataset route
  requires a bearer token, compared in constant time and never logged or
  echoed. `DEPLOYMENT_ENV=hosted` refuses to boot without tokens. A token
  holder can still reach any dataset id they observe; ids are random UUIDs
  that expire in 24 hours. Without `API_TOKENS` (local only) every route is
  open to anyone who can reach the process, so keep it bound to localhost.
- **Rate limits** cap each client's uploads, generations (protecting the
  shared model quota), runs, and general requests.
- **Prompt injection is a considered threat, not an oversight.** The only
  user-controlled text that reaches the LLM prompt is column names and a
  small number of capped, truncated category-level names; the system prompt
  explicitly instructs the model to treat all of it as inert data, never as
  instructions, and to flag anything suspicious in the `risks` field rather
  than act on it.
- **A dev-only npm advisory is currently open** - see
  [Known Limitations](#known-limitations).
- **Beyond localhost:** set `DEPLOYMENT_ENV=hosted` and `API_TOKENS`, use
  `EXECUTION_BACKEND=docker` if execution is on, run a single worker, and put
  it behind a TLS-terminating reverse proxy - tokens sent over plain HTTP can
  be read on the wire.

## Contributing / Development

Read [`CLAUDE.md`](CLAUDE.md) first - it is the binding rule set for this
repository (dependency constraints, the prompt-surface-vs-comment split in
`models.py`, why `GenResult`'s field order must not change, testing
requirements). Local-dev gotchas that have already cost time once - CORS
between `localhost` and `127.0.0.1`, the Gemini timeout floor, cassette
invalidation, async task garbage collection - are catalogued in
[`docs/development.md`](docs/development.md) so they only cost time once.

Before proposing a feature, check
[`docs/not-building.md`](docs/not-building.md) - a proposal that appears
there is closed until that file is edited with a reason, not quietly built
around it.

## License

No license file is present in this repository. Treat the code as
all-rights-reserved by default unless the repository owner adds one.
