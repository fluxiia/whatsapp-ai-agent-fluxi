# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libmagic1 \
    libmagic-dev \
    file \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Upgrade pip to fix CVE-2025-8869 and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip>=25.3 && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories with proper permissions
RUN mkdir -p uploads/rags sessoes rags && \
    chmod -R 755 uploads sessoes rags

# Create database directory and set permissions
RUN mkdir -p /app/data && \
    chmod 755 /app/data

# Expose port (default 8000, can be overridden)
EXPOSE 8000

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:///./data/fluxi.db

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "main.py"]
