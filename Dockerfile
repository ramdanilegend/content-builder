FROM python:3.11-slim

# Install FFmpeg, system dependencies, and a comprehensive font library
# for professional video rendering (covers 30+ font families)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    # ── Sans-serif / Modern ───────────────────────────────────────
    fonts-open-sans \
    fonts-roboto-hinted \
    fonts-lato \
    fonts-ubuntu \
    fonts-cantarell \
    fonts-noto \
    # ── Serif / Editorial ─────────────────────────────────────────
    fonts-freefont-ttf \
    fonts-ebgaramond \
    fonts-vollkorn \
    fonts-linux-libertine \
    # ── Condensed / Narrow ────────────────────────────────────────
    fonts-croscore \
    fonts-crosextra-caladea \
    fonts-crosextra-carlito \
    # ── Monospace / Techy ─────────────────────────────────────────
    fonts-inconsolata \
    fonts-hack \
    # ── Decorative / Special ──────────────────────────────────────
    fonts-jura \
    fonts-mplus \
    fonts-urw-base35 \
    && fc-cache -fv \
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
