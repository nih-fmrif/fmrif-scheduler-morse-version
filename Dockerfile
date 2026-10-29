FROM python:3.11.2-slim
SHELL ["/bin/bash", "--login", "-c"]
WORKDIR /app
ENV IS_CONTAINER=1
ARG PIXI_VERSION=0.56.0
ENV PIXI_HOME=/root/.pixi
ENV PATH="${PIXI_HOME}/bin:/app/.pixi/envs/default/bin:$PATH"

# Install postgres client for health check
RUN apt-get update && apt-get install -y curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Pixi without mutating shell startup files inside the image.
RUN export PIXI_NO_PATH_UPDATE=1 \
    && curl -fsSL https://pixi.sh/install.sh | PIXI_VERSION="${PIXI_VERSION}" bash

# Install the repository-managed environment.
COPY pixi.toml .
COPY pyproject.toml .
COPY README.md .
COPY ./scheduler ./scheduler
RUN sed -i 's/^platforms = \[.*\]/platforms = ["linux-64"]/g' /app/pixi.toml \
    && "${PIXI_HOME}/bin/pixi" install --manifest-path /app/pixi.toml --environment default --no-progress

COPY ./entrypoint.sh ./entrypoint.sh

# Make entrypoint executable
RUN chmod a+x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
