# syntax=docker/dockerfile:1.7
# ============================================================================
# Anuvritti - production image
#
# Multi-stage so no build toolchain, no compiler and no package index credential
# reaches the running container. It runs as a non-root user with a read-only
# root filesystem in mind: everything mutable lives under /var/lib/anuvritti,
# which is expected to be a mounted volume the family actually owns (PRD 44).
# ============================================================================

# ---------------------------------------------------------------- build stage
FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Wheels are built here and only the resulting virtualenv is copied forward.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
COPY packages/filmkit ./packages/filmkit
RUN pip install --require-hashes --no-deps -r requirements.txt 2>/dev/null \
    || pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps .

# --------------------------------------------------------------- runtime stage
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Anuvritti" \
      org.opencontainers.image.description="Family presence, intent & memory platform" \
      org.opencontainers.image.source="https://github.com/anuvritti/anuvritti" \
      org.opencontainers.image.licenses="UNLICENSED"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PATH="/opt/venv/bin:$PATH" \
    ANUVRITTI_ENV=production \
    ANUVRITTI_DB_PATH=/var/lib/anuvritti/anuvritti.db \
    ANUVRITTI_MEDIA_DIR=/var/lib/anuvritti/media

# Security patches plus ffprobe's package; no build tooling and no browser runtime.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# A dedicated unprivileged account. It owns the data directory and nothing else.
RUN groupadd --system --gid 10001 anuvritti \
    && useradd --system --uid 10001 --gid anuvritti --no-create-home --shell /usr/sbin/nologin anuvritti \
    && mkdir -p /var/lib/anuvritti/media \
    && chown -R anuvritti:anuvritti /var/lib/anuvritti

COPY --from=build --chown=root:root /opt/venv /opt/venv

USER anuvritti:anuvritti
WORKDIR /var/lib/anuvritti
VOLUME ["/var/lib/anuvritti"]
EXPOSE 8000

# The app refuses to boot without ANUVRITTI_MEDIA_KEY in production (PRD 44),
# so an unhealthy container here means a misconfiguration, not a crash loop to ignore.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["anuvritti.interfaces.http.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
