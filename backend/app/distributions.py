"""Per-column distribution data for the Profile screen's charts.

Not prompt surface, and the separation is the point of this module. A
histogram or a per-level count is close to raw data. Showing it to the person
who uploaded the file is fine; sending it to the model is what the core rule
forbids. So none of this lives on ProfileCard - which is serialised into every
prompt - and nothing in llm.py or prompts.py imports this module.

The column types and flags come from the stored ProfileCard rather than from
re-running the dtype ladder, so a chart can never disagree with the type the
profile table shows beside it.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app import heuristics
from app.dtypes import coerce_numeric
from app.models import (
    ColumnDistribution,
    ColumnFlag,
    ColumnProfile,
    DistributionKind,
    DistributionsResponse,
    HistogramBin,
    InferredType,
    LevelCount,
    ProfileCard,
)

_NO_CHART_REASON = {
    InferredType.TEXT: "Free text has no meaningful distribution to chart.",
    InferredType.DATETIME: "Datetime columns are not charted.",
    InferredType.UNKNOWN: "No usable values to chart.",
}


def _format_level(value: object) -> str:
    """A level as the user would recognise it: 3.0 read from a float column
    with gaps is shown as 3, not 3.0."""
    if isinstance(value, float | np.floating) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _histogram(values: pd.Series) -> list[HistogramBin]:
    finite = values[np.isfinite(values.to_numpy(dtype=float))].to_numpy(dtype=float)
    if finite.size == 0:
        return []
    low, high = float(finite.min()), float(finite.max())
    if math.isclose(low, high):
        return [HistogramBin(lower=low, upper=high, count=int(finite.size))]
    counts, edges = np.histogram(finite, bins=heuristics.DISTRIBUTION_HISTOGRAM_BINS)
    return [
        HistogramBin(lower=float(edges[i]), upper=float(edges[i + 1]), count=int(counts[i]))
        for i in range(len(counts))
    ]


def _levels(values: pd.Series, ordinal: bool) -> tuple[list[LevelCount], int]:
    counts = values.value_counts(dropna=True)
    if ordinal:
        # A rating or a small count reads in value order: 1, 2, 3, 4, 5. The
        # most common levels are kept first, then shown in order.
        kept = counts.head(heuristics.DISTRIBUTION_MAX_LEVELS).sort_index()
    else:
        kept = counts.head(heuristics.DISTRIBUTION_MAX_LEVELS)
    levels = [LevelCount(value=_format_level(v), count=int(c)) for v, c in kept.items()]
    other = int(counts.sum() - kept.sum())
    return levels, other


def column_distribution(series: pd.Series, column: ColumnProfile) -> ColumnDistribution:
    name = column.name
    missing = int(series.isna().sum())
    kind_none = DistributionKind.NONE

    if ColumnFlag.ALL_MISSING in column.flags:
        return ColumnDistribution(
            name=name, kind=kind_none, missing_count=missing, reason="Every value is missing."
        )
    # ID_LIKE only rules out a chart for columns charted level by level. A
    # continuous column where every value is unique - prices, amounts - is
    # flagged ID_LIKE too, and its histogram is exactly what the user needs.
    if (
        ColumnFlag.ID_LIKE in column.flags
        and column.inferred_type is not InferredType.NUMERIC_CONTINUOUS
    ):
        return ColumnDistribution(
            name=name,
            kind=kind_none,
            missing_count=missing,
            reason="Nearly every value is unique, so a chart would be one bar per row.",
        )
    if column.inferred_type in _NO_CHART_REASON:
        return ColumnDistribution(
            name=name,
            kind=kind_none,
            missing_count=missing,
            reason=_NO_CHART_REASON[column.inferred_type],
        )

    numeric = column.inferred_type in {
        InferredType.NUMERIC_CONTINUOUS,
        InferredType.NUMERIC_DISCRETE,
    }
    values = series
    if numeric and ColumnFlag.NUMERIC_AS_STRING in column.flags:
        values = coerce_numeric(series)
        # Values that did not parse count as missing for the chart, exactly
        # as the profiler's statistics treat them.
        missing = int(values.isna().sum())
    values = values.dropna()

    if column.inferred_type is InferredType.NUMERIC_CONTINUOUS:
        return ColumnDistribution(
            name=name,
            kind=DistributionKind.HISTOGRAM,
            bins=_histogram(pd.to_numeric(values, errors="coerce").dropna()),
            missing_count=missing,
        )

    levels, other = _levels(values, ordinal=column.inferred_type is InferredType.NUMERIC_DISCRETE)
    return ColumnDistribution(
        name=name,
        kind=DistributionKind.LEVELS,
        levels=levels,
        other_count=other,
        missing_count=missing,
    )


def distributions(frame: pd.DataFrame, profile: ProfileCard) -> DistributionsResponse:
    """Chart data for every profiled column, in profile order."""
    columns = [
        column_distribution(frame[column.name], column)
        for column in profile.columns
        if column.name in frame.columns
    ]
    return DistributionsResponse(
        dataset_id=profile.dataset_id, n_rows=int(frame.shape[0]), columns=columns
    )
