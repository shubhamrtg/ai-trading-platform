# ---- Builder stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ---- Runtime stage ----
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r trading && useradd -r -g trading -d /app -s /sbin/nologin trading

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY backend/ .

# Switch to non-root user
USER trading

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
