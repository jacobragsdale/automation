FROM ghcr.io/astral-sh/uv:python3.13-bookworm
WORKDIR /app

# Cache dependencies
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen

# Add application code
COPY . .

# Prefer the project's venv
ENV PATH="/app/.venv/bin:${PATH}"

# Expose the application port
EXPOSE 8000

# Run the app
CMD ["uv", "run", "python", "app.py", "--host", "0.0.0.0", "--port", "8000"]
