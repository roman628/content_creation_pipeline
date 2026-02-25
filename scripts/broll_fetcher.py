#!/usr/bin/env python3
"""
B-Roll Fetcher
Downloads and processes video/image assets from Pexels and Pixabay APIs.
Supports fast 2-3 second cuts with speed adjustment for engaging short-form video.
"""

import argparse
import json
import logging
import math
import os
import random
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
                self.logger.info(f"Applying speed factor: {speed_factor:.2f}x")

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

    def process_image(self, input_path: str, output_path: str, target_resolution: Tuple[int, int],
                      target_duration: Optional[float] = None) -> bool:
        """Process image: crop/scale to target resolution and convert to video clip.

        Always outputs an .mp4 video (still frame) so the assembler can concatenate it
        with other video clips seamlessly.
        """
        try:
            width, height = target_resolution
            self.logger.info(f"Processing image: {input_path} -> {width}x{height}")

            # First crop/scale the image
            with Image.open(input_path) as img:
                img = img.convert('RGB')
                input_width, input_height = img.size

                input_aspect = input_width / input_height
                target_aspect = width / height

                if input_aspect > target_aspect:
                    new_width = int(input_height * target_aspect)
                    left = (input_width - new_width) // 2
                    box = (left, 0, left + new_width, input_height)
                else:
                    new_height = int(input_width / target_aspect)
                    top = (input_height - new_height) // 2
                    box = (0, top, input_width, top + new_height)

                img = img.crop(box)
                img = img.resize((width, height), Image.Resampling.LANCZOS)

                # Save processed image to temp file
                temp_img = output_path.replace('.mp4', '_img.jpg')
                img.save(temp_img, quality=95)

            # Convert still image to video clip using FFmpeg
            duration = target_duration if target_duration else 3.0
            self.logger.info(f"Converting image to {duration:.2f}s video clip")

            # Ensure output is .mp4
            if not output_path.endswith('.mp4'):
                output_path = output_path.rsplit('.', 1)[0] + '.mp4'

            stream = ffmpeg.input(temp_img, loop=1, t=duration, framerate=30)
            stream = ffmpeg.output(stream, output_path,
                                   vcodec='libx264',
                                   crf=23,
                                   preset='medium',
                                   r=30,
                                   pix_fmt='yuv420p',
                                   movflags='faststart',
                                   loglevel='error')
            ffmpeg.run(stream, overwrite_output=True)

            # Cleanup temp image
            if os.path.exists(temp_img):
                os.remove(temp_img)

            self.logger.info(f"Image converted to video: {output_path}")
            return True

        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
            return False

    def _expand_search_queries(self, broll_clips: List[Dict], num_needed: int) -> List[Dict]:
        """Expand clip list by generating query variations when more clips are needed."""
        expanded = list(broll_clips)
        suffixes = ['cinematic', 'aerial', 'close up', 'dramatic', 'slow motion',
                     'abstract', 'nature', 'urban', 'texture', 'background']
        idx = 0
        while len(expanded) < num_needed:
            base_clip = broll_clips[idx % len(broll_clips)]
            variation = dict(base_clip)
            suffix = suffixes[(len(expanded) - len(broll_clips)) % len(suffixes)]
            variation['search_query'] = f"{base_clip['search_query']} {suffix}"
            expanded.append(variation)
            idx += 1
        return expanded[:num_needed]

    def _get_download_url(self, media_item: Dict, clip_type: str) -> Optional[str]:
        """Extract download URL from API result item."""
        if clip_type == 'video':
            if 'video_files' in media_item:  # Pexels
                video_files = media_item['video_files']
                video_file = next((v for v in video_files if v.get('quality') == 'hd'), video_files[0])
                return video_file['link']
            elif 'videos' in media_item:  # Pixabay
                videos = media_item['videos']
                video_file = videos.get('medium', videos.get('small', {}))
                return video_file.get('url', '')
        else:
            if 'src' in media_item:  # Pexels
                return media_item['src'].get('large2x', media_item['src'].get('large'))
            elif 'largeImageURL' in media_item:  # Pixabay
                return media_item['largeImageURL']
        return None

    def _search_with_fallback(self, query: str, clip_type: str, result_index: int = 0) -> Optional[Dict]:
        """Search Pexels then Pixabay, return a single result item."""
        results = self.search_pexels(query, clip_type)
        if not results:
            results = self.search_pixabay(query, clip_type)
        if not results:
            return None
        # Use result_index to get different results from same query
        idx = result_index % len(results)
        return results[idx]

    def fetch_for_segment(self, config: Dict, segment_id: int, output_dir: str,
                          resolution: Tuple[int, int], segment_duration: Optional[float] = None,
                          audio_dir: Optional[str] = None,
                          cut_frequency: float = 2.5,
                          speed_range: Tuple[float, float] = (1.2, 2.0)) -> bool:
        """Fetch and process b-roll for a specific segment with fast cuts."""
        try:
            # Get segment duration from audio file if not provided directly
            if segment_duration is None and audio_dir:
                audio_file = Path(audio_dir) / f"segment_{segment_id:03d}.wav"
                if audio_file.exists():
                    try:
                        probe = ffmpeg.probe(str(audio_file))
                        segment_duration = float(probe['format']['duration'])
                        self.logger.info(f"Target duration from audio: {segment_duration:.2f}s")
                    except Exception as e:
                        self.logger.warning(f"Could not read audio duration: {e}")

            if segment_duration is None:
                self.logger.error(f"No segment duration available for segment {segment_id}")
                return False

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

            # Calculate how many clips we need for fast cuts
            num_clips_needed = max(1, math.ceil(segment_duration / cut_frequency))
            clip_display_duration = segment_duration / num_clips_needed

            self.logger.info(
                f"Segment {segment_id}: {segment_duration:.2f}s, "
                f"need {num_clips_needed} clips at {clip_display_duration:.2f}s each"
            )

            # Expand clips if we need more than what's in the JSON
            if num_clips_needed > len(broll_clips):
                self.logger.info(
                    f"Expanding from {len(broll_clips)} to {num_clips_needed} clips via query variations"
                )
                broll_clips = self._expand_search_queries(broll_clips, num_clips_needed)

            os.makedirs(output_dir, exist_ok=True)
            success_count = 0

            for idx, clip in enumerate(broll_clips[:num_clips_needed]):
                clip_type = clip.get('type', 'video')
                search_query = clip.get('search_query', '')

                if not search_query:
                    self.logger.warning(f"Clip {idx} has no search_query, skipping")
                    continue

                # Search with fallback, use idx to get different results
                media_item = self._search_with_fallback(search_query, clip_type, result_index=idx)

                if not media_item:
                    self.logger.error(f"No results found for '{search_query}'")
                    continue

                download_url = self._get_download_url(media_item, clip_type)
                if not download_url:
                    self.logger.error(f"Could not extract download URL for '{search_query}'")
                    continue

                if clip_type == 'video':
                    # Download video
                    temp_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}_temp.mp4")
                    if not self.download_media(download_url, temp_file):
                        continue

                    # Apply random speed factor for more dynamic feel
                    speed_factor = random.uniform(speed_range[0], speed_range[1])

                    output_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}.mp4")
                    if self.process_video(temp_file, output_file, resolution, clip_display_duration, speed_factor):
                        success_count += 1
                        os.remove(temp_file)
                    else:
                        self.logger.error(f"Failed to process video clip {idx}")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)

                else:  # image
                    temp_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}_temp.jpg")
                    if not self.download_media(download_url, temp_file):
                        continue

                    # Output as .mp4 (still frame converted to video) so assembler can concatenate
                    output_file = os.path.join(output_dir, f"segment_{segment_id:03d}_clip_{idx:03d}.mp4")
                    if self.process_image(temp_file, output_file, resolution, clip_display_duration):
                        success_count += 1
                        os.remove(temp_file)
                    else:
                        self.logger.error(f"Failed to process image clip {idx}")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)

            self.logger.info(f"B-roll fetch complete: {success_count}/{num_clips_needed} clips for segment {segment_id}")
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
    parser.add_argument('--log-file', type=str, help='Path to log file')

    # New v2 arguments
    parser.add_argument('--segment-duration', type=float,
                        help='Duration of this segment in seconds (from timestamps)')
    parser.add_argument('--audio-dir', type=str,
                        help='Directory containing audio segments (legacy, use --segment-duration instead)')
    parser.add_argument('--cut-frequency', type=float, default=2.5,
                        help='Target b-roll cut frequency in seconds (default: 2.5)')
    parser.add_argument('--speed-min', type=float, default=1.2,
                        help='Minimum speed factor for clips (default: 1.2)')
    parser.add_argument('--speed-max', type=float, default=2.0,
                        help='Maximum speed factor for clips (default: 2.0)')

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

            success = fetcher.fetch_for_segment(
                config, args.segment_id, args.output_dir, resolution,
                segment_duration=args.segment_duration,
                audio_dir=args.audio_dir,
                cut_frequency=args.cut_frequency,
                speed_range=(args.speed_min, args.speed_max)
            )
        else:
            # Standalone mode
            results = fetcher.search_pexels(args.query, args.type)
            if not results:
                results = fetcher.search_pixabay(args.query, args.type)

            if not results:
                print(f"No results found for '{args.query}'", file=sys.stderr)
                sys.exit(1)

            media_item = results[0]
            success = False

            download_url = fetcher._get_download_url(media_item, args.type)
            if download_url:
                if args.type == 'video':
                    temp_file = os.path.join(args.output_dir, "temp_video.mp4")
                    output_file = os.path.join(args.output_dir, "output_video.mp4")
                    if fetcher.download_media(download_url, temp_file):
                        success = fetcher.process_video(temp_file, output_file, resolution, args.duration)
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                else:
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
