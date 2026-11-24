"""MVP-1.5 execution: preflight, sampling, and the real subprocess sandbox.

The sandbox tests start real processes. The runner is the test venv's own
interpreter, which has pandas but not scikit-learn, so every script here uses
pandas only. That is enough to exercise what matters: the timeout kill, the
scrubbed environment, the working directory, and output truncation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from app import execution, heuristics, profiler
from app.config import settings
from app.errors import AppError, ErrorCode
from app.execution import LocalSubprocessSandbox
from app.models import (
    ColumnProfile,
    GenResult,
    InferredType,
    Metric,
    ProblemType,
    ProfileCard,
)

PYTHON = Path(sys.executable)


def _profile(problem_type=ProblemType.BINARY_CLASSIFICATION, target="y") -> ProfileCard:
    columns = [
        ColumnProfile(
            name=name,
            inferred_type=InferredType.NUMERIC_CONTINUOUS,
            pandas_dtype="float64",
            missing_count=0,
            missing_pct=0.0,
            unique_count=10,
            unique_pct=0.1,
        )
        for name in ("x", target)
    ]
    return ProfileCard(
        dataset_id="ds",
        filename="f.csv",
        n_rows=100,
        n_columns=2,
        target_column=target,
        problem_type=problem_type,
        task_confidence=0.95,
        primary_metric=Metric.F1 if problem_type is not ProblemType.REGRESSION else Metric.RMSE,
        columns=columns,
    )


def _result(code: str, profile: ProfileCard) -> GenResult:
    return GenResult(
        problem_type=profile.problem_type,
        target_column=profile.target_column,
        primary_metric=profile.primary_metric,
        dropped_columns=[],
        preprocessing=[],
        candidate_models=[
            {"name": "LogisticRegression", "library": "scikit-learn", "rationale": "a"},
            {"name": "RandomForestClassifier", "library": "scikit-learn", "rationale": "b"},
        ],
        validation_strategy="Five-fold stratified cross-validation.",
        analysis_summary="Test.",
        risks=[],
        code=code,
    )


def _sandbox(timeout_s: int = 30, max_chars: int = 20_000) -> LocalSubprocessSandbox:
    return LocalSubprocessSandbox(python=PYTHON, timeout_s=timeout_s, max_output_chars=max_chars)


SAMPLE = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [0, 1, 0]})


# --- Preflight ---------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "f = open('secrets.txt')\n",
        "import pandas as pd\npd.io.common.os.system('echo hi')\n",
        "x = ().__class__.__bases__\n",
        "import pandas as pd\nx = getattr(pd, '__builtins__')\n",
        "import pandas as pd\ndf = pd.read_csv('https://example.com/data.csv')\n",
        "import pandas as pd\ndf = pd.read_csv('/etc/passwd')\n",
        "import pandas as pd\ndf = pd.read_csv('C:\\\\Windows\\\\win.ini')\n",
        "g = globals()\n",
    ],
)
def test_preflight_flags_escape_hatches(code):
    assert execution.preflight_findings(code)


def test_preflight_accepts_an_ordinary_pipeline():
    code = (
        "import pandas as pd\n"
        "from sklearn.model_selection import train_test_split\n"
        "df = pd.read_csv('data.csv', engine='c')\n"
        "X = df.drop(columns=['y'])\n"
        "imp = getattr(object(), 'feature_importances_', None)\n"
        "if __name__ == '__main__':\n"
        "    print('f1:', 0)\n"
    )
    assert execution.preflight_findings(code) == []


def test_preflight_refuses_a_failed_safety_check_with_validation_failed():
    profile = _profile()
    result = _result("import os\nos.system('rm -rf /')\ny = 'y'\n", profile)
    with pytest.raises(AppError) as exc_info:
        execution.preflight(result, profile, [])
    assert exc_info.value.code is ErrorCode.VALIDATION_FAILED
    assert "Imports are allowlisted" in exc_info.value.message


def test_preflight_does_not_block_on_correctness_checks():
    """A near-miss column name is an ERROR check, but running the code is how
    the user finds out what it does - so it must not block execution."""
    profile = _profile()
    result = _result("import pandas as pd\ndf = pd.read_csv('data.csv')\nz = df['xx']\n", profile)
    execution.preflight(result, profile, [])


# --- Sampling ----------------------------------------------------------------


def test_small_frames_are_used_whole():
    frame = pd.DataFrame({"x": range(10), "y": [0, 1] * 5})
    assert execution.build_sample(frame, _profile(), 500).equals(frame)


def test_sample_is_deterministic_and_keeps_row_order():
    frame = pd.DataFrame({"x": range(5_000), "y": [0, 1] * 2_500})
    first = execution.build_sample(frame, _profile(), 500)
    second = execution.build_sample(frame, _profile(), 500)
    assert len(first) == 500
    assert first.index.equals(second.index)
    assert first.index.is_monotonic_increasing


def test_every_class_survives_a_severely_imbalanced_sample():
    """50:1 imbalance on 5,100 rows. A plain random draw of 500 would hold
    roughly ten minority rows; the guarantee holds it at the constant."""
    frame = pd.DataFrame({"x": range(5_100), "y": [1] * 100 + [0] * 5_000})
    sample = execution.build_sample(frame, _profile(), 500)
    assert len(sample) == 500
    assert (sample["y"] == 1).sum() >= heuristics.EXECUTION_MIN_ROWS_PER_CLASS


def test_regression_samples_are_plain_random():
    frame = pd.DataFrame({"x": range(5_000), "y": [float(i) for i in range(5_000)]})
    sample = execution.build_sample(frame, _profile(ProblemType.REGRESSION), 500)
    assert len(sample) == 500


# --- The sandbox -------------------------------------------------------------


def test_a_successful_run_reads_data_csv_and_reports_stdout():
    code = (
        "import pandas as pd\n"
        "df = pd.read_csv('data.csv', engine='c')\n"
        "print('rows', len(df))\n"
    )
    outcome = _sandbox().run(code, SAMPLE)
    assert outcome.exit_code == 0, outcome.stderr
    assert not outcome.timed_out
    assert "rows 3" in outcome.stdout


def test_a_crash_is_an_outcome_not_an_exception():
    outcome = _sandbox().run("raise ValueError('boom')\n", SAMPLE)
    assert outcome.exit_code not in (0, None)
    assert "boom" in outcome.stderr


def test_a_runaway_script_is_killed_at_the_timeout():
    started = time.monotonic()
    outcome = _sandbox(timeout_s=2).run("while True:\n    pass\n", SAMPLE)
    elapsed = time.monotonic() - started
    assert outcome.timed_out
    assert outcome.exit_code is None
    assert elapsed < 15, "the kill must not wait for the script to finish"


def test_a_spawned_child_does_not_outlive_the_timeout(tmp_path):
    """The process group is killed, not just the parent. The child writes a
    heartbeat file; once the run returns, the heartbeat must stop."""
    heartbeat = tmp_path / "beat.txt"
    child = (
        "import time, pathlib\n"
        f"p = pathlib.Path({str(heartbeat)!r})\n"
        "while True:\n"
        "    p.write_text(str(time.time()))\n"
        "    time.sleep(0.1)\n"
    )
    # multiprocessing is how n_jobs fans out in practice.
    code = (
        "import multiprocessing as mp, time\n"
        "def work():\n"
        f"    exec({child!r})\n"
        "if __name__ == '__main__':\n"
        "    p = mp.Process(target=work)\n"
        "    p.start()\n"
        "    time.sleep(60)\n"
    )
    outcome = _sandbox(timeout_s=4).run(code, SAMPLE)
    assert outcome.timed_out
    if not heartbeat.exists():
        pytest.skip("child never started on this platform; nothing to assert")
    time.sleep(1.0)
    first = heartbeat.read_text()
    time.sleep(1.0)
    assert heartbeat.read_text() == first, "a worker survived the process-group kill"


def test_the_api_environment_never_reaches_the_script(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "secret-should-not-leak")
    code = "import os\nprint(sorted(os.environ))\nprint(os.environ.get('GOOGLE_API_KEY'))\n"
    outcome = _sandbox().run(code, SAMPLE)
    assert outcome.exit_code == 0, outcome.stderr
    assert "secret-should-not-leak" not in outcome.stdout
    assert "GOOGLE_API_KEY" not in outcome.stdout


def test_the_script_runs_in_a_throwaway_directory():
    code = "import os\nprint(sorted(os.listdir('.')))\nprint(os.getcwd())\n"
    outcome = _sandbox().run(code, SAMPLE)
    assert "data.csv" in outcome.stdout
    assert "pipeline.py" in outcome.stdout
    assert str(Path.cwd()) not in outcome.stdout


def test_output_past_the_cap_is_cut_and_flagged():
    outcome = _sandbox(max_chars=100).run("print('x' * 10_000)\n", SAMPLE)
    assert len(outcome.stdout) == 100
    assert outcome.stdout_truncated


def test_non_ascii_output_survives():
    outcome = _sandbox().run("print('caf\\u00e9 \\u2713')\n", SAMPLE)
    assert outcome.exit_code == 0, outcome.stderr
    assert "caf\u00e9 \u2713" in outcome.stdout


# --- Wiring ------------------------------------------------------------------


def test_disabled_execution_refuses_before_looking_for_a_runner(monkeypatch):
    monkeypatch.setattr(settings, "enable_local_execution", False)
    monkeypatch.setattr(settings, "runner_python", "does/not/exist")
    with pytest.raises(AppError) as exc_info:
        execution.default_sandbox()
    assert exc_info.value.code is ErrorCode.EXECUTION_DISABLED


def test_a_missing_runner_is_reported_with_a_remedy(monkeypatch):
    monkeypatch.setattr(settings, "enable_local_execution", True)
    monkeypatch.setattr(settings, "runner_python", "does/not/exist/python")
    with pytest.raises(AppError) as exc_info:
        execution.default_sandbox()
    assert exc_info.value.code is ErrorCode.EXECUTION_UNAVAILABLE
    assert "runner" in exc_info.value.message.lower()


def test_a_configured_runner_is_found(monkeypatch):
    monkeypatch.setattr(settings, "enable_local_execution", True)
    monkeypatch.setattr(settings, "runner_python", str(PYTHON))
    sandbox = execution.default_sandbox()
    assert Path(sandbox.python) == PYTHON


@pytest.mark.skipif(os.name != "nt", reason="Windows venv layout translation")
def test_the_posix_default_is_translated_on_windows():
    candidates = execution.runner_candidates(".venv-runner/bin/python")
    assert any(c.parts[-3:] == (".venv-runner", "Scripts", "python.exe") for c in candidates)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("churn.csv", ["data.csv", "churn.csv"]),
        ("Sales Q3-2024.csv", ["data.csv", "Sales Q3-2024.csv"]),
        ("data.csv", ["data.csv"]),
        ("../escape.csv", ["data.csv"]),
        ("sub/dir.csv", ["data.csv"]),
        ("notes.txt", ["data.csv"]),
        ("pipeline.py", ["data.csv"]),
        ("café.csv", ["data.csv"]),
        ("", ["data.csv"]),
    ],
)
def test_the_original_filename_is_aliased_only_when_safe(filename, expected):
    assert execution.data_file_names(filename) == expected


def test_code_reading_the_original_filename_still_runs():
    """Observed live: given a realistic filename in the profile, the model
    read that name instead of data.csv. The run must not fail on that."""
    profile = _profile().model_copy(update={"filename": "churn_e2e.csv"})
    frame = pd.DataFrame({"x": range(20), "y": [0, 1] * 10})
    code = "import pandas as pd\nprint(len(pd.read_csv('churn_e2e.csv', engine='c')))\n"
    run = execution.run_pipeline(code=code, frame=frame, profile=profile, sandbox=_sandbox())
    assert run.succeeded, run.stderr
    assert run.stdout.strip() == "20"


def test_run_pipeline_packages_a_run_result():
    profile = _profile()
    frame = pd.DataFrame({"x": range(20), "y": [0, 1] * 10})
    run = execution.run_pipeline(
        code="print('ok')\n", frame=frame, profile=profile, sandbox=_sandbox()
    )
    assert run.succeeded
    assert run.sample_rows == 20
    assert run.stdout.strip() == "ok"


# --- Docker sandbox ----------------------------------------------------------


def _docker_sandbox(timeout_s: int = 60) -> execution.DockerSandbox:
    return execution.DockerSandbox(
        docker="docker",
        image=settings.execution_docker_image,
        timeout_s=timeout_s,
        max_output_chars=20_000,
    )


def test_the_container_command_carries_every_isolation_flag(tmp_path):
    command = _docker_sandbox().command(tmp_path, "autonexus-run-test")
    joined = " ".join(command)
    for flag in (
        "--rm",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 65534:65534",
        f"--memory {heuristics.EXECUTION_DOCKER_MEMORY_MB}m",
        f"--pids-limit {heuristics.EXECUTION_DOCKER_PIDS_LIMIT}",
        "--name autonexus-run-test",
    ):
        assert flag in joined, flag
    mount = command[command.index("--mount") + 1]
    assert mount.endswith(",target=/work,readonly")
    assert command[-5:] == ["python", "-I", "-X", "utf8", "pipeline.py"]


def test_the_container_gets_no_host_environment(tmp_path, monkeypatch):
    """docker run passes only explicit -e flags. None may carry a secret."""
    monkeypatch.setenv("GOOGLE_API_KEY", "secret-should-not-leak")
    command = _docker_sandbox().command(tmp_path, "n")
    passed = [command[i + 1] for i, part in enumerate(command) if part == "-e"]
    assert all(not value.startswith("GOOGLE") for value in passed)
    assert "secret-should-not-leak" not in " ".join(command)


def test_docker_backend_reports_a_missing_cli(monkeypatch):
    monkeypatch.setattr(settings, "enable_local_execution", True)
    monkeypatch.setattr(settings, "execution_backend", "docker")
    monkeypatch.setattr(execution.shutil, "which", lambda _: None)
    with pytest.raises(AppError) as exc_info:
        execution.default_sandbox()
    assert exc_info.value.code is ErrorCode.EXECUTION_UNAVAILABLE
    assert "docker" in exc_info.value.message.lower()


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("failed to connect to the docker API at npipe", "not running"),
        ("Error: No such image: autonexus-runner:latest", "docker build"),
    ],
)
def test_docker_backend_tells_engine_down_from_image_missing(monkeypatch, stderr, expected):
    monkeypatch.setattr(settings, "enable_local_execution", True)
    monkeypatch.setattr(settings, "execution_backend", "docker")
    monkeypatch.setattr(execution.shutil, "which", lambda _: "docker")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(execution.subprocess, "run", fake_run)
    with pytest.raises(AppError) as exc_info:
        execution.default_sandbox()
    assert exc_info.value.code is ErrorCode.EXECUTION_UNAVAILABLE
    assert expected in exc_info.value.message


def _runner_image_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "image", "inspect", settings.execution_docker_image],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


docker_only = pytest.mark.skipif(
    not _runner_image_available(),
    reason="Docker engine not running or runner image not built",
)


@docker_only
def test_a_real_container_run_reads_the_sample():
    code = "import pandas as pd\nprint('rows', len(pd.read_csv('data.csv', engine='c')))\n"
    outcome = _docker_sandbox().run(code, SAMPLE)
    assert outcome.exit_code == 0, outcome.stderr
    assert "rows 3" in outcome.stdout


@docker_only
def test_the_container_has_no_network():
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('NETWORK OPEN')\n"
        "except OSError as exc:\n"
        "    print('blocked', type(exc).__name__)\n"
    )
    outcome = _docker_sandbox().run(code, SAMPLE)
    assert "blocked" in outcome.stdout, outcome.stdout + outcome.stderr
    assert "NETWORK OPEN" not in outcome.stdout


@docker_only
def test_the_container_cannot_write_its_inputs():
    code = (
        "try:\n"
        "    open('data.csv', 'w').write('x')\n"
        "    print('WRITABLE')\n"
        "except OSError:\n"
        "    print('read-only')\n"
    )
    outcome = _docker_sandbox().run(code, SAMPLE)
    assert "read-only" in outcome.stdout, outcome.stdout + outcome.stderr


@docker_only
def test_a_runaway_container_is_killed_at_the_timeout():
    started = time.monotonic()
    outcome = _docker_sandbox(timeout_s=5).run("while True:\n    pass\n", SAMPLE)
    assert outcome.timed_out
    assert time.monotonic() - started < 40
    names = subprocess.run(
        ["docker", "ps", "--filter", "name=autonexus-run-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert names.strip() == "", f"container survived the timeout: {names}"


@docker_only
def test_real_generated_pipelines_run_in_the_container():
    """The recorded Gemini pipelines are real scikit-learn code. They must run
    unchanged in the container image."""
    import json as _json

    from app.models import GenResult

    cassettes = sorted((Path(__file__).parent / "cassettes").glob("*.json"))
    assert cassettes
    for path in cassettes:
        payload = _json.loads(path.read_text())
        frame = pd.read_csv(
            Path(__file__).parent / "fixtures" / "profiler" / payload["fixture"], engine="c"
        )
        card = profiler.profile(frame, "x", payload["fixture"], "target")
        result = GenResult.model_validate_json(payload["raw_text"])
        run = execution.run_pipeline(
            code=result.code, frame=frame, profile=card, sandbox=_docker_sandbox(timeout_s=180)
        )
        assert run.succeeded, f"{payload['fixture']}: {run.stderr[-800:]}"
