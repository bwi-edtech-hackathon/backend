FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps. README.md is referenced by pyproject.toml's `readme` field
# so it must be present at build time even though it's just metadata.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && \
    pip install -e .

# Copy app
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
