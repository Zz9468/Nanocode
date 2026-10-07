# =============================================================================
# Nanocode Python — Multi-stage Dockerfile
# =============================================================================
# Inspired by Hermes Agent's flexible deployment model:
#   - Lightweight CLI container for local/CI use
#   - Gateway-ready base for multi-platform access (Telegram/Discord/Web)
#   - Headless mode for cron/scheduled tasks
#
# Quick start:
#   docker build -t nanocode-py .
#   docker run -it --rm \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v $(pwd):/workspace \
#     nanocode-py
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install package into venv
# ---------------------------------------------------------------------------
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE} AS builder

WORKDIR /build

# Copy package source
COPY pyproject.toml README.md ./
COPY nanocode/ ./nanocode/
COPY Main/ ./Main/
COPY Package/ ./Package/

# Install into a clean venv (keeps final image small)
RUN python -m venv /opt/nanocode-venv && \
    /opt/nanocode-venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/nanocode-venv/bin/pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image with only the venv
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="Nanocode Python"
LABEL org.opencontainers.image.description="A lightweight terminal coding assistant — the agent that grows with you"
LABEL org.opencontainers.image.source="https://github.com/Zz9468/Nanocode"

# Create non-root user for security
RUN groupadd --gid 1000 nanocode && \
    useradd --uid 1000 --gid nanocode --create-home --shell /bin/bash nanocode

# Copy venv from builder
COPY --from=builder /opt/nanocode-venv /opt/nanocode-venv

# Make nanocode-py available on PATH
ENV PATH="/opt/nanocode-venv/bin:${PATH}"

# Create persistent data directories
RUN mkdir -p /home/nanocode/.nanocode/memory /home/nanocode/.nanocode/skills && \
    chown -R nanocode:nanocode /home/nanocode/.nanocode

# Default workspace
RUN mkdir -p /workspace && chown nanocode:nanocode /workspace
WORKDIR /workspace

# Environment defaults (override at runtime)
ENV NANO_CODE_LOG_LEVEL=WARNING \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    # Container hint — lets Nanocode know it's running in Docker
    NANO_CODE_CONTAINER=docker

# Health check: verify the CLI entry point works
HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from nanocode.main import main; print('ok')" || exit 1

# Switch to non-root user
USER nanocode

# Default entry: interactive CLI mode
ENTRYPOINT ["nanocode-py"]
CMD ["--help"]
