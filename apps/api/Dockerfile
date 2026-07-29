ARG PYTHON_IMAGE=python:3.13.14-slim-trixie@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91
ARG SOURCE_DATE_EPOCH=0

FROM ${PYTHON_IMAGE} AS builder
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

FROM ${PYTHON_IMAGE} AS runner
ARG SOURCE_DATE_EPOCH
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system opencanvas && adduser --system --ingroup opencanvas opencanvas
COPY --from=builder /wheels /wheels
RUN python -m pip install \
        --no-index \
        --no-compile \
        --find-links=/wheels \
        opencanvas-api==0.1.0 \
    && rm -rf /wheels
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/scripts ./scripts
COPY LICENSE COPYRIGHT NOTICE THIRD_PARTY_NOTICES.md ./
RUN mkdir -p /app/data/documents && chown -R opencanvas:opencanvas /app/data
USER opencanvas
EXPOSE 8000
CMD ["uvicorn", "opencanvas_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
