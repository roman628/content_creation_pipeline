#!/usr/bin/env python3
"""
Audio Generator using Kokoro-ONNX TTS
Generates audio segments from text using GPU-accelerated TTS
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

    def generate_audio_from_text(self, text: str, output_path: str) -> bool:
        """Generate audio file from text."""
        try:
            self.logger.info(f"Generating audio for: '{text[:50]}...'")

            # Initialize pipeline if not already done
            self._init_pipeline()

            # Generate audio using Kokoro pipeline
            generator = self.pipeline(text, voice=self.voice_name)

            # Get the audio from the generator
            audio_array = None
            for i, (gs, ps, audio) in enumerate(generator):
                audio_array = audio
                break  # Take first output

            if audio_array is None:
                raise RuntimeError("No audio generated")

            # Save audio file (Kokoro returns numpy array at 24kHz)
            sf.write(output_path, audio_array, 24000)

            duration = len(audio_array) / 24000
            self.logger.info(f"Audio generated: {output_path} (duration: {duration:.2f}s)")

            return True
        except Exception as e:
            self.logger.error(f"Failed to generate audio: {e}")
            return False

    def generate_from_json(self, json_path: str, output_dir: str) -> bool:
        """Generate audio segments from JSON configuration."""
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

                if self.generate_audio_from_text(audio_text, output_file):
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
            # Helper script mode
            success = generator.generate_from_json(args.json, args.output_dir)
        else:
            # Standalone mode
            os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)
            success = generator.generate_audio_from_text(args.text, args.output)

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
