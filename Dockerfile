# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Bind to all interfaces *inside the container* so `docker run -p` works.
# (Native runs default to 127.0.0.1; the container is the isolation boundary.)
ENV OBSCURA_HOST=0.0.0.0

# Install system dependencies
# 1. Tor for dark web access
# 2. Firefox and Geckodriver for Selenium deep-crawling
# 3. curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    tor \
    firefox-esr \
    wget \
    curl \
    ca-certificates \
    && wget -q https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz \
    && tar -xzf geckodriver-v0.34.0-linux64.tar.gz -C /usr/local/bin \
    && rm geckodriver-v0.34.0-linux64.tar.gz \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Ensure entrypoint is executable
RUN chmod +x entrypoint.sh

# Expose the Flask port
EXPOSE 8501

# Run the entrypoint script
ENTRYPOINT ["./entrypoint.sh"]
