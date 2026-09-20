# The API image.
#
# At the repository root, with this exact name, because that is where
# `fly launch` and every other build-detection tool looks. The worker's
# image is infra/Dockerfile.worker — it needs the tracer binaries and this
# one does not, and it is never the image a detector should pick by
# default.
#
#   docker build -t vectorize-api .

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

WORKDIR /srv

COPY packages/engine /srv/packages/engine
COPY apps/api /srv/apps/api

RUN pip install --no-cache-dir "/srv/packages/engine[emit]" && \
    pip install --no-cache-dir /srv/apps/api

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
