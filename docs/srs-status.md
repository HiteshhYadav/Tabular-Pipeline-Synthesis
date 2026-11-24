# SRS implementation status

This repository has no standalone SRS or design document committed to it.
`IMPLEMENTATION_PLAN.md:300` references "the SRS" as the source the
[not-building list](not-building.md) exists to test proposals against, but
that source document itself was never checked in - it lived in an external
"final blueprint" the plan was built from. This file, `not-building.md`, and
`IMPLEMENTATION_PLAN.md` together are the closest thing to a requirements
record this repository has, and this table is measured against them, not
against a file that does not exist here.

This file supersedes an earlier `docs/backend-refinement-plan.md`. That
document proposed eleven numbered recommendations (R0-R11); most have since
been acted on. What follows is the current state and the backlog that
remains, not the original proposal document.

---

## Full status table

Status legend: ✅ Complete · 🟡 Partial · ❌ Not implemented · ❌* Not
implemented, deliberately (see `not-building.md`)

| Feature | Status | Current implementation | Remaining work |
|---|---|---|---|
| CSV upload, size/shape validation | ✅ | `ingest.py`: streamed size check, pre-pandas duplicate-header check, 7 rejection codes | - |
| Target column selection | ✅ | `ProfileRequest.target_column` | - |
| Target/task override | ✅ | `problem_type_override`, coherence-checked in `profiler._apply_task_override` | - |
| Feature exclusion | ✅ | `GenerateRequest.excluded_columns`, validated against the stored profile | - |
| Task inference (classification/regression) | ✅ | `dtypes.py` 7-rung ladder + `profiler._map_problem_type` | - |
| Dataset profiling (dtypes, missing, cardinality, duplicates) | ✅ | `profiler.py` | - |
| Class balance / imbalance detection | ✅ | `metrics.py::class_balance_ratio` | - |
| Leakage / target-association signal | ✅ | `leakage.py`, 3 formulas by type | - |
| Metric recommendation | ✅ | `metrics.py::select_metrics`, band-based | - |
| Metric override | ❌ | - | Not designed. Task override exists; metric is always re-derived from the (possibly overridden) task. Low priority - no reported need yet |
| LLM strategy generation | ✅ | `llm.py`, `prompts.py`, Gemini structured output | - |
| Structured `GenResult` (Pydantic response_schema) | ✅ | `models.py`, verified field-order preservation - see `spike-01` | - |
| Preprocessing strategy | ✅ | `GenResult.preprocessing`, LLM-authored, grounded in profile facts | - |
| Candidate model selection | ✅ | `GenResult.candidate_models`, 2-4, no score field | - |
| Validation-strategy description | ✅ | `GenResult.validation_strategy`, prose, not executed | - |
| Static code validation (13 checks) | ✅ | `validation.py` - see README's Validation section for the full list | - |
| Invented-column detection | ✅ | `hallucinated_columns` check, fuzzy-match against real names | - |
| Strategy/code self-consistency | ✅ | `gen_result_self_consistency` check | - |
| One automatic repair attempt (schema failure) | ✅ | `llm.py::generate`, `MAX_ATTEMPTS = 2` | - |
| Repair loop on a *failed validation check* | ✅ | `llm.generate_validated`, one round (`CHECK_REPAIR_ROUNDS`), failing checks named in the repair prompt, better result kept | - |
| Frontend 5-screen workflow | ✅ | `frontend/src/screens/` | - |
| Real per-screen URLs, back/forward | ✅ | `frontend/src/routes.ts`, hand-rolled History API | - |
| Dataset/profile recovery (`GET /datasets/{id}`) | ✅ | `api/datasets.py` | - |
| Usage/quota visibility (`GET .../usage`) | ✅ | `api/datasets.py`, real token/latency data | - |
| Execution of generated code | ✅ | MVP-1.5, `execution.py` + `POST /datasets/{id}/execute`, off by default, local only | Container boundary before any non-local use |
| Local subprocess sandbox | ✅ | `LocalSubprocessSandbox`: separate `.venv-runner`, scrubbed env, temp dir, process-group kill on timeout | - |
| Docker execution sandbox | ✅ | `DockerSandbox` + `backend/runner.Dockerfile`: no network, read-only FS and inputs, non-root, no capabilities, memory/CPU/PID limits, killed by name on timeout | - |
| Model training / scores / comparison | ❌* | `GenResult` has no field capable of holding one | Not building until execution exists; even then the number must be labelled as measured on a sample |
| Feature importance | ❌ | Depends on execution | Not designed |
| Model download | ❌ | Depends on execution - no trained artifact exists anywhere | Not designed |
| Self-correction loop | ✅ | Schema repair plus check repair, one round each | - |
| Async jobs / progress polling | ❌ | `JobState` deliberately narrowed to `pending\|complete`; both routes are synchronous | Two honest paths: build it for real (job table, `GET /jobs/{id}`, real transitions), or leave both routes synchronous permanently. Leaving `JobState` half-built was the actual defect that was fixed - see `docs/development.md` |
| Distribution / histogram chart data | ✅ | `distributions.py` + `GET /datasets/{id}/distributions`, deliberately not on `ProfileCard`; charts and values table on the Profile screen | - |
| BigQuery | ❌ | No reference anywhere in the codebase | Not part of this architecture; would need its own design if ever proposed |
| WebSocket | ❌ | REST/HTTP only | Not needed unless async jobs are built |
| Authentication | ✅ | Shared bearer tokens (`API_TOKENS`, `security.py`); mandatory for `DEPLOYMENT_ENV=hosted` by boot guard; frontend token prompt | User accounts and per-user dataset ownership are not built |
| Rate limiting (multi-user) | ✅ | Per-client sliding windows for uploads, generations, runs and other requests, plus the per-dataset in-flight guard | In-process only: one worker |
| Database persistence | ✅ | SQLite, `storage.py` | - |
| SQLite WAL mode | ✅ | `storage.py::connect` sets `PRAGMA journal_mode=WAL` | - |
| TTL cleanup | ✅ | Hourly sweep + boot-time sweep, `DATASET_TTL_HOURS` | - |
| Backend test suite | ✅ | 362 tests, pytest, fixture-corpus-driven, real-subprocess sandbox tests | - |
| Large-dataset sampling coverage | ✅ | Frames above 200,000 rows built at test time: sampling engages, column stats stay exact, leakage still caught, deterministic | - |
| Frontend test suite | ✅ | Vitest + Testing Library, 27 tests: reducer invariants, API client, rendering contracts | - |
| Security testing | 🟡 | Static validation and execution preflight for generated code; auth, rate-limit, boot-guard and container-isolation tests; no dependency scanning, no formal pen test | See Security Notes in README |
| Performance / load testing | ❌ | None | Not started |
| CI/CD | ✅ (CI) | `.github/workflows/ci.yml`: backend lint+tests, Docker sandbox build + live container tests, frontend tests+build | No CD |
| Deployment tooling (Docker, compose) | ✅ | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` + `nginx.conf`, plus the sandbox image; verified healthy end to end | TLS is the host's reverse proxy |
| Multi-target prediction | ❌* | - | Deliberately out - see `not-building.md` #2 |
| Unsupervised learning | ❌* | - | Deliberately out - see `not-building.md` #3 |
| User-chosen algorithms/hyperparameters | ❌* | - | Deliberately out - see `not-building.md` #4 |
| User-chosen preprocessing steps | ❌* | - | Deliberately out - see `not-building.md` #5 |
| Client-supplied `ProfileCard` | ❌* | Explicitly forbidden as a security boundary | See `not-building.md` #6 |
| In-browser code editing | ❌* | - | Deliberately out - see `not-building.md` #7 |
| Chat / conversational refinement | ❌* | - | Deliberately out - see `not-building.md` #8 |
| Accounts, projects, history, sharing | ❌* | - | Deliberately out - see `not-building.md` #9 |
| Formats other than CSV | ❌* | - | Deliberately out - see `not-building.md` #11 |
| Streaming/chunked profiling | ❌* | Files are capped and read whole; sampling (not streaming) handles large row counts | See `not-building.md` #12 |
| Model/provider choice exposed to the user | ❌* | `LLM_MODEL` is deployment config, not a user setting | See `not-building.md` #13 |
| Prompt customization by the user | ❌* | - | Deliberately out - see `not-building.md` #14 |

---

## Ranked remaining work

Everything previously ranked here is done: large-dataset sampling tests,
the repair-on-failed-check loop, MVP-1.5 local execution, distribution
charts, the Docker execution sandbox, access tokens and rate limiting,
frontend tests and CI, container deployment, and the stage 7 real-world run
(`docs/stage7-real-world-run.md`).

If the scope grows, in this order:

1. **User accounts and per-user dataset ownership.** Shared tokens keep
   strangers out but let any token holder reach any dataset id they learn.
2. **A shared rate-limit store.** Only needed for more than one worker; the
   in-process windows are correct for the single worker this app runs as.
3. **A prompt note on removed scikit-learn APIs.** Only if the
   `removed_sklearn_api` repair round fires on most regression generations;
   the validator already catches it deterministically.

## Explicitly not recommended

| Proposal | Why not |
|---|---|
| Multi-target prediction | Touches `problem_type`, `task_confidence`, `primary_metric`, and `class_balance_ratio` on every profile - turns `target_association` from a scalar into a matrix. Changes the prompt, therefore invalidates all three cassettes, for a need that is genuinely niche against "give a defensible starting pipeline" |
| User-chosen algorithms or hyperparameters | The model choosing an approach *and justifying it against the profile* is the product. A dropdown of estimators makes this a form with an LLM attached |
| User-chosen preprocessing steps | Same reasoning, and `PreprocessingStep.step` is free text rather than an enum - there is no fixed vocabulary to expose as a UI control even if this were wanted |
| Accepting a client-supplied `ProfileCard` | Permanently forbidden - a caller who can edit the profile can make the model justify any pipeline, and the self-consistency check would still pass because it compares the result against the same forged profile |
| Any metric/score value on `GenResult` | Forbidden by `CLAUDE.md`. No execution means any number here would be fabricated, and it would render with the same formatting as a measured one |
| Executing generated code in the API process | The separate runner venv and subprocess boundary exist specifically so execution is never in-process |
