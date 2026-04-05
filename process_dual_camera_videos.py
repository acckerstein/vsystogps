# VSYSTO Dual-Camera GPS Processor - Process dual-camera videos with PiP and Map overlays.
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
import argparse
import os
import sys
import re
from pathlib import Path

def run_command(cmd, description):
    print(f"--- {description} ---")
    print(f"Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during {description}: {e}")
        sys.exit(1)

def get_pairs(video_list):
    """
    Groups files into (Front, Rear) pairs based on naming: *F.ext and *R.ext.
    Expected format: 01F.MOV and 01R.MOV
    """
    fronts = {}
    rears = {}
    
    # regex to match base name and the F/R suffix
    pattern = re.compile(r"^(.*)([FR])\.[^.]+$", re.IGNORECASE)
    
    for v in video_list:
        match = pattern.match(v.name)
        if match:
            base, side = match.groups()
            if side.upper() == 'F':
                fronts[base] = v
            else:
                rears[base] = v
    
    pairs = []
    bases = sorted(list(set(fronts.keys()) | set(rears.keys())))
    
    for b in bases:
        if b in fronts and b in rears:
            pairs.append((fronts[b], rears[b], b))
        else:
            missing = "Rear" if b in fronts else "Front"
            print(f"Warning: Missing {missing} camera for base '{b}'. Skipping pair.")
            
    return pairs

def main():
    parser = argparse.ArgumentParser(description="Process dual-camera videos (Front/Rear) with PiP and Map.")
    parser.add_argument("videos", nargs="*", type=Path, help="List of video files (F and R versions).")
    parser.add_argument("--file", type=Path, help="Text file containing a list of video paths.")
    parser.add_argument("--output", default="final_trip.mp4", help="Base output filename (will generate _F and _R versions).")
    parser.add_argument("--temp_dir", default="temp_dual_processing", help="Directory for intermediate files.")
    parser.add_argument("--margin", type=int, default=20, help="Margin for overlays (default 20px).")
    parser.add_argument("--pip_pos", default="tl", choices=['tl', 'tr', 'bl', 'br'], help="Position of the PiP video overlay.")
    parser.add_argument("--map_pos", default="tr", choices=['tl', 'tr', 'bl', 'br'], help="Position of the Map overlay.")
    parser.add_argument("--keep_temp", action="store_true", help="Keep temporary segment files after finishing.")
    
    args = parser.parse_args()
    script_dir = Path(__file__).parent.absolute()
    sys.path.append(str(script_dir))

    # 1. Consolidate and Group Videos
    input_list = args.videos
    if args.file and args.file.exists():
        with open(args.file, 'r') as f:
            input_list.extend([Path(line.strip()) for line in f if line.strip()])
    
    input_list = [v for v in input_list if v.exists()]
    pairs = get_pairs(input_list)

    if not pairs:
        print("Error: No valid Front/Rear pairs found. Ensure files end in F or R before the extension.")
        sys.exit(1)

    os.makedirs(args.temp_dir, exist_ok=True)
    
    final_f_segments = []
    final_r_segments = []

    # 2. Process each pair
    for i, (f_vid, r_vid, base) in enumerate(pairs):
        # ...
        # (Inside the loop, ensuring we don't hold onto large JSON objects)
        print(f"\nProcessing Pair {i+1}/{len(pairs)}: {base} (F & R)")
        
        from extract_gps_frames import extract_gps_track
        points = extract_gps_track(f_vid)
        if not points:
            print(f"No GPS in Front camera, trying Rear...")
            points = extract_gps_track(r_vid)
        
        # b. Generate Map Animation
        map_path = Path(args.temp_dir) / f"map_{i:03d}.mp4"
        if points:
            gps_json = Path(args.temp_dir) / f"track_{i:03d}.json"
            with open(gps_json, 'w') as f:
                json.dump(points, f, indent=4)
            
            # Explicitly delete points from memory before calling sub-process
            del points
            
            try:
                run_command([
                    sys.executable, str(script_dir / 'export_video.py'), 
                    str(gps_json), 
                    '--source', str(f_vid), 
                    '--output', str(map_path)
                ], f"Generating map for {base}")
            except SystemExit:
                print(f"Warning: Map generation failed for {base}. Proceeding without map.")
                map_path = None
        else:
            print(f"Warning: No GPS found for {base}. No map will be overlaid.")
            map_path = None

        # Double check file actually exists even if command "succeeded"
        if map_path and not map_path.exists():
            print(f"Warning: Map file {map_path} not found. Proceeding without map.")
            map_path = None

        # c. Create Dual Overlay Versions (Front-centric and Rear-centric)
        def get_pos(pos_code, margin):
            if pos_code == 'tl': return f"{margin}:{margin}"
            if pos_code == 'tr': return f"main_w-overlay_w-{margin}:{margin}"
            if pos_code == 'bl': return f"{margin}:main_h-overlay_h-{margin}"
            if pos_code == 'br': return f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}"
            return f"{margin}:{margin}"

        pip_xy = get_pos(args.pip_pos, args.margin)
        map_xy = get_pos(args.map_pos, args.margin)

        for mode in ['F', 'R']:
            bg = f_vid if mode == 'F' else r_vid
            pip = r_vid if mode == 'F' else f_vid
            out_seg = Path(args.temp_dir) / f"seg_{i:03d}_{mode}.mp4"
            
            # Using scale=iw/4:-2 to ensure even height (required for libx264)
            filter_complex = f"[1:v]scale=iw/4:-2[pip];"
            
            if map_path:
                filter_complex += f"[2:v]colorkey=0x00FF00:0.1:0.1[map];"
                filter_complex += f"[0:v][pip]overlay={pip_xy}[tmp];"
                filter_complex += f"[tmp][map]overlay={map_xy}"
            else:
                filter_complex += f"[0:v][pip]overlay={pip_xy}"

            cmd = [
                'ffmpeg', '-y',
                '-i', str(bg),
                '-i', str(pip)
            ]
            if map_path:
                cmd.extend(['-i', str(map_path)])
            
            cmd.extend([
                '-filter_complex', filter_complex,
                '-map', '0:a?',        # Keep audio from background
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
                '-c:a', 'aac', '-shortest',
                str(out_seg)
            ])
            
            run_command(cmd, f"Creating {mode}-centric overlay for {base}")
            
            if mode == 'F':
                final_f_segments.append(out_seg)
            else:
                final_r_segments.append(out_seg)

    # 3. Concatenate Results
    output_path = Path(args.output)
    output_f = output_path.parent / (output_path.stem + "_F" + output_path.suffix)
    output_r = output_path.parent / (output_path.stem + "_R" + output_path.suffix)

    for mode, segments, final_out in [('F', final_f_segments, output_f), ('R', final_r_segments, output_r)]:
        if not segments:
            continue
            
        print(f"\nConcatenating final {mode}-centric video into {final_out}...")
        concat_list = Path(args.temp_dir) / f"concat_list_{mode}.txt"
        with open(concat_list, 'w') as f:
            for seg in segments:
                if seg.exists():
                    f.write(f"file '{seg.absolute()}'\n")
        
        run_command([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', 
            '-i', str(concat_list), 
            '-c', 'copy',
            str(final_out)
        ], f"Merging final {mode} output")

    print(f"\n✨ ALL DONE!")
    print(f"Front-centric video: {output_f.absolute()}")
    print(f"Rear-centric video:  {output_r.absolute()}")
    
    if not args.keep_temp:
        print(f"Cleaning up temporary segments in {args.temp_dir}...")
        for seg in final_f_segments + final_r_segments:
            if seg.exists():
                seg.unlink()
        # Also clean up map segments
        for map_file in Path(args.temp_dir).glob("map_*.mp4"):
            map_file.unlink()
        print("Cleanup complete.")
    else:
        print(f"Temporary files are preserved in: {args.temp_dir}")

if __name__ == "__main__":
    main()
