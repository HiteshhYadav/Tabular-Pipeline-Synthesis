# The execution sandbox image (EXECUTION_BACKEND=docker).
#
# Same packages as the local .venv-runner, from the same requirements file, so
# a pipeline behaves identically under either sandbox. Nothing of the API is
# in this image: no app code, no google-genai, no keys.
#
# Build from backend/:
#   docker build -f runner.Dockerfile -t autonexus-runner:latest .
#
# Every run is started by execution.DockerSandbox with no network, a
# read-only root filesystem, the sample mounted read-only, all capabilities
# dropped, and memory/CPU/PID limits. The image only has to be small and
# unprivileged; the run-time flags are the boundary.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY runner-requirements.txt /tmp/runner-requirements.txt
RUN pip install -r /tmp/runner-requirements.txt && rm /tmp/runner-requirements.txt

# 65534 is "nobody". Nothing in the container runs as root.
USER 65534:65534
WORKDIR /work

CMD ["python", "-I", "-X", "utf8", "pipeline.py"]
