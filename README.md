# Dual-Camera Video Processor with GPS Overlay

This tool is designed for **VSYSTO dashcam systems** (and similar dual-camera setups) that record front and rear views simultaneously into `.MOV` files with embedded GPS metadata.

It automatically pairs front/rear files, generates a synchronized map animation for each segment, and creates two final videos:
1.  **Front-centric**: Front camera as background, Rear as Picture-in-Picture (PiP).
2.  **Rear-centric**: Rear camera as background, Front as Picture-in-Picture (PiP).

Both versions include a synchronized map overlay in your choice of corners.

## Prerequisites

### System Dependencies
- **Linux** (Tested on Ubuntu/Debian/Fedora)
- **FFmpeg**: For video processing and overlays.
- **ExifTool**: For extracting embedded GPS metadata from the video files.
- **Python 3.8+**

#### Installation (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install ffmpeg exiftool python3 python3-pip
```

### Python Modules
Install the required libraries via pip:
```bash
pip install numpy matplotlib requests scipy pillow
```

## Installation

1. Copy all `.py` files to your working directory.
2. Ensure you have the `tiles_cache` directory or allow the script to create it (requires internet to download map tiles initially).

## Usage

Place your VSYSTO `F.MOV` and `R.MOV` files in a folder and run:

```bash
python3 process_dual_camera_videos.py *F.MOV *R.MOV --output my_trip.mp4
```

### Options
- `--pip_pos {tl,tr,bl,br}`: Position of the small camera overlay (Default: `tl`).
- `--map_pos {tl,tr,bl,br}`: Position of the map animation (Default: `tr`).
- `--margin MARGIN`: Distance from the edges in pixels (Default: `20`).
- `--temp_dir DIR`: Where to store intermediate segments.

## VSYSTO Specifics
VSYSTO cameras typically store files in `DCIM/F` (Front) and `DCIM/R` (Rear). This script expects the filenames to be identical except for the `F` or `R` suffix before the extension (e.g., `250602-070001F.MOV` and `250602-070001R.MOV`).

## Running with Docker

For non-Linux users or for a clean environment, use the provided `Dockerfile`.

### Build
```bash
docker build -t vsysto-processor .
```

### Run
```bash
docker run --rm -v $(pwd):/data vsysto-processor /data/*F.MOV /data/*R.MOV --output /data/final_trip.mp4
```

## Troubleshooting
- **Memory Errors**: If processing many files, ensure you are not using a RAM disk for the temporary directory. Use `--temp_dir ./tmp` to force storage on a physical disk.
- **No Map**: If no GPS data is found in a segment, the map for that segment will be automatically skipped without crashing the rest of the process.
