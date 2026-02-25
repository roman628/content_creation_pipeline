#!/usr/bin/env python3
"""
Video Assembler
Combines b-roll clips, single audio file, and background music into final video.
V2: Works with single full audio and timestamps-based assembly.
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
            duration = float(probe['format']['duration'])
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
        """Combine video with audio track, handling duration mismatches.

        If video is longer than audio: trims video.
        If video is shorter than audio: loops video to fill.
        """
        try:
            self.logger.info(f"Combining video and audio")

            video_duration = self.get_video_duration(video_path)
            audio_duration = self.get_audio_duration(audio_path)

            self.logger.info(f"Video duration: {video_duration:.2f}s, Audio duration: {audio_duration:.2f}s")

            if video_duration < audio_duration - 0.1:
                # Video is shorter than audio — loop the video to fill
                self.logger.info(f"Video shorter than audio, looping video to match {audio_duration:.2f}s")
                import subprocess

                cmd = [
                    'ffmpeg',
                    '-stream_loop', '-1',  # Loop video indefinitely
                    '-i', video_path,
                    '-i', audio_path,
                    '-map', '0:v',
                    '-map', '1:a',
                    '-t', str(audio_duration),  # Cut at audio duration
                    '-c:v', 'libx264',
                    '-preset', 'medium',
                    '-crf', '23',
                    '-c:a', 'aac',
                    '-b:a', '192k',
                    '-shortest',
                    '-y', output_path
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    self.logger.error(f"FFmpeg loop+combine error: {result.stderr}")
                    return False
            else:
                video_input = ffmpeg.input(video_path)
                audio_input = ffmpeg.input(audio_path)

                # Trim video to exact audio duration if needed
                if video_duration - audio_duration > 0.1:
                    self.logger.info(f"Trimming video to match audio duration: {audio_duration:.2f}s")
                    video_stream = video_input.video.trim(duration=audio_duration).setpts('PTS-STARTPTS')
                else:
                    video_stream = video_input.video

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

    def assemble_video(self, config_path: str, project_dir: str, music_genre: str,
                       timestamps_path: Optional[str] = None) -> bool:
        """Assemble final video from all components.

        V2 flow (when timestamps_path provided):
        1. Collect ALL b-roll clips across all segments in order
        2. Concatenate into one continuous video (no audio)
        3. Combine with single full audio
        4. Mix background music
        5. Output final_output.mp4
        """
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

            # V2: Single audio + timestamps-based assembly
            if timestamps_path:
                return self._assemble_v2(
                    config, project_dir, music_genre,
                    timestamps_path, audio_dir, broll_dir, target_duration
                )

            # Legacy: per-segment assembly
            return self._assemble_legacy(
                config, project_dir, music_genre,
                audio_dir, broll_dir, target_duration
            )

        except Exception as e:
            self.logger.error(f"Failed to assemble video: {e}")
            return False

    def _assemble_v2(self, config: Dict, project_dir: str, music_genre: str,
                     timestamps_path: str, audio_dir: Path, broll_dir: Path,
                     target_duration: float) -> bool:
        """V2 assembly: single audio + all b-roll clips concatenated globally."""
        try:
            # Load timestamps
            with open(timestamps_path, 'r', encoding='utf-8') as f:
                timestamps = json.load(f)

            # Step 1: Collect ALL b-roll clips across all segments in order
            self.logger.info("Collecting all b-roll clips...")
            all_clips = []
            for seg_timing in timestamps['segments']:
                seg_id = seg_timing['segment_id']
                seg_clips = sorted(broll_dir.glob(f"segment_{seg_id:03d}_clip_*.mp4"))
                all_clips.extend([str(c) for c in seg_clips])
                self.logger.info(f"Segment {seg_id}: {len(seg_clips)} clips")

            if not all_clips:
                self.logger.error("No b-roll clips found")
                return False

            self.logger.info(f"Total b-roll clips: {len(all_clips)}")

            # Step 2: Concatenate all clips into one continuous video (no audio)
            temp_all_broll = Path(project_dir) / "temp_all_broll.mp4"
            self.logger.info("Concatenating all b-roll clips...")

            if not self.concatenate_clips(all_clips, str(temp_all_broll), include_audio=False):
                return False

            # Step 3: Combine with single full audio
            full_audio = audio_dir / "full_audio.wav"
            if not full_audio.exists():
                self.logger.error(f"Full audio file not found: {full_audio}")
                return False

            temp_with_audio = Path(project_dir) / "temp_with_audio.mp4"
            self.logger.info("Combining video with full audio...")

            if not self.combine_audio_video(str(temp_all_broll), str(full_audio), str(temp_with_audio)):
                return False

            # Step 4: Extract audio for music mixing
            temp_voiceover = Path(project_dir) / "temp_voiceover.mp3"
            self.logger.info("Extracting audio for music mixing...")

            try:
                stream = ffmpeg.input(str(temp_with_audio))
                stream = ffmpeg.output(stream, str(temp_voiceover), acodec='libmp3lame', audio_bitrate='192k')
                ffmpeg.run(stream, overwrite_output=True, quiet=True)
            except Exception as e:
                self.logger.error(f"Failed to extract audio: {e}")
                return False

            # Step 5: Mix background music
            music_file = self.select_random_music(music_genre)
            audio_for_final = temp_voiceover

            if music_file:
                mixed_audio = Path(project_dir) / "final_audio_with_music.mp3"
                if self.mix_background_music(str(temp_voiceover), music_file, str(mixed_audio)):
                    audio_for_final = mixed_audio
                else:
                    self.logger.warning("Failed to mix music, using voiceover only")
            else:
                self.logger.warning("No background music found, using voiceover only")

            # Step 6: Create final video with mixed audio
            final_output = Path(project_dir) / "final_output.mp4"
            self.logger.info("Creating final video with mixed audio...")

            if not self.combine_audio_video(str(temp_with_audio), str(audio_for_final), str(final_output)):
                return False

            # Step 7: Validate duration
            final_duration = self.get_video_duration(str(final_output))
            duration_diff = abs(final_duration - target_duration)

            self.logger.info(f"Final video duration: {final_duration:.2f}s (target: {target_duration}s)")

            if duration_diff > 1.0:
                self.logger.warning(f"Duration mismatch: {duration_diff:.2f}s difference")
            else:
                self.logger.info("Duration within tolerance")

            # Cleanup temp files
            self._cleanup_temp_files(project_dir)

            self.logger.info(f"Video assembly complete: {final_output}")
            return True

        except Exception as e:
            self.logger.error(f"V2 assembly failed: {e}")
            return False

    def _assemble_legacy(self, config: Dict, project_dir: str, music_genre: str,
                         audio_dir: Path, broll_dir: Path, target_duration: float) -> bool:
        """Legacy per-segment assembly (backward compatible)."""
        try:
            script_segments = config.get('script_segments', [])
            segment_videos = []

            for segment in script_segments:
                segment_id = segment['segment_id']
                self.logger.info(f"Processing segment {segment_id}")

                # Get audio file
                audio_file = audio_dir / f"segment_{segment_id:03d}.wav"
                if not audio_file.exists():
                    self.logger.error(f"Audio file not found: {audio_file}")
                    continue

                # Get video clips for this segment
                video_clips = sorted(broll_dir.glob(f"segment_{segment_id:03d}_clip_*.mp4"))

                if not video_clips:
                    self.logger.error(f"No video clips found for segment {segment_id}")
                    continue

                # Concatenate clips if multiple
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

            # Concatenate all segments
            temp_final = Path(project_dir) / "temp_final_no_music.mp4"
            if not self.concatenate_clips(segment_videos, str(temp_final)):
                return False

            # Extract audio
            temp_audio = Path(project_dir) / "temp_voiceover.mp3"
            try:
                stream = ffmpeg.input(str(temp_final))
                stream = ffmpeg.output(stream, str(temp_audio), acodec='libmp3lame', audio_bitrate='192k')
                ffmpeg.run(stream, overwrite_output=True, quiet=True)
            except Exception as e:
                self.logger.error(f"Failed to extract audio: {e}")
                return False

            # Mix background music
            music_file = self.select_random_music(music_genre)
            if music_file:
                mixed_audio = Path(project_dir) / "final_audio_with_music.mp3"
                if self.mix_background_music(str(temp_audio), music_file, str(mixed_audio)):
                    temp_audio = mixed_audio

            # Final combination
            final_output = Path(project_dir) / "final_output.mp4"
            try:
                video_duration = self.get_video_duration(str(temp_final))
                audio_duration = self.get_audio_duration(str(temp_audio))

                video_input = ffmpeg.input(str(temp_final))
                audio_input = ffmpeg.input(str(temp_audio))

                if abs(video_duration - audio_duration) > 0.1:
                    video_stream = video_input.video.trim(duration=audio_duration).setpts('PTS-STARTPTS')
                else:
                    video_stream = video_input.video

                output = ffmpeg.output(
                    video_stream, audio_input.audio, str(final_output),
                    vcodec='libx264', acodec='aac', audio_bitrate='192k',
                    preset='medium', crf=23, movflags='faststart'
                )
                ffmpeg.run(output, overwrite_output=True, quiet=True)

            except Exception as e:
                self.logger.error(f"Failed to create final video: {e}")
                return False

            # Validate
            final_duration = self.get_video_duration(str(final_output))
            self.logger.info(f"Final video duration: {final_duration:.2f}s (target: {target_duration}s)")

            # Cleanup
            self._cleanup_temp_files(project_dir)

            self.logger.info(f"Video assembly complete: {final_output}")
            return True

        except Exception as e:
            self.logger.error(f"Legacy assembly failed: {e}")
            return False

    def _cleanup_temp_files(self, project_dir: str):
        """Remove temporary files from project directory."""
        self.logger.info("Cleaning up temporary files")
        temp_files = (
            list(Path(project_dir).glob("temp_*.mp4")) +
            list(Path(project_dir).glob("temp_*.mp3")) +
            list(Path(project_dir).glob("segment_*_final.mp4"))
        )
        for temp_file in temp_files:
            try:
                temp_file.unlink()
            except:
                pass


def main():
    parser = argparse.ArgumentParser(description="Assemble final video from components")

    parser.add_argument('--json', type=str, required=True, help='Path to JSON configuration file')
    parser.add_argument('--project-dir', type=str, required=True, help='Project directory')
    parser.add_argument('--music-genre', type=str, required=True,
                        help='Background music genre (lofi, trap, hiphop, edm, ambient)')
    parser.add_argument('--music-dir', type=str, default='music', help='Music library directory')
    parser.add_argument('--log-file', type=str, help='Path to log file')

    # New v2 argument
    parser.add_argument('--timestamps-json', type=str,
                        help='Path to audio_timestamps.json for v2 assembly')

    args = parser.parse_args()

    try:
        # Initialize assembler
        assembler = VideoAssembler(log_file=args.log_file)

        # Assemble video
        success = assembler.assemble_video(
            args.json, args.project_dir, args.music_genre,
            timestamps_path=args.timestamps_json
        )

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
