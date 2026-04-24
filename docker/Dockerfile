# =============================================================================
# ComfyUI Server Dockerfile
# Python 3.10 + FastAPI + MySQL 8.0
# =============================================================================

FROM m.daocloud.io/docker.io/library/python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    comfyui_env=prod \
    # Set default database config (can be overridden by env vars)
    DB_HOST=mysql \
    DB_PORT=3306 \
    DB_USER=root \
    DB_PASSWORD=3bTgThWP2xeX \
    DB_NAME=zjt

# Set working directory
WORKDIR /app

# Install system dependencies
# 兼容不同版本 Debian 的源文件路径
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY requirements.txt pyproject.toml ./
COPY api/ ./api/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY config/ ./config/
COPY llm/ ./llm/
COPY model/ ./model/
COPY perseids_server/ ./perseids_server/
COPY script_writer_core/ ./script_writer_core/
COPY scripts/ ./scripts/
COPY task/ ./task/
COPY templates/ ./templates/
COPY tests/ ./tests/
COPY utils/ ./utils/
COPY web/ ./web/
COPY server.py ./
COPY config.example.yml ./

# Copy entrypoint script and fix line endings for Windows compatibility
COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

# Configure pip to use Aliyun mirror for faster downloads in China
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/upload/cache /app/dist

# Expose the application port
EXPOSE 9003

# Set the entrypoint
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default command - start the production server
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9003", "--timeout-keep-alive", "600"]
