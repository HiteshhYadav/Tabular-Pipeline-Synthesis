/** The reducer's invariants - the ones the whole single-useReducer design exists for. */

import { describe, expect, it } from "vitest";
import { initialState, reducer, type AppState } from "./state";
import { dataset, detail, profile, result, run, validation } from "./test/fixtures";

function profiled(): AppState {
  let state = reducer(initialState, { type: "UPLOAD_SUCCEEDED", dataset });
  state = reducer(state, { type: "TARGET_SELECTED", targetColumn: "churned" });
  return reducer(state, { type: "PROFILE_SUCCEEDED", profile, taskWasOverridden: false });
}

function generated(): AppState {
  return reducer(profiled(), {
    type: "GENERATE_SUCCEEDED",
    result,
    validation,
    usage: null,
  });
}

describe("reducer", () => {
  it("keeps the profile when a generation fails", () => {
    let state = reducer(profiled(), { type: "REQUEST_STARTED", operation: "generate" });
    state = reducer(state, {
      type: "REQUEST_FAILED",
      error: { code: "LLM_TIMEOUT", message: "slow", retryable: true, details: {} },
    });
    expect(state.profile).toEqual(profile);
    expect(state.busy).toBe(false);
    expect(state.error?.code).toBe("LLM_TIMEOUT");
  });

  it("discards the pipeline, its run and its charts on a re-profile", () => {
    let state = reducer(generated(), { type: "EXECUTE_SUCCEEDED", run: run() });
    state = reducer(state, {
      type: "DISTRIBUTIONS_LOADED",
      distributions: { dataset_id: "ds-1", n_rows: 3000, columns: [] },
    });
    state = reducer(state, { type: "PROFILE_SUCCEEDED", profile, taskWasOverridden: true });
    expect(state.result).toBeNull();
    expect(state.validation).toBeNull();
    expect(state.run).toBeNull();
    expect(state.distributions).toBeNull();
  });

  it("a new generation hides the previous run", () => {
    let state = reducer(generated(), { type: "EXECUTE_SUCCEEDED", run: run() });
    state = reducer(state, { type: "GENERATE_SUCCEEDED", result, validation, usage: null });
    expect(state.run).toBeNull();
  });

  it("a failed run is still a stored run, and the pipeline stays", () => {
    const failed = run({ succeeded: false, exit_code: 1, stderr: "Traceback" });
    const state = reducer(generated(), { type: "EXECUTE_SUCCEEDED", run: failed });
    expect(state.run).toEqual(failed);
    expect(state.result).toEqual(result);
    expect(state.error).toBeNull();
  });

  it("restores the pipeline and its latest run from the server", () => {
    const latest = run();
    const state = reducer(initialState, {
      type: "SESSION_RESTORED",
      dataset: detail({
        pipeline: {
          result,
          validation,
          excluded_columns: ["plan"],
          generated_at: "2026-11-24T09:30:00Z",
          latest_run: latest,
        },
      }),
    });
    expect(state.screen).toBe("code");
    expect(state.result).toEqual(result);
    expect(state.validation).toEqual(validation);
    expect(state.excludedColumns).toEqual(["plan"]);
    expect(state.run).toEqual(latest);
  });

  it("restores to the profile screen when nothing was generated", () => {
    const state = reducer(initialState, { type: "SESSION_RESTORED", dataset: detail() });
    expect(state.screen).toBe("profile");
    expect(state.result).toBeNull();
  });

  it("turns UNAUTHORIZED into the access prompt, not an error banner", () => {
    let state = reducer(initialState, { type: "ACCESS_TOKEN_SET" });
    state = reducer(state, {
      type: "REQUEST_FAILED",
      error: { code: "UNAUTHORIZED", message: "no", retryable: false, details: {} },
    });
    expect(state.error).toBeNull();
    expect(state.access).toEqual({ required: true, hasToken: false, rejected: true });
  });

  it("keeps deployment capabilities across a reset and a new upload", () => {
    let state = reducer(initialState, {
      type: "HEALTH_LOADED",
      health: {
        status: "ok",
        version: "0.1.0",
        execution_enabled: true,
        execution_sample_rows: 500,
        auth_required: true,
      },
    });
    state = reducer(state, { type: "RESET" });
    expect(state.execution).toEqual({ enabled: true, sampleRows: 500 });
    expect(state.access.required).toBe(true);
    state = reducer(state, { type: "UPLOAD_SUCCEEDED", dataset });
    expect(state.execution.enabled).toBe(true);
  });

  it("ignores chart data for a dataset the session has left", () => {
    const state = reducer(profiled(), {
      type: "DISTRIBUTIONS_LOADED",
      distributions: { dataset_id: "some-other-dataset", n_rows: 1, columns: [] },
    });
    expect(state.distributions).toBeNull();
  });
});
