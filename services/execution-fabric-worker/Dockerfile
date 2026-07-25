FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTIC_OS_ROOT=/var/lib/agentic-os

WORKDIR /opt/genomes-agentic-os
COPY pyproject.toml setup.py MANIFEST.in README.md ./
COPY src ./src
COPY harness ./harness
COPY templates ./templates
COPY schemas ./schemas
COPY operating-manual ./operating-manual
RUN python -m pip install --no-cache-dir . \
    && addgroup --system --gid 65532 worker \
    && adduser --system --uid 65532 --ingroup worker --home /nonexistent worker \
    && mkdir -p /var/lib/agentic-os \
    && chown -R worker:worker /var/lib/agentic-os

USER 65532:65532
ENTRYPOINT ["python", "-m", "genomes_agentic_os.execution_fabric_worker"]
