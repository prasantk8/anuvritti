# syntax=docker/dockerfile:1.7
# ============================================================================
# Anuvritti - Offline Render Worker (PRD 44, HARDENING 5.1, TASK-1203)
#
# Runs in an isolated sandbox with:
# 1. No network access (--network none).
# 2. Read-only root filesystem (--read-only).
# 3. Dedicated unprivileged user (UID 10001).
# 4. Ephemeral job media volume mounted for one job only, then cleanly removed.
# 5. Offline bundled fonts and Chromium browser binaries.
# ============================================================================

FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for world scene renderer
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY packages/filmkit ./packages/filmkit
RUN pip install --no-deps -r requirements.txt 2>/dev/null || pip install -r requirements.txt
RUN pip install playwright

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps .

# ---------------------------------------------------------------- runtime stage
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Anuvritti Render Worker" \
      org.opencontainers.image.description="Offline sandboxed film rendering engine" \
      org.opencontainers.image.licenses="UNLICENSED"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PATH="/opt/venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    NODE_PATH=/usr/lib/node_modules \
    TMPDIR=/tmp \
    ANUVRITTI_ENV=production

# Install runtime dependencies: ffmpeg, nodejs, and browser libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ffmpeg \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Dedicated unprivileged render user
RUN groupadd --system --gid 10001 anuvritti \
    && useradd --system --uid 10001 --gid anuvritti --no-create-home --shell /usr/sbin/nologin anuvritti

COPY --from=build --chown=root:root /opt/venv /opt/venv

# Install and bundle Chromium browser offline
RUN /opt/venv/bin/playwright install --with-deps chromium \
    && mkdir -p /opt/playwright-browsers \
    && cp -r /root/.cache/ms-playwright/* /opt/playwright-browsers/ 2>/dev/null || true \
    && chown -R anuvritti:anuvritti /opt/playwright-browsers

# Create workspace and temp directories
RUN mkdir -p /workspace /var/film /tmp \
    && chown -R anuvritti:anuvritti /workspace /var/film /tmp \
    && chmod 1777 /tmp

USER anuvritti:anuvritti
WORKDIR /workspace

# Default entrypoint runs single job in isolation and exits
ENTRYPOINT ["python3", "scripts/render_worker.py"]
CMD ["--once"]
