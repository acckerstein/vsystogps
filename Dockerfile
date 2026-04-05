# Use a slim Python base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    exiftool \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir \
    numpy \
    matplotlib \
    requests \
    scipy \
    pillow

# Copy the application scripts
COPY *.py /app/

# Set the script as the entrypoint
ENTRYPOINT ["python3", "/app/process_dual_camera_videos.py"]

# Default command if no arguments are provided
CMD ["--help"]
