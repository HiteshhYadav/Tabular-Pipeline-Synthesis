/** Rendering contracts for the screens and components added since MVP-1. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccessTokenPanel } from "./components/shared/AccessTokenPanel";
import { DistributionDetail, MiniDistribution } from "./components/profile/DistributionChart";
import { CodeScreen } from "./screens/CodeScreen";
import { result, run, validation } from "./test/fixtures";
import type { ColumnDistribution } from "./types";

// shiki highlighting is irrelevant to these contracts and slow in jsdom.
vi.mock("./components/pipeline/CodeBlock", () => ({
  CodeBlock: ({ code }: { code: string }) => <pre data-testid="code">{code}</pre>,
}));

afterEach(cleanup);

function renderCode(overrides: Partial<Parameters<typeof CodeScreen>[0]> = {}) {
  const props: Parameters<typeof CodeScreen>[0] = {
    result,
    validation,
    usage: null,
    run: null,
    execution: { enabled: false, sampleRows: null },
    totalRows: 3000,
    executing: false,
    onExecute: vi.fn(),
    onBack: vi.fn(),
    onRestart: vi.fn(),
    ...overrides,
  };
  render(<CodeScreen {...props} />);
  return props;
}

describe("CodeScreen", () => {
  it("with execution off it is the MVP-1 screen: notice, no run button", () => {
    renderCode();
    expect(screen.getByText(/has not been executed/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /run on sample/i })).toBeNull();
  });

  it("with execution on it offers a run, and the click reaches the handler", () => {
    const props = renderCode({ execution: { enabled: true, sampleRows: 500 } });
    expect(screen.getByText(/against 500 rows/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /run on sample/i }));
    expect(props.onExecute).toHaveBeenCalledOnce();
  });

  it("after a run, the 'not executed' notice is replaced by the sample label", () => {
    renderCode({ execution: { enabled: true, sampleRows: 500 }, run: run() });
    expect(screen.queryByText(/has not been executed/i)).toBeNull();
    expect(screen.getByText(/executed on a 500-row sample/i)).toBeTruthy();
    expect(screen.getByText(/your file has 3,000 rows/i)).toBeTruthy();
    expect(screen.getByText(/pr_auc: 0.2530/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /run again/i })).toBeTruthy();
  });

  it("shows a timeout as a timeout, with stderr", () => {
    renderCode({
      execution: { enabled: true, sampleRows: 500 },
      run: run({ timed_out: true, exit_code: null, succeeded: false, stdout: "", stderr: "" }),
    });
    expect(screen.getByText(/timed out, process killed/i)).toBeTruthy();
    expect(screen.getByText("stderr")).toBeTruthy();
  });

  it("never renders the stdout as a headline number", () => {
    renderCode({ execution: { enabled: true, sampleRows: 500 }, run: run() });
    // The metric appears once, inside the verbatim output pane only.
    expect(screen.getAllByText(/0\.2530/)).toHaveLength(1);
    expect(screen.getByText(/0\.2530/).closest("pre")).not.toBeNull();
  });
});

const histogram: ColumnDistribution = {
  name: "tenure",
  kind: "histogram",
  bins: [
    { lower: 0, upper: 10, count: 5 },
    { lower: 10, upper: 20, count: 15 },
  ],
  levels: [],
  other_count: 0,
  missing_count: 3,
  reason: null,
};

describe("DistributionChart", () => {
  it("labels the compact chart in words, not only bars", () => {
    render(<MiniDistribution distribution={histogram} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toMatch(
      /tenure: 2 bins, most common 10 to 20 with 15 rows/,
    );
  });

  it("says why a column has no chart", () => {
    render(
      <DistributionDetail
        totalRows={100}
        distribution={{ ...histogram, kind: "none", bins: [], reason: "Free text has no chart." }}
      />,
    );
    expect(screen.getByText("Free text has no chart.")).toBeTruthy();
  });

  it("shows folded levels as an explicit row, and missing rows as text", () => {
    render(
      <DistributionDetail
        totalRows={100}
        distribution={{
          ...histogram,
          kind: "levels",
          bins: [],
          levels: [{ value: "basic", count: 60 }],
          other_count: 37,
        }}
      />,
    );
    expect(screen.getByText("Other levels")).toBeTruthy();
    expect(screen.getByText("37")).toBeTruthy();
    expect(screen.getByText(/3 missing rows are not charted/)).toBeTruthy();
  });
});

describe("AccessTokenPanel", () => {
  it("submits the trimmed token and only when one is entered", () => {
    const onSubmit = vi.fn();
    render(<AccessTokenPanel rejected={false} onSubmit={onSubmit} />);
    const button = screen.getByRole("button", { name: /continue/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "  t1  " } });
    fireEvent.click(button);
    expect(onSubmit).toHaveBeenCalledWith("t1");
  });

  it("says a refused token was refused, without echoing it", () => {
    render(<AccessTokenPanel rejected onSubmit={vi.fn()} />);
    expect(screen.getByRole("alert").textContent).toMatch(/refused/i);
  });
});
