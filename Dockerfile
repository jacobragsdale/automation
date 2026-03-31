FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS builder
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install only production dependencies first to maximize layer reuse.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Add application code and install the project environment.
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm
WORKDIR /app

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8000"]
