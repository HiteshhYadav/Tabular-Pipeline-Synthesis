"""frontend/src/types.ts must mirror backend/app/models.py.

IMPLEMENTATION_PLAN.md lists TypeScript drifting from Pydantic as one of the
ten things that will go wrong. The types are hand-written, so this test is the
tripwire: every interface named below must declare exactly the fields of its
Pydantic model, and every string-union type exactly the members of its enum.
A field added on one side and forgotten on the other fails here, in CI, rather
than as `undefined` in a browser.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel

from app import models

TYPES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types.ts"

INTERFACES = [
    "ColumnProfile",
    "ProfileCard",
    "DroppedColumn",
    "PreprocessingStep",
    "CandidateModel",
    "GenResult",
    "ValidationCheck",
    "ValidationReport",
    "ErrorDetail",
    "ErrorResponse",
    "DatasetUploadResponse",
    "ProfileRequest",
    "ProfileResponse",
    "GenerateResponse",
    "DatasetDetail",
    "GenerationAttempt",
    "UsageResponse",
    "HealthResponse",
    "RunResult",
    "ExecuteResponse",
    "StoredPipeline",
    "HistogramBin",
    "LevelCount",
    "ColumnDistribution",
    "DistributionsResponse",
]

ENUMS = [
    "ProblemType",
    "Metric",
    "InferredType",
    "ColumnFlag",
    "AssociationMethod",
    "ValidationSeverity",
    "JobState",
    "DistributionKind",
]


def _source() -> str:
    text = TYPES_TS.read_text(encoding="utf-8")
    # Comments may mention field names; they must not count as declarations.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _interface_fields(source: str, name: str) -> set[str]:
    match = re.search(
        rf"export interface {name}\b(?:\s+extends\s+(\w+))?\s*\{{(.*?)\n\}}", source, re.DOTALL
    )
    assert match, f"interface {name} not found in types.ts"
    parent, body = match.group(1), match.group(2)
    fields = set(re.findall(r"^\s*(\w+)\??\s*:", body, re.MULTILINE))
    if parent:
        fields |= _interface_fields(source, parent)
    return fields


def _union_members(source: str, name: str) -> set[str]:
    match = re.search(rf"export type {name}\s*=(.*?);", source, re.DOTALL)
    assert match, f"type {name} not found in types.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


@pytest.mark.parametrize("name", INTERFACES)
def test_interface_mirrors_its_model(name):
    model: type[BaseModel] = getattr(models, name)
    ts_fields = _interface_fields(_source(), name)
    py_fields = set(model.model_fields)
    assert ts_fields == py_fields, (
        f"{name}: only in Python {sorted(py_fields - ts_fields)}, "
        f"only in TypeScript {sorted(ts_fields - py_fields)}"
    )


@pytest.mark.parametrize("name", ENUMS)
def test_union_mirrors_its_enum(name):
    enum: type[StrEnum] = getattr(models, name)
    assert _union_members(_source(), name) == {member.value for member in enum}
