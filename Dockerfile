# Stage 1: change the lock file into a plain requirements list.
FROM python:3.13-slim AS requirements

RUN pip install --no-cache-dir pipenv==2026.0.3
WORKDIR /tmp
COPY Pipfile Pipfile.lock ./
# pipenv verify stops the build if the Pipfile and the lock file do not agree.
RUN pipenv verify && pipenv requirements > requirements.txt

# Stage 2: build the server image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create a non-root user.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

# Install the locked requirements.
COPY --from=requirements /tmp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the code.
COPY settleup_mcp ./settleup_mcp

# Run as the non-root user.
USER appuser

# Open the server port.
EXPOSE 8000

# Start the MCP server.
CMD ["python", "-m", "settleup_mcp.server"]
