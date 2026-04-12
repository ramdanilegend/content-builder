# Blueprint Video Generator

A Python tool that generates videos from JSON blueprint configurations. Perfect for programmatic video creation with text-to-speech, images, and dynamic scene composition.

## Requirements

- Python 3.11+ **or** Docker
- FFmpeg (required by moviepy — included automatically in Docker)

## Installation

1. **Clone or navigate to the project directory:**

   ```bash
   cd content-builder
   ```

2. **Create a virtual environment (recommended):**

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

   **Note:** You may also need FFmpeg installed on your system:
   - **macOS:** `brew install ffmpeg`
   - **Ubuntu/Debian:** `sudo apt-get install ffmpeg`
   - **Windows:** Download from https://ffmpeg.org/download.html

## Usage

### Basic Usage

```bash
python main.py blueprint.json
```

The script will:

1. Load the blueprint configuration from `blueprint.json`
2. Process all scenes (text, images, transitions, etc.)
3. Generate text-to-speech audio via Edge TTS
4. Render the video
5. Save output as `output/<title>.mp4`

### Custom Blueprint Path

```bash
python main.py /path/to/your/blueprint.json
```

### Blueprint Format

Your JSON blueprint file should include:

```json
{
  "meta": {
    "title": "My Video",
    "resolution": "1080x1920",
    "fps": 30
  },
  "scenes": [
    {
      "type": "text",
      "text": "Hello World",
      "duration": 3
    }
  ]
}
```

## Docker

The easiest way to run without installing Python or FFmpeg locally.

### Build the image

```bash
docker build -t content-builder .
```

### Run with your blueprint and assets

```bash
docker run --rm \
  -v $(pwd)/blueprint.json:/app/blueprint.json \
  -v $(pwd)/assets:/app/assets \
  -v $(pwd)/output:/app/output \
  content-builder
```

### Run with a custom blueprint path

```bash
docker run --rm \
  -v $(pwd)/assets:/app/assets \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/my_blueprint.json:/app/my_blueprint.json \
  content-builder python main.py my_blueprint.json
```

### ready to run example

docker build -t content-builder .
docker run --rm \
 -v $(pwd)/blueprint.ready.json:/app/blueprint.ready.json \
 -v $(pwd)/assets:/app/assets \
 -v $(pwd)/output:/app/output \
 content-builder python main.py blueprint.ready.json

The generated `.mp4` will appear in your local `output/` folder.

## Output

Generated videos are saved to the `output/` directory with the blueprint title as filename:

- `output/My_Video.mp4`

## Project Structure

```
.
├── main.py              # Entry point
├── blueprint.json       # Example configuration file
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker build definition
├── .dockerignore        # Files excluded from Docker build
├── renderer/            # Video rendering logic
├── assets/              # Static assets (images, videos, audio)
├── output/              # Generated video files (git-ignored)
└── README.md            # This file
```

## Troubleshooting

### FFmpeg Not Found

If you get an error about FFmpeg, install it:

- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt-get install ffmpeg`
- **Windows:** Download from https://ffmpeg.org/download.html

### Memory Issues with Large Videos

Increase available memory or reduce video resolution/duration in your blueprint.

### TTS Errors

The project uses Edge TTS (free, no API key required). Check your internet connection if TTS fails.

## License

[Add your license information here]

## Running Backend

uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Docker (recommended) → just rebuild: docker build -t content-builder . — the updated Dockerfile installs all font packages automatically via apt-get
Local dev (no Docker) → run sudo python setup_fonts.py --install inside the content-builder folder
