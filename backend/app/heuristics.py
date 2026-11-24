"""Every threshold in the system. Constants only, no functions, no imports.

Two rules govern this file. First, no magic number appears anywhere else in the
codebase; if a rule needs a number, it gets a name here. Second, every constant
carries the reasoning for its value and what moving it costs in each direction,
because a threshold you cannot defend is a bug that looks like a decision.

Three of these constants interact with sampling in a way that is not obvious.
See the note above SAMPLE_THRESHOLD before writing the profiler.
"""

# ---------------------------------------------------------------------------
# Missingness
# ---------------------------------------------------------------------------

# Proportion of missing values above which a column is flagged HIGH_MISSING.
#
# 0.5 is the point where imputation starts inventing more of the column than it
# preserves: past half, a median or mode fill is mostly synthetic values wearing
# the authority of real ones, and any model reading that column is largely
# reading the imputer.
#
# Lower (0.3): flags columns that impute perfectly well and pushes the LLM to
# drop usable signal. Higher (0.7): lets near-empty columns through unremarked.
#
# Known blind spot: missing-not-at-random columns, where absence is itself the
# signal (a discharge date that is null for patients still admitted). The flag
# will suggest dropping when a missing-indicator feature would be better. This
# is why the flag is advisory and the LLM makes the drop decision.
HIGH_MISSING_P = 0.5

# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------

# unique_count / n_rows at or above which a column is flagged ID_LIKE.
#
# Not 1.0. Real exports contain duplicated rows, re-issued keys, and a handful
# of collisions from an upstream join, and a primary key with four repeats in
# 50,000 rows is still a primary key. Demanding exactness makes the check fire
# only on synthetic data.
#
# Lower (0.95): starts catching genuine high-cardinality features such as a
# transaction amount in cents, which is legitimately near-unique and predictive.
# Higher (1.0): useless on real files, as above.
ID_UNIQUENESS = 0.99

# Absolute unique-count above which a categorical column is flagged
# HIGH_CARDINALITY. The comparison is strictly greater than, which matters:
# US states are exactly 50, and one-hot encoding 50 states is ordinary practice,
# not a warning.
#
# 50 is roughly where one-hot encoding stops being free. Below it the widened
# matrix is manageable for any model; above it the encoding starts to dominate
# the feature space and target or frequency encoding becomes the better answer.
#
# Lower (20): flags things every practitioner one-hots without thinking.
# Higher (100): a 90-category column silently one-hot expands.
HIGH_CARD_ABS = 50

# unique_count / n_rows above which a categorical column is flagged
# HIGH_CARDINALITY regardless of the absolute count.
#
# Needed because the absolute rule alone is wrong at both extremes of dataset
# size. In a 40-row file a 30-category column is nearly an identifier but never
# reaches 50. In a million-row file a 200-category column is perfectly ordinary
# but exceeds 50 easily. A column is flagged when either rule fires.
#
# 0.5 means over half the rows carry their own category. Lower (0.2): fires on
# ordinary categoricals in small files. Higher (0.8): overlaps ID_UNIQUENESS and
# stops adding information.
HIGH_CARD_REL = 0.5

# Share of non-null rows held by the single most common value, above which a
# column is flagged QUASI_CONSTANT.
#
# At 0.99 the column separates at most 1% of the data, so nearly every tree
# split or coefficient on it is fitted to a hundredth of the rows. That is a
# variance problem, not a signal.
#
# Lower (0.95): flags legitimately skewed features such as a fraud indicator.
# Higher (0.995): only catches columns that are constant in all but a rounding
# error.
#
# Hard constraint for stage 2: this flag must never be applied to the target
# column. A 1%-positive target is the entire point of an imbalanced
# classification problem, not a defect in the column.
QUASI_CONSTANT_P = 0.99

# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

# Fraction of sampled non-null values that must parse successfully for a column
# stored as strings to be reclassified as a richer type.
#
# One threshold, two rungs of the ladder. It decides whether an object column
# becomes DATETIME, and whether an object column that is really digits with
# thousands separators, currency symbols, or stray whitespace becomes numeric
# and earns the NUMERIC_AS_STRING flag. Both rungs ask the identical question -
# what share of the values are genuinely of type X - so they take the identical
# answer, and splitting them would be two names for one decision.
#
# 0.90 tolerates the real-world mess (a few "N/A" strings, a stray footer row,
# two rows in a different format) without accepting a free-text column that
# happens to mention dates or prices.
#
# Lower (0.7): coerces messy text and silently nulls a third of the column,
# which is worse than leaving it categorical because the loss is invisible
# downstream. Higher (0.98): rejects ordinary export files.
PARSE_RATE = 0.90

# Distinct-value count at or below which a numeric column is classified
# NUMERIC_DISCRETE rather than NUMERIC_CONTINUOUS.
#
# The distinction is not cosmetic: a discrete numeric column is a set of levels
# and often wants encoding rather than scaling, and an integer column with five
# values is a categorical wearing an int64.
#
# 20 covers essentially every ordinal scale that occurs in practice - Likert 1-5
# and 1-7, star ratings, satisfaction scores, small counts, number of
# dependents - while leaving genuine measurements alone. Age in whole years has
# roughly 80 distinct values and stays continuous, correctly.
#
# Known blind spot, accepted: hour-of-day (24) and day-of-month (31) fall on the
# continuous side. Raising this to 32 would catch them, and would also start
# swallowing genuinely continuous measurements that happen to have a narrow
# range, which is the more expensive error - a one-hot on a measurement destroys
# its ordering. Those two cases belong to datetime feature extraction anyway.
#
# Interaction to respect in stage 2: in a very small file every numeric column
# has few distinct values, so this rule must not fire when unique_count is close
# to n_rows. HIGH_CARD_REL and ID_UNIQUENESS govern that regime.
NUMERIC_DISCRETE_MAX_UNIQUE = 20

# ---------------------------------------------------------------------------
# Prompt exposure
# ---------------------------------------------------------------------------
#
# The only values from the user's file that ever reach a prompt. Everything else
# crossing that boundary is a derived statistic. These two constants are the
# width of that gap, so they are deliberately narrow.

# Distinct-value count at or below which a CATEGORICAL column's level names are
# carried in ColumnProfile.sample_values (capped at five values regardless).
#
# Level names are metadata of the kind a data dictionary publishes, and without
# them the model cannot separate ordinal from nominal, cannot see whether a
# binary column reads Y/N or Yes/No or 1/0, and writes mapping code that does
# not match the file.
#
# 20 is the point where a level name stops being a label and starts being an
# identifier. Above it the values are more likely to be free text, user-entered
# strings, or codes with real information in them, and none of those help the
# model while all of them widen the exposure.
#
# It matching NUMERIC_DISCRETE_MAX_UNIQUE is a coincidence, not a shared rule.
# They answer unrelated questions and either would move without the other.
#
# Never populate for TEXT or numeric columns, and never for a column flagged
# ID_LIKE or HIGH_CARDINALITY, whatever this threshold says.
SAMPLE_VALUES_MAX_UNIQUE = 20

# Character cap applied to each individual value in sample_values.
#
# 40 characters is longer than any real category label and short enough that a
# column which slipped through the guards above cannot dump a paragraph into the
# prompt. With at most five values per qualifying column, total exposure across
# a typical dataset stays around fifty tokens.
SAMPLE_VALUE_MAX_CHARS = 40

# Rows sampled for the datetime parse-rate test.
#
# Parsing a full messy column with a format inference per value is the classic
# way to make profiling hang, and it buys nothing: 1,000 rows puts the standard
# error on a parse rate near 0.90 at about 1%, which is far tighter than the
# distance between a real date column and a text one.
#
# The sample must be random with a fixed seed, not a head slice. CSVs arrive
# sorted by date, or with a leading block of nulls, or with a differently
# formatted first section, and every one of those biases a head slice in exactly
# the cases the check exists for. The fixed seed keeps profiling deterministic
# across reruns of the same file.
DTYPE_SAMPLE_N = 1000

# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------

# Absolute association between a feature and the target above which the column
# is flagged POTENTIAL_LEAKAGE.
#
# 0.98 is deliberately near-deterministic. A leaked column is usually a
# post-outcome artefact (`churn_date` predicting `churned`, `payout_amount`
# predicting `claim_approved`) and those sit at 0.99 or above, not at 0.9.
#
# Lower (0.90): flags genuinely strong legitimate predictors and trains the user
# to ignore the warning, which is the worse failure. Higher (0.995): misses
# leaks carrying a little noise.
#
# Use a rank correlation (Spearman) rather than Pearson: it is monotonic rather
# than linear, survives ordinal encodings, and is unaffected by scale. Compute
# it on a sample, and report the absolute value so both directions flag.
LEAKAGE_R = 0.98

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

# Row count above which the profiler computes its statistics on a sample and
# sets ProfileCard.profiled_on_sample.
#
# 200,000 rows is comfortably enough for every distributional statistic here
# (means, quantiles, missing rates, correlations) while keeping a full profile
# pass in the low seconds. Given MAX_FILE_MB, roughly the top decile of accepted
# files will trip it.
#
# THE INTERACTION THAT WILL BITE: unique counts do not subsample. Cardinality on
# a 10% sample collapses toward the sample size, so ID_UNIQUENESS,
# HIGH_CARD_REL and QUASI_CONSTANT_P all shift when this threshold trips - an
# identifier still looks unique, but an ordinary 200-category column starts
# looking near-unique in a small enough sample. Cardinality must be computed on
# the full column even when everything else is sampled. `nunique()` over one
# column of a 500k-row frame is cheap; the sampling exists for the correlation
# matrix and the parse loops, not for counting.
SAMPLE_THRESHOLD = 200_000

# ---------------------------------------------------------------------------
# Ingest limits
# ---------------------------------------------------------------------------

# Maximum accepted upload size, in megabytes. Enforced while streaming, before
# the file is buffered.
#
# Caveat worth stating plainly: this is a disk figure standing in for a memory
# figure. A 50MB CSV of predominantly string columns occupies roughly 400-600MB
# once pandas materialises it as object dtype, so the real ceiling this implies
# is an order of magnitude above the number. Safe on a development machine,
# fatal on a small hosted instance. If this ever runs anywhere memory-capped,
# the fix is a resident-memory guard, not a smaller number here.
MAX_FILE_MB = 50

# Maximum in-memory size of the parsed frame, in megabytes, measured with
# df.memory_usage(deep=True).sum(). Exceeding it rejects with
# DATASET_TOO_LARGE_IN_MEMORY.
#
# DERIVED FROM MAX_FILE_MB, NOT CHOSEN INDEPENDENTLY. It is MAX_FILE_MB times
# the roughly 10x expansion that object-dtype string columns undergo when pandas
# materialises them. If MAX_FILE_MB changes, this number has to change with it,
# or the two limits start contradicting each other and one rejects files the
# other accepts for reasons nobody can reconstruct later.
#
# 50 * 10 = 500.
#
# Lower (250): rejects legitimate files. A 30MB CSV of mostly free text clears
# the disk check easily and lands near 300MB in memory, and that is an ordinary
# dataset, not an abusive one. Higher (1000): profiling transiently copies for
# value_counts, the correlation matrix, astype conversions and sampling, so peak
# runs about 2 to 2.5x the resident frame. A 1GB frame implies 2.5GB peak, which
# swaps or dies on an 8GB laptop also running a browser and an editor. 500
# resident is about 1.25GB peak, which survives.
#
# WHAT THIS DOES NOT DO: it is a post-parse check, so the memory is already
# allocated by the time it can be measured. It protects the profiler from
# working on a frame that should never have been accepted. It cannot protect the
# parse itself. Genuinely closing that needs chunked reading with running
# accounting, which chunksize supports on the C engine and which complicates
# ingest considerably. The disk check catches the common case first.
#
# Also note memory_usage(deep=True) walks every Python string object, so it is
# O(total characters) rather than free. One-time cost, but on a wide object
# frame it is the same order as the parse.
MAX_MEMORY_MB = 500

# Maximum accepted column count. Above this the upload is rejected outright.
#
# 1,000 is a structural sanity bound: a tabular file wider than this is a
# feature matrix from some other pipeline, or a transposed file, and neither is
# what this tool is for.
#
# It does not protect the prompt. A 1,000-column ProfileCard is on the order of
# 50,000 tokens, which fits in the model's window and degrades its reasoning
# well before it overflows, and Screen 2 would render a 1,000-row table. Stage 3
# needs its own column budget for what gets serialised into the prompt; this
# constant is not it.
MAX_COLS = 1000

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# difflib.SequenceMatcher ratio at or above which two column names are treated
# as the same name, used to turn "the generated code references a column that
# does not exist" into "did you mean X".
#
# 0.85 over the get_close_matches default of 0.6, which is far too loose and
# will confidently pair unrelated column names. The check only runs on names
# that are already known not to exist, so a false positive costs a misleading
# suggestion rather than a spurious error.
#
# Casefold and strip separators before comparing, or the easy cases are missed:
# SequenceMatcher on "Age" against "age" scores 0.67 and would not match at any
# sane cutoff. Tune this against real generations once stage 3 produces them,
# not against intuition.
SIMILARITY_CUTOFF = 0.85

# ---------------------------------------------------------------------------
# Metric selection bands
# ---------------------------------------------------------------------------
#
# Applied to class_balance_ratio (n_majority / n_minority) to choose the
# primary metric:
#
#   class_balance_ratio <= BALANCE_ACCURACY_MAX          -> accuracy
#   BALANCE_ACCURACY_MAX < class_balance_ratio <= BALANCE_F1_MAX -> F1
#   class_balance_ratio > BALANCE_F1_MAX                 -> PR-AUC
#
# The bands are only meaningful once class_balance_ratio is defined, and the
# binary definition (n_majority / n_minority) does not transfer to multiclass:
# a fifteen-class dataset that is entirely reasonable to model can show a 12:1
# spread between its largest and smallest class, which would route it to PR-AUC,
# a metric that is not even well defined for multiclass without an averaging
# choice. metrics.py must therefore branch on problem type before applying
# these, and use macro-F1 for multiclass rather than reading the upper band.

# Upper bound on class_balance_ratio for accuracy to remain an honest metric.
#
# 1.5 is a 60/40 split. The majority-class baseline is 60%, a real model clears
# it visibly, and accuracy still means what a user assumes it means.
#
# Higher (2.0): a 67% baseline goes in front of a non-expert reading it as a
# good score. Lower (1.2): pushes near-balanced problems onto F1 for no gain,
# since the two agree closely at that point anyway.
BALANCE_ACCURACY_MAX = 1.5

# Upper bound on class_balance_ratio for F1 to remain the better choice over
# PR-AUC.
#
# 10 is roughly a 9% minority class. Below it F1 at a sensible threshold is
# informative and far easier to explain. Above it F1 becomes acutely sensitive
# to the decision threshold, and PR-AUC's threshold independence is worth the
# loss of intuitiveness.
#
# Higher (20): F1 is still defensible at 5% positives, so this is a soft edge
# rather than a cliff. Lower (5): reaches for PR-AUC on problems most
# practitioners would report F1 on.
BALANCE_F1_MAX = 10

# Regression takes no bands. RMSE is always the primary, with MAE and R-squared
# always reported as secondaries.
#
# The tempting alternative is to switch the primary to MAE when the target is
# heavy-tailed, on the grounds that RMSE is outlier-sensitive. That is
# defensible statistics and it is rejected here for a product reason: it makes
# the headline metric depend on a distributional property the user cannot see
# the derivation of, so two similar datasets get different primaries for reasons
# that are invisible. RMSE always is explainable in one sentence and it matches
# the classification side, where the primary depends only on class balance.
# R-squared is never primary: it is scale-free, so it hides the magnitude of the
# error, which is usually the thing the user actually needs.
#
# Every problem type reports secondary metrics. Suppressing the alternatives is
# the black-box behaviour this tool argues against - a primary metric shown
# alone cannot be checked for whether it was chosen to flatter the result.

# Absolute target skew above which the generated rationale mentions a log
# transform. It selects no metric and never will.
#
# 2.0 is the conventional line for "substantially skewed" and it is used here
# only to trigger a sentence of prose, so the cost of being slightly wrong is a
# suggestion the user ignores. That is deliberately the lowest-stakes possible
# use of a threshold, which is why a rule of thumb is adequate where the metric
# bands needed argument.
TARGET_SKEW_THRESHOLD = 2.0

# ---------------------------------------------------------------------------
# Generated output bounds
# ---------------------------------------------------------------------------

# Character cap on GenResult.analysis_summary.
#
# 2,000 characters is roughly three dense paragraphs, which is more than enough
# to justify a pipeline and short enough that the strategy screen stays
# readable. The model will otherwise fill whatever space it is given.
#
# Whether this survives into the request schema is a provider question, not a
# Pydantic one. If the constraint is dropped in translation the field must be
# truncated server side, because a model that has not been told a limit will
# eventually exceed it.
ANALYSIS_SUMMARY_MAX_CHARS = 2000

# Maximum number of ColumnProfile entries serialised into a prompt.
#
# Added in stage 3. MAX_COLS is a structural bound on what the tool will accept
# at all, and its own comment says plainly that it does not protect the prompt:
# a 1,000-column ProfileCard is on the order of 50,000 tokens, which fits in the
# model's window and degrades its reasoning long before it overflows. This is
# the budget MAX_COLS is not.
#
# 200 columns is roughly 12,000 tokens of profile at the compact serialisation
# in prompts.py, which leaves the model's attention on the modelling problem
# rather than on a wall of facts. It is also past the point where per-column
# reasoning is the right approach at all: a dataset wider than this needs
# dimensionality reduction as its strategy, which is a different task from the
# one this tool performs.
#
# Lower (50): starts truncating ordinary wide datasets, and the model then
# plans around columns it cannot see. Higher (500): 30,000 tokens of profile,
# where the reasoning degradation the number exists to prevent has already set
# in.
#
# Truncation is never silent. When it applies, the target and every flagged
# column are kept first, the remainder fills by descending target association,
# and the prompt states how many columns were omitted so the model knows its
# view is partial. See prompts.py.
PROMPT_MAX_COLUMNS = 200

# Cap on the number of entries in GenResult.risks.
#
# 8 is past the point of diminishing returns. A risk list long enough to need
# scrolling reads as hedging and gets skipped entirely, which loses the two or
# three items that actually mattered. Bounds the list length, not the length of
# each entry.
RISKS_MAX_ITEMS = 8

# ---------------------------------------------------------------------------
# Task inference
# ---------------------------------------------------------------------------
#
# Added in stage 2, not in the original 21. task_confidence is a required
# ProfileCard field with no formula specified anywhere in the plan or in this
# file, and CLAUDE.md's rule against magic numbers outside this file applies to
# it exactly as it does to every threshold above. These two constants are the
# alternative to a bare 0.95 sitting in profiler.py with no name. Flagged for
# review rather than assumed approved, the same way MAX_MEMORY_MB was proposed
# before it was used.
#
# The mapping from a target's inferred type to a problem type is deterministic
# once the dtype ladder has run: BOOLEAN and CATEGORICAL targets are
# classification, NUMERIC_CONTINUOUS is regression, and none of those three
# leave the choice in doubt. NUMERIC_DISCRETE does leave it in doubt - a target
# with 6 distinct integer values could be star ratings (classification) or a
# small count (regression, e.g. Poisson-shaped), and nothing in the profile
# distinguishes the two cases. Splitting the confidence in two lets the
# frontend signal that doubt honestly rather than reporting false precision.

# Confidence assigned when the target's inferred type maps to a problem type
# with no ambiguity: BOOLEAN and CATEGORICAL to classification,
# NUMERIC_CONTINUOUS to regression.
#
# Not 1.0. The dtype ladder itself is a heuristic (PARSE_RATE tolerates up to
# 10% mismatch, ID_UNIQUENESS tolerates duplicate keys), so the type call it
# produced is not certain even when the type-to-problem mapping downstream of
# it is. 0.95 reflects confidence in the mapping while leaving room for the
# type call underneath it to be wrong.
TASK_CONFIDENCE_TYPE_MATCH = 0.95

# Confidence assigned when the target is NUMERIC_DISCRETE: classification or
# regression is a genuine judgment call, not a fact the profiler can settle.
#
# 0.65 is deliberately in the region a frontend would render as "verify this"
# rather than "trust this". Lower (0.4) reads as a coin flip, which
# understates the real signal - low unique_count on a numeric column does lean
# toward classification, most numeric columns with 20 or fewer values in
# practice are rating scales or small categories, not counts. Higher (0.8)
# undersells how often this guess is wrong.
TASK_CONFIDENCE_DISCRETE_AMBIGUOUS = 0.65

# ---------------------------------------------------------------------------
# Self-correction (repair on a failed static check)
# ---------------------------------------------------------------------------

# How many extra generation rounds to spend when a parsed GenResult fails an
# ERROR-severity static check (a hallucinated column, a forbidden import, a
# strategy that contradicts the profile).
#
# One. The repair round tells the model exactly which checks failed and why,
# which is new information the first round did not have, so it is a real
# repair rather than a blind reroll. A second repair round would repeat the
# same information to a model that already ignored it once, and on a free tier
# of 20 requests per day per model each extra round is 5% of the day's budget.
# Zero would leave the reserved VALIDATION_FAILED path unused and ship
# fixable mistakes to the user.
CHECK_REPAIR_ROUNDS = 1

# ---------------------------------------------------------------------------
# MVP-1.5 local execution
# ---------------------------------------------------------------------------
#
# The row count and the timeout are deployment settings (EXECUTION_SAMPLE_ROWS,
# EXECUTION_TIMEOUT_S in .env), because they trade speed for fidelity on the
# operator's own machine. The constants below are properties of the sandbox
# itself and do not vary by deployment.

# Seed for drawing the execution sample. Same reasoning as the profiler's fixed
# seed: running the same pipeline twice on the same file must see the same
# rows, or a difference in output could be the sample rather than the code.
EXECUTION_SAMPLE_SEED = 42

# For classification targets, each class is guaranteed up to this many rows in
# the sample before the remainder is filled at random.
#
# A plain random 500-row sample of a 50:1 imbalanced file holds about ten
# minority rows, and often fewer, and a stratified 5-fold split refuses to run
# with fewer than five members of a class. The pipeline would then crash on
# the sample for a reason that has nothing to do with the code. 10 covers a
# train/test split followed by 5-fold CV on the training part. Higher (50)
# starts to distort the class balance the profile reported on small samples;
# lower (5) fails the moment a holdout split takes one row away.
EXECUTION_MIN_ROWS_PER_CLASS = 10

# Cap on captured stdout and stderr, each, in characters.
#
# 20,000 characters is several screens of training log, far more than any
# reasonable pipeline prints, and small enough to store per run and render
# without a virtualised list. Output past the cap is cut and flagged as
# truncated, never silently dropped. The cap also bounds what a runaway print
# loop can cost: output goes to temp files, not memory, and only the head is
# read back.
EXECUTION_OUTPUT_MAX_CHARS = 20_000

# Thread cap for the numerical libraries inside an execution run (OpenMP,
# OpenBLAS, MKL, and joblib's loky workers).
#
# A 500-row fit gains nothing measurable from more than two threads, and
# generated code commonly passes n_jobs=-1, which would otherwise fan out to
# every core on the developer's machine while the API is serving requests.
# 1 would be safe too, but leaves HistGradientBoosting visibly slower on the
# wider end of what the profiler accepts.
EXECUTION_THREAD_CAP = 2

# ---------------------------------------------------------------------------
# Distribution charts (Profile screen)
# ---------------------------------------------------------------------------
#
# These feed GET /datasets/{id}/distributions only. That endpoint is for the
# user's own eyes and is deliberately not part of ProfileCard, so none of the
# counts or level names below ever reach the model prompt.

# Equal-width bins for a continuous numeric column.
#
# 20 resolves the shapes that change a modelling decision - skew, a second
# mode, a spike at zero, a long tail - on files from a few hundred rows up.
# Fewer (10) merges a spike at zero into its neighbour; more (50) turns a
# 300-row file into mostly empty bins and noise, and stops fitting the
# compact chart the profile table has room for.
DISTRIBUTION_HISTOGRAM_BINS = 20

# Levels shown for a categorical, boolean or discrete column before the rest
# fold into one "other" count.
#
# 12 covers every boolean and nearly every genuinely categorical column in
# full, while a 500-level column still renders as a readable chart rather
# than 500 hairline bars. The folded remainder is always shown as a count, so
# nothing is silently dropped.
DISTRIBUTION_MAX_LEVELS = 12

# ---------------------------------------------------------------------------
# Rate limiting (per client: per access token, or per IP when auth is off)
# ---------------------------------------------------------------------------
#
# Sliding one-hour windows, except reads. The numbers protect two different
# things, so they differ by an order of magnitude.

# Model calls. The binding constraint is the provider quota - 20 requests per
# day per project per model on the free tier - not this server. 10 per hour
# lets one person iterate freely (each generate is one or two requests) while
# making it impossible for a single client to drain a whole day's quota in a
# few minutes and lock every other user out until tomorrow.
RATE_LIMIT_GENERATIONS_PER_HOUR = 10

# Uploads. Each one parses up to MAX_FILE_MB of CSV and holds it in memory.
# 30 per hour is far above a person trying files one by one, and far below
# what it takes to keep the parser busy on purpose.
RATE_LIMIT_UPLOADS_PER_HOUR = 30

# Local executions. Each one is up to EXECUTION_TIMEOUT_S of CPU in a
# subprocess. 30 per hour allows a rerun every two minutes.
RATE_LIMIT_EXECUTIONS_PER_HOUR = 30

# Everything else (reads, profiling) per minute. Profiling is the heaviest
# member of this group at a second or two on a large file; 120 per minute is
# well beyond any page's worth of polling and still caps a scripted loop.
RATE_LIMIT_REQUESTS_PER_MINUTE = 120

# ---------------------------------------------------------------------------
# Docker execution sandbox (EXECUTION_BACKEND=docker)
# ---------------------------------------------------------------------------

# Memory ceiling for one container run, in MB.
#
# A 500-row sample with a gradient-boosted model peaks well under 300 MB in
# practice; 1024 leaves room for a wide file and a forest of a few hundred
# trees while making a runaway allocation an OOM kill inside the container
# rather than swap pressure on the host.
EXECUTION_DOCKER_MEMORY_MB = 1024

# Maximum processes/threads inside the container.
#
# joblib and OpenMP together start tens of threads at most under the
# EXECUTION_THREAD_CAP environment. 256 is generous for that and still stops a
# fork bomb from exhausting the host's PID table.
EXECUTION_DOCKER_PIDS_LIMIT = 256

# Size of the writable /tmp inside an otherwise read-only container, in MB.
#
# Libraries write small scratch files (joblib's memmapping folder, numpy's
# config probes). 64 MB covers those; the pipeline itself is told not to write
# files, so anything needing more is the script misbehaving.
EXECUTION_DOCKER_TMPFS_MB = 64
