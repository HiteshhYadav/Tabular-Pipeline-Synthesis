/**
 * The one piece of flow state in the application.
 *
 * Every screen reads from this object and none of them hold state of their own.
 * That is the whole point: with per-screen state, a failed generation unmounts
 * the strategy screen and takes the profile with it, and the user has to
 * re-upload to get back to where they were. Here a failure sets `error` and
 * leaves `profile` untouched, so retrying costs one click.
 *
 * The reducer lives here rather than in App.tsx so it can be read and tested
 * without the component around it. The single useReducer call is in App.tsx.
 */

import type {
  DatasetUploadResponse,
  DatasetDetail,
  DistributionsResponse,
  ErrorDetail,
  GenResult,
  HealthResponse,
  ProblemType,
  ProfileCard,
  RunResult,
  UsageResponse,
  ValidationReport,
} from "./types";

export type Screen = "landing" | "upload" | "target" | "profile" | "strategy" | "code";
export type Operation = "upload" | "profile" | "generate" | "execute" | null;

/** What this deployment allows, read once from /health at boot. */
export interface ExecutionCapability {
  enabled: boolean;
  sampleRows: number | null;
}

/** Whether the server wants a bearer token, and whether one is held. */
export interface AccessState {
  required: boolean;
  /** True once the browser holds a token. Not the token itself. */
  hasToken: boolean;
  /** Set when the server refused the held token, so the prompt can say so. */
  rejected: boolean;
}

export interface AppState {
  screen: Screen;
  busy: boolean;
  operation: Operation;
  profileOverride: ProblemType | null;
  error: ErrorDetail | null;
  dataset: DatasetUploadResponse | null;
  targetColumn: string | null;
  profile: ProfileCard | null;
  result: GenResult | null;
  validation: ValidationReport | null;
  excludedColumns: string[];
  taskWasOverridden: boolean;
  usage: UsageResponse | null;
  /** The latest run of the current pipeline. Null until one is executed. */
  run: RunResult | null;
  /** Deployment capability, not session data - survives RESET and new uploads. */
  execution: ExecutionCapability;
  access: AccessState;
  /** Chart data for the current profile. Null until loaded; never sent anywhere. */
  distributions: DistributionsResponse | null;
}

const executionUnknown: ExecutionCapability = { enabled: false, sampleRows: null };

export const initialState: AppState = {
  screen: "landing",
  busy: false,
  operation: null,
  profileOverride: null,
  error: null,
  dataset: null,
  targetColumn: null,
  profile: null,
  result: null,
  validation: null,
  excludedColumns: [],
  taskWasOverridden: false,
  usage: null,
  run: null,
  execution: executionUnknown,
  access: { required: false, hasToken: false, rejected: false },
  distributions: null,
};

export type Action =
  | {
      type: "REQUEST_STARTED";
      operation: Exclude<Operation, null>;
      profileOverride?: ProblemType;
    }
  | { type: "REQUEST_FAILED"; error: ErrorDetail }
  | { type: "UPLOAD_SUCCEEDED"; dataset: DatasetUploadResponse }
  | { type: "TARGET_SELECTED"; targetColumn: string }
  | { type: "PROFILE_SUCCEEDED"; profile: ProfileCard; taskWasOverridden: boolean }
  | { type: "GENERATE_SUCCEEDED"; result: GenResult; validation: ValidationReport; usage: UsageResponse | null }
  | { type: "EXECUTE_SUCCEEDED"; run: RunResult }
  | { type: "HEALTH_LOADED"; health: HealthResponse }
  | { type: "USAGE_LOADED"; usage: UsageResponse }
  | { type: "DISTRIBUTIONS_LOADED"; distributions: DistributionsResponse }
  | { type: "ACCESS_TOKEN_SET" }
  | { type: "EXCLUSIONS_CHANGED"; columns: string[] }
  | { type: "SESSION_RESTORED"; dataset: DatasetDetail }
  | { type: "NAVIGATED"; screen: Screen }
  | { type: "DISMISSED_ERROR" }
  | { type: "RESET" };

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "REQUEST_STARTED":
      return {
        ...state,
        busy: true,
        operation: action.operation,
        profileOverride: action.operation === "profile" ? action.profileOverride ?? null : state.profileOverride,
        error: null,
      };

    case "REQUEST_FAILED":
      // Note what is absent: nothing is cleared. A generation that fails leaves
      // the profile in place so the retry does not restart the flow.
      if (action.error.code === "UNAUTHORIZED") {
        // Shown as the access prompt, not as a generic error banner.
        return {
          ...state,
          busy: false,
          error: null,
          access: { required: true, hasToken: false, rejected: state.access.hasToken },
        };
      }
      return { ...state, busy: false, error: action.error };

    case "UPLOAD_SUCCEEDED":
      return {
        ...initialState,
        execution: state.execution,
        access: state.access,
        dataset: action.dataset,
        screen: "target",
      };

    case "TARGET_SELECTED":
      return {
        ...state,
        targetColumn: action.targetColumn,
        profile: null,
        result: null,
        validation: null,
        usage: null,
        run: null,
        distributions: null,
        excludedColumns: [],
        taskWasOverridden: false,
        error: null,
      };

    case "PROFILE_SUCCEEDED":
      return {
        ...state,
        busy: false,
        operation: null,
        profileOverride: null,
        error: null,
        profile: action.profile,
        result: null,
        validation: null,
        usage: null,
        // The server discards the old pipeline and its runs on a re-profile,
        // so the client must too, or it would show a run of deleted code.
        run: null,
        distributions: null,
        taskWasOverridden: action.taskWasOverridden,
        screen: "profile",
      };

    case "GENERATE_SUCCEEDED":
      return {
        ...state,
        busy: false,
        operation: null,
        profileOverride: null,
        error: null,
        result: action.result,
        validation: action.validation,
        usage: action.usage,
        run: null,
        screen: "strategy",
      };

    case "EXECUTE_SUCCEEDED":
      // A crashed or timed-out run is still a success here: the request
      // worked, and the RunResult says how the pipeline itself fared.
      return {
        ...state,
        busy: false,
        operation: null,
        error: null,
        run: action.run,
      };

    case "HEALTH_LOADED":
      return {
        ...state,
        execution: {
          enabled: action.health.execution_enabled,
          sampleRows: action.health.execution_sample_rows,
        },
        access: { ...state.access, required: action.health.auth_required },
      };

    case "DISTRIBUTIONS_LOADED":
      // Ignore a response for a dataset the session has since moved off.
      if (state.dataset?.dataset_id !== action.distributions.dataset_id) return state;
      return { ...state, distributions: action.distributions };

    case "ACCESS_TOKEN_SET":
      return { ...state, error: null, access: { ...state.access, hasToken: true, rejected: false } };

    case "USAGE_LOADED":
      return { ...state, usage: action.usage };

    case "EXCLUSIONS_CHANGED":
      return { ...state, excludedColumns: action.columns };

    case "SESSION_RESTORED": {
      // The stored pipeline is only ever the one generated against the stored
      // profile - the server deletes it on re-profile - so restoring both
      // together cannot pair a result with the wrong profile.
      const pipeline = action.dataset.profile ? action.dataset.pipeline : null;
      return {
        ...initialState,
        execution: state.execution,
        access: state.access,
        dataset: {
          dataset_id: action.dataset.dataset_id,
          filename: action.dataset.filename,
          n_rows: action.dataset.n_rows,
          n_columns: action.dataset.n_columns,
          columns: action.dataset.columns,
          state: action.dataset.state,
        },
        targetColumn: action.dataset.profile?.target_column ?? null,
        profile: action.dataset.profile,
        taskWasOverridden: action.dataset.task_was_overridden,
        result: pipeline?.result ?? null,
        validation: pipeline?.validation ?? null,
        excludedColumns: pipeline?.excluded_columns ?? [],
        run: pipeline?.latest_run ?? null,
        screen: pipeline ? "code" : action.dataset.profile ? "profile" : "target",
      };
    }

    case "NAVIGATED":
      return { ...state, screen: action.screen, error: null };

    case "DISMISSED_ERROR":
      return { ...state, error: null };

    case "RESET":
      return { ...initialState, execution: state.execution, access: state.access };
  }
}
