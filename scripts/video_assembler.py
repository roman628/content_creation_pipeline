#!/usr/bin/env python3
"""
Video Assembler
Combines audio segments, b-roll, subtitles, and background music into final video
"""

import argparse
import json
import logging
import os
import sys
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple

try:
    import ffmpeg
    from pydub import AudioSegment
except ImportError as e:
    print(f"Error: Missing required package: {e}")
    print("Install with: pip install ffmpeg-python pydub")
    sys.exit(1)


PLATFORM_RESOLUTIONS = {
    "youtube_shorts": {"width": 1080, "height": 1920, "aspect": "9:16"},
    "tiktok": {"width": 1080, "height": 1920, "aspect": "9:16"},
    "instagram_reels": {"width": 1080, "height": 1920, "aspect": "9:16"},
    "youtube_long": {"width": 1920, "height": 1080, "aspect": "16:9"}
}


class VideoAssembler:
    def __init__(self, log_file: Optional[str] = None):
        """Initialize video assembler."""
        self.setup_logging(log_file)
        self.logger.info("Video Assembler initialized")

    def setup_logging(self, log_file: Optional[str] = None):
        """Configure logging."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def get_audio_duration(self, audio_path: str) -> float:
        """Get duration of audio file in seconds."""
        try:
            probe = ffmpeg.probe(audio_path)
            duration = float(probe['format']['duration'])
            return duration
        except Exception as e:
            self.logger.error(f"Failed to get audio duration: {e}")
            return 0.0

    def get_video_duration(self, video_path: str) -> float:
        """Get duration of video file in seconds."""
        try:
            probe = ffmpeg.probe(video_path)
            duration = float(probe['streams'][0]['duration'])
            return duration
        except Exception as e:
            self.logger.error(f"Failed to get video duration: {e}")
            return 0.0

    def concatenate_clips(self, clip_paths: List[str], output_path: str, include_audio: bool = True) -> bool:
        """Concatenate multiple video clips into one."""
        try:
            self.logger.info(f"Concatenating {len(clip_paths)} clips")

            # Create concat file list
            concat_file = output_path.replace('.mp4', '_concat.txt')
            with open(concat_file, 'w') as f:
                for clip in clip_paths:
                    # Convert to absolute path for ffmpeg
                    abs_path = os.path.abspath(clip).replace('\\', '/')
                    f.write(f"file '{abs_path}'\n")

            # Run ffmpeg concat with re-encoding for better compatibility
            # Re-encoding ensures smooth transitions even if clips have slight parameter differences
            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-r', '30',  # Force consistent frame rate
            ]

            # Add audio encoding if requested
            if include_audio:
                cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
            else:
                cmd.append('-an')  # No audio

            cmd.extend(['-y', output_path])

            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                self.logger.error(f"FFmpeg concat error: {result.stderr}")
                return False

            # Cleanup concat file
            if os.path.exists(concat_file):
                os.remove(concat_file)

            self.logger.info(f"Clips concatenated: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to concatenate clips: {e}")
            return False

    def combine_audio_video(self, video_path: str, audio_path: str, output_path: str) -> bool:
        """Combine video with audio track."""
        try:
            self.logger.info(f"Combining video and audio")

            # Get durations to check if they match
            video_duration = self.get_video_duration(video_path)
            audio_duration = self.get_audio_duration(audio_path)

            self.logger.info(f"Video duration: {video_duration:.2f}s, Audio duration: {audio_duration:.2f}s")

            video_input = ffmpeg.input(video_path)
            audio_input = ffmpeg.input(audio_path)

            # Trim video to exact audio duration if needed
            if abs(video_duration - audio_duration) > 0.1:
                self.logger.info(f"Trimming video to match audio duration: {audio_duration:.2f}s")
                video_stream = video_input.video.trim(duration=audio_duration).setpts('PTS-STARTPTS')
            else:
                video_stream = video_input.video

            # Combine with audio
            output = ffmpeg.output(
                video_stream,
                audio_input.audio,
                output_path,
                vcodec='libx264',
                preset='medium',
                crf=23,
                acodec='aac',
                audio_bitrate='192k'
            )

            ffmpeg.run(output, overwrite_output=True, quiet=True)

            self.logger.info(f"Audio and video combined: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to combine audio and video: {e}")
            return False

    def mix_background_music(self, voiceover_path: str, music_path: str, output_path: str,
                             music_volume_db: float = -22, fade_duration: float = 2.0) -> bool:
        """Mix voiceover with background music."""
        try:
            self.logger.info(f"Mixing background music: {music_path}")

            # Load audio files
            voiceover = AudioSegment.from_file(voiceover_path)
            music = AudioSegment.from_file(music_path)

            # Adjust music volume
            music = music + music_volume_db

            # Match music duration to voiceover
            vo_duration = len(voiceover)
            music_duration = len(music)

            if music_duration < vo_duration:
                # Loop music to match voiceover duration
                loops_needed = (vo_duration // music_duration) + 1
                music = music * loops_needed

            # Trim music to exact duration
            music = music[:vo_duration]

            # Apply fade in and fade out to music
            fade_ms = int(fade_duration * 1000)
            if fade_ms > 0:
                music = music.fade_in(fade_ms).fade_out(fade_ms)

            # Overlay music on voiceover
            mixed = voiceover.overlay(music)

            # Export
            mixed.export(output_path, format="mp3", bitrate="192k")

            self.logger.info(f"Background music mixed: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to mix background music: {e}")
            return False

    def select_random_music(self, genre: str, music_dir: str = "music") -> Optional[str]:
        """Select random music track from genre folder."""
        try:
            genre_path = Path(music_dir) / genre

            if not genre_path.exists():
                self.logger.warning(f"Music genre folder not found: {genre_path}")
                return None

            # Find all music files
            music_files = list(genre_path.glob("*.mp3")) + list(genre_path.glob("*.wav"))

            if not music_files:
                self.logger.warning(f"No music files found in {genre_path}")
                return None

            selected = random.choice(music_files)
            self.logger.info(f"Selected background music: {selected.name}")

            return str(selected)

        except Exception as e:
            self.logger.error(f"Failed to select music: {e}")
            return None

    def assemble_video(self, config_path: str, project_dir: str, music_genre: str) -> bool:
        """Assemble final video from all components."""
        try:
            # Load configuration
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            video_name = config.get('video_name', 'output')
            target_platform = config.get('target_platform', 'youtube_shorts')
            target_duration = config.get('target_duration_seconds', 60)

            resolution = PLATFORM_RESOLUTIONS.get(target_platform, PLATFORM_RESOLUTIONS['youtube_shorts'])

            self.logger.info(f"Assembling video: {video_name}")
            self.logger.info(f"Target: {target_platform} ({resolution['width']}x{resolution['height']})")

            # Paths
            audio_dir = Path(project_dir) / "audio_segments"
            broll_dir = Path(project_dir) / "broll"

            # Step 1: Process each segment
            segment_videos = []
            script_segments = config.get('script_segments', [])

            for segment in script_segments:
                segment_id = segment['segment_id']
                self.logger.info(f"Processing segment {segment_id}")

                # Get audio file
                audio_file = audio_dir / f"segment_{segment_id:03d}.wav"
                if not audio_file.exists():
                    self.logger.error(f"Audio file not found: {audio_file}")
                    continue

                audio_duration = self.get_audio_duration(str(audio_file))

                # Get video clips for this segment (from b-roll, not subtitles)
                video_clips = sorted(broll_dir.glob(f"segment_{segment_id:03d}_clip_*.mp4"))

                if not video_clips:
                    self.logger.error(f"No video clips found for segment {segment_id}")
                    continue

                # Concatenate clips if multiple (b-roll has no audio)
                if len(video_clips) > 1:
                    concat_output = Path(project_dir) / f"temp_segment_{segment_id:03d}_video.mp4"
                    if not self.concatenate_clips([str(c) for c in video_clips], str(concat_output), include_audio=False):
                        continue
                    segment_video = concat_output
                else:
                    segment_video = video_clips[0]

                # Combine with audio
                segment_final = Path(project_dir) / f"segment_{segment_id:03d}_final.mp4"
                if not self.combine_audio_video(str(segment_video), str(audio_file), str(segment_final)):
                    continue

                segment_videos.append(str(segment_final))

            if not segment_videos:
                self.logger.error("No segments were successfully processed")
                return False

            # Step 2: Concatenate all segments
            self.logger.info("Concatenating all segments")
            temp_final = Path(project_dir) / "temp_final_no_music.mp4"

            if not self.concatenate_clips(segment_videos, str(temp_final)):
                return False

            # Step 3: Extract audio from concatenated video
            temp_audio = Path(project_dir) / "temp_voiceover.mp3"
            self.logger.info("Extracting audio for music mixing")

            try:
                stream = ffmpeg.input(str(temp_final))
                stream = ffmpeg.output(stream, str(temp_audio), acodec='libmp3lame', audio_bitrate='192k')
                ffmpeg.run(stream, overwrite_output=True, quiet=True)
            except Exception as e:
                self.logger.error(f"Failed to extract audio: {e}")
                return False

            # Step 4: Mix background music
            music_file = self.select_random_music(music_genre)

            if music_file:
                mixed_audio = Path(project_dir) / "final_audio_with_music.mp3"
                if self.mix_background_music(str(temp_audio), music_file, str(mixed_audio)):
                    temp_audio = mixed_audio
                else:
                    self.logger.warning("Failed to mix music, using voiceover only")
            else:
                self.logger.warning("No background music found, using voiceover only")

            # Step 5: Combine final video with mixed audio
            final_output = Path(project_dir) / "final_output.mp4"
            self.logger.info("Creating final video with mixed audio")

            try:
                # Check durations to ensure sync
                video_duration = self.get_video_duration(str(temp_final))
                audio_duration = self.get_audio_duration(str(temp_audio))
                self.logger.info(f"Final video: {video_duration:.2f}s, Final audio: {audio_duration:.2f}s")

                video_input = ffmpeg.input(str(temp_final))
                audio_input = ffmpeg.input(str(temp_audio))

                # Trim video to match audio duration if needed
                if abs(video_duration - audio_duration) > 0.1:
                    self.logger.info(f"Trimming final video to match audio: {audio_duration:.2f}s")
                    video_stream = video_input.video.trim(duration=audio_duration).setpts('PTS-STARTPTS')
                else:
                    video_stream = video_input.video

                output = ffmpeg.output(
                    video_stream,
                    audio_input.audio,
                    str(final_output),
                    vcodec='libx264',
                    acodec='aac',
                    audio_bitrate='192k',
                    preset='medium',
                    crf=23,
                    movflags='faststart'
                )

                ffmpeg.run(output, overwrite_output=True, quiet=True)

            except Exception as e:
                self.logger.error(f"Failed to create final video: {e}")
                return False

            # Step 6: Validate duration
            final_duration = self.get_video_duration(str(final_output))
            duration_diff = abs(final_duration - target_duration)

            self.logger.info(f"Final video duration: {final_duration:.2f}s (target: {target_duration}s)")

            if duration_diff > 1.0:
                self.logger.warning(f"Duration mismatch: {duration_diff:.2f}s difference")
            else:
                self.logger.info("Duration within tolerance")

            # Cleanup temp files
            self.logger.info("Cleaning up temporary files")
            temp_files = list(Path(project_dir).glob("temp_*.mp4")) + \
                        list(Path(project_dir).glob("temp_*.mp3")) + \
                        list(Path(project_dir).glob("segment_*_final.mp4"))

            for temp_file in temp_files:
                try:
                    temp_file.unlink()
                except:
                    pass

            self.logger.info(f"Video assembly complete: {final_output}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to assemble video: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Assemble final video from components")

    parser.add_argument('--json', type=str, required=True, help='Path to JSON configuration file')
    parser.add_argument('--project-dir', type=str, required=True, help='Project directory')
    parser.add_argument('--music-genre', type=str, required=True,
                        help='Background music genre (lofi, trap, hiphop, edm, ambient)')
    parser.add_argument('--music-dir', type=str, default='music', help='Music library directory')
    parser.add_argument('--log-file', type=str, help='Path to log file')

    args = parser.parse_args()

    try:
        # Initialize assembler
        assembler = VideoAssembler(log_file=args.log_file)

        # Assemble video
        success = assembler.assemble_video(args.json, args.project_dir, args.music_genre)

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
