/**
 * MVP-1.5: running the pipeline on a sample, and what came back.
 *
 * Rendered only when the backend reports execution_enabled. With it off the
 * pipeline screen is exactly what it was in MVP-1 - the UnexecutedNotice and
 * nothing else - which is the stage 6 definition of done.
 *
 * The output is shown verbatim and never parsed. The pipeline prints its own
 * primary metric; pulling that number out into a big tile would present a
 * figure measured on a few hundred rows with the visual authority of a
 * headline result. Leaving it inside the log, under a label that states the
 * sample size, keeps it read in context.
 */

import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { StatusBadge, type BadgeTone } from "../shared/StatusBadge";
import type { RunResult } from "../../types";

const number = new Intl.NumberFormat("en-US");

function duration(ms: number) {
  return ms < 1_000 ? `${ms} ms` : `${(ms / 1_000).toFixed(1)} s`;
}

function outcome(run: RunResult): { tone: BadgeTone; label: string } {
  if (run.timed_out) return { tone: "error", label: "Timed out, process killed" };
  if (run.succeeded) return { tone: "success", label: "Exited cleanly (code 0)" };
  return { tone: "error", label: `Failed (exit code ${run.exit_code})` };
}

function OutputPane({
  title,
  text,
  truncated,
  emptyLabel,
}: {
  title: string;
  text: string;
  truncated: boolean;
  emptyLabel: string;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-code-border">
      <div className="flex items-center justify-between bg-code-chrome px-4 py-2">
        <span className="font-mono text-data-sm text-code-gutter">{title}</span>
        {truncated ? (
          <span className="font-mono text-data-sm text-code-gutter">truncated</span>
        ) : null}
      </div>
      <pre className="max-h-80 overflow-auto bg-code-bg px-4 py-3 font-mono text-code whitespace-pre-wrap break-words text-code-text">
        {text.length > 0 ? text : <span className="text-code-gutter">{emptyLabel}</span>}
      </pre>
    </div>
  );
}

/** Replaces UnexecutedNotice once a run exists, because that notice would
 * then be false. Same weight and position, so the honest label stays the
 * first thing above the code either way. */
export function ExecutedNotice({ run, totalRows }: { run: RunResult; totalRows: number | null }) {
  return (
    <div
      role="status"
      className="flex w-full items-start gap-3 rounded-lg border border-info-subtle border-l-2 border-l-info bg-info-subtle px-5 py-4"
    >
      <div>
        <p className="text-body font-semibold text-text-primary">
          Executed on a {number.format(run.sample_rows)}-row sample.
        </p>
        <p className="mt-1 text-secondary-size text-text-secondary">
          {totalRows !== null && totalRows > run.sample_rows
            ? `Your file has ${number.format(totalRows)} rows. `
            : ""}
          Any figure in the output below was measured on this sample only, on this machine. It
          shows the code runs, not how well it will perform on your full data.
        </p>
      </div>
    </div>
  );
}

export function ExecutionPanel({
  run,
  sampleRows,
  busy,
  onExecute,
}: {
  run: RunResult | null;
  sampleRows: number | null;
  busy: boolean;
  onExecute: () => void;
}) {
  const rows = sampleRows !== null ? `${number.format(sampleRows)} rows` : "a small sample";
  const status = run ? outcome(run) : null;

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <p className="label-caps text-text-tertiary">Local execution</p>
          <h2 className="mt-1 text-heading font-heading text-text-primary">
            {run ? "Run output" : "Run this pipeline on a sample"}
          </h2>
          <p className="mt-1 text-secondary-size text-text-secondary">
            Runs exactly the code below in a separate process on this machine, against {rows}{" "}
            of your file with every class represented, under a hard time limit. Output is shown
            as printed.
          </p>
        </div>
        <Button
          variant={run ? "secondary" : "primary"}
          onClick={() => onExecute()}
          loading={busy}
        >
          {run ? "Run again" : "Run on sample"}
        </Button>
      </div>

      {run && status ? (
        <div className="mt-5 space-y-4 border-t border-separator pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <span className="font-mono text-data-sm text-text-tertiary">
              {duration(run.duration_ms)} · {number.format(run.sample_rows)} rows
            </span>
          </div>
          <OutputPane
            title="stdout"
            text={run.stdout}
            truncated={run.stdout_truncated}
            emptyLabel="(no output)"
          />
          {run.stderr.length > 0 || !run.succeeded ? (
            <OutputPane
              title="stderr"
              text={run.stderr}
              truncated={run.stderr_truncated}
              emptyLabel="(empty)"
            />
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
