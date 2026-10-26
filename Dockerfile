FROM python:3.15-slim-bookworm@sha256:575f8bc12ec26542e0678bc6b60e385218248019d433157ec327264a78c3a853 AS builder
WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.11.2
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --extra models --no-dev --no-install-project
COPY shared shared
COPY services services
COPY scripts scripts
COPY prompts prompts
COPY migrations migrations
RUN uv sync --locked --extra models --no-dev --no-editable

FROM python:3.15-slim-bookworm@sha256:575f8bc12ec26542e0678bc6b60e385218248019d433157ec327264a78c3a853
RUN useradd --uid 10001 --create-home rag && mkdir /models /documents && chown rag:rag /models /documents
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/models
USER 10001
EXPOSE 8000
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "70"]
