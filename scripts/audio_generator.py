#!/usr/bin/env python3
"""
Audio Generator using Kokoro-ONNX TTS
Generates audio from text using GPU-accelerated TTS.
Supports single full-audio generation with word-level timestamps.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

try:
    from kokoro import KPipeline
    import numpy as np
    from scipy.io import wavfile
    import soundfile as sf
except ImportError as e:
    print(f"Error: Missing required package: {e}")
    print("Install with: pip install kokoro scipy soundfile")
    sys.exit(1)


class AudioGenerator:
    # American English voices from Kokoro-82M
    VALID_VOICES = [
        # Female voices (11)
        'af_heart', 'af_alloy', 'af_aoede', 'af_bella', 'af_jessica',
        'af_kore', 'af_nicole', 'af_nova', 'af_river', 'af_sarah', 'af_sky',
        # Male voices (9)
        'am_adam', 'am_echo', 'am_eric', 'am_fenrir', 'am_liam',
        'am_michael', 'am_onyx', 'am_puck', 'am_santa'
    ]

    def __init__(self, voice_name: str = "af_bella", use_gpu: bool = True, log_file: Optional[str] = None):
        """Initialize TTS engine with GPU acceleration."""
        self.voice_name = voice_name
        self.use_gpu = use_gpu
        self.setup_logging(log_file)
        self.pipeline = None  # Lazy initialization

        if voice_name not in self.VALID_VOICES:
            raise ValueError(f"Unknown voice: {voice_name}. Available: {self.VALID_VOICES}")

    def _init_pipeline(self):
        """Lazy initialize Kokoro pipeline (downloads model on first use)."""
        if self.pipeline is not None:
            return

        try:
            self.logger.info(f"Initializing Kokoro TTS pipeline...")
            # Initialize pipeline - it will auto-download model to cache
            self.pipeline = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M')
            self.logger.info(f"Kokoro pipeline initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Kokoro pipeline: {e}")
            raise

    def setup_logging(self, log_file: Optional[str] = None):
        """Configure logging to console and optional file."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File handler
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def generate_audio_from_text(self, text: str, output_path: str) -> Optional[float]:
        """Generate audio file from text. Returns duration in seconds, or None on failure."""
        try:
            self.logger.info(f"Generating audio for: '{text[:50]}...'")

            # Initialize pipeline if not already done
            self._init_pipeline()

            # Generate audio using Kokoro pipeline
            # Collect all chunks from the generator and concatenate
            generator = self.pipeline(text, voice=self.voice_name)

            audio_chunks = []
            for i, (gs, ps, audio) in enumerate(generator):
                audio_chunks.append(audio)

            if not audio_chunks:
                raise RuntimeError("No audio generated")

            # Concatenate all audio chunks
            audio_array = np.concatenate(audio_chunks) if len(audio_chunks) > 1 else audio_chunks[0]

            # Save audio file (Kokoro returns numpy array at 24kHz)
            sf.write(output_path, audio_array, 24000)

            duration = len(audio_array) / 24000
            self.logger.info(f"Audio generated: {output_path} (duration: {duration:.2f}s)")

            return duration
        except Exception as e:
            self.logger.error(f"Failed to generate audio: {e}")
            return None

    def generate_full_audio(self, json_path: str, output_dir: str) -> bool:
        """Generate single audio file from all segments, transcribe, and output timestamps."""
        try:
            # Load JSON configuration
            with open(json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            os.makedirs(output_dir, exist_ok=True)

            # Extract voice name if specified in JSON
            if 'voice_name' in config:
                self.voice_name = config['voice_name']
                self.logger.info(f"Using voice: {self.voice_name}")

            script_segments = config.get('script_segments', [])
            if not script_segments:
                self.logger.error("No script_segments found in JSON")
                return False

            # Step 1: Join all segment texts and track word boundaries
            full_text_parts = []
            segment_word_boundaries = []
            cumulative_words = 0

            for seg in script_segments:
                text = seg['audio_text'].strip()
                words_in_segment = len(text.split())
                segment_word_boundaries.append({
                    'segment_id': seg['segment_id'],
                    'start_word_idx': cumulative_words,
                    'end_word_idx': cumulative_words + words_in_segment - 1,
                    'text': text
                })
                cumulative_words += words_in_segment
                full_text_parts.append(text)

            full_text = " ".join(full_text_parts)
            self.logger.info(f"Full script: {len(full_text_parts)} segments, {cumulative_words} words")

            # Step 2: Generate single audio file
            full_audio_path = os.path.join(output_dir, "full_audio.wav")
            duration = self.generate_audio_from_text(full_text, full_audio_path)
            if duration is None:
                return False

            self.logger.info(f"Full audio generated: {duration:.2f}s")

            # Step 3: Transcribe with faster-whisper for word-level timestamps
            self.logger.info("Transcribing audio for word-level timestamps...")
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                self.logger.error("faster-whisper not installed. pip install faster-whisper")
                return False

            device = "cuda" if self.use_gpu else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            model = WhisperModel("base", device=device, compute_type=compute_type)

            segments_iter, info = model.transcribe(
                full_audio_path,
                word_timestamps=True,
                language="en",
                vad_filter=True
            )

            word_timestamps = []
            for segment in segments_iter:
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        word_timestamps.append({
                            'word': word.word.strip(),
                            'start': round(word.start, 3),
                            'end': round(word.end, 3)
                        })

            self.logger.info(f"Transcribed {len(word_timestamps)} words (expected {cumulative_words})")

            if not word_timestamps:
                self.logger.error("No words transcribed")
                return False

            # Step 4: Map words back to segments using cumulative word index
            segment_timings = []
            for boundary in segment_word_boundaries:
                seg_start_idx = boundary['start_word_idx']
                seg_end_idx = boundary['end_word_idx']

                # Clamp to actual transcribed word count
                seg_start_idx = min(seg_start_idx, len(word_timestamps) - 1)
                seg_end_idx = min(seg_end_idx, len(word_timestamps) - 1)

                start_time = word_timestamps[seg_start_idx]['start']
                end_time = word_timestamps[seg_end_idx]['end']

                segment_timings.append({
                    'segment_id': boundary['segment_id'],
                    'start_time': start_time,
                    'end_time': end_time,
                    'duration': round(end_time - start_time, 3),
                    'word_start_idx': seg_start_idx,
                    'word_end_idx': seg_end_idx
                })

                self.logger.info(
                    f"Segment {boundary['segment_id']}: "
                    f"{start_time:.2f}s - {end_time:.2f}s "
                    f"({end_time - start_time:.2f}s)"
                )

            # Step 5: Write timestamps JSON
            timestamps_data = {
                'full_audio_path': 'full_audio.wav',
                'total_duration': round(duration, 3),
                'words': word_timestamps,
                'segments': segment_timings
            }

            timestamps_path = os.path.join(output_dir, "audio_timestamps.json")
            with open(timestamps_path, 'w', encoding='utf-8') as f:
                json.dump(timestamps_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Timestamps written: {timestamps_path}")
            self.logger.info(f"Full audio generation complete: {duration:.2f}s, {len(word_timestamps)} words")
            return True

        except Exception as e:
            self.logger.error(f"Error generating full audio: {e}")
            import traceback
            traceback.print_exc()
            return False

    def generate_from_json(self, json_path: str, output_dir: str) -> bool:
        """Generate audio segments from JSON configuration (legacy per-segment mode)."""
        try:
            # Load JSON configuration
            with open(json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Extract voice name if specified in JSON
            if 'voice_name' in config:
                self.voice_name = config['voice_name']
                self.logger.info(f"Using voice: {self.voice_name}")

            # Generate audio for each script segment
            script_segments = config.get('script_segments', [])

            if not script_segments:
                self.logger.error("No script_segments found in JSON")
                return False

            self.logger.info(f"Generating {len(script_segments)} audio segments")

            success_count = 0
            for segment in script_segments:
                segment_id = segment.get('segment_id', 0)
                audio_text = segment.get('audio_text', '')

                if not audio_text:
                    self.logger.warning(f"Segment {segment_id} has no audio_text, skipping")
                    continue

                output_file = os.path.join(output_dir, f"segment_{segment_id:03d}.wav")

                if self.generate_audio_from_text(audio_text, output_file) is not None:
                    success_count += 1
                else:
                    self.logger.error(f"Failed to generate audio for segment {segment_id}")

            self.logger.info(f"Audio generation complete: {success_count}/{len(script_segments)} segments")
            return success_count == len(script_segments)

        except Exception as e:
            self.logger.error(f"Error processing JSON: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio using Kokoro-ONNX")

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--json', type=str, help='Path to JSON configuration file')
    mode_group.add_argument('--text', type=str, help='Text to convert to speech (standalone mode)')

    # Common arguments
    parser.add_argument('--voice', type=str, default='af_bella',
                        help='Voice name (af_heart, af_bella, af_sarah, af_adam, af_michael)')
    parser.add_argument('--output-dir', type=str, help='Output directory for audio segments')
    parser.add_argument('--output', type=str, help='Output file path (for --text mode)')
    parser.add_argument('--full-audio', action='store_true',
                        help='Generate single audio file from all segments with timestamps')
    parser.add_argument('--use-gpu', action='store_true', default=True, help='Use GPU acceleration (default: True)')
    parser.add_argument('--no-gpu', dest='use_gpu', action='store_false', help='Disable GPU acceleration')
    parser.add_argument('--log-file', type=str, help='Path to log file')

    args = parser.parse_args()

    # Validate arguments
    if args.json and not args.output_dir:
        parser.error("--json requires --output-dir")

    if args.text and not args.output:
        parser.error("--text requires --output")

    try:
        # Initialize audio generator
        generator = AudioGenerator(
            voice_name=args.voice,
            use_gpu=args.use_gpu,
            log_file=args.log_file
        )

        # Process based on mode
        if args.json:
            if args.full_audio:
                success = generator.generate_full_audio(args.json, args.output_dir)
            else:
                success = generator.generate_from_json(args.json, args.output_dir)
        else:
            # Standalone mode
            os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)
            success = generator.generate_audio_from_text(args.text, args.output) is not None

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
