# VSYSTO Dual-Camera GPS Processor - Extract GPS track from video files.
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
import json
import logging
import shutil
import argparse
from pathlib import Path
from typing import Any, Dict, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class ExifToolError(Exception):
    """Custom exception for ExifTool related errors."""
    pass

def extract_gps_track(video_path: Path) -> List[Dict[str, Any]]:
    """
    Extracts all embedded GPS data points from a video file using ExifTool.
    Uses the -ee (Extract Embedded) flag to get timed metadata.

    Args:
        video_path (Path): The path to the video file.

    Returns:
        List[dict]: A list of GPS data points with coordinates and timing.
    """
    if not shutil.which('exiftool'):
        raise ExifToolError("exiftool not found in PATH.")

    if not video_path.is_file():
        raise FileNotFoundError(f"File not found: {video_path}")

    # -ee: Extract embedded metadata (timed metadata tracks)
    # -c "%.6f": Format coordinates as decimal degrees
    # -json: Output as JSON
    # -G3: Group tags by document number (useful for identifying samples)
    command = [
        'exiftool', 
        '-ee', 
        '-G3',
        '-c', '%.6f', 
        '-json', 
        str(video_path)
    ]
    
    try:
        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            check=True, 
            timeout=60  # GPS extraction can take longer for large videos
        )
        
        metadata_list = json.loads(result.stdout)
        gps_track = []

        if not metadata_list:
            return []

        # Some formats return a single object with "DocN:Tag" keys
        # Others return a list of objects. We handle both.
        
        all_data = {}
        if isinstance(metadata_list, list):
            # Merge or iterate. Often with -ee it's a list where the first item 
            # has the bulk of DocN: keys if they are flattened.
            for obj in metadata_list:
                all_data.update(obj)
        else:
            all_data = metadata_list

        # 1. Check for individual objects in the list (standard behavior for some formats)
        if isinstance(metadata_list, list) and len(metadata_list) > 1:
            for entry in metadata_list:
                if 'GPSLatitude' in entry and 'GPSLongitude' in entry:
                    gps_track.append(parse_entry(entry))
            
            if gps_track:
                return gps_track

        # 2. Check for flattened DocN: keys in all_data
        # We'll group keys by their Doc index
        docs = {}
        for key, value in all_data.items():
            if ':' in key:
                prefix, tag = key.split(':', 1)
                if prefix.startswith('Doc'):
                    doc_id = prefix
                    if doc_id not in docs:
                        docs[doc_id] = {}
                    docs[doc_id][tag] = value
            elif key.startswith('GPS'):
                # Handle cases where some GPS tags might not have Doc prefix but are relevant
                # (usually the first point or global metadata)
                pass

        # Sort docs by their numerical ID (Doc1, Doc2, ...)
        sorted_doc_ids = sorted(docs.keys(), key=lambda x: int(x[3:]) if x[3:].isdigit() else 0)
        
        for doc_id in sorted_doc_ids:
            entry = docs[doc_id]
            if 'GPSLatitude' in entry and 'GPSLongitude' in entry:
                point = parse_entry(entry)
                # Simple downsampling: only keep if time has changed or it's the first point
                if not gps_track or point['timestamp'] != gps_track[-1]['timestamp']:
                    gps_track.append(point)

        return gps_track

    except subprocess.CalledProcessError as e:
        logger.error(f"ExifTool failed: {e.stderr}")
        raise ExifToolError(e.stderr) from e
    except Exception as e:
        logger.error(f"Error during GPS extraction: {e}")
        return []

def parse_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Parses a single metadata entry into a GPS point."""
    point = {
        'timestamp': entry.get('GPSDateTime') or entry.get('SampleTime'),
        'latitude': parse_coord(entry.get('GPSLatitude')),
        'longitude': parse_coord(entry.get('GPSLongitude')),
        'altitude': entry.get('GPSAltitude'),
        'speed': entry.get('GPSSpeed'),
        'track': entry.get('GPSTrack'),
    }
    return point

def parse_coord(val: Any) -> float:
    """Helper to convert exiftool decimal strings like '30.638094 N' to float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    
    # Remove N/S/E/W and handle sign
    clean_val = str(val).split(' ')[0]
    try:
        f_val = float(clean_val)
        if 'S' in str(val) or 'W' in str(val):
            f_val = -f_val
        return f_val
    except ValueError:
        return 0.0

def main():
    parser = argparse.ArgumentParser(
        description="Extract GPS track from video files (frame-by-frame timed metadata)."
    )
    parser.add_argument("input", type=Path, help="Path to the video file.")
    parser.add_argument(
        "--output", 
        type=Path, 
        help="Path to save the GPS track as JSON."
    )
    
    args = parser.parse_args()

    try:
        gps_points = extract_gps_track(args.input)
        
        if not gps_points:
            logger.warning(f"No GPS track found in {args.input}. Ensure the video was recorded with GPS enabled.")
            return

        logger.info(f"Extracted {len(gps_points)} GPS points.")

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(gps_points, f, indent=4)
            logger.info(f"GPS track saved to {args.output}")
        else:
            # Print first 5 and last 1 as a sample
            print(json.dumps(gps_points[:5], indent=4))
            if len(gps_points) > 5:
                print("...")
                print(json.dumps(gps_points[-1], indent=4))

    except Exception as e:
        logger.error(f"Operation failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
