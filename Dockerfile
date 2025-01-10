FROM debian:bookworm-slim
SHELL ["/bin/bash", "--login", "-c"]
WORKDIR /app
# Add virtual env to the path
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.5.10 /uv /bin/uv
# Install requirements first in a separate layer to avoid re-installing them on
# every code changes
COPY pyproject.toml .
# Create the virtual environment
RUN uv sync --python 3.11
# # Copy the application code
COPY . .
RUN uv sync
CMD ["flask", "run", "--host", "0.0.0.0"]