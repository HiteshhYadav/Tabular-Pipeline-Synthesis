"""Distribution chart data, and the rule that it never reaches the prompt."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import distributions, heuristics, profiler, prompts
from app.models import DistributionKind, ProfileCard

FIXTURES = Path(__file__).parent / "fixtures" / "profiler"


def _load(name: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / name, engine="c")


def _charts(frame: pd.DataFrame, target: str):
    card = profiler.profile(frame, "ds", "f.csv", target)
    return card, {c.name: c for c in distributions.distributions(frame, card).columns}


def test_continuous_columns_get_a_histogram_that_covers_every_value():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {"amount": rng.lognormal(3, 1, 500), "target": rng.choice(["a", "b"], 500)}
    )
    frame.loc[:9, "amount"] = np.nan
    _, charts = _charts(frame, "target")
    amount = charts["amount"]
    assert amount.kind is DistributionKind.HISTOGRAM
    assert len(amount.bins) == heuristics.DISTRIBUTION_HISTOGRAM_BINS
    assert sum(b.count for b in amount.bins) == 490
    assert amount.missing_count == 10
    pairs = zip(amount.bins[:-1], amount.bins[1:], strict=True)
    assert all(a.upper == pytest.approx(b.lower) for a, b in pairs), "bins must be contiguous"


def test_a_zero_width_range_is_one_bin_not_a_crash():
    """np.histogram on a single repeated value would invent a 1-wide range."""
    bins = distributions._histogram(pd.Series([2.5] * 40))
    assert [(b.lower, b.upper, b.count) for b in bins] == [(2.5, 2.5, 40)]


def test_a_constant_column_is_one_level():
    frame = pd.DataFrame({"flat": [2.5] * 40, "target": ["a", "b"] * 20})
    _, charts = _charts(frame, "target")
    assert [(lv.value, lv.count) for lv in charts["flat"].levels] == [("2.5", 40)]


def test_a_continuous_column_with_all_unique_values_is_still_charted():
    """Every price unique flags ID_LIKE, but a histogram is still the point."""
    rng = np.random.default_rng(2)
    frame = pd.DataFrame({"price": rng.uniform(1, 999, 300), "target": ["a", "b"] * 150})
    _, charts = _charts(frame, "target")
    assert charts["price"].kind is DistributionKind.HISTOGRAM


def test_categorical_levels_fold_the_rest_into_other():
    levels = [f"L{i:02d}" for i in range(30)]
    frame = pd.DataFrame(
        {"code": [levels[i % 30] for i in range(600)], "target": ["y", "n"] * 300}
    )
    _, charts = _charts(frame, "target")
    code = charts["code"]
    assert code.kind is DistributionKind.LEVELS
    assert len(code.levels) == heuristics.DISTRIBUTION_MAX_LEVELS
    assert sum(level.count for level in code.levels) + code.other_count == 600


def test_discrete_numeric_levels_read_in_value_order():
    frame = pd.DataFrame({"rating": [5, 1, 3, 2, 4, 5, 5, 1] * 10, "target": ["a", "b"] * 40})
    _, charts = _charts(frame, "rating")
    rating = charts["rating"]
    assert [level.value for level in rating.levels] == ["1", "2", "3", "4", "5"]


def test_float_levels_are_shown_as_the_user_wrote_them():
    """A discrete column with gaps is read as float; 3.0 must display as 3."""
    frame = pd.DataFrame({"stars": [1, 2, 3, None] * 10, "target": ["a", "b"] * 20})
    _, charts = _charts(frame, "target")
    assert [level.value for level in charts["stars"].levels] == ["1", "2", "3"]
    assert charts["stars"].missing_count == 10


def test_booleans_keep_the_files_spelling():
    frame = pd.DataFrame({"churned": ["yes", "no", "no", "no"] * 10, "x": range(40)})
    _, charts = _charts(frame, "churned")
    assert {level.value for level in charts["churned"].levels} == {"yes", "no"}


def test_currency_strings_are_charted_as_numbers():
    _, charts = _charts(_load("numeric_as_string.csv"), "target")
    price = charts["price"]
    assert price.kind in (DistributionKind.HISTOGRAM, DistributionKind.LEVELS)
    if price.kind is DistributionKind.HISTOGRAM:
        assert price.bins[0].lower > 0


@pytest.mark.parametrize(
    ("fixture", "column"),
    [
        ("all_null_column.csv", "empty_col"),
        ("id_column.csv", "row_id"),
        ("datetime_three_formats.csv", "date_iso"),
    ],
)
def test_columns_with_no_meaningful_chart_say_why(fixture, column):
    _, charts = _charts(_load(fixture), "target")
    chart = charts[column]
    assert chart.kind is DistributionKind.NONE
    assert chart.reason
    assert chart.bins == [] and chart.levels == []


def test_distribution_data_never_reaches_the_prompt():
    """The separation this module exists for. ProfileCard gains no field from
    it, and the serialised prompt carries no per-level counts."""
    assert not {"bins", "levels", "distribution", "distributions"} & set(ProfileCard.model_fields)
    frame = pd.DataFrame({"code": ["aa", "bb", "cc"] * 50, "target": ["y", "n", "n"] * 50})
    card = profiler.profile(frame, "ds", "f.csv", "target")
    message = prompts.build_user_message(card)
    assert "other_count" not in message
    assert "histogram" not in message.lower()


# --- Route -------------------------------------------------------------------


CSV = (
    b"id,amount,plan,churn\n"
    + b"".join(
        f"{i},{i * 1.5},{'gold' if i % 3 else 'basic'},{'yes' if i % 4 == 0 else 'no'}\n".encode()
        for i in range(1, 81)
    )
)


def test_route_returns_one_chart_per_column(client):
    dataset_id = client.post(
        "/api/datasets", files={"file": ("c.csv", io.BytesIO(CSV), "text/csv")}
    ).json()["dataset_id"]
    client.post(f"/api/datasets/{dataset_id}/profile", json={"target_column": "churn"})
    response = client.get(f"/api/datasets/{dataset_id}/distributions")
    assert response.status_code == 200
    body = response.json()
    assert body["n_rows"] == 80
    assert [c["name"] for c in body["columns"]] == ["id", "amount", "plan", "churn"]


def test_route_requires_a_profile(client):
    dataset_id = client.post(
        "/api/datasets", files={"file": ("c.csv", io.BytesIO(CSV), "text/csv")}
    ).json()["dataset_id"]
    response = client.get(f"/api/datasets/{dataset_id}/distributions")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "DATASET_EXPIRED"
