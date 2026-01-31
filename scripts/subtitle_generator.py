#!/usr/bin/env python3
"""
Subtitle Generator using faster-whisper
Generates word-level timestamps and creates animated subtitles
"""

import argparse
import json
import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

try:
    from faster_whisper import WhisperModel
    import ffmpeg
except ImportError as e:
    print(f"Error: Missing required package: {e}")
    print("Install with: pip install faster-whisper ffmpeg-python")
    sys.exit(1)


class SubtitleGenerator:
    def __init__(self, model_size: str = "base", device: str = "cuda", log_file: Optional[str] = None):
        """Initialize Whisper model with GPU acceleration."""
        self.model_size = model_size
        self.device = device
        self.setup_logging(log_file)

        try:
            self.logger.info(f"Loading Whisper model: {model_size} on {device}")
            self.model = WhisperModel(model_size, device=device, compute_type="float16" if device == "cuda" else "int8")
            self.logger.info("Whisper model loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load Whisper model: {e}")
            raise

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

    def transcribe_audio(self, audio_path: str) -> List[Dict]:
        """Transcribe audio and get word-level timestamps."""
        try:
            self.logger.info(f"Transcribing: {audio_path}")

            segments, info = self.model.transcribe(
                audio_path,
                word_timestamps=True,
                language="en",
                vad_filter=True
            )

            self.logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")

            word_segments = []
            for segment in segments:
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        word_segments.append({
                            'word': word.word.strip(),
                            'start': word.start,
                            'end': word.end
                        })

            self.logger.info(f"Transcribed {len(word_segments)} words")
            return word_segments

        except Exception as e:
            self.logger.error(f"Transcription failed: {e}")
            return []

    def create_srt(self, word_segments: List[Dict], output_path: str, words_per_subtitle: int = 3) -> bool:
        """Create SRT subtitle file from word segments."""
        try:
            self.logger.info(f"Creating SRT file: {output_path}")

            with open(output_path, 'w', encoding='utf-8') as f:
                subtitle_index = 1

                # Group words into subtitle chunks
                i = 0
                while i < len(word_segments):
                    chunk = word_segments[i:i + words_per_subtitle]
                    if not chunk:
                        break

                    start_time = chunk[0]['start']
                    end_time = chunk[-1]['end']
                    text = ' '.join([w['word'] for w in chunk])

                    # Write SRT entry
                    f.write(f"{subtitle_index}\n")
                    f.write(f"{self._format_timestamp(start_time)} --> {self._format_timestamp(end_time)}\n")
                    f.write(f"{text}\n\n")

                    subtitle_index += 1
                    i += words_per_subtitle

            self.logger.info(f"SRT file created: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create SRT: {e}")
            return False

    def _format_timestamp(self, seconds: float) -> str:
        """Convert seconds to SRT timestamp format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def create_animated_subtitles(self, video_path: str, word_segments: List[Dict], output_path: str,
                                   style: str = "tiktok") -> bool:
        """Create video with animated word-by-word subtitles using FFmpeg drawtext."""
        try:
            self.logger.info(f"Adding animated subtitles to: {video_path}")

            # Load style configuration
            if style == "tiktok":
                config = {
                    'fontsize': 70,
                    'fontcolor': 'yellow',
                    'highlight_color': 'white',
                    'outline_color': 'black',
                    'outline_width': 4,
                    'position_y': 'h-200'
                }
            else:  # youtube_shorts
                config = {
                    'fontsize': 70,
                    'fontcolor': 'yellow',
                    'highlight_color': 'white',
                    'outline_color': 'black',
                    'outline_width': 4,
                    'position_y': 'h-200'
                }

            # Group words into subtitle lines (max 2-3 words per line for readability)
            subtitle_lines = []
            i = 0
            while i < len(word_segments):
                chunk = word_segments[i:min(i + 3, len(word_segments))]
                if chunk:
                    subtitle_lines.append({
                        'words': chunk,
                        'start': chunk[0]['start'],
                        'end': chunk[-1]['end'],
                        'text': ' '.join([w['word'] for w in chunk])
                    })
                i += 3

            # Create simple subtitle filters - one line at a time, no overlap
            simple_filters = []
            for line in subtitle_lines:
                # Escape text for FFmpeg
                text_escaped = line['text'].replace("'", "'\\\\\\''")

                # Create a single drawtext filter for this line
                filter_str = (
                    f"drawtext=text='{text_escaped}':"
                    f"fontfile=/Windows/Fonts/impact.ttf:"
                    f"fontsize={config['fontsize']}:"
                    f"fontcolor={config['fontcolor']}:"
                    f"borderw={config['outline_width']}:"
                    f"bordercolor={config['outline_color']}:"
                    f"x=(w-text_w)/2:"  # Center horizontally
                    f"y={config['position_y']}:"
                    f"enable='between(t,{line['start']},{line['end']})'"
                )
                simple_filters.append(filter_str)

            # Combine all filters
            filter_complex = ','.join(simple_filters)

            # Run FFmpeg with filter
            self.logger.info("Running FFmpeg to burn subtitles...")

            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vf', filter_complex,
                '-c:a', 'copy',
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-y',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                self.logger.error(f"FFmpeg error: {result.stderr}")
                return False

            self.logger.info(f"Subtitles added: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to add animated subtitles: {e}")
            return False

    def process_video_with_subtitles(self, video_path: str, output_path: str, style: str = "tiktok") -> bool:
        """Process video: extract audio, transcribe, add subtitles."""
        try:
            # Extract audio from video
            audio_path = video_path.replace('.mp4', '_audio.wav')
            self.logger.info(f"Extracting audio from video...")

            stream = ffmpeg.input(video_path)
            stream = ffmpeg.output(stream, audio_path, acodec='pcm_s16le', ac=1, ar='16000')
            ffmpeg.run(stream, overwrite_output=True, quiet=True)

            # Transcribe audio
            word_segments = self.transcribe_audio(audio_path)

            if not word_segments:
                self.logger.error("No words transcribed")
                return False

            # Add animated subtitles
            success = self.create_animated_subtitles(video_path, word_segments, output_path, style)

            # Cleanup temp audio
            if os.path.exists(audio_path):
                os.remove(audio_path)

            return success

        except Exception as e:
            self.logger.error(f"Failed to process video: {e}")
            return False

    def process_segments(self, audio_dir: str, video_dir: str, output_dir: str, style: str = "tiktok") -> bool:
        """Process multiple audio+video segments and add subtitles."""
        try:
            # Convert to Path objects for path operations
            output_dir = Path(output_dir)
            video_dir = Path(video_dir)
            audio_dir = Path(audio_dir)

            os.makedirs(output_dir, exist_ok=True)

            # Find all audio segments
            audio_files = sorted(audio_dir.glob("segment_*.wav"))

            if not audio_files:
                self.logger.error(f"No audio segments found in {audio_dir}")
                return False

            self.logger.info(f"Processing {len(audio_files)} segments")
            success_count = 0

            for audio_file in audio_files:
                # Extract segment number from filename
                segment_name = audio_file.stem  # e.g., "segment_001"

                # Find corresponding video clips
                video_clips = sorted(video_dir.glob(f"{segment_name}_clip_*.mp4"))

                if not video_clips:
                    self.logger.warning(f"No video clips found for {segment_name}")
                    continue

                # Transcribe audio
                word_segments = self.transcribe_audio(str(audio_file))

                if not word_segments:
                    self.logger.error(f"Failed to transcribe {audio_file}")
                    continue

                # Add subtitles to each video clip
                for video_clip in video_clips:
                    output_file = output_dir / video_clip.name
                    if self.create_animated_subtitles(str(video_clip), word_segments, str(output_file), style):
                        success_count += 1
                    else:
                        self.logger.error(f"Failed to add subtitles to {video_clip}")

            self.logger.info(f"Subtitle generation complete: {success_count} clips processed")
            return success_count > 0

        except Exception as e:
            self.logger.error(f"Error processing segments: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Generate and overlay animated subtitles")

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--video', type=str, help='Path to video file (standalone mode)')
    mode_group.add_argument('--audio-dir', type=str, help='Directory with audio segments (helper mode)')

    # Common arguments
    parser.add_argument('--video-dir', type=str, help='Directory with video clips (for --audio-dir mode)')
    parser.add_argument('--output', type=str, help='Output video file (for --video mode)')
    parser.add_argument('--output-dir', type=str, help='Output directory (for --audio-dir mode)')
    parser.add_argument('--style', type=str, choices=['tiktok', 'youtube_shorts'], default='tiktok',
                        help='Subtitle style')
    parser.add_argument('--model-size', type=str, default='base',
                        choices=['tiny', 'base', 'small', 'medium', 'large'],
                        help='Whisper model size')
    parser.add_argument('--device', type=str, default='cuda', choices=['cuda', 'cpu'],
                        help='Device for inference')
    parser.add_argument('--srt-only', action='store_true', help='Generate SRT file only')
    parser.add_argument('--log-file', type=str, help='Path to log file')

    args = parser.parse_args()

    # Validate arguments
    if args.audio_dir and not (args.video_dir and args.output_dir):
        parser.error("--audio-dir requires --video-dir and --output-dir")

    if args.video and not args.output:
        parser.error("--video requires --output")

    try:
        # Initialize subtitle generator
        generator = SubtitleGenerator(
            model_size=args.model_size,
            device=args.device,
            log_file=args.log_file
        )

        # Process based on mode
        if args.audio_dir:
            # Helper script mode: process multiple segments
            success = generator.process_segments(args.audio_dir, args.video_dir, args.output_dir, args.style)
        else:
            # Standalone mode: process single video
            if args.srt_only:
                # Extract audio and create SRT only
                audio_path = args.video.replace('.mp4', '_audio.wav')
                stream = ffmpeg.input(args.video)
                stream = ffmpeg.output(stream, audio_path, acodec='pcm_s16le', ac=1, ar='16000')
                ffmpeg.run(stream, overwrite_output=True, quiet=True)

                word_segments = generator.transcribe_audio(audio_path)
                srt_path = args.output.replace('.mp4', '.srt')
                success = generator.create_srt(word_segments, srt_path)

                if os.path.exists(audio_path):
                    os.remove(audio_path)
            else:
                success = generator.process_video_with_subtitles(args.video, args.output, args.style)

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
