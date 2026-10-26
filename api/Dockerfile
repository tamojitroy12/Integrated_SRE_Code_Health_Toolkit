# syntax=docker/dockerfile:1.7
# One image for the api, the worker and the one-shot migrate job (DEC-001).

ARG PYTHON_IMAGE=python:3.13.12-slim-trixie
ARG TRIVY_IMAGE=aquasec/trivy:0.75.0

FROM ${TRIVY_IMAGE} AS trivy

FROM ${PYTHON_IMAGE} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install uv==0.9.29
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY toolkit ./toolkit
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
# Semgrep lives in its own virtualenv so its dependencies never clash with the app's.
RUN python -m venv /opt/semgrep && /opt/semgrep/bin/pip install semgrep==1.180.0

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:/opt/semgrep/bin:${PATH}" \
    SEMGREP_SEND_METRICS=off SEMGREP_ENABLE_VERSION_CHECK=0 \
    TRIVY_NO_PROGRESS=true HOME=/home/toolkit
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 toolkit \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/toolkit toolkit \
 && mkdir -p /work /var/cache/trivy \
 && chown toolkit:toolkit /work /var/cache/trivy
COPY --from=trivy /usr/local/bin/trivy /usr/local/bin/trivy
COPY --from=build /opt/semgrep /opt/semgrep
COPY --from=build --chown=toolkit:toolkit /app /app
WORKDIR /app
USER 10001:10001
EXPOSE 8000 9100
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "toolkit.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
