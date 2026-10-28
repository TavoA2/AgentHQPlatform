# Image used by the sandbox runner's "python-pytest" template (ADR-0011).
# Runs with no network, so everything tests may use must be installed here.
FROM python:3.13-slim

RUN pip install --no-cache-dir "pytest==9.2.0"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
WORKDIR /tmp
