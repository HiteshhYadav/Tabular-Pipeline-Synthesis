/**
 * Per-column distribution: a compact bar chart for the column table, and an
 * expanded view with hover tooltips and an exact values table.
 *
 * One series per chart, so one hue - the accent - and no legend: the column
 * name labels it. Bars are separated by a 2px surface gap and grow from a
 * shared baseline. Counts are always available as text (tooltip, aria label,
 * and the table), so nothing is encoded by colour or bar height alone.
 *
 * The data comes from GET /distributions, which exists only for this screen.
 * It is never part of ProfileCard and never reaches the model.
 */

import { useState } from "react";
import type { ColumnDistribution } from "../../types";

const number = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 });

interface Bar {
  label: string;
  count: number;
}

function bars(distribution: ColumnDistribution): Bar[] {
  if (distribution.kind === "histogram") {
    return distribution.bins.map((bin) => ({
      label:
        bin.lower === bin.upper
          ? compact.format(bin.lower)
          : `${compact.format(bin.lower)} to ${compact.format(bin.upper)}`,
      count: bin.count,
    }));
  }
  const levels = distribution.levels.map((level) => ({ label: level.value, count: level.count }));
  if (distribution.other_count > 0) {
    levels.push({ label: "Other levels", count: distribution.other_count });
  }
  return levels;
}

function summary(distribution: ColumnDistribution, data: Bar[]): string {
  if (data.length === 0) return `${distribution.name}: no chart.`;
  const top = data.reduce((best, bar) => (bar.count > best.count ? bar : best), data[0]);
  const unit = distribution.kind === "histogram" ? "bins" : "levels";
  return `${distribution.name}: ${data.length} ${unit}, most common ${top.label} with ${number.format(top.count)} rows.`;
}

function Bars({
  data,
  width,
  height,
  gap,
  onHover,
  active,
}: {
  data: Bar[];
  width: number;
  height: number;
  gap: number;
  onHover?: (index: number | null) => void;
  active?: number | null;
}) {
  const max = Math.max(1, ...data.map((bar) => bar.count));
  const barWidth = Math.max(1, (width - gap * (data.length - 1)) / data.length);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
      className="block overflow-visible"
      onMouseLeave={() => onHover?.(null)}
    >
      <line x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} className="stroke-border" />
      {data.map((bar, index) => {
        const h = bar.count === 0 ? 0 : Math.max(1.5, (bar.count / max) * (height - 1));
        const x = index * (barWidth + gap);
        return (
          <g key={`${bar.label}-${index}`}>
            <rect
              x={x}
              y={height - 1 - h}
              width={barWidth}
              height={h}
              rx={Math.min(2, barWidth / 2)}
              className={
                active === null || active === undefined || active === index
                  ? "fill-accent"
                  : "fill-accent opacity-40"
              }
            />
            {onHover ? (
              // Hit target taller than the bar, so short bars are hoverable.
              <rect
                x={x - gap / 2}
                y={0}
                width={barWidth + gap}
                height={height}
                fill="transparent"
                onMouseEnter={() => onHover(index)}
              />
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

/** The compact chart for a table cell. */
export function MiniDistribution({ distribution }: { distribution: ColumnDistribution }) {
  if (distribution.kind === "none") {
    return <span className="text-data-sm text-text-tertiary">-</span>;
  }
  const data = bars(distribution);
  return (
    <span role="img" aria-label={summary(distribution, data)} title={summary(distribution, data)}>
      <Bars data={data} width={96} height={24} gap={2} />
    </span>
  );
}

/** The expanded view: larger chart, hover tooltip, and the exact numbers. */
export function DistributionDetail({
  distribution,
  totalRows,
}: {
  distribution: ColumnDistribution;
  totalRows: number;
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  if (distribution.kind === "none") {
    return (
      <p className="text-secondary-size text-text-secondary">
        {distribution.reason ?? "No chart for this column."}
      </p>
    );
  }

  const data = bars(distribution);
  const width = 560;
  const height = 120;
  const shown = hovered !== null ? data[hovered] : null;
  const share = (count: number) =>
    totalRows > 0 ? `${((count / totalRows) * 100).toFixed(1)}%` : "";

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
      <div>
        <div className="relative max-w-full overflow-x-auto">
          <div role="img" aria-label={summary(distribution, data)}>
            <Bars
              data={data}
              width={width}
              height={height}
              gap={2}
              onHover={setHovered}
              active={hovered}
            />
          </div>
          <div
            className="pointer-events-none mt-2 min-h-5 font-mono text-data-sm text-text-secondary"
            aria-live="polite"
          >
            {shown
              ? `${shown.label}: ${number.format(shown.count)} rows (${share(shown.count)})`
              : "Hover a bar for its count."}
          </div>
          {distribution.kind === "histogram" && data.length > 0 ? (
            <div className="flex justify-between font-mono text-data-sm text-text-tertiary" style={{ width }}>
              <span>{compact.format(distribution.bins[0].lower)}</span>
              <span>{compact.format(distribution.bins[distribution.bins.length - 1].upper)}</span>
            </div>
          ) : null}
        </div>
        <p className="mt-2 text-small text-text-tertiary">
          {distribution.missing_count > 0
            ? `${number.format(distribution.missing_count)} missing rows are not charted.`
            : "No missing values."}
        </p>
      </div>

      <details className="text-secondary-size">
        <summary className="cursor-pointer text-text-secondary hover:text-text-primary">
          Show values as a table
        </summary>
        <table className="mt-2 w-full text-left">
          <thead>
            <tr className="label-caps text-text-tertiary">
              <th className="py-1 pr-3 font-bold">
                {distribution.kind === "histogram" ? "Range" : "Value"}
              </th>
              <th className="py-1 text-right font-bold">Rows</th>
            </tr>
          </thead>
          <tbody className="font-mono text-data-sm">
            {data.map((bar, index) => (
              <tr key={`${bar.label}-${index}`} className="border-t border-separator">
                <td className="py-1 pr-3 text-text-primary">{bar.label}</td>
                <td className="py-1 text-right text-text-secondary">{number.format(bar.count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
