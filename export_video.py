# VSYSTO Dual-Camera GPS Processor - Export GPS track synced with original video speed.
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

import json
import math
import requests
import argparse
import subprocess
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from pathlib import Path
from PIL import Image
from scipy.interpolate import interp1d

# --- Video Metadata Extraction ---

def get_video_info(video_path: Path):
    """Returns (duration_seconds, fps) of the video."""
    cmd = [
        'ffprobe', '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-show_entries', 'stream=r_frame_rate', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        str(video_path)
    ]
    output = subprocess.check_output(cmd).decode().split()
    
    # ffprobe returns fps as a fraction "25000/1001" or "30/1"
    fps_frac = output[0].split('/')
    fps = float(fps_frac[0]) / float(fps_frac[1]) if len(fps_frac) > 1 else float(fps_frac[0])
    duration = float(output[2])
    
    return duration, fps

# --- Mapping Utilities ---

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile

def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg

def get_map_background(lats, lons, zoom=14):
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    
    # Calculate center and span
    lat_center = (max_lat + min_lat) / 2
    lon_center = (max_lon + min_lon) / 2
    lat_span = (max_lat - min_lat)
    lon_span = (max_lon - min_lon)
    
    # Force a square span based on the larger dimension
    # Convert degrees to roughly equivalent distances (simplified)
    # At latitude L, 1 deg lon is approx cos(L) * 111km. 1 deg lat is approx 111km.
    cos_lat = math.cos(math.radians(lat_center))
    lon_span_norm = lon_span * cos_lat
    
    max_span = max(lat_span, lon_span_norm) * 1.3 # Add 30% padding
    
    half_span_lat = max_span / 2
    half_span_lon = (max_span / cos_lat) / 2
    
    x0, y0 = deg2num(lat_center + half_span_lat, lon_center - half_span_lon, zoom)
    x1, y1 = deg2num(lat_center - half_span_lat, lon_center + half_span_lon, zoom)
    
    # --- Memory Optimization: Cap Tile Count ---
    num_x, num_y = x1 - x0 + 1, y1 - y0 + 1
    if (num_x > 8 or num_y > 8) and zoom > 1:
        print(f"Warning: Trip area too large ({num_x}x{num_y} tiles). Reducing zoom to {zoom-1}.")
        return get_map_background(lats, lons, zoom - 1)
    
    cache_dir = Path("tiles_cache")
    cache_dir.mkdir(exist_ok=True)
    
    # Create image with Pure Green background for Chroma Keying
    num_x, num_y = x1 - x0 + 1, y1 - y0 + 1
    # Pure Green (0, 255, 0, 255)
    full_img = Image.new('RGBA', (num_x * 256, num_y * 256), (0, 255, 0, 255))
    
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            cache_path = cache_dir / f"{zoom}_{x}_{y}.png"
            if not cache_path.exists():
                url = f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
                headers = {'User-Agent': 'Mozilla/5.0 (GPSAnimationBot/1.0)'}
                r = requests.get(url, headers=headers)
                if r.status_code == 200:
                    with open(cache_path, 'wb') as f:
                        f.write(r.content)
            
            if cache_path.exists():
                tile = Image.open(cache_path).convert("RGBA")
                full_img.paste(tile, ((x - x0) * 256, (y - y0) * 256))
    
    north, west = num2deg(x0, y0, zoom)
    south, east = num2deg(x1 + 1, y1 + 1, zoom)
    return full_img, (west, east, south, north)

# --- Main Export Logic ---

def export_synced_mp4(json_path: Path, source_video: Path, output_path: str):
    print(f"Analyzing source video: {source_video}")
    duration, target_fps = get_video_info(source_video)
    total_frames = int(duration * target_fps)
    
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    # --- Memory & Accuracy Optimization: Filter Outliers ---
    # 1. Remove (0,0) or obviously invalid points
    # 2. Remove points that are far from the median (prevents "jumps" to default coords)
    filtered_data = []
    for p in data:
        lat, lon = p['latitude'], p['longitude']
        if abs(lat) < 0.01 and abs(lon) < 0.01: # Skip near 0,0
            continue
        filtered_data.append(p)
    
    if not filtered_data:
        print("Error: No valid GPS points left after filtering.")
        return

    # Use median-based filtering to remove extreme jumps
    all_lats = np.array([p['latitude'] for p in filtered_data])
    all_lons = np.array([p['longitude'] for p in filtered_data])
    med_lat, med_lon = np.median(all_lats), np.median(all_lons)
    
    # Keep only points within ~1 degree of the median (approx 111km)
    # This is a safe threshold for a single video segment.
    final_data = []
    for p in filtered_data:
        if abs(p['latitude'] - med_lat) < 1.0 and abs(p['longitude'] - med_lon) < 1.0:
            final_data.append(p)
    
    if not final_data:
        final_data = filtered_data # Fallback if everything was "far"
        
    data = final_data
    lats = [p['latitude'] for p in data]
    lons = [p['longitude'] for p in data]
    
    # Interpolation
    x_old = np.linspace(0, duration, len(data), dtype=np.float32)
    x_new = np.linspace(0, duration, total_frames, dtype=np.float32)
    lat_interp = interp1d(x_old, lats, kind='linear')(x_new).astype(np.float32)
    lon_interp = interp1d(x_old, lons, kind='linear')(x_new).astype(np.float32)
    
    print("Fetching map background...")
    img, extent = get_map_background(lats, lons)
    
    # Set up figure with Green Screen background
    fig, ax = plt.subplots(figsize=(2.7, 2.7), dpi=100)
    fig.patch.set_facecolor('#00FF00')
    
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    
    # Map overlay
    ax.imshow(img, extent=extent, interpolation='bilinear')
    ax.patch.set_facecolor('#00FF00')
    
    # Background "Full Path"
    ax.plot(lons, lats, color='silver', alpha=0.8, linewidth=2, zorder=1)
    
    line, = ax.plot([], [], color='midnightblue', linewidth=4, zorder=2)
    point, = ax.plot([], [], 'ro', markersize=6, zorder=3)
    
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.axis('off')

    def init():
        line.set_data([], [])
        point.set_data([], [])
        return line, point

    def update(frame):
        # Memory Optimization: Limit the "tail" length of the line to prevent
        # matplotlib from slowing down or crashing on very long tracks.
        # Showing the last 500 points is usually enough for a good effect.
        start_idx = max(0, frame - 500)
        line.set_data(lon_interp[start_idx:frame+1], lat_interp[start_idx:frame+1])
        point.set_data([lon_interp[frame]], [lat_interp[frame]])
        return line, point

    print(f"Generating synced video ({total_frames} frames)...")
    ani = animation.FuncAnimation(
        fig, update, frames=total_frames, 
        init_func=init, blit=True
    )

    Writer = animation.writers['ffmpeg']
    writer = Writer(fps=target_fps, bitrate=1000) # Lower bitrate for map
    
    ani.save(output_path, writer=writer)
    
    # Explicitly clear and close figure to free memory
    plt.clf()
    plt.cla()
    plt.close(fig)
    print(f"Synced video saved to: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Export GPS track synced with original video speed.")
    parser.add_argument("input", type=Path, help="Path to track.json")
    parser.add_argument("--source", type=Path, required=True, help="Path to original video (to match duration)")
    parser.add_argument("--output", default="synced_animation.mp4", help="Output video file name")
    args = parser.parse_args()
    
    try:
        import scipy  # Verify scipy is installed for interp1d
        export_synced_mp4(args.input, args.source, args.output)
    except ImportError:
        print("\nError: Missing 'scipy' for smooth interpolation.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
