FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies + the app package. Copy metadata + source first so the
# build is reproducible. (psycopg[binary] ships its own libpq, so no apt needed.)
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

# Default command runs the WEB service (producer + webhook).
# The WORKER service overrides this with: python -m app.worker
# $PORT is provided by the platform (Railway/Render); falls back to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
