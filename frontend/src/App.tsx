/**
 * The whole flow.
 *
 * One useReducer holds every piece of state in the application. No screen owns
 * state of its own, which is what stops a failed generation from taking the
 * profile down with it. See state.ts for the reducer.
 */

import { useEffect, useReducer, useRef, useState } from "react";
import {
  ApiError,
  executePipeline,
  generatePipeline,
  getDataset,
  getAccessToken,
  getDatasetUsage,
  getDistributions,
  getHealth,
  profileDataset,
  setAccessToken,
  uploadDataset,
} from "./api";
import { AccessTokenPanel } from "./components/shared/AccessTokenPanel";
import { pathForScreen, screenForPath, titleForScreen } from "./routes";
import { ErrorPanel } from "./components/shared/ErrorPanel";
import { ActivityDialog } from "./components/layout/ActivityDialog";
import { WorkflowShell } from "./components/layout/WorkflowShell";
import { CodeScreen } from "./screens/CodeScreen";
import { LandingScreen } from "./screens/LandingScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { StrategyScreen } from "./screens/StrategyScreen";
import { TargetScreen } from "./screens/TargetScreen";
import { UploadScreen } from "./screens/UploadScreen";
import { initialState, reducer, type AppState, type Screen } from "./state";
import type { ErrorDetail, ProblemType } from "./types";

const RECOVERY_KEY = "autonexus-dataset-id";
const MIN_REQUEST_WINDOW_MS = 700;
const HANDOFF_WINDOW_MS = 650;

function pause(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

function toDetail(error: unknown): ErrorDetail {
  if (error instanceof ApiError) return error.detail;
  return {
    code: "UNKNOWN_ERROR",
    message: error instanceof Error ? error.message : "Something went wrong.",
    retryable: true,
    details: {},
  };
}

export default function App() {
  // Annotated, not inferred: without it the object literal widens `screen` to
  // string, no useReducer overload matches, and the failure surfaces as every
  // dispatch call in the file reporting "expected 0 arguments".
  const [state, dispatch] = useReducer(reducer, initialState, (base): AppState => ({
    ...base,
    // Upload and landing are the only screens that need no data, so they are
    // the only two enterable straight from the address bar. Everything else
    // starts at landing and gets corrected below, once the session restore has
    // said what it can actually supply.
    screen: screenForPath(window.location.pathname) === "upload" ? "upload" : "landing",
    access: { required: false, hasToken: getAccessToken() !== null, rejected: false },
  }));
  // Bumped when a token is entered, so the session restore below runs again
  // with it instead of having failed once, unauthenticated, at boot.
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [activityPhase, setActivityPhase] = useState<"working" | "handoff">("working");

  // A typed or bookmarked URL is an intent, not a destination. It is held here
  // until we know whether the restore can supply what that screen needs, and
  // it also parks the URL-sync effect below so the address being resolved is
  // not overwritten while we are still resolving it.
  const [pendingPath, setPendingPath] = useState<string | null>(() => window.location.pathname);
  const [restoring, setRestoring] = useState(
    () => window.sessionStorage.getItem(RECOVERY_KEY) !== null,
  );
  const bootedRef = useRef(false);

  async function completeRequestWindow(startedAt: number) {
    const remaining = MIN_REQUEST_WINDOW_MS - (Date.now() - startedAt);
    if (remaining > 0) await pause(remaining);
    setActivityPhase("handoff");
    await pause(HANDOFF_WINDOW_MS);
  }

  // Each screen is a fresh document, not a continuation of wherever the
  // user scrolled to on the last one - a long Profile screen should not
  // leave Strategy or Pipeline opening halfway down.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [state.screen]);

  // Whether this deployment offers MVP-1.5 execution. A failed read leaves it
  // off, which is the MVP-1 screen exactly - the safe default.
  useEffect(() => {
    let cancelled = false;
    void getHealth()
      .then((health) => {
        if (!cancelled) dispatch({ type: "HEALTH_LOADED", health });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // The API exposes the server-side profile and pipeline, so a refresh no
  // longer discards a still-valid upload or a generation that cost quota.
  useEffect(() => {
    const datasetId = window.sessionStorage.getItem(RECOVERY_KEY);
    if (!datasetId) return;
    let cancelled = false;

    void getDataset(datasetId)
      .then(async (dataset) => {
        if (cancelled) return;
        dispatch({ type: "SESSION_RESTORED", dataset });
        if (dataset.pipeline) {
          // Supplementary, same as after a fresh generation.
          try {
            const usage = await getDatasetUsage(datasetId);
            if (!cancelled) dispatch({ type: "USAGE_LOADED", usage });
          } catch {
            // The pipeline is already restored; usage is not worth an error.
          }
        }
      })
      .catch((error) => {
        const detail = toDetail(error);
        if (detail.code === "UNAUTHORIZED") {
          // Not expired - just not authenticated yet. Keep the id, ask for a
          // token, and retry once one is entered.
          if (!cancelled) dispatch({ type: "REQUEST_FAILED", error: detail });
          return;
        }
        // An expired dataset should not keep attempting recovery on every load.
        window.sessionStorage.removeItem(RECOVERY_KEY);
      })
      .finally(() => {
        // Settled either way. The routing effect stops waiting on a deep link
        // it can no longer satisfy, rather than sitting on the address bar.
        if (!cancelled) setRestoring(false);
      });

    return () => {
      cancelled = true;
    };
  }, [restoreAttempt]);

  // Chart data for the Profile screen. Supplementary: a failure leaves the
  // table without its distribution column, never blocks the flow.
  const profileKey = state.profile
    ? `${state.profile.dataset_id}:${state.profile.target_column}:${state.profile.problem_type}`
    : null;
  useEffect(() => {
    if (!profileKey || !state.dataset) return;
    let cancelled = false;
    void getDistributions(state.dataset.dataset_id)
      .then((distributions) => {
        if (!cancelled) dispatch({ type: "DISTRIBUTIONS_LOADED", distributions });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [profileKey]);

  function handleAccessToken(token: string) {
    setAccessToken(token);
    dispatch({ type: "ACCESS_TOKEN_SET" });
    if (window.sessionStorage.getItem(RECOVERY_KEY)) {
      setRestoring(true);
      setRestoreAttempt((attempt) => attempt + 1);
    }
  }

  const needsToken = state.access.required && !state.access.hasToken;

  async function handleUpload(file: File) {
    const startedAt = Date.now();
    setActivityPhase("working");
    dispatch({ type: "REQUEST_STARTED", operation: "upload" });
    try {
      const dataset = await uploadDataset(file);
      window.sessionStorage.setItem(RECOVERY_KEY, dataset.dataset_id);
      await completeRequestWindow(startedAt);
      dispatch({ type: "UPLOAD_SUCCEEDED", dataset });
    } catch (error) {
      dispatch({ type: "REQUEST_FAILED", error: toDetail(error) });
    }
  }

  async function handleProfile(problemTypeOverride?: ProblemType) {
    if (!state.dataset || !state.targetColumn) return;
    const startedAt = Date.now();
    setActivityPhase("working");
    dispatch({ type: "REQUEST_STARTED", operation: "profile", profileOverride: problemTypeOverride });
    try {
      const response = await profileDataset(
        state.dataset.dataset_id,
        state.targetColumn,
        problemTypeOverride,
      );
      await completeRequestWindow(startedAt);
      dispatch({
        type: "PROFILE_SUCCEEDED",
        profile: response.profile,
        taskWasOverridden: problemTypeOverride !== undefined,
      });
    } catch (error) {
      dispatch({ type: "REQUEST_FAILED", error: toDetail(error) });
    }
  }

  async function handleGenerate() {
    if (!state.dataset) return;
    const startedAt = Date.now();
    setActivityPhase("working");
    dispatch({ type: "REQUEST_STARTED", operation: "generate" });
    try {
      const response = await generatePipeline(state.dataset.dataset_id, state.excludedColumns);
      let usage = null;
      try {
        usage = await getDatasetUsage(state.dataset.dataset_id);
      } catch {
        // Generation succeeded. Usage is supplementary, so a failed read must
        // not hide the strategy or make the user repeat a model request.
      }
      await completeRequestWindow(startedAt);
      dispatch({
        type: "GENERATE_SUCCEEDED",
        result: response.result,
        validation: response.validation,
        usage,
      });
    } catch (error) {
      // The profile survives this. The user retries from where they were.
      dispatch({ type: "REQUEST_FAILED", error: toDetail(error) });
    }
  }

  async function handleExecute() {
    if (!state.dataset) return;
    const startedAt = Date.now();
    setActivityPhase("working");
    dispatch({ type: "REQUEST_STARTED", operation: "execute" });
    try {
      const response = await executePipeline(state.dataset.dataset_id);
      await completeRequestWindow(startedAt);
      dispatch({ type: "EXECUTE_SUCCEEDED", run: response.run });
    } catch (error) {
      // A refused run leaves the pipeline and the previous run on screen.
      dispatch({ type: "REQUEST_FAILED", error: toDetail(error) });
    }
  }

  const retryHandler =
    state.operation === "generate"
      ? handleGenerate
      : state.operation === "profile"
        ? () => handleProfile(state.profileOverride ?? undefined)
        : undefined;

  const availableScreens = [
    "upload",
    ...(state.dataset ? ["target"] : []),
    ...(state.profile ? ["profile"] : []),
    ...(state.result ? ["strategy"] : []),
    ...(state.validation ? ["code"] : []),
  ] as Exclude<Screen, "landing">[];

  // --- Routing ---------------------------------------------------------------
  //
  // The address bar follows the app; it never drives it on its own. A URL may
  // only select a screen the current state can actually render, which is the
  // same rule the sidebar already enforces - so /strategy in a fresh tab lands
  // on the furthest screen that does exist instead of a blank panel.

  function canEnter(screen: Screen): boolean {
    return (
      screen === "landing" ||
      availableScreens.includes(screen as Exclude<Screen, "landing">)
    );
  }

  // The array identity changes every render; its contents do not. Effects
  // depend on this string so they re-run when reachability really changes.
  const reachable = availableScreens.join(",");

  useEffect(() => {
    document.title = titleForScreen(state.screen);
  }, [state.screen]);

  useEffect(() => {
    if (pendingPath === null) return;
    const requested = screenForPath(pendingPath);

    if (requested && canEnter(requested)) {
      setPendingPath(null);
      if (requested !== state.screen) dispatch({ type: "NAVIGATED", screen: requested });
      return;
    }
    // Unknown path, or a screen whose data this session does not have. Keep
    // waiting only while a restore might still produce it; otherwise give up
    // and let the sync effect rewrite the address to where we really are.
    if (!restoring) setPendingPath(null);
  }, [pendingPath, reachable, restoring, state.screen]);

  useEffect(() => {
    if (pendingPath !== null) return;
    const path = pathForScreen(state.screen);
    if (window.location.pathname !== path) {
      // The first write after boot corrects an address this session cannot
      // honour, so it replaces rather than pushes. Pressing back should leave
      // the app, not return to a URL that never worked in the first place.
      if (bootedRef.current) window.history.pushState(null, "", path);
      else window.history.replaceState(null, "", path);
    }
    bootedRef.current = true;
  }, [state.screen, pendingPath]);

  useEffect(() => {
    function handlePopState() {
      const screen = screenForPath(window.location.pathname);
      if (screen && canEnter(screen)) {
        dispatch({ type: "NAVIGATED", screen });
        return;
      }
      // Back or forward landed somewhere unrenderable. Correct the address to
      // the screen still on display instead of blanking it.
      window.history.replaceState(null, "", pathForScreen(state.screen));
    }

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [reachable, state.screen]);

  function handleRestart() {
    window.sessionStorage.removeItem(RECOVERY_KEY);
    dispatch({ type: "RESET" });
  }

  return (
    <div className="min-h-screen bg-bg">
      {state.screen !== "landing" ? (
        <WorkflowShell
          activeScreen={state.screen}
          busy={state.busy}
          filename={state.dataset?.filename}
          availableScreens={availableScreens}
          onNavigate={(screen) => dispatch({ type: "NAVIGATED", screen })}
          onHome={() => dispatch({ type: "NAVIGATED", screen: "landing" })}
        >
          {needsToken ? (
            <AccessTokenPanel rejected={state.access.rejected} onSubmit={handleAccessToken} />
          ) : null}

          {state.error ? (
            <ErrorPanel
              detail={state.error}
              onRetry={state.error.retryable ? retryHandler : undefined}
              onDismiss={() => dispatch({ type: "DISMISSED_ERROR" })}
            />
          ) : null}

          <div key={state.screen} className="screen-enter">
            {state.screen === "upload" ? (
              <UploadScreen onFile={handleUpload} busy={state.busy} hasError={Boolean(state.error)} />
            ) : null}

            {state.screen === "target" && state.dataset ? (
              <TargetScreen
                dataset={state.dataset}
                selected={state.targetColumn}
                onSelect={(column) => dispatch({ type: "TARGET_SELECTED", targetColumn: column })}
                // Wrapped, not passed directly. Button forwards its click event
                // as the first argument, which would land in handleProfile's
                // problemTypeOverride parameter. TypeScript allows the direct
                // form because a zero-arg function is assignable to a handler
                // that receives an event, so this only fails at runtime.
                onConfirm={() => handleProfile()}
                busy={state.busy}
              />
            ) : null}

            {state.screen === "profile" && state.profile ? (
              <ProfileScreen
                profile={state.profile}
                onGenerate={handleGenerate}
                excludedColumns={state.excludedColumns}
                onExclusionsChange={(columns) => dispatch({ type: "EXCLUSIONS_CHANGED", columns })}
                onOverrideTask={handleProfile}
                taskWasOverridden={state.taskWasOverridden}
                onBack={() => dispatch({ type: "NAVIGATED", screen: "target" })}
                busy={state.busy}
                distributions={state.distributions}
              />
            ) : null}

            {state.screen === "strategy" && state.result ? (
              <StrategyScreen
                result={state.result}
                onViewCode={() => dispatch({ type: "NAVIGATED", screen: "code" })}
                onBack={() => dispatch({ type: "NAVIGATED", screen: "profile" })}
              />
            ) : null}

            {state.screen === "code" && state.result && state.validation ? (
              <CodeScreen
                result={state.result}
                validation={state.validation}
                usage={state.usage}
                run={state.run}
                execution={state.execution}
                totalRows={state.dataset?.n_rows ?? null}
                executing={state.busy && state.operation === "execute"}
                onExecute={handleExecute}
                onBack={() => dispatch({ type: "NAVIGATED", screen: "strategy" })}
                onRestart={handleRestart}
              />
            ) : null}
          </div>
          <ActivityDialog operation={state.operation} open={state.busy} phase={activityPhase} />
        </WorkflowShell>
      ) : null}

      {state.screen === "landing" ? (
        <LandingScreen onStart={() => dispatch({ type: "NAVIGATED", screen: "upload" })} />
      ) : null}
    </div>
  );
}
