FROM debian:bookworm-slim
SHELL ["/bin/bash", "--login", "-c"]
WORKDIR /app

# Add virtual env to the path
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.5.10 /uv /bin/uv

# Install requirements first
COPY pyproject.toml .
RUN uv sync --python 3.11

# Copy the application code
COPY . .
RUN uv sync

# Make entrypoint executable
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
