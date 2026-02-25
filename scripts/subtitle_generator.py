#!/usr/bin/env python3
"""
Subtitle Generator using faster-whisper and pysubs2
Generates word-by-word animated subtitles in ASS format with build-up highlight effect.
Words appear one at a time, current word highlighted, resets after N words.
"""

import argparse
import json
import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

try:
    from faster_whisper import WhisperModel
    import ffmpeg
    import pysubs2
except ImportError as e:
    print(f"Error: Missing required package: {e}")
    print("Install with: pip install faster-whisper ffmpeg-python pysubs2")
    sys.exit(1)


class SubtitleGenerator:
    def __init__(self, model_size: str = "base", device: str = "cuda", log_file: Optional[str] = None):
        """Initialize Whisper model with GPU acceleration."""
        self.model_size = model_size
        self.device = device
        self.setup_logging(log_file)
        self.model = None  # Lazy init - only load if we need to transcribe

    def _init_model(self):
        """Lazy initialize Whisper model."""
        if self.model is not None:
            return
        try:
            self.logger.info(f"Loading Whisper model: {self.model_size} on {self.device}")
            compute_type = "float16" if self.device == "cuda" else "int8"
            self.model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
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
            self._init_model()
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

    def create_ass_subtitles(self, word_segments: List[Dict], output_ass_path: str,
                              video_width: int = 1080, video_height: int = 1920,
                              settings: Optional[Dict] = None) -> bool:
        """Create ASS subtitle file with word-by-word build-up animation.

        Style C: Words pop onto screen one at a time, current word highlighted,
        previous words shown in normal color, resets after words_per_group words.
        """
        try:
            if not word_segments:
                self.logger.error("No word segments to create subtitles from")
                return False

            # Default settings
            if settings is None:
                settings = {}

            font = settings.get('font', 'Impact')
            fontsize = settings.get('fontsize', 70)
            outline_width = settings.get('outline_width', 4)
            highlight_scale = settings.get('highlight_scale', 120)
            words_per_group = settings.get('words_per_group', 3)
            # ASS colors are in &HBBGGRR& format
            highlight_color = settings.get('highlight_color', '&H00FFFF&')  # Yellow
            normal_color = settings.get('normal_color', '&HFFFFFF&')  # White
            outline_color = settings.get('outline_color', '&H000000&')  # Black

            self.logger.info(
                f"Creating ASS subtitles: {len(word_segments)} words, "
                f"{words_per_group} per group, font={font}"
            )

            # Create ASS file
            subs = pysubs2.SSAFile()
            subs.info['PlayResX'] = str(video_width)
            subs.info['PlayResY'] = str(video_height)

            # Create default style
            default_style = pysubs2.SSAStyle(
                fontname=font,
                fontsize=fontsize,
                primarycolor=pysubs2.Color(255, 255, 255, 0),  # White (will be overridden per word)
                outlinecolor=pysubs2.Color(0, 0, 0, 0),  # Black outline
                outline=outline_width,
                shadow=0,
                alignment=5,  # \an5 = middle center
                marginv=0,
                marginl=0,
                marginr=0,
                bold=True
            )
            subs.styles['Default'] = default_style

            # Position: center of screen
            pos_x = video_width // 2
            pos_y = video_height // 2

            # Group words into chunks
            groups = []
            for i in range(0, len(word_segments), words_per_group):
                groups.append(word_segments[i:i + words_per_group])

            self.logger.info(f"Created {len(groups)} subtitle groups")

            # Generate events for build-up effect
            for group in groups:
                for word_idx in range(len(group)):
                    current_word = group[word_idx]

                    # Timing: from when this word starts to when next word starts (or group ends)
                    start_ms = int(current_word['start'] * 1000)

                    if word_idx + 1 < len(group):
                        # Show until the next word in group starts
                        end_ms = int(group[word_idx + 1]['start'] * 1000)
                    else:
                        # Last word in group: show until this word ends
                        end_ms = int(current_word['end'] * 1000)

                    # Ensure minimum display time of 50ms
                    if end_ms <= start_ms:
                        end_ms = start_ms + 100

                    # Build the text line with ASS override tags
                    parts = []

                    # Previous words in normal color
                    for prev_idx in range(word_idx):
                        prev_word = group[prev_idx]['word']
                        parts.append(f"{{\\c{normal_color}}}{prev_word}")

                    # Current word: highlighted color + scaled up
                    current_text = current_word['word']
                    parts.append(
                        f"{{\\fscx{highlight_scale}\\fscy{highlight_scale}"
                        f"\\c{highlight_color}}}{current_text}"
                        f"{{\\fscx100\\fscy100}}"
                    )

                    # Combine with position tag
                    text = f"{{\\an5\\pos({pos_x},{pos_y})}}" + " ".join(parts)

                    event = pysubs2.SSAEvent(
                        start=start_ms,
                        end=end_ms,
                        text=text,
                        style='Default'
                    )
                    subs.events.append(event)

            # Save ASS file
            subs.save(output_ass_path)
            self.logger.info(f"ASS subtitle file created: {output_ass_path} ({len(subs.events)} events)")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create ASS subtitles: {e}")
            import traceback
            traceback.print_exc()
            return False

    def burn_ass_subtitles(self, video_path: str, ass_path: str, output_path: str) -> bool:
        """Burn ASS subtitles into video using FFmpeg."""
        try:
            self.logger.info(f"Burning ASS subtitles into video...")

            # Handle Windows path for ASS filter - need forward slashes and escaped colons
            ass_path_escaped = ass_path.replace('\\', '/')
            # Escape colons for FFmpeg filter (C: -> C\:)
            if len(ass_path_escaped) >= 2 and ass_path_escaped[1] == ':':
                ass_path_escaped = ass_path_escaped[0] + '\\' + ass_path_escaped[1:]

            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f"ass='{ass_path_escaped}'",
                '-c:a', 'copy',
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-y',
                output_path
            ]

            self.logger.info(f"FFmpeg command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                self.logger.error(f"FFmpeg error: {result.stderr}")
                # Try without quotes around the ass path
                cmd[5] = f"ass={ass_path_escaped}"
                self.logger.info("Retrying without quotes...")
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    self.logger.error(f"FFmpeg retry error: {result.stderr}")
                    return False

            self.logger.info(f"Subtitles burned: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to burn ASS subtitles: {e}")
            return False

    def process_video_with_subtitles(self, video_path: str, output_path: str,
                                      word_segments: Optional[List[Dict]] = None,
                                      settings: Optional[Dict] = None) -> bool:
        """Process video: optionally transcribe, create ASS subtitles, burn into video."""
        try:
            # Get word segments either from parameter or by transcribing
            if word_segments is None:
                # Extract audio from video
                audio_path = video_path.replace('.mp4', '_audio.wav')
                self.logger.info(f"Extracting audio from video...")

                stream = ffmpeg.input(video_path)
                stream = ffmpeg.output(stream, audio_path, acodec='pcm_s16le', ac=1, ar='16000')
                ffmpeg.run(stream, overwrite_output=True, quiet=True)

                # Transcribe audio
                word_segments = self.transcribe_audio(audio_path)

                # Cleanup temp audio
                if os.path.exists(audio_path):
                    os.remove(audio_path)

            if not word_segments:
                self.logger.error("No words to create subtitles from")
                return False

            # Get video dimensions
            try:
                probe = ffmpeg.probe(video_path)
                video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
                video_width = int(video_info['width'])
                video_height = int(video_info['height'])
            except Exception:
                video_width = 1080
                video_height = 1920

            # Create ASS subtitle file
            ass_path = output_path.replace('.mp4', '.ass')
            if not self.create_ass_subtitles(word_segments, ass_path, video_width, video_height, settings):
                return False

            # Burn subtitles into video
            success = self.burn_ass_subtitles(video_path, ass_path, output_path)

            return success

        except Exception as e:
            self.logger.error(f"Failed to process video: {e}")
            return False

    def create_srt(self, word_segments: List[Dict], output_path: str, words_per_subtitle: int = 3) -> bool:
        """Create SRT subtitle file from word segments (legacy fallback)."""
        try:
            self.logger.info(f"Creating SRT file: {output_path}")

            with open(output_path, 'w', encoding='utf-8') as f:
                subtitle_index = 1
                i = 0
                while i < len(word_segments):
                    chunk = word_segments[i:i + words_per_subtitle]
                    if not chunk:
                        break

                    start_time = chunk[0]['start']
                    end_time = chunk[-1]['end']
                    text = ' '.join([w['word'] for w in chunk])

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


def main():
    parser = argparse.ArgumentParser(description="Generate and overlay animated subtitles")

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--video', type=str, help='Path to video file (standalone mode)')
    mode_group.add_argument('--audio-dir', type=str, help='Directory with audio segments (legacy mode)')

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
    parser.add_argument('--srt-only', action='store_true', help='Generate SRT file only (legacy)')
    parser.add_argument('--log-file', type=str, help='Path to log file')

    # New v2 arguments
    parser.add_argument('--timestamps-json', type=str,
                        help='Path to audio_timestamps.json (skip transcription, use pre-computed timestamps)')

    args = parser.parse_args()

    # Validate arguments
    if args.audio_dir and not (args.video_dir and args.output_dir):
        parser.error("--audio-dir requires --video-dir and --output-dir")

    if args.video and not args.output:
        parser.error("--video requires --output")

    try:
        # Load subtitle animation settings
        settings = None
        settings_path = Path("config/settings.json")
        if settings_path.exists():
            with open(settings_path, 'r') as f:
                all_settings = json.load(f)
            settings = all_settings.get('subtitle_animation', None)

        # Initialize subtitle generator
        generator = SubtitleGenerator(
            model_size=args.model_size,
            device=args.device,
            log_file=args.log_file
        )

        # Load pre-computed word timestamps if provided
        word_segments = None
        if args.timestamps_json:
            with open(args.timestamps_json, 'r', encoding='utf-8') as f:
                timestamps_data = json.load(f)
            word_segments = timestamps_data.get('words', [])
            if word_segments:
                print(f"Loaded {len(word_segments)} pre-computed word timestamps")

        # Process based on mode
        if args.video:
            if args.srt_only:
                # Legacy SRT mode
                if word_segments is None:
                    audio_path = args.video.replace('.mp4', '_audio.wav')
                    stream = ffmpeg.input(args.video)
                    stream = ffmpeg.output(stream, audio_path, acodec='pcm_s16le', ac=1, ar='16000')
                    ffmpeg.run(stream, overwrite_output=True, quiet=True)
                    word_segments = generator.transcribe_audio(audio_path)
                    if os.path.exists(audio_path):
                        os.remove(audio_path)

                srt_path = args.output.replace('.mp4', '.srt')
                success = generator.create_srt(word_segments, srt_path)
            else:
                # Main mode: ASS word-by-word subtitles
                success = generator.process_video_with_subtitles(
                    args.video, args.output,
                    word_segments=word_segments,
                    settings=settings
                )
        else:
            # Legacy audio-dir mode (not used in v2 pipeline)
            success = False
            print("Legacy --audio-dir mode is deprecated. Use --video with --timestamps-json instead.")

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
