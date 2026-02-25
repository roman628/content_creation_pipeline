#!/usr/bin/env python3
"""
AI-Powered Short-Form Video Generation Pipeline
Main orchestrator script that coordinates all helper scripts.
V2: Single audio generation, fast b-roll cuts, ASS word-by-word subtitles.
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

            print(f"Configuration loaded: {config['video_name']}")
            print(f"  Platform: {config['target_platform']}")
            print(f"  Duration: {config['target_duration_seconds']}s")
            print(f"  Segments: {len(config['script_segments'])}")
            return config

        except Exception as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            sys.exit(1)

    def clean_previous_runs(self, video_name: str):
        """Remove incomplete previous runs for this video."""
        try:
            base_dir = Path("generated_videos")
            if not base_dir.exists():
                return

            pattern = f"{video_name}_*"
            matching_dirs = sorted(base_dir.glob(pattern), reverse=True)

            for project_dir in matching_dirs:
                final_video = project_dir / "final_output.mp4"
                if not final_video.exists():
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

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

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
        """Main video generation pipeline (V2: single audio + fast cuts + ASS subtitles)."""
        try:
            # Step 1: Create project structure
            print("\n" + "="*70)
            print("STEP 1: Creating Project Structure")
            print("="*70)

            self.project_dir = self.create_project_structure()
            self.setup_logging(self.project_dir)

            audio_dir = Path(self.project_dir) / "audio_segments"
            broll_dir = Path(self.project_dir) / "broll"
            log_file = Path(self.project_dir) / "generation.log"

            # Step 2: Generate SINGLE audio file + transcribe + timestamps
            print("\n" + "="*70)
            print("STEP 2: Generating Full Audio (Single TTS + Transcription)")
            print("="*70)

            success = self.run_helper_script(
                'audio_generator.py',
                f'--json "{self.config_path}" --output-dir "{audio_dir}" '
                f'--voice {self.config["voice_name"]} --full-audio --log-file "{log_file}"'
            )

            if not success:
                self.logger.error("Audio generation failed")
                return False

            # Load timestamps for subsequent steps
            timestamps_path = audio_dir / "audio_timestamps.json"
            if not timestamps_path.exists():
                self.logger.error("audio_timestamps.json not found after audio generation")
                return False

            with open(timestamps_path, 'r', encoding='utf-8') as f:
                timestamps = json.load(f)

            self.logger.info(f"Audio timestamps loaded: {len(timestamps['words'])} words, "
                           f"{len(timestamps['segments'])} segments, "
                           f"{timestamps['total_duration']:.2f}s total")

            # Step 3: Fetch b-roll for each segment (with fast cuts)
            print("\n" + "="*70)
            print("STEP 3: Fetching B-Roll Footage (Fast Cuts)")
            print("="*70)

            target_platform = self.config['target_platform']
            platform_resolutions = {
                "youtube_shorts": "1080x1920",
                "tiktok": "1080x1920",
                "instagram_reels": "1080x1920",
                "youtube_long": "1920x1080"
            }
            resolution = platform_resolutions.get(target_platform, "1080x1920")

            # Load broll settings from settings.json
            broll_settings = {}
            settings_path = Path("config/settings.json")
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    all_settings = json.load(f)
                broll_settings = all_settings.get('broll', {})

            cut_freq = broll_settings.get('cut_frequency_seconds', 2.5)
            speed_range = broll_settings.get('speed_range', [1.2, 2.0])

            for seg_timing in timestamps['segments']:
                segment_id = seg_timing['segment_id']
                segment_duration = seg_timing['duration']

                self.logger.info(f"Fetching b-roll for segment {segment_id} ({segment_duration:.2f}s)")

                success = self.run_helper_script(
                    'broll_fetcher.py',
                    f'--json "{self.config_path}" --segment-id {segment_id} '
                    f'--output-dir "{broll_dir}" --resolution {resolution} '
                    f'--segment-duration {segment_duration} '
                    f'--cut-frequency {cut_freq} '
                    f'--speed-min {speed_range[0]} --speed-max {speed_range[1]} '
                    f'--log-file "{log_file}"'
                )

                if not success:
                    self.logger.warning(f"B-roll fetch failed for segment {segment_id}")

            # Step 4: Assemble video (single audio + all b-roll + music)
            print("\n" + "="*70)
            print("STEP 4: Assembling Video (Audio + B-Roll + Music)")
            print("="*70)

            music_genre = self.config['background_music_genre']

            success = self.run_helper_script(
                'video_assembler.py',
                f'--json "{self.config_path}" --project-dir "{self.project_dir}" '
                f'--music-genre {music_genre} '
                f'--timestamps-json "{timestamps_path}" '
                f'--log-file "{log_file}"'
            )

            if not success:
                self.logger.error("Video assembly failed")
                return False

            # Step 5: Add ASS subtitles using pre-computed word timestamps
            print("\n" + "="*70)
            print("STEP 5: Adding Word-by-Word Animated Subtitles")
            print("="*70)

            style = "tiktok" if target_platform in ["tiktok", "instagram_reels"] else "youtube_shorts"

            final_video_no_subs = Path(self.project_dir) / "final_output.mp4"
            final_video_with_subs = Path(self.project_dir) / "final_output_with_subtitles.mp4"

            success = self.run_helper_script(
                'subtitle_generator.py',
                f'--video "{final_video_no_subs}" --output "{final_video_with_subs}" '
                f'--timestamps-json "{timestamps_path}" '
                f'--style {style} --log-file "{log_file}"'
            )

            if success:
                # Replace original with subtitled version
                import shutil
                shutil.move(str(final_video_with_subs), str(final_video_no_subs))
                self.logger.info("Subtitles added to final video")
            else:
                self.logger.warning("Subtitle generation failed, keeping video without subtitles")

            # Step 6: Validate final video
            print("\n" + "="*70)
            print("STEP 6: Validation")
            print("="*70)

            final_video = Path(self.project_dir) / "final_output.mp4"

            if not final_video.exists():
                self.logger.error("Final video file not found")
                return False

            target_duration = self.config['target_duration_seconds']
            actual_duration = self.get_video_duration(str(final_video))
            duration_diff = abs(actual_duration - target_duration)

            self.logger.info(f"Target duration: {target_duration}s")
            self.logger.info(f"Actual duration: {actual_duration:.2f}s")
            self.logger.info(f"Difference: {duration_diff:.2f}s")

            if duration_diff > 1.0:
                self.logger.warning("Duration exceeds tolerance. Manual review recommended.")
                print("\nWarning: Duration mismatch detected")
            else:
                self.logger.info("Duration within tolerance")
                print("\nDuration validation passed")

            # Success!
            print("\n" + "="*70)
            print("VIDEO GENERATION COMPLETE!")
            print("="*70)
            print(f"\nFinal video: {final_video}")
            print(f"Project folder: {self.project_dir}")
            print(f"Duration: {actual_duration:.2f}s")
            print(f"\nVideo generated successfully!")

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
    ================================================================
       AI-Powered Short-Form Video Generation Pipeline v2
       Single Audio | Fast B-Roll Cuts | Animated Subtitles
    ================================================================
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
