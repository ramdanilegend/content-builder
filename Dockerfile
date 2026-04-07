FROM python:3.11-slim

# Install FFmpeg and system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY main.py .
COPY renderer/ ./renderer/

# Output directory (mount this volume for access to generated videos)
RUN mkdir -p output

# Assets are expected to be mounted or copied at runtime
# Usage: docker run -v $(pwd)/assets:/app/assets -v $(pwd)/output:/app/output ...

CMD ["python", "main.py", "blueprint.json"]
