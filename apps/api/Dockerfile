ARG PYTHON_IMAGE=python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ARG SOURCE_DATE_EPOCH=0

FROM ${PYTHON_IMAGE} AS patched-base
# The pinned upstream base predates Debian DSA-6613-1 (both zlib CVEs).
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade \
        zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

FROM patched-base AS builder
ARG SOURCE_DATE_EPOCH
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
WORKDIR /build
COPY apps/api/build-requirements.lock apps/api/requirements.lock ./
RUN python -m pip install --require-hashes -r build-requirements.lock \
    && python -m pip download \
        --require-hashes \
        --only-binary=:all: \
        --dest /wheels \
        -r requirements.lock
COPY apps/api/pyproject.toml ./
COPY apps/api/opencanvas_api ./opencanvas_api
RUN python -m pip wheel \
    --no-build-isolation \
    --no-deps \
    --wheel-dir /wheels \
    .

FROM patched-base AS runner
ARG SOURCE_DATE_EPOCH
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system opencanvas && adduser --system --ingroup opencanvas opencanvas
COPY --from=builder /wheels /wheels
# Runtime jobs use preinstalled modules; remove the installer and its bootstrap archive.
RUN python -m pip install \
        --no-index \
        --no-compile \
        --find-links=/wheels \
        opencanvas-api==0.1.0 \
    && python -m pip check \
    && python -m pip uninstall --yes pip \
    && rm -rf /wheels /usr/local/lib/python3.13/ensurepip \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && python -c "import importlib.util; assert all(importlib.util.find_spec(name) is None for name in ('pip', 'ensurepip'))"
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/scripts ./scripts
COPY LICENSE COPYRIGHT NOTICE THIRD_PARTY_NOTICES.md ./
RUN mkdir -p /app/data/documents && chown -R opencanvas:opencanvas /app/data
USER opencanvas
EXPOSE 8000
CMD ["uvicorn", "opencanvas_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
