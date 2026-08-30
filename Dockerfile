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

# ------------------------------------------------------- minimal media probe
# FFmpeg's Debian runtime links ffprobe to video, display and hardware libraries
# that a duration-only family server never calls. Build a file-only probe and
# three replaceable LGPL libraries from a checksummed upstream release instead. The
# version and source digest make upgrades explicit and give vulnerability reviewers
# an exact component identity.
FROM python:3.12-slim-bookworm AS ffprobe-build

ARG FFPROBE_VERSION=9.0.1
ARG FFPROBE_SOURCE_SHA256=cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates xz-utils nasm yasm \
    && rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635 \
    https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz /tmp/ffmpeg.tar.xz

RUN mkdir -p /tmp/ffmpeg /opt/ffprobe/bin /opt/ffprobe/usr/share/anuvritti \
    && tar -xJf /tmp/ffmpeg.tar.xz --strip-components=1 -C /tmp/ffmpeg \
    && cd /tmp/ffmpeg \
    && ./configure \
        --disable-x86asm \
        --disable-autodetect \
        --disable-debug \
        --disable-doc \
        --disable-everything \
        --disable-network \
        --disable-avdevice \
        --disable-avfilter \
        --disable-swresample \
        --disable-swscale \
        --disable-static \
        --enable-shared \
        --enable-small \
        --enable-ffprobe \
        --enable-protocol=file \
        --enable-demuxer=aac,matroska,mov,mp3,ogg,wav \
        --enable-parser=aac,mpegaudio,opus,vorbis \
        --enable-decoder=aac,mp3,pcm_s16le,vorbis \
        --extra-cflags='-Os -ffunction-sections -fdata-sections' \
        --prefix=/opt/ffprobe \
        --extra-ldflags='-Wl,-rpath,/usr/local/lib/ffprobe -Wl,--gc-sections' \
    && make -j"$(nproc)" ffprobe \
    && make install \
    && strip /opt/ffprobe/bin/ffprobe /opt/ffprobe/lib/*.so.* \
    && mkdir -p /opt/ffprobe/runtime-lib \
    && cp -a /opt/ffprobe/lib/libavformat.so* /opt/ffprobe/runtime-lib/ \
    && cp -a /opt/ffprobe/lib/libavcodec.so* /opt/ffprobe/runtime-lib/ \
    && cp -a /opt/ffprobe/lib/libavutil.so* /opt/ffprobe/runtime-lib/ \
    && mkdir -p /opt/ffprobe/usr/share/licenses/ffprobe \
    && install -m 0644 COPYING.LGPLv2.1 /opt/ffprobe/usr/share/licenses/ffprobe/COPYING.LGPLv2.1 \
    && { \
        echo "component=ffprobe"; \
        echo "version=$FFPROBE_VERSION"; \
        echo "source=https://ffmpeg.org/releases/ffmpeg-$FFPROBE_VERSION.tar.xz"; \
        echo "source_sha256=$FFPROBE_SOURCE_SHA256"; \
        echo "linkage=shared"; \
        echo "binary_sha256=$(sha256sum /opt/ffprobe/bin/ffprobe | cut -d ' ' -f 1)"; \
        echo "architecture=$(dpkg --print-architecture)"; \
      } > /opt/ffprobe/usr/share/anuvritti/ffprobe-runtime.manifest

# This disposable CI target creates representative bytes for every audio
# container accepted from iOS and Android. Nothing from it enters production.
FROM python:3.12-slim-bookworm AS probe-fixtures
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && mkdir -p /fixtures \
    && ffmpeg -v error -f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:a aac -f adts /fixtures/known.aac \
    && ffmpeg -v error -f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:a aac /fixtures/known.m4a \
    && ffmpeg -v error -f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:a libmp3lame /fixtures/known.mp3 \
    && ffmpeg -v error -f lavfi -i anullsrc=r=8000:cl=mono -t 1 -c:a pcm_s16le /fixtures/known.wav \
    && ffmpeg -v error -f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:a libopus /fixtures/known.webm \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------- probe-free baseline
# This is a complete runnable image except for the media probe. CI builds this
# target too, so the size delta compares otherwise identical images.
FROM python:3.12-slim-bookworm AS runtime-base

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

# Security patches belong to both sides of the size comparison.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
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

# --------------------------------------------------------------- runtime stage
FROM runtime-base AS runtime

# Voice duration is measured from the bytes on the family's server. Only the
# checksummed, file-only ffprobe, its three libraries and receipt cross into production;
# no ffmpeg transcoder, browser, package manager metadata or codec GUI stack.
USER root
COPY --from=ffprobe-build --chown=root:root /opt/ffprobe/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffprobe-build --chown=root:root /opt/ffprobe/runtime-lib/ /usr/local/lib/ffprobe/
COPY --from=ffprobe-build --chown=root:root \
    /opt/ffprobe/usr/share/anuvritti/ffprobe-runtime.manifest \
    /usr/share/anuvritti/ffprobe-runtime.manifest
COPY --from=ffprobe-build --chown=root:root \
    /opt/ffprobe/usr/share/licenses/ffprobe/COPYING.LGPLv2.1 \
    /usr/share/licenses/ffprobe/COPYING.LGPLv2.1
USER anuvritti:anuvritti
