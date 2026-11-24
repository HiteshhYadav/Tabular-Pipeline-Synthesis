# The API image. Built by docker-compose.yml at the repo root.
#
# Contains the FastAPI app and its runtime dependencies only: no tests, no
# scikit-learn (generated code never runs in the API process - see ADR 0002),
# and no .env. Configuration arrives as environment variables from compose.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# SQLite database and uploaded CSVs live on a mounted volume, owned by a
# non-root user. The TTL sweeper deletes both after DATASET_TTL_HOURS.
RUN useradd --system --uid 10001 --no-create-home autonexus \
    && mkdir -p /app/data/uploads \
    && chown -R autonexus /app/data
USER autonexus

ENV DB_PATH=/app/data/app.db \
    UPLOAD_DIR=/app/data/uploads

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# One worker, on purpose: rate-limit windows and the one-generation-per-dataset
# guard are in process memory. --proxy-headers makes rate limits count the real
# client rather than the nginx container; that is safe only because this port
# is never published - compose exposes it to the web container alone, and
# nginx overwrites X-Forwarded-For instead of appending to it.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
