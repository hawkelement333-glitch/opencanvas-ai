FROM python:3.13-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY apps/api/pyproject.toml ./
COPY apps/api/opencanvas_api ./opencanvas_api
RUN pip wheel --wheel-dir /wheels .

FROM python:3.13-slim AS runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system opencanvas && adduser --system --ingroup opencanvas opencanvas
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY LICENSE COPYRIGHT NOTICE THIRD_PARTY_NOTICES.md ./
RUN mkdir -p /app/data/documents && chown -R opencanvas:opencanvas /app/data
USER opencanvas
EXPOSE 8000
CMD ["uvicorn", "opencanvas_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
