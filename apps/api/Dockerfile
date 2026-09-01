FROM ghcr.io/astral-sh/uv@sha256:ee13d7fcccc31de713bf90b3474ae8682adf7f0dd5b6697c687e86b3fc8d11e6

WORKDIR /app
RUN apk add --upgrade --no-cache libcrypto3=3.5.8-r0 libssl3=3.5.8-r0 sqlite-libs=3.53.4-r0
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && uv pip uninstall --system setuptools wheel pip
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN adduser -D -u 10001 cifra && chown -R cifra /app/app
USER cifra
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
