/** Typed fixtures for frontend tests. Shapes mirror backend/app/models.py. */

import type {
  ColumnProfile,
  DatasetDetail,
  DatasetUploadResponse,
  GenResult,
  ProfileCard,
  RunResult,
  ValidationReport,
} from "../types";

export const dataset: DatasetUploadResponse = {
  dataset_id: "ds-1",
  filename: "churn.csv",
  n_rows: 3000,
  n_columns: 3,
  columns: ["tenure", "plan", "churned"],
  state: "pending",
};

function column(overrides: Partial<ColumnProfile> & Pick<ColumnProfile, "name">): ColumnProfile {
  return {
    inferred_type: "numeric_continuous",
    pandas_dtype: "float64",
    missing_count: 0,
    missing_pct: 0,
    unique_count: 10,
    unique_pct: 0.01,
    top_value_pct: null,
    sample_values: null,
    min: null,
    max: null,
    mean: null,
    std: null,
    median: null,
    parse_rate: null,
    target_association: null,
    association_method: "none",
    flags: [],
    ...overrides,
  };
}

export const profile: ProfileCard = {
  dataset_id: "ds-1",
  filename: "churn.csv",
  n_rows: 3000,
  n_columns: 3,
  target_column: "churned",
  problem_type: "binary_classification",
  task_confidence: 0.95,
  primary_metric: "pr_auc",
  secondary_metrics: ["roc_auc", "f1"],
  class_balance_ratio: 10.9,
  duplicate_row_count: 0,
  profiled_on_sample: false,
  sample_rows: null,
  columns: [
    column({ name: "tenure" }),
    column({ name: "plan", inferred_type: "categorical", sample_values: ["basic", "plus"] }),
    column({ name: "churned", inferred_type: "boolean", sample_values: ["no", "yes"] }),
  ],
};

export const result: GenResult = {
  problem_type: "binary_classification",
  target_column: "churned",
  primary_metric: "pr_auc",
  dropped_columns: [],
  preprocessing: [],
  candidate_models: [
    { name: "HistGradientBoostingClassifier", library: "scikit-learn", rationale: "a" },
    { name: "LogisticRegression", library: "scikit-learn", rationale: "b" },
  ],
  validation_strategy: "Stratified 5-fold cross-validation.",
  analysis_summary: "Test summary.",
  risks: [],
  code: "import pandas as pd\ndf = pd.read_csv('data.csv', engine='c')\n",
};

export const validation: ValidationReport = {
  passed: true,
  error_count: 0,
  warning_count: 0,
  checks: [
    {
      check_id: "syntax_compile",
      title: "Code compiles",
      severity: "error",
      passed: true,
      message: "ok",
      details: [],
    },
  ],
};

export function run(overrides: Partial<RunResult> = {}): RunResult {
  return {
    run_id: "run-1",
    executed_at: "2026-11-24T10:00:00Z",
    sample_rows: 500,
    exit_code: 0,
    timed_out: false,
    duration_ms: 6100,
    stdout: "pr_auc: 0.2530\n",
    stderr: "",
    stdout_truncated: false,
    stderr_truncated: false,
    succeeded: true,
    ...overrides,
  };
}

export function detail(overrides: Partial<DatasetDetail> = {}): DatasetDetail {
  return {
    ...dataset,
    created_at: "2026-11-24T09:00:00Z",
    state: "complete",
    task_was_overridden: false,
    profile,
    pipeline: null,
    ...overrides,
  };
}
