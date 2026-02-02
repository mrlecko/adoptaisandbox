# CSV Analyst Chat - Runner Dockerfile
#
# Security-hardened container for executing SQL queries against CSV datasets.
#
# Security features:
# - Non-root user (UID 1000)
# - Read-only root filesystem (use /tmp for working directory)
# - Minimal attack surface (no unnecessary packages)
# - No network access (enforced by --network none at runtime)

FROM python:3.13-slim

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash runner

# Create directories
RUN mkdir -p /app /data /tmp/duckdb && \
    chown -R runner:runner /app /tmp/duckdb

# Copy runner script
COPY runner.py /app/runner.py
RUN chmod +x /app/runner.py && \
    chown runner:runner /app/runner.py

# Switch to non-root user
USER runner

# Set working directory
WORKDIR /app

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    DUCKDB_TEMP_DIRECTORY=/tmp/duckdb

# Run the runner script
# Expects JSON on stdin, outputs JSON to stdout
ENTRYPOINT ["python3", "/app/runner.py"]
