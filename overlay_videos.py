# VSYSTO Dual-Camera GPS Processor - Overlay the smaller of two videos over the larger one.
# Copyright (C) 2026  Alberto B. Acckerstein
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import subprocess
import argparse
import sys
from pathlib import Path

def get_resolution(video_path: Path):
    """Returns (width, height) of the video using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error', 
        '-select_streams', 'v:0', 
        '-show_entries', 'stream=width,height', 
        '-of', 'csv=s=x:p=0', 
        str(video_path)
    ]
    try:
        output = subprocess.check_output(cmd).decode().strip().split('x')
        return int(output[0]), int(output[1])
    except Exception as e:
        print(f"Error reading {video_path}: {e}")
        return 0, 0

def overlay_videos(vid_a: Path, vid_b: Path, output: str, margin: int = 10):
    """Overlays the smaller video onto the larger one in the top-left."""
    
    # 1. Determine which is larger
    w_a, h_a = get_resolution(vid_a)
    w_b, h_b = get_resolution(vid_b)
    
    area_a = w_a * h_a
    area_b = w_b * h_b
    
    if area_a >= area_b:
        background, overlay = vid_a, vid_b
    else:
        background, overlay = vid_b, vid_a
    
    print(f"Background: {background} ({w_a if area_a >= area_b else w_b}x{h_a if area_a >= area_b else h_b})")
    print(f"Overlay:    {overlay} ({w_b if area_a >= area_b else w_a}x{h_b if area_a >= area_b else h_a})")

    # 2. Build FFmpeg command
    # [1:v]colorkey=0x00FF00:0.1:0.1: removes pure green
    # format=yuva420p: ensures transparency is handled before overlay
    cmd = [
        'ffmpeg', '-y',
        '-i', str(background),
        '-i', str(overlay),
        '-filter_complex', f'[1:v]colorkey=0x00FF00:0.1:0.1[ckout];[0:v][ckout]overlay={margin}:{margin}',
        '-map', '0:a?',        # Try to map audio from background if it exists
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '22',
        '-c:a', 'aac',
        '-shortest',
        output
    ]
    
    print("Starting overlay process...")
    try:
        subprocess.run(cmd, check=True)
        print(f"\nSuccess! Video saved to: {output}")
    except subprocess.CalledProcessError as e:
        print(f"\nError: FFmpeg failed with exit code {e.returncode}")

def main():
    parser = argparse.ArgumentParser(
        description="Overlay the smaller of two videos over the larger one in the top-left corner."
    )
    parser.add_argument("video1", type=Path, help="First video file.")
    parser.add_argument("video2", type=Path, help="Second video file.")
    parser.add_argument("--output", default="overlay_result.mp4", help="Output file name.")
    parser.add_argument("--margin", type=int, default=15, help="Margin from the top-left corner (default 15px).")
    
    args = parser.parse_args()
    
    if not args.video1.exists() or not args.video2.exists():
        print("Error: One or both input files do not exist.")
        sys.exit(1)
        
    overlay_videos(args.video1, args.video2, args.output, args.margin)

if __name__ == "__main__":
    main()
