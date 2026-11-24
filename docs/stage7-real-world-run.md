# Stage 7: three real-world CSVs, end to end

`IMPLEMENTATION_PLAN.md` closes stage 7 with *"one run against three genuinely
messy real-world CSVs you have not seen before."* This is that run, recorded
honestly, including what failed.

**Files.** Three public datasets from the seaborn-data repository, chosen
because each carries a trap a careless pipeline falls into:

| File | Shape | Target | Trap |
|---|---|---|---|
| `titanic.csv` | 891 x 15 | `survived` | `alive` is the target spelled differently; 77% of `deck` is missing; 107 duplicate rows; `class` and `embark_town` duplicate other columns |
| `penguins.csv` | 344 x 7 | `species` | Multiclass, small, missing values in five columns |
| `taxis.csv` | 6,433 x 14 | `tip` | Raw timestamps; `total` includes the tip being predicted; high-cardinality zones |

**How.** Each file went through the real API exactly as a user's would:
upload, profile, `/distributions`, `/generate` against live Gemini
(`gemini-3.1-flash-lite`), then `/execute` on a 500-row sample under the
subprocess sandbox. Nothing was hand-edited between steps.

---

## Results

| | titanic | penguins | taxis |
|---|---|---|---|
| Task / metric (decided by rule) | binary / F1 (balance 1.61:1) | multiclass / F1-macro | regression / RMSE |
| Profiler flags | `alive` **potential_leakage** (association 1.0), `deck` high_missing | none | `pickup`, `dropoff` id_like; both zones high_cardinality |
| Dropped by the strategy | `alive`, `deck`, `class`, `embark_town` | none | `pickup`, `dropoff`, `total` |
| Static checks (13) | all passed | all passed | failed 1, **repaired**, then all passed |
| Model requests | 1 | 1 | 2 (first + check repair) |
| Run on sample | exit 0 | exit 0 | exit 0 |
| Printed by the pipeline | CV F1 0.732, holdout F1 0.795 | CV F1-macro 0.980 | CV RMSE 1.505, holdout RMSE 3.329 |

The printed figures are what each pipeline printed on a 500-row sample (all
344 rows for penguins). They show the code runs and is not degenerate; they
are not a claim about performance on the full data, and the product never
presents them as one.

---

## What the run found

### 1. The profiler catches a direct leak; the model catches a semantic one

On titanic, `alive` ("yes"/"no") is `survived` (1/0) renamed. The purity
statistic scored it 1.0, the profiler set `potential_leakage`, and the
strategy dropped it citing that number.

On taxis, `total` = fare + tip + tolls. Its rank association with `tip` is
only 0.499, so no threshold in `heuristics.py` flags it, and none should: a
univariate statistic cannot tell "contains the target" from "correlates with
the target". The model dropped it anyway, from the column's meaning, and said
why in `dropped_columns` and again in `risks`.

That is the architecture working as designed rather than a gap: Python
computes the facts it can compute exactly, and the model contributes the
judgement a statistic cannot. It is also a limit worth stating: leakage
detection is only as good as the combination, and a leak that is neither
statistically obvious nor semantically named would get through both.

### 2. A whole bug class the static checks did not cover - now fixed

Twice out of two regression generations for taxis, the model wrote

```python
mean_squared_error(y_test, preds, squared=False)
```

`squared=` was removed in scikit-learn 1.6. All twelve checks passed, and the
run crashed with `TypeError: got an unexpected keyword argument 'squared'`.
This is the "stale training data" risk `IMPLEMENTATION_PLAN.md` section 5
warns about, observed live.

**Fix:** a thirteenth check, `removed_sklearn_api` (ERROR), in
`backend/app/validation.py`. It flags APIs that were *removed* (not merely
deprecated) in a release the runner's `scikit-learn>=1.5` pin can install:
`squared=` on `mean_squared_error`/`mean_squared_log_error`, `sparse=` on
`OneHotEncoder`, `base_estimator=`, `max_features="auto"`, and the removed
`plot_*` metric helpers. Each finding names the replacement. Corpus entries
were added for three of them; the check flags the real taxis code at the exact
line.

Because it is ERROR severity, it feeds the existing repair round. The final
taxis attempt shows the closed loop: first response used `squared=False`, the
check failed it, the repair prompt carried the failure and its replacement,
the second response used `root_mean_squared_error`, all thirteen checks
passed, and the run exited 0.

### 3. Provider unavailability is routine, and handled

Gemini returned 503 on five of the eleven model calls made during this run (including the deployment smoke test). Each surfaced
as `LLM_UNAVAILABLE` with `retryable: true` - a retry button in the UI - and
never as a 500. In one case the 503 hit the *repair* round: as designed, the
already-paid-for first result was kept and returned with its real, failing
report rather than discarded.

### 4. Found by deploying, not by this run, but in the same pass

The first clean container build (`docker compose up`) crashed on import:
`llm.py` imports `httpx` directly, which was listed only as a dev dependency
and used to arrive transitively through `google-genai`. It is now a declared
runtime dependency. No test could have caught it, because every test
environment installs the dev extras; only a production-shaped install could.

---

## What was not changed, and why

The prompt was not edited to forbid `squared=`. The validator plus repair
round fixes the mistake for any model and any phrasing, and a prompt change
would invalidate all three recorded cassettes for a problem that is already
caught deterministically. If the repair round turns out to be needed on most
regression generations, a one-line prompt note becomes worth its re-record
cost; that is a judgement for more data than two generations.
