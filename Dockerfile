# Use a small Python base image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create a non-root user.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

# Install the pinned requirements.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the code.
COPY settleup_mcp ./settleup_mcp

# Run as the non-root user.
USER appuser

# Open the server port.
EXPOSE 8000

# Start the MCP server.
CMD ["python", "-m", "settleup_mcp.server"]
