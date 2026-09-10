FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN apt-get update && apt-get install -y --no-install-recommends wireguard-tools iproute2 && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

RUN addgroup --system g-one \
    && adduser --system --ingroup g-one --home /app g-one \
    && mkdir -p /var/lib/g-one \
    && chown g-one:g-one /var/lib/g-one

USER g-one

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"

CMD ["uvicorn", "g_one.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
