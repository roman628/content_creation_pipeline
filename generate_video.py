#!/usr/bin/env python3
"""
AI-Powered Short-Form Video Generation Pipeline
Main orchestrator script that coordinates all helper scripts
"""

import argparse
import json
import logging
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional


class VideoGenerator:
    def __init__(self, config_path: str, clean_previous: bool = False):
        """Initialize video generator with configuration."""
        self.config_path = config_path
        self.config = self.load_config(config_path)
        self.project_dir = None
        self.logger = None
        self.clean_previous = clean_previous

    def load_config(self, config_path: str) -> Dict:
        """Load and validate JSON configuration."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Validate required fields
            required_fields = ['video_name', 'target_platform', 'target_duration_seconds',
                             'background_music_genre', 'voice_name', 'script_segments']

            for field in required_fields:
                if field not in config:
                    raise ValueError(f"Missing required field: {field}")

            # Validate platform
            valid_platforms = ['youtube_shorts', 'tiktok', 'instagram_reels', 'youtube_long']
            if config['target_platform'] not in valid_platforms:
                raise ValueError(f"Invalid platform: {config['target_platform']}. Must be one of: {', '.join(valid_platforms)}")

            # Validate voice (American English voices from Kokoro-82M)
            valid_voices = [
                # Female voices
                'af_heart', 'af_alloy', 'af_aoede', 'af_bella', 'af_jessica',
                'af_kore', 'af_nicole', 'af_nova', 'af_river', 'af_sarah', 'af_sky',
                # Male voices
                'am_adam', 'am_echo', 'am_eric', 'am_fenrir', 'am_liam',
                'am_michael', 'am_onyx', 'am_puck', 'am_santa'
            ]
            if config['voice_name'] not in valid_voices:
                raise ValueError(f"Invalid voice: {config['voice_name']}. Must be one of: {', '.join(valid_voices)}")

            # Validate music genre
            valid_genres = ['lofi', 'trap', 'hiphop', 'edm', 'ambient']
            if config['background_music_genre'] not in valid_genres:
                raise ValueError(f"Invalid genre: {config['background_music_genre']}. Must be one of: {', '.join(valid_genres)}")

            # Validate script segments
            if not config['script_segments']:
                raise ValueError("script_segments cannot be empty")

            for idx, segment in enumerate(config['script_segments']):
                if 'segment_id' not in segment:
                    raise ValueError(f"Segment {idx} missing 'segment_id'")
                if 'audio_text' not in segment:
                    raise ValueError(f"Segment {segment.get('segment_id', idx)} missing 'audio_text'")
                if 'broll_clips' not in segment:
                    raise ValueError(f"Segment {segment.get('segment_id', idx)} missing 'broll_clips'")

                for clip_idx, clip in enumerate(segment.get('broll_clips', [])):
                    if 'type' in clip and clip['type'] not in ['video', 'image']:
                        raise ValueError(f"Segment {segment['segment_id']} clip {clip_idx}: type must be 'video' or 'image'")

            print(f"✓ Configuration loaded: {config['video_name']}")
            print(f"  Platform: {config['target_platform']}")
            print(f"  Duration: {config['target_duration_seconds']}s")
            print(f"  Segments: {len(config['script_segments'])}")
            return config

        except Exception as e:
            print(f"✗ Error loading configuration: {e}", file=sys.stderr)
            sys.exit(1)

    def clean_previous_runs(self, video_name: str):
        """Remove incomplete previous runs for this video."""
        try:
            base_dir = Path("generated_videos")
            if not base_dir.exists():
                return

            # Find all directories for this video name
            pattern = f"{video_name}_*"
            matching_dirs = sorted(base_dir.glob(pattern), reverse=True)

            for project_dir in matching_dirs:
                final_video = project_dir / "final_output.mp4"
                if not final_video.exists():
                    # Incomplete run - delete it
                    print(f"Removing incomplete run: {project_dir.name}")
                    import shutil
                    shutil.rmtree(project_dir)
                else:
                    print(f"Keeping completed run: {project_dir.name}")

        except Exception as e:
            print(f"Warning: Could not clean previous runs: {e}")

    def create_project_structure(self) -> str:
        """Create project directory structure."""
        try:
            video_name = self.config['video_name'].replace(' ', '_')

            # Clean previous incomplete runs if requested
            if self.clean_previous:
                self.clean_previous_runs(video_name)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = f"{video_name}_{timestamp}"

            base_dir = Path("generated_videos")
            base_dir.mkdir(exist_ok=True)

            project_dir = base_dir / project_name
            project_dir.mkdir(exist_ok=True)

            # Create subdirectories
            (project_dir / "audio_segments").mkdir(exist_ok=True)
            (project_dir / "broll").mkdir(exist_ok=True)
            (project_dir / "subtitles").mkdir(exist_ok=True)

            # Copy input JSON to project directory
            import shutil
            shutil.copy(self.config_path, project_dir / "input.json")

            print(f"\nProject directory created: {project_dir}")
            return str(project_dir)

        except Exception as e:
            print(f"Error creating project structure: {e}", file=sys.stderr)
            sys.exit(1)

    def setup_logging(self, project_dir: str):
        """Setup logging to file and console."""
        log_file = Path(project_dir) / "generation.log"

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        self.logger.info("="*70)
        self.logger.info(f"Video Generation Started: {self.config['video_name']}")
        self.logger.info("="*70)

    def run_helper_script(self, script_name: str, args: str) -> bool:
        """Execute helper script in venv with error handling."""
        try:
            # Use current Python executable (assumes we're running in venv)
            python_exe = sys.executable

            script_path = Path("scripts") / script_name
            if not script_path.exists():
                self.logger.error(f"Helper script not found: {script_path}")
                return False

            cmd = f'"{python_exe}" "{script_path}" {args}'

            self.logger.info(f"Running: {script_name}")
            self.logger.debug(f"Command: {cmd}")

            result = subprocess.run(
                cmd,
                shell=True,
                check=True,
                capture_output=True,
                text=True
            )

            # Log output
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    self.logger.info(f"  {line}")

            self.logger.info(f"Completed: {script_name}")
            return True

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error running {script_name}:")
            if e.stderr:
                for line in e.stderr.strip().split('\n'):
                    self.logger.error(f"  {line}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error running {script_name}: {e}")
            return False

    def generate_video(self) -> bool:
        """Main video generation pipeline."""
        try:
            # Step 1: Create project structure
            print("\n" + "="*70)
            print("STEP 1: Creating Project Structure")
            print("="*70)

            self.project_dir = self.create_project_structure()
            self.setup_logging(self.project_dir)

            # Step 2: Generate audio segments
            print("\n" + "="*70)
            print("STEP 2: Generating Audio Segments (TTS)")
            print("="*70)

            audio_dir = Path(self.project_dir) / "audio_segments"
            log_file = Path(self.project_dir) / "generation.log"

            success = self.run_helper_script(
                'audio_generator.py',
                f'--json "{self.config_path}" --output-dir "{audio_dir}" --voice {self.config["voice_name"]} --log-file "{log_file}"'
            )

            if not success:
                self.logger.error("Audio generation failed")
                return False

            # Step 3: Fetch b-roll for each segment
            print("\n" + "="*70)
            print("STEP 3: Fetching B-Roll Footage")
            print("="*70)

            broll_dir = Path(self.project_dir) / "broll"
            target_platform = self.config['target_platform']

            # Get resolution for platform
            platform_resolutions = {
                "youtube_shorts": "1080x1920",
                "tiktok": "1080x1920",
                "instagram_reels": "1080x1920",
                "youtube_long": "1920x1080"
            }
            resolution = platform_resolutions.get(target_platform, "1080x1920")

            for segment in self.config['script_segments']:
                segment_id = segment['segment_id']
                self.logger.info(f"Fetching b-roll for segment {segment_id}")

                success = self.run_helper_script(
                    'broll_fetcher.py',
                    f'--json "{self.config_path}" --segment-id {segment_id} --output-dir "{broll_dir}" --resolution {resolution} --audio-dir "{audio_dir}" --log-file "{log_file}"'
                )

                if not success:
                    self.logger.warning(f"B-roll fetch failed for segment {segment_id}")
                    # Continue with other segments

            # Step 4: Assemble video (audio + b-roll + music)
            print("\n" + "="*70)
            print("STEP 4: Assembling Video (Audio + B-Roll + Music)")
            print("="*70)

            music_genre = self.config['background_music_genre']

            success = self.run_helper_script(
                'video_assembler.py',
                f'--json "{self.config_path}" --project-dir "{self.project_dir}" --music-genre {music_genre} --log-file "{log_file}"'
            )

            if not success:
                self.logger.error("Video assembly failed")
                return False

            # Step 5: Add subtitles to final video
            print("\n" + "="*70)
            print("STEP 5: Adding Subtitles to Final Video")
            print("="*70)

            # Determine subtitle style based on platform
            style = "tiktok" if target_platform in ["tiktok", "instagram_reels"] else "youtube_shorts"

            # Concatenate all audio segments for transcription
            temp_full_audio = Path(self.project_dir) / "temp_full_audio.wav"
            audio_files = sorted(audio_dir.glob("segment_*.wav"))

            if audio_files:
                # Concatenate audio segments
                import subprocess
                concat_list = Path(self.project_dir) / "audio_concat_list.txt"
                with open(concat_list, 'w') as f:
                    for audio_file in audio_files:
                        abs_path = audio_file.absolute().as_posix()
                        f.write(f"file '{abs_path}'\n")

                concat_cmd = [
                    'ffmpeg', '-f', 'concat', '-safe', '0', '-i', str(concat_list),
                    '-c', 'copy', '-y', str(temp_full_audio)
                ]
                subprocess.run(concat_cmd, capture_output=True, check=True)

                # Generate subtitles on final video
                final_video_no_subs = Path(self.project_dir) / "final_output.mp4"
                final_video_with_subs = Path(self.project_dir) / "final_output_with_subtitles.mp4"

                success = self.run_helper_script(
                    'subtitle_generator.py',
                    f'--video "{final_video_no_subs}" --output "{final_video_with_subs}" --style {style} --log-file "{log_file}"'
                )

                if success:
                    # Replace original with subtitled version
                    import shutil
                    shutil.move(str(final_video_with_subs), str(final_video_no_subs))
                    self.logger.info("Subtitles added to final video")
                else:
                    self.logger.warning("Subtitle generation failed, keeping video without subtitles")

                # Cleanup temp files
                if temp_full_audio.exists():
                    temp_full_audio.unlink()
                if concat_list.exists():
                    concat_list.unlink()

            # Step 6: Validate final video
            print("\n" + "="*70)
            print("STEP 6: Validation")
            print("="*70)

            final_video = Path(self.project_dir) / "final_output.mp4"

            if not final_video.exists():
                self.logger.error("Final video file not found")
                return False

            # Check duration
            target_duration = self.config['target_duration_seconds']
            actual_duration = self.get_video_duration(str(final_video))
            duration_diff = abs(actual_duration - target_duration)

            self.logger.info(f"Target duration: {target_duration}s")
            self.logger.info(f"Actual duration: {actual_duration:.2f}s")
            self.logger.info(f"Difference: {duration_diff:.2f}s")

            if duration_diff > 1.0:
                self.logger.warning("Duration exceeds tolerance (±1s). Manual review recommended.")
                print("\n⚠ Warning: Duration mismatch detected")
            else:
                self.logger.info("Duration within tolerance")
                print("\n✓ Duration validation passed")

            # Success!
            print("\n" + "="*70)
            print("VIDEO GENERATION COMPLETE!")
            print("="*70)
            print(f"\nFinal video: {final_video}")
            print(f"Project folder: {self.project_dir}")
            print(f"Duration: {actual_duration:.2f}s")
            print(f"\n✓ Video generated successfully!")

            self.logger.info("="*70)
            self.logger.info("Video generation completed successfully")
            self.logger.info("="*70)

            return True

        except Exception as e:
            if self.logger:
                self.logger.error(f"Video generation failed: {e}")
            else:
                print(f"Error: {e}", file=sys.stderr)
            return False

    def get_video_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe."""
        try:
            import ffmpeg
            probe = ffmpeg.probe(video_path)
            duration = float(probe['format']['duration'])
            return duration
        except:
            return 0.0


def main():
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║   AI-Powered Short-Form Video Generation Pipeline            ║
    ║   Transform JSON configs into publish-ready videos           ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)

    parser = argparse.ArgumentParser(
        description="Generate short-form videos from JSON configuration"
    )

    parser.add_argument('config', type=str, help='Path to JSON configuration file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--clean', action='store_true',
                        help='Remove incomplete previous runs for this video before starting')

    args = parser.parse_args()

    # Validate config file exists
    if not os.path.exists(args.config):
        print(f"Error: Configuration file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    try:
        # Initialize generator
        generator = VideoGenerator(args.config, clean_previous=args.clean)

        # Run generation pipeline
        success = generator.generate_video()

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nGeneration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
