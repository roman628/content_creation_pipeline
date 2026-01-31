#!/usr/bin/env python3
"""
B-Roll Fetcher
Downloads and processes video/image assets from Pexels and Pixabay APIs
"""

import argparse
import json
import logging
import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

try:
    import requests
    from PIL import Image
    import ffmpeg
except ImportError as e:
    print(f"Error: Missing required package: {e}")
    print("Install with: pip install requests Pillow ffmpeg-python")
    sys.exit(1)


class BRollFetcher:
    def __init__(self, api_keys: Dict[str, str], cache_dir: str = ".cache", log_file: Optional[str] = None):
        """Initialize b-roll fetcher with API credentials."""
        self.pexels_key = api_keys.get('pexels', '')
        self.pixabay_key = api_keys.get('pixabay', '')
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.setup_logging(log_file)

        # API rate limiting
        self.pexels_requests = []
        self.pixabay_requests = []
        self.max_pexels_per_hour = 200
        self.max_pixabay_per_hour = 5000

        self.logger.info("B-Roll Fetcher initialized")

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

    def _check_rate_limit(self, api: str) -> bool:
        """Check if we're within API rate limits."""
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        if api == 'pexels':
            self.pexels_requests = [req for req in self.pexels_requests if req > one_hour_ago]
            if len(self.pexels_requests) >= self.max_pexels_per_hour:
                self.logger.warning(f"Pexels rate limit reached ({self.max_pexels_per_hour}/hour)")
                return False
            self.pexels_requests.append(now)
        elif api == 'pixabay':
            self.pixabay_requests = [req for req in self.pixabay_requests if req > one_hour_ago]
            if len(self.pixabay_requests) >= self.max_pixabay_per_hour:
                self.logger.warning(f"Pixabay rate limit reached ({self.max_pixabay_per_hour}/hour)")
                return False
            self.pixabay_requests.append(now)

        return True

    def _get_cache_path(self, query: str, media_type: str) -> Path:
        """Generate cache file path for API response."""
        cache_key = hashlib.md5(f"{query}_{media_type}".encode()).hexdigest()
        return self.cache_dir / f"{cache_key}.json"

    def _is_cache_valid(self, cache_path: Path, max_age_hours: int = 24) -> bool:
        """Check if cached API response is still valid."""
        if not cache_path.exists():
            return False

        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        return age < timedelta(hours=max_age_hours)

    def search_pexels(self, query: str, media_type: str = "video", per_page: int = 15) -> List[Dict]:
        """Search Pexels API for videos or images."""
        if not self.pexels_key:
            self.logger.error("Pexels API key not found")
            return []

        # Check cache first
        cache_path = self._get_cache_path(f"pexels_{query}", media_type)
        if self._is_cache_valid(cache_path):
            self.logger.info(f"Using cached Pexels results for '{query}'")
            with open(cache_path, 'r') as f:
                return json.load(f)

        # Check rate limit
        if not self._check_rate_limit('pexels'):
            return []

        try:
            if media_type == "video":
                url = "https://api.pexels.com/videos/search"
            else:
                url = "https://api.pexels.com/v1/search"

            headers = {"Authorization": self.pexels_key}
            params = {"query": query, "per_page": per_page, "orientation": "portrait"}

            self.logger.info(f"Searching Pexels for '{query}' ({media_type})")
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = data.get('videos' if media_type == "video" else 'photos', [])

            # Cache results
            with open(cache_path, 'w') as f:
                json.dump(results, f)

            self.logger.info(f"Found {len(results)} results on Pexels")
            return results

        except Exception as e:
            self.logger.error(f"Pexels API error: {e}")
            return []

    def search_pixabay(self, query: str, media_type: str = "video", per_page: int = 15) -> List[Dict]:
        """Search Pixabay API for videos or images."""
        if not self.pixabay_key:
            self.logger.error("Pixabay API key not found")
            return []

        # Check cache first
        cache_path = self._get_cache_path(f"pixabay_{query}", media_type)
        if self._is_cache_valid(cache_path):
            self.logger.info(f"Using cached Pixabay results for '{query}'")
            with open(cache_path, 'r') as f:
                return json.load(f)

        # Check rate limit
        if not self._check_rate_limit('pixabay'):
            return []

        try:
            url = "https://pixabay.com/api/videos/" if media_type == "video" else "https://pixabay.com/api/"
            params = {
                "key": self.pixabay_key,
                "q": query,
                "per_page": per_page,
                "orientation": "vertical"
            }

            self.logger.info(f"Searching Pixabay for '{query}' ({media_type})")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = data.get('hits', [])

            # Cache results
            with open(cache_path, 'w') as f:
                json.dump(results, f)

            self.logger.info(f"Found {len(results)} results on Pixabay")
            return results

        except Exception as e:
            self.logger.error(f"Pixabay API error: {e}")
            return []

    def download_media(self, url: str, output_path: str) -> bool:
        """Download media file from URL."""
        try:
            self.logger.info(f"Downloading: {url}")
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            self.logger.info(f"Downloaded: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def process_video(self, input_path: str, output_path: str, target_resolution: Tuple[int, int],
                      target_duration: Optional[float] = None, speed_factor: float = 1.0) -> bool:
        """Process video: crop/scale to target resolution and adjust speed."""
        try:
            width, height = target_resolution
            self.logger.info(f"Processing video: {input_path} -> {width}x{height}")

            # Probe input video
            probe = ffmpeg.probe(input_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            input_width = int(video_info['width'])
            input_height = int(video_info['height'])
            duration = float(video_info.get('duration', 0))

            # Calculate crop/scale parameters
            input_aspect = input_width / input_height
            target_aspect = width / height

            if input_aspect > target_aspect:
                # Input is wider, crop width
                scale_height = input_height
                scale_width = int(scale_height * target_aspect)
                crop_x = (input_width - scale_width) // 2
                crop_y = 0
            else:
                # Input is taller, crop height
                scale_width = input_width
                scale_height = int(scale_width / target_aspect)
                crop_x = 0
                crop_y = (input_height - scale_height) // 2

            # Build FFmpeg filter chain
            stream = ffmpeg.input(input_path)

            video_stream = stream.video

            # Apply speed adjustment if needed
            if speed_factor != 1.0:
                video_stream = video_stream.filter('setpts', f'{1/speed_factor}*PTS')
                self.logger.info(f"Applying speed factor: {speed_factor}x")

            # Crop and scale
            video_stream = video_stream.filter('crop', scale_width, scale_height, crop_x, crop_y)
            video_stream = video_stream.filter('scale', width, height)

            # ALWAYS trim to exact target duration if specified (ensures precise sync)
            if target_duration:
                video_stream = video_stream.trim(duration=target_duration).setpts('PTS-STARTPTS')
                self.logger.info(f"Trimming to exact duration: {target_duration:.2f}s")

            # Output with constant frame rate for better concatenation compatibility
            stream = ffmpeg.output(video_stream, output_path,
                                   vcodec='libx264',
                                   crf=23,
                                   preset='medium',
                                   r=30,  # Force 30fps for consistency
                                   movflags='faststart',
                                   loglevel='error')
            ffmpeg.run(stream, overwrite_output=True)

            self.logger.info(f"Video processed: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Video processing failed: {e}")
            return False

    def process_image(self, input_path: str, output_path: str, target_resolution: Tuple[int, int]) -> bool:
        """Process image: crop/scale to target resolution."""
        try:
            width, height = target_resolution
            self.logger.info(f"Processing image: {input_path} -> {width}x{height}")

            with Image.open(input_path) as img:
                img = img.convert('RGB')
                input_width, input_height = img.size

                # Calculate crop box for center crop
                input_aspect = input_width / input_height
                target_aspect = width / height

                if input_aspect > target_aspect:
                    # Image is wider, crop width
                    new_width = int(input_height * target_aspect)
                    left = (input_width - new_width) // 2
                    box = (left, 0, left + new_width, input_height)
                else:
                    # Image is taller, crop height
                    new_height = int(input_width / target_aspect)
                    top = (input_height - new_height) // 2
                    box = (0, top, input_width, top + new_height)

                img = img.crop(box)
                img = img.resize((width, height), Image.Resampling.LANCZOS)
                img.save(output_path, quality=95)

            self.logger.info(f"Image processed: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
            return False

    def fetch_for_segment(self, config: Dict, segment_id: int, output_dir: str, resolution: Tuple[int, int], audio_dir: Optional[str] = None) -> bool:
        """Fetch and process b-roll for a specific segment."""
        try:
            # Get audio duration for this segment if audio_dir provided
            target_duration = None
            if audio_dir:
                audio_file = Path(audio_dir) / f"segment_{segment_id:03d}.wav"
                if audio_file.exists():
                    try:
                        probe = ffmpeg.probe(str(audio_file))
                        target_duration = float(probe['format']['duration'])
                        self.logger.info(f"Target duration from audio: {target_duration:.2f}s")
                    except Exception as e:
                        self.logger.warning(f"Could not read audio duration: {e}")

            # Find segment in config
            script_segments = config.get('script_segments', [])
            segment = next((s for s in script_segments if s['segment_id'] == segment_id), None)

            if not segment:
                self.logger.error(f"Segment {segment_id} not found in config")
                return False

            broll_clips = segment.get('broll_clips', [])
            if not broll_clips:
                self.logger.warning(f"No b-roll clips defined for segment {segment_id}")
                return False

            self.logger.info(f"Fetching {len(broll_clips)} b-roll clips for segment {segment_id}")

            os.makedirs(output_dir, exist_ok=True)
            success_count = 0

            # Calculate duration per clip if we have a target
            if target_duration and len(broll_clips) > 0:
                duration_per_clip = target_duration / len(broll_clips)
            else:
                duration_per_clip = None

            for idx, clip in enumerate(broll_clips):
                clip_type = clip.get('type', 'video')
                search_query = clip.get('search_query', '')
                min_duration = clip.get('min_duration', 3)

                # Use calculated duration from audio if available, otherwise fall back to JSON
                if duration_per_clip:
                    display_duration = duration_per_clip
                    self.logger.info(f"Clip {idx}: Using calculated duration {display_duration:.2f}s")
                else:
                    display_duration = clip.get('display_duration', min_duration)

                if not search_query:
                    self.logger.warning(f"Clip {idx} has no search_query, skipping")
                    continue

                # Search Pexels first
                results = self.search_pexels(search_query, clip_type)

                # Fallback to Pixabay if Pexels fails
                if not results:
                    self.logger.info("Pexels failed, trying Pixabay...")
                    results = self.search_pixabay(search_query, clip_type)

                if not results:
                    self.logger.error(f"No results found for '{search_query}'")
                    continue

                # Get first suitable result
                media_item = results[0]

                if clip_type == 'video':
                    # Extract video URL (highest quality)
                    if 'video_files' in media_item:  # Pexels
                        video_files = media_item['video_files']
                        # Prefer HD quality
                        video_file = next((v for v in video_files if v.get('quality') == 'hd'), video_files[0])
                        download_url = video_file['link']
                    elif 'videos' in media_item:  # Pixabay
                        videos = media_item['videos']
                        # Get medium quality
                        video_file = videos.get('medium', videos.get('small', {}))
                        download_url = video_file.get('url', '')
                    else:
                        self.logger.error("Unexpected video format")
                        continue

                    # Download video
                    temp_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}_temp.mp4")
                    if not self.download_media(download_url, temp_file):
                        continue

                    # Process video (crop, scale, adjust speed if needed)
                    output_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}.mp4")

                    # Calculate speed adjustment if needed (slow down to stretch duration)
                    speed_factor = 0.85 if display_duration > min_duration else 1.0

                    if self.process_video(temp_file, output_file, resolution, display_duration, speed_factor):
                        success_count += 1
                        os.remove(temp_file)  # Clean up temp file
                    else:
                        self.logger.error(f"Failed to process video clip {idx}")

                else:  # image
                    # Extract image URL
                    if 'src' in media_item:  # Pexels
                        download_url = media_item['src'].get('large2x', media_item['src'].get('large'))
                    elif 'largeImageURL' in media_item:  # Pixabay
                        download_url = media_item['largeImageURL']
                    else:
                        self.logger.error("Unexpected image format")
                        continue

                    # Download image
                    temp_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}_temp.jpg")
                    if not self.download_media(download_url, temp_file):
                        continue

                    # Process image
                    output_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}.jpg")
                    if self.process_image(temp_file, output_file, resolution):
                        success_count += 1
                        os.remove(temp_file)  # Clean up temp file
                    else:
                        self.logger.error(f"Failed to process image clip {idx}")

            self.logger.info(f"B-roll fetch complete: {success_count}/{len(broll_clips)} clips")
            return success_count > 0

        except Exception as e:
            self.logger.error(f"Error fetching b-roll for segment: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Fetch and process b-roll footage")

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--json', type=str, help='Path to JSON configuration file')
    mode_group.add_argument('--query', type=str, help='Search query (standalone mode)')

    # Common arguments
    parser.add_argument('--segment-id', type=int, help='Segment ID to fetch (required for --json)')
    parser.add_argument('--output-dir', type=str, required=True, help='Output directory')
    parser.add_argument('--resolution', type=str, default='1080x1920', help='Target resolution (WxH)')
    parser.add_argument('--type', type=str, choices=['video', 'image'], default='video',
                        help='Media type (for --query mode)')
    parser.add_argument('--duration', type=float, help='Target duration in seconds (for --query mode)')
    parser.add_argument('--api-keys', type=str, default='config/api_keys.json',
                        help='Path to API keys JSON file')
    parser.add_argument('--audio-dir', type=str, help='Directory containing audio segments (to match duration)')
    parser.add_argument('--log-file', type=str, help='Path to log file')

    args = parser.parse_args()

    # Validate arguments
    if args.json and not args.segment_id:
        parser.error("--json requires --segment-id")

    # Parse resolution
    try:
        width, height = map(int, args.resolution.split('x'))
        resolution = (width, height)
    except:
        print(f"Error: Invalid resolution format: {args.resolution}", file=sys.stderr)
        sys.exit(1)

    try:
        # Load API keys
        if not os.path.exists(args.api_keys):
            print(f"Error: API keys file not found: {args.api_keys}", file=sys.stderr)
            print("Copy config/api_keys.json.example to config/api_keys.json and add your keys")
            sys.exit(1)

        with open(args.api_keys, 'r') as f:
            api_keys = json.load(f)

        # Initialize fetcher
        fetcher = BRollFetcher(api_keys, log_file=args.log_file)

        # Process based on mode
        if args.json:
            # Helper script mode
            with open(args.json, 'r', encoding='utf-8') as f:
                config = json.load(f)

            success = fetcher.fetch_for_segment(config, args.segment_id, args.output_dir, resolution, args.audio_dir)
        else:
            # Standalone mode
            # Search for media
            results = fetcher.search_pexels(args.query, args.type)
            if not results:
                results = fetcher.search_pixabay(args.query, args.type)

            if not results:
                print(f"No results found for '{args.query}'", file=sys.stderr)
                sys.exit(1)

            # Download and process first result
            media_item = results[0]
            success = False

            if args.type == 'video':
                if 'video_files' in media_item:
                    video_files = media_item['video_files']
                    video_file = next((v for v in video_files if v.get('quality') == 'hd'), video_files[0])
                    download_url = video_file['link']
                elif 'videos' in media_item:
                    videos = media_item['videos']
                    video_file = videos.get('medium', videos.get('small', {}))
                    download_url = video_file.get('url', '')

                temp_file = os.path.join(args.output_dir, "temp_video.mp4")
                output_file = os.path.join(args.output_dir, "output_video.mp4")

                if fetcher.download_media(download_url, temp_file):
                    success = fetcher.process_video(temp_file, output_file, resolution, args.duration)
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
            else:
                if 'src' in media_item:
                    download_url = media_item['src'].get('large2x', media_item['src'].get('large'))
                elif 'largeImageURL' in media_item:
                    download_url = media_item['largeImageURL']

                temp_file = os.path.join(args.output_dir, "temp_image.jpg")
                output_file = os.path.join(args.output_dir, "output_image.jpg")

                if fetcher.download_media(download_url, temp_file):
                    success = fetcher.process_image(temp_file, output_file, resolution)
                    if os.path.exists(temp_file):
                        os.remove(temp_file)

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
