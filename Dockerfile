FROM python:3.11.2-slim
SHELL ["/bin/bash", "--login", "-c"]
WORKDIR /app
ENV IS_CONTAINER=1
# Add virtual env to the path
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.5.10 /uv /bin/uv

# Install postgres client for health check
RUN apt-get update && apt-get install -y postgresql-client

# Install requirements first
COPY pyproject.toml .
RUN uv sync

# Copy the application code
COPY ./scheduler ./scheduler
COPY ./entrypoint.sh ./entrypoint.sh
COPY ./alembic.ini ./alembic.ini
RUN uv sync

# Make entrypoint executable
RUN chmod a+x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]