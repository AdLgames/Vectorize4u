# The API image.
#
# At the repository root, with this exact name, because that is where
# `fly launch` and every other build-detection tool looks. The worker's
# image is infra/Dockerfile.worker — it needs *all three* tracers, and it
# is never the image a detector should pick by default.
#
# This one needs resvg, and only resvg. §7.4 renders preview tiles
# server-side, because an SVG in the DOM *is* the download: the watermark
# is composited onto a raster, and the vector never leaves the server
# until the job is unlocked. That rasteriser is the resvg binary, reached
# through engine.raster.render_svg, so without it every preview answers
# 500 while conversion itself looks perfectly healthy.
#
# It has to be the same resvg the worker scores with, at the same pin: a
# score measured with one rasteriser describes an image nobody is shown
# if the tiles come from another.
#
#   docker build -t vectorize-api .

ARG RESVG_VERSION=0.48.1

FROM rust:1.85-slim-bookworm AS tracers
ARG RESVG_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN cargo install resvg --version "${RESVG_VERSION}" --locked --root /out


FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libgl/libglib are OpenCV's runtime; cairo is cairosvg's (PDF output).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 \
      libglib2.0-0 \
      libcairo2 \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=tracers /out/bin/resvg /usr/local/bin/resvg

WORKDIR /srv

COPY packages/engine /srv/packages/engine
COPY apps/api /srv/apps/api

RUN pip install --no-cache-dir "/srv/packages/engine[emit]" && \
    pip install --no-cache-dir /srv/apps/api

# Fail the build, not the first preview anyone asks for.
RUN resvg --help > /dev/null

# Nothing here runs as root: a tracer bug should not be a root bug, and the
# API writes nothing to its own filesystem that matters.
RUN useradd --system --uid 10001 --home /srv vectorize && chown -R vectorize /srv
USER vectorize

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

WORKDIR /srv/apps/api

# One worker process per CPU is wrong here: this process is I/O bound and
# the CPU belongs to the tracer pool. Two workers, and scale by adding
# machines rather than by adding processes to one.
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
