"""Access tokens, rate limits, and the hosted-mode boot guard."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.security import RateLimiter

BACKEND = Path(__file__).resolve().parents[1]
CSV = b"a,b\n1,2\n3,4\n"


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(settings, "api_tokens", "alpha-token, beta-token")
    with TestClient(create_app()) as client:
        yield client


def _upload(client, **headers):
    return client.post(
        "/api/datasets",
        files={"file": ("d.csv", io.BytesIO(CSV), "text/csv")},
        headers=headers,
    )


# --- Tokens ------------------------------------------------------------------


def test_without_tokens_configured_the_api_is_open(client):
    assert _upload(client).status_code == 201
    assert client.get("/api/health").json()["auth_required"] is False


def test_health_stays_open_and_says_a_token_is_needed(secured):
    response = secured.get("/api/health")
    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_a_missing_token_is_refused_with_the_envelope(secured):
    response = _upload(secured)
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "UNAUTHORIZED"
    assert body["retryable"] is False


def test_a_wrong_token_is_refused(secured):
    response = _upload(secured, Authorization="Bearer not-a-real-token")
    assert response.status_code == 401
    assert "not valid" in response.json()["error"]["message"]


@pytest.mark.parametrize("token", ["alpha-token", "beta-token"])
def test_every_configured_token_works(secured, token):
    assert _upload(secured, Authorization=f"Bearer {token}").status_code == 201


def test_every_dataset_route_is_protected(secured):
    """Not only upload. A read route that leaked a profile would undo the
    point of requiring a token for the write routes."""
    dataset_id = "00000000-0000-4000-8000-000000000000"
    for method, path in [
        ("get", f"/api/datasets/{dataset_id}"),
        ("get", f"/api/datasets/{dataset_id}/usage"),
        ("get", f"/api/datasets/{dataset_id}/distributions"),
        ("post", f"/api/datasets/{dataset_id}/profile"),
        ("post", f"/api/datasets/{dataset_id}/generate"),
        ("post", f"/api/datasets/{dataset_id}/execute"),
    ]:
        response = getattr(secured, method)(path)
        assert response.status_code == 401, path


def test_a_token_is_never_echoed_back(secured):
    response = _upload(secured, Authorization="Bearer leaked-secret-value")
    assert "leaked-secret-value" not in response.text


# --- Rate limits -------------------------------------------------------------


def test_uploads_beyond_the_hourly_budget_are_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_uploads_per_hour", 2)
    assert _upload(client).status_code == 201
    assert _upload(client).status_code == 201
    response = _upload(client)
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["retryable"] is True
    assert int(error["details"]["retry_after_s"]) > 0


def test_generation_has_its_own_budget_before_any_model_call(client, stub_provider, monkeypatch):
    """The point of this budget is the provider quota, so a refused request
    must not reach the provider at all."""
    monkeypatch.setattr(settings, "rate_limit_generations_per_hour", 1)
    dataset_id = "00000000-0000-4000-8000-000000000000"
    client.post(f"/api/datasets/{dataset_id}/generate", json={})
    response = client.post(f"/api/datasets/{dataset_id}/generate", json={})
    assert response.status_code == 429
    assert response.json()["error"]["details"]["bucket"] == "generate"
    assert stub_provider.calls == 0


def test_budgets_are_per_token(monkeypatch):
    monkeypatch.setattr(settings, "api_tokens", "alpha-token,beta-token")
    monkeypatch.setattr(settings, "rate_limit_uploads_per_hour", 1)
    with TestClient(create_app()) as client:
        assert _upload(client, Authorization="Bearer alpha-token").status_code == 201
        assert _upload(client, Authorization="Bearer alpha-token").status_code == 429
        assert _upload(client, Authorization="Bearer beta-token").status_code == 201


def test_the_window_slides():
    now = [1000.0]
    limiter = RateLimiter(clock=lambda: now[0])
    original = settings.rate_limit_uploads_per_hour
    settings.rate_limit_uploads_per_hour = 2
    try:
        limiter.hit("c", "upload")
        limiter.hit("c", "upload")
        with pytest.raises(AppError) as exc_info:
            limiter.hit("c", "upload")
        assert exc_info.value.code is ErrorCode.RATE_LIMITED
        now[0] += 3601
        limiter.hit("c", "upload")
    finally:
        settings.rate_limit_uploads_per_hour = original


# --- Boot guard --------------------------------------------------------------


def _boot(**env) -> subprocess.CompletedProcess:
    scrubbed = {"API_TOKENS", "DEPLOYMENT_ENV", "ENABLE_LOCAL_EXECUTION", "EXECUTION_BACKEND"}
    clean = {k: v for k, v in os.environ.items() if k not in scrubbed}
    clean.update(env)
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=BACKEND,
        env=clean,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hosted_without_tokens_refuses_to_boot():
    result = _boot(DEPLOYMENT_ENV="hosted", API_TOKENS="", ENABLE_LOCAL_EXECUTION="false")
    assert result.returncode != 0
    assert "API_TOKENS" in result.stderr


def test_hosted_with_tokens_boots():
    result = _boot(DEPLOYMENT_ENV="hosted", API_TOKENS="t1", ENABLE_LOCAL_EXECUTION="false")
    assert result.returncode == 0, result.stderr


def test_hosted_execution_without_a_container_refuses_to_boot():
    result = _boot(
        DEPLOYMENT_ENV="hosted",
        API_TOKENS="t1",
        ENABLE_LOCAL_EXECUTION="true",
        EXECUTION_BACKEND="subprocess",
    )
    assert result.returncode != 0
    assert "EXECUTION_BACKEND=docker" in result.stderr


def test_hosted_execution_in_a_container_boots():
    result = _boot(
        DEPLOYMENT_ENV="hosted",
        API_TOKENS="t1",
        ENABLE_LOCAL_EXECUTION="true",
        EXECUTION_BACKEND="docker",
    )
    assert result.returncode == 0, result.stderr
