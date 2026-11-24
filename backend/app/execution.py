"""MVP-1.5: running a generated pipeline on a small sample, in a subprocess.

Not prompt surface. Nothing in this module reaches the model.

What this is, stated plainly so nobody mistakes it for more:

  A convenience for a developer on their own machine. The pipeline runs in a
  separate interpreter (RUNNER_PYTHON, its own venv with scikit-learn), in a
  fresh temporary directory holding only the script and a sample of the data,
  with an environment that carries none of the API's variables - in particular
  no GOOGLE_API_KEY - and a hard timeout that kills the whole process group.

  It is NOT a security sandbox. A determined script can still read files the
  user can read and open network connections through some library path the
  static checks did not anticipate. That is why ENABLE_LOCAL_EXECUTION is
  refused at boot outside DEPLOYMENT_ENV=local, and why the phase-2 plan puts
  a container around this same Sandbox protocol before it ever runs anywhere
  else. The static checks and the preflight below raise the bar; they are not
  the boundary.

Only code the server generated and stored is ever executed. The route never
accepts code from the client, for the same reason it never accepts a profile.
"""

from __future__ import annotations

import ast
import contextlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from app import heuristics, validation
from app.config import settings
from app.errors import AppError, ErrorCode
from app.models import GenResult, ProblemType, ProfileCard, RunResult

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# The file names the generated code is told to expect. The prompt says
# "read data.csv", so the sample must be written under exactly that name.
SCRIPT_NAME = "pipeline.py"
DATA_NAME = "data.csv"

# The static checks that bear on safety rather than correctness. A pipeline
# that fails one of these is never run. The other ERROR checks - a
# hallucinated column, a strategy that contradicts the profile - are about
# whether the code is right, and running it is precisely how a user finds out
# what a wrong column name actually does, so they do not block execution.
SAFETY_CHECK_IDS = ("syntax_compile", "ast_import_allowlist", "dangerous_calls")

# Variables that cap numerical-library threads. The cap itself is
# heuristics.EXECUTION_THREAD_CAP.
_THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "LOKY_MAX_CPU_COUNT")


# ---------------------------------------------------------------------------
# Preflight: a second, execution-only static screen
# ---------------------------------------------------------------------------
#
# validation.py's checks were written for code a human will read before
# running. Code this server is about to run itself deserves a stricter screen,
# kept here rather than in validation.py so that the twelve-check report the
# user sees stays exactly what it was, and so the validation corpus tests are
# untouched.

# Builtins with no legitimate use in a modelling script and an obvious use in
# escaping one. getattr is not listed: `getattr(model, "feature_importances_",
# None)` is idiomatic, and the dunder-string rule below covers its abuse.
_PREFLIGHT_BUILTINS = {
    "open",
    "globals",
    "locals",
    "vars",
    "setattr",
    "delattr",
    "breakpoint",
    "memoryview",
}

# Attribute names that reach the OS through a library that re-exports it, for
# example `pd.io.common.os.system`. The import allowlist cannot see these,
# because nothing is imported.
_PREFLIGHT_ATTRS = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "builtins",
    "importlib",
    "ctypes",
    "socket",
    "pathlib",
    "system",
    "popen",
}

# `if __name__ == "__main__":` is idiomatic and harmless.
_ALLOWED_DUNDER_STRINGS = {"__main__"}

_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://")
_ABSOLUTE_PATH = re.compile(r"^(?:/[A-Za-z_.]|~[/\\]|[A-Za-z]:[\\/]|\\\\)")


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def preflight_findings(code: str) -> list[str]:
    """Return every reason this code should not be run, or [] if none.

    Assumes the code already parsed; the syntax check runs first.
    """
    tree = ast.parse(code)
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _PREFLIGHT_BUILTINS:
                findings.append(f"line {node.lineno}: call to {node.func.id}()")
        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr):
                findings.append(f"line {node.lineno}: dunder attribute .{node.attr}")
            elif node.attr in _PREFLIGHT_ATTRS:
                findings.append(f"line {node.lineno}: attribute .{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if _is_dunder(value) and value not in _ALLOWED_DUNDER_STRINGS:
                findings.append(f"line {node.lineno}: dunder string {value!r}")
            elif _URL.search(value):
                findings.append(f"line {node.lineno}: URL literal")
            elif _ABSOLUTE_PATH.match(value):
                findings.append(f"line {node.lineno}: absolute path literal")
    return findings


def preflight(result: GenResult, profile: ProfileCard, excluded: Sequence[str]) -> None:
    """Refuse to run code that failed a safety check. Raises VALIDATION_FAILED.

    Re-runs the static checks on the stored result rather than trusting a
    report computed earlier: the checks are cheap and deterministic, and
    gating execution on a stored boolean would make a stale row the thing
    that decides whether code runs.
    """
    report = validation.validate(result, profile, excluded)
    failed = [
        check.title
        for check in report.checks
        if check.check_id in SAFETY_CHECK_IDS and not check.passed
    ]
    if failed:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "This pipeline failed a safety check and will not be run: "
            + ", ".join(failed)
            + ". Read the checklist, then run it yourself only if you are satisfied.",
            {"failed_checks": ", ".join(failed)},
        )
    findings = preflight_findings(result.code)
    if findings:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "This pipeline uses constructs that are not run automatically ("
            + "; ".join(findings[:5])
            + "). It is still shown in full - run it yourself if it looks right.",
            {"preflight": "; ".join(findings)},
        )


# ---------------------------------------------------------------------------
# The sample
# ---------------------------------------------------------------------------


def build_sample(frame: pd.DataFrame, profile: ProfileCard, n_rows: int) -> pd.DataFrame:
    """Draw the rows the pipeline will run on.

    Fixed seed, so two runs of the same pipeline see the same rows. For a
    classification target, every class first gets up to
    EXECUTION_MIN_ROWS_PER_CLASS rows, then the rest is filled at random - see
    that constant for why a plain random draw breaks stratified CV on
    imbalanced files. Original row order is restored afterwards, so a file
    sorted by time stays sorted.
    """
    if len(frame) <= n_rows:
        return frame

    seed = heuristics.EXECUTION_SAMPLE_SEED
    chosen: list = []
    is_classification = profile.problem_type in {
        ProblemType.BINARY_CLASSIFICATION,
        ProblemType.MULTICLASS_CLASSIFICATION,
    }
    if is_classification and profile.target_column in frame.columns:
        for _, group in frame.groupby(profile.target_column, dropna=True, sort=True):
            take = min(len(group), heuristics.EXECUTION_MIN_ROWS_PER_CLASS)
            chosen.extend(group.sample(n=take, random_state=seed).index)
        chosen = chosen[:n_rows]

    remaining = frame.index.difference(pd.Index(chosen))
    fill = n_rows - len(chosen)
    if fill > 0:
        chosen.extend(frame.loc[remaining].sample(n=fill, random_state=seed).index)
    return frame.loc[sorted(chosen)]


# ---------------------------------------------------------------------------
# The sandbox
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessOutcome:
    """What one subprocess run produced, before it becomes a RunResult."""

    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool


class Sandbox(Protocol):
    """Somewhere a script can run against a data file and report back.

    One implementation today. The phase-2 Docker runner implements the same
    method, which is why the API depends on this protocol and not on the
    subprocess details.
    """

    name: str

    def run(
        self, code: str, sample: pd.DataFrame, data_names: Sequence[str] = (DATA_NAME,)
    ) -> ProcessOutcome: ...


# Names the sandbox itself writes into the run directory; an alias must never
# overwrite one of them.
_RESERVED_NAMES = {SCRIPT_NAME.lower(), "stdout.txt", "stderr.txt"}
_SAFE_CSV_NAME = re.compile(r"[\w.\- ]{1,120}\.csv", re.IGNORECASE)


def data_file_names(original_filename: str) -> list[str]:
    """Every name the sample is written under: data.csv, plus the user's own
    file name when it is safe to use as a bare file name.

    The prompt tells the model to read exactly data.csv, and recorded
    generations do. A live one, given a realistic filename in the profile,
    read `pd.read_csv("churn.csv")` instead - correct for the user, who runs
    the download against their own file, and a spurious FileNotFoundError
    here that says nothing about whether the pipeline works. Writing the same
    sample under both names removes that failure without touching the prompt
    (and so without invalidating the cassettes).

    Only a bare, plain name qualifies: no directory parts, ASCII word
    characters, dots, hyphens and spaces, ending in .csv. Anything else is
    simply not aliased.
    """
    names = [DATA_NAME]
    candidate = original_filename.strip()
    if (
        candidate
        and Path(candidate).name == candidate
        and _SAFE_CSV_NAME.fullmatch(candidate)
        and candidate.isascii()
        and candidate.lower() not in _RESERVED_NAMES
        and candidate.lower() != DATA_NAME
    ):
        names.append(candidate)
    return names


def _child_env(workdir: Path, python: Path) -> dict[str, str]:
    """A minimal environment, built from nothing rather than filtered.

    Filtering os.environ would have to anticipate every secret it might hold.
    Starting empty means GOOGLE_API_KEY, cloud credentials and anything else
    in the API's environment never reach the script. Windows needs a handful
    of system variables for the interpreter and numpy's DLLs to load at all.
    """
    env = {
        "PATH": str(python.parent),
        "TMP": str(workdir),
        "TEMP": str(workdir),
        "TMPDIR": str(workdir),
        "HOME": str(workdir),
        "USERPROFILE": str(workdir),
    }
    env.update(dict.fromkeys(_THREAD_ENV, str(heuristics.EXECUTION_THREAD_CAP)))
    if os.name == "nt":
        for key in (
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        system_root = os.environ.get("SYSTEMROOT")
        if system_root:
            env["PATH"] += os.pathsep + str(Path(system_root) / "System32")
    return env


def _group_kwargs() -> dict:
    """Start the child as the leader of its own process group, so the group
    can be killed as a unit - a pipeline using n_jobs spawns workers, and
    killing only the parent leaves them running."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_group(process: subprocess.Popen) -> None:
    """Kill the child and everything it spawned. Safe to call on a process
    that already exited."""
    if os.name == "nt":
        # taskkill /T walks the tree from the parent, so it is only useful
        # while the parent is alive. Once it has exited, its workers detect
        # the broken pipe to their parent and exit on their own.
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
    else:
        # The group outlives its leader, so this also reaps stragglers after
        # a normal exit. ProcessLookupError means there is nothing left.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()


def _read_head(path: Path, max_chars: int) -> tuple[str, bool]:
    """Read at most max_chars of a captured stream, and whether it was cut.

    Output goes to files rather than pipes so a print loop cannot grow the
    API process's memory, and only the head is read back.
    """
    if not path.exists():
        return "", False
    # UTF-8 is at most 4 bytes per character, so this many bytes always
    # covers max_chars characters.
    budget = max_chars * 4
    size = path.stat().st_size
    with path.open("rb") as handle:
        raw = handle.read(budget)
    text = raw.decode("utf-8", errors="replace")
    truncated = size > budget or len(text) > max_chars
    return text[:max_chars], truncated


class LocalSubprocessSandbox:
    """Runs the script under RUNNER_PYTHON in a throwaway directory."""

    name = "local-subprocess"

    def __init__(self, python: Path, timeout_s: int, max_output_chars: int) -> None:
        self.python = python
        self.timeout_s = timeout_s
        self.max_output_chars = max_output_chars

    def run(
        self, code: str, sample: pd.DataFrame, data_names: Sequence[str] = (DATA_NAME,)
    ) -> ProcessOutcome:
        with tempfile.TemporaryDirectory(
            prefix="autonexus-run-", ignore_cleanup_errors=True
        ) as tmp:
            workdir = Path(tmp)
            (workdir / SCRIPT_NAME).write_text(code, encoding="utf-8")
            for data_name in data_names:
                sample.to_csv(workdir / data_name, index=False)
            stdout_path = workdir / "stdout.txt"
            stderr_path = workdir / "stderr.txt"

            # -I: isolated mode. Ignores PYTHON* variables and the user site,
            # and does not put the working directory on sys.path, so a stray
            # file named pandas.py next to the script could not shadow pandas.
            # -X utf8: -I also ignores PYTHONIOENCODING, and without UTF-8
            # mode a non-ASCII column name printed on Windows raises
            # UnicodeEncodeError against the console code page.
            command = [str(self.python), "-I", "-X", "utf8", SCRIPT_NAME]

            timed_out = False
            started = time.monotonic()
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.Popen(
                    command,
                    cwd=workdir,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    env=_child_env(workdir, self.python),
                    **_group_kwargs(),
                )
                try:
                    process.wait(timeout=self.timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                finally:
                    # Always, not only on timeout: this is the reap. An
                    # exception anywhere above must not leave a child behind.
                    _kill_group(process)
                    process.wait()
            duration_ms = int((time.monotonic() - started) * 1000)

            stdout, stdout_cut = _read_head(stdout_path, self.max_output_chars)
            stderr, stderr_cut = _read_head(stderr_path, self.max_output_chars)

        return ProcessOutcome(
            exit_code=None if timed_out else process.returncode,
            timed_out=timed_out,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_cut,
            stderr_truncated=stderr_cut,
        )


class DockerSandbox:
    """Runs the script in a locked-down, throwaway container.

    The phase-2 boundary the local sandbox was designed to be swapped for.
    What the container gets, and what each flag removes:

      --network none           no network at all, so no exfiltration and no
                               pd.read_csv("http://...") however it is spelled
      --read-only + --tmpfs    nothing persists; only a small /tmp is writable
      --mount ...,readonly     the script and sample are visible, not editable,
                               and nothing else of the host filesystem is
      --user 65534             not root inside the container
      --cap-drop ALL,          no Linux capabilities, no setuid escalation
      no-new-privileges
      --memory/--cpus/         a runaway script is killed inside its own
      --pids-limit             cgroup instead of starving the host
      --rm + --name            removed after the run; the name is what the
                               timeout path kills, because killing the docker
                               CLI process alone would leave the container
                               running
    """

    name = "docker"

    def __init__(
        self, docker: str, image: str, timeout_s: int, max_output_chars: int
    ) -> None:
        self.docker = docker
        self.image = image
        self.timeout_s = timeout_s
        self.max_output_chars = max_output_chars

    def command(self, workdir: Path, container_name: str) -> list[str]:
        threads = str(heuristics.EXECUTION_THREAD_CAP)
        env_flags: list[str] = []
        for key in (*_THREAD_ENV, "HOME", "TMPDIR"):
            value = "/tmp" if key in {"HOME", "TMPDIR"} else threads
            env_flags += ["-e", f"{key}={value}"]
        return [
            self.docker,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,size={heuristics.EXECUTION_DOCKER_TMPFS_MB}m",
            "--mount",
            f"type=bind,source={workdir},target=/work,readonly",
            "--workdir",
            "/work",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            f"{heuristics.EXECUTION_DOCKER_MEMORY_MB}m",
            "--cpus",
            threads,
            "--pids-limit",
            str(heuristics.EXECUTION_DOCKER_PIDS_LIMIT),
            *env_flags,
            self.image,
            "python",
            "-I",
            "-X",
            "utf8",
            SCRIPT_NAME,
        ]

    def _kill_container(self, container_name: str) -> None:
        subprocess.run(
            [self.docker, "kill", container_name],
            capture_output=True,
            check=False,
            timeout=30,
        )

    def run(
        self, code: str, sample: pd.DataFrame, data_names: Sequence[str] = (DATA_NAME,)
    ) -> ProcessOutcome:
        container_name = f"autonexus-run-{uuid.uuid4().hex[:12]}"
        with tempfile.TemporaryDirectory(
            prefix="autonexus-run-", ignore_cleanup_errors=True
        ) as tmp:
            # The mounted directory holds only what the script may read. The
            # captured streams live beside it, outside the mount.
            workdir = Path(tmp) / "work"
            workdir.mkdir()
            (workdir / SCRIPT_NAME).write_text(code, encoding="utf-8")
            for data_name in data_names:
                sample.to_csv(workdir / data_name, index=False)
            stdout_path = Path(tmp) / "stdout.txt"
            stderr_path = Path(tmp) / "stderr.txt"

            timed_out = False
            started = time.monotonic()
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.Popen(
                    self.command(workdir, container_name),
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    **_group_kwargs(),
                )
                try:
                    process.wait(timeout=self.timeout_s)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._kill_container(container_name)
                finally:
                    _kill_group(process)
                    process.wait()
            duration_ms = int((time.monotonic() - started) * 1000)

            stdout, stdout_cut = _read_head(stdout_path, self.max_output_chars)
            stderr, stderr_cut = _read_head(stderr_path, self.max_output_chars)

        return ProcessOutcome(
            exit_code=None if timed_out else process.returncode,
            timed_out=timed_out,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_cut,
            stderr_truncated=stderr_cut,
        )


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def resolve_docker() -> str:
    """The docker CLI, with the configured image present and the engine up.

    Checked per request rather than at boot: Docker Desktop is routinely
    started after the API, and a stale "unavailable" decided at boot would
    outlive the problem.
    """
    docker = shutil.which("docker")
    if docker is None:
        raise AppError(
            ErrorCode.EXECUTION_UNAVAILABLE,
            "EXECUTION_BACKEND=docker, but the docker command was not found. "
            "Install Docker, or set EXECUTION_BACKEND=subprocess.",
        )
    probe = subprocess.run(
        [docker, "image", "inspect", settings.execution_docker_image],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0:
        engine_down = "daemon" in probe.stderr.lower() or "docker api" in probe.stderr.lower()
        raise AppError(
            ErrorCode.EXECUTION_UNAVAILABLE,
            "The Docker engine is not running. Start Docker Desktop and try again."
            if engine_down
            else f"The runner image {settings.execution_docker_image} has not been built. "
            "From backend/, run: docker build -f runner.Dockerfile -t "
            f"{settings.execution_docker_image} .",
            {"image": settings.execution_docker_image},
        )
    return docker


def runner_candidates(configured: str) -> list[Path]:
    """Every path RUNNER_PYTHON could reasonably mean, most literal first.

    Relative paths are tried against the working directory and then against
    the backend directory, so the server works whether it was started from
    backend/ (as the README says) or from the repo root. On Windows the venv
    layout is Scripts\\python.exe rather than bin/python, so the POSIX default
    in .env.example is translated rather than forcing a second .env.
    """
    raw = Path(configured)
    names = [raw]
    if os.name == "nt" and raw.parts[-2:] in {("bin", "python"), ("bin", "python3")}:
        names.append(raw.parent.parent / "Scripts" / "python.exe")
    candidates: list[Path] = []
    for name in names:
        if name.is_absolute():
            candidates.append(name)
        else:
            candidates.extend([Path.cwd() / name, BACKEND_ROOT / name])
    return candidates


def resolve_runner_python() -> Path:
    for candidate in runner_candidates(settings.runner_python):
        if candidate.is_file():
            return candidate
    raise AppError(
        ErrorCode.EXECUTION_UNAVAILABLE,
        f"Local execution is enabled, but the runner interpreter was not found at "
        f"{settings.runner_python}. Create the runner venv described in the README "
        "(backend/.venv-runner with runner-requirements.txt installed).",
        {"runner_python": settings.runner_python},
    )


def ensure_enabled() -> None:
    if not settings.enable_local_execution:
        raise AppError(
            ErrorCode.EXECUTION_DISABLED,
            "Running pipelines is switched off for this deployment. Set "
            "ENABLE_LOCAL_EXECUTION=true in backend/.env on a local machine to enable it.",
        )


def default_sandbox() -> Sandbox:
    """FastAPI dependency. Overridden in tests.

    Checks the flag before the runner, so a deployment with execution off is
    told it is off rather than that a venv it never needed is missing.
    """
    ensure_enabled()
    if settings.execution_backend == "docker":
        return DockerSandbox(
            docker=resolve_docker(),
            image=settings.execution_docker_image,
            timeout_s=settings.execution_timeout_s,
            max_output_chars=heuristics.EXECUTION_OUTPUT_MAX_CHARS,
        )
    return LocalSubprocessSandbox(
        python=resolve_runner_python(),
        timeout_s=settings.execution_timeout_s,
        max_output_chars=heuristics.EXECUTION_OUTPUT_MAX_CHARS,
    )


def run_pipeline(
    *, code: str, frame: pd.DataFrame, profile: ProfileCard, sandbox: Sandbox
) -> RunResult:
    """Sample, run, and package the outcome. The caller has already passed
    preflight()."""
    sample = build_sample(frame, profile, settings.execution_sample_rows)
    outcome = sandbox.run(code, sample, data_file_names(profile.filename))
    return RunResult(
        run_id=str(uuid.uuid4()),
        executed_at=datetime.now(UTC).isoformat(),
        sample_rows=len(sample),
        exit_code=outcome.exit_code,
        timed_out=outcome.timed_out,
        duration_ms=outcome.duration_ms,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        stdout_truncated=outcome.stdout_truncated,
        stderr_truncated=outcome.stderr_truncated,
        succeeded=outcome.exit_code == 0 and not outcome.timed_out,
    )
