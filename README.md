# AI-Powered Short-Form Video Generation Pipeline

Transform JSON configuration files into publish-ready short-form videos for YouTube Shorts, TikTok, and Instagram Reels.

## Features

- **Automated TTS**: GPU-accelerated text-to-speech using Kokoro-ONNX
- **Smart B-Roll**: Automatic footage fetching from Pexels and Pixabay APIs
- **Animated Subtitles**: Word-by-word color-change subtitles using faster-whisper
- **Background Music**: Automatic genre-based music selection and mixing
- **Multi-Platform**: Optimized for TikTok, YouTube Shorts, Instagram Reels, and YouTube Long
- **Modular Design**: Each component works standalone for testing/debugging

## System Requirements

- **OS**: Windows 11 (tested), Windows 10, or Linux
- **Python**: 3.12 or 3.13 (recommended) - Kokoro-ONNX requires Python >=3.12
- **GPU**: NVIDIA RTX 4070 SUPER (CUDA 12.x) for GPU acceleration
- **FFmpeg**: Must be installed and in PATH
- **Disk Space**: ~5GB for dependencies + space for generated videos

## Installation

### 1. Clone or Download Repository

```bash
cd C:\Users\roman\code\content_creation_pipeline
```

### 2. Create Virtual Environment

Using Python 3.13 (required for kokoro-onnx):
```bash
C:/Python313/python.exe -m venv venv
```

**Note**: Python 3.12+ is required. Kokoro-ONNX doesn't work on Python 3.10 or 3.11.

### 3. Activate Virtual Environment

**PowerShell:**
```powershell
.\venv\Scripts\Activate.ps1
```

**Command Prompt:**
```cmd
venv\Scripts\activate.bat
```

**Git Bash:**
```bash
source venv/Scripts/activate
```

### 4. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Note**: Installation may take 10-15 minutes due to large packages (faster-whisper, ONNX runtime, etc.)

### 5. Install FFmpeg

**Windows (using winget):**
```powershell
winget install FFmpeg
```

**Windows (manual):**
1. Download from https://www.gyan.dev/ffmpeg/builds/
2. Extract to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to System PATH

**Verify installation:**
```bash
ffmpeg -version
```

### 6. Configure API Keys

```bash
cp config/api_keys.json.example config/api_keys.json
```

Edit `config/api_keys.json` and add your API keys:

```json
{
  "pexels": "YOUR_PEXELS_API_KEY",
  "pixabay": "YOUR_PIXABAY_API_KEY"
}
```

**Get API Keys:**
- Pexels: https://www.pexels.com/api/ (free, 200 requests/hour)
- Pixabay: https://pixabay.com/api/docs/ (free, 5000 requests/hour)

### 7. Setup Music Library (Optional but Recommended)

Create genre folders and add background music:

```
music/
├── lofi/
│   ├── track1.mp3
│   └── track2.mp3
├── trap/
├── hiphop/
├── edm/
└── ambient/
```

**Where to find royalty-free music:**
- YouTube Audio Library
- Pixabay Music
- Free Music Archive (FMA)
- Bensound

## Quick Start

### Generate Your First Video

```bash
python generate_video.py input_jsons/test_video_config.json

# Or, if you want to remove incomplete previous runs first:
python generate_video.py input_jsons/test_video_config.json --clean
```

This will:
1. Create a project folder in `generated_videos/`
2. Generate TTS audio for each segment
3. Download and process b-roll footage
4. Generate and overlay animated subtitles
5. Mix background music
6. Output final video: `generated_videos/motivational_morning_routine_TIMESTAMP/final_output.mp4`

### View Output

```bash
ls generated_videos/motivational_morning_routine_*/
```

Output structure:
```
generated_videos/motivational_morning_routine_20260129_153045/
├── input.json                 # Copy of input configuration
├── audio_segments/            # Generated TTS audio
│   ├── segment_001.wav
│   ├── segment_002.wav
│   └── ...
├── broll/                     # Downloaded b-roll clips
│   ├── segment_001_clip_000.mp4
│   └── ...
├── subtitles/                 # Videos with burned subtitles
│   ├── segment_001_clip_000.mp4
│   └── ...
├── generation.log             # Detailed generation log
└── final_output.mp4          # Final ready-to-upload video
```

### Re-running Videos

**Default Behavior**: Each run creates a new timestamped folder, keeping all previous attempts.

```bash
generated_videos/
├── motivational_morning_routine_20260129_153045/  # First attempt
├── motivational_morning_routine_20260129_160230/  # Second attempt
└── motivational_morning_routine_20260129_162145/  # Third attempt
```

**Clean Mode**: Use `--clean` to automatically remove incomplete previous runs before starting:

```bash
python generate_video.py input_jsons/test_video_config.json --clean
```

This will:
- Keep completed runs (those with `final_output.mp4`)
- Delete incomplete runs (failed or interrupted generations)
- Then create a fresh run

**Manual Cleanup**: To remove all runs for a specific video:
```bash
rm -rf generated_videos/motivational_morning_routine_*
# Then generate fresh
python generate_video.py input_jsons/test_video_config.json
```

## JSON Configuration Schema

```json
{
  "video_name": "string",
  "target_platform": "youtube_shorts | tiktok | instagram_reels | youtube_long",
  "target_duration_seconds": 30,
  "background_music_genre": "lofi | trap | hiphop | edm | ambient",
  "voice_name": "af_heart | af_bella | af_sarah | af_adam | af_michael",
  "script_segments": [
    {
      "segment_id": 1,
      "audio_text": "Text to be spoken",
      "duration_target_seconds": 5,
      "broll_clips": [
        {
          "type": "video",
          "search_query": "sunset beach waves",
          "min_duration": 3,
          "display_duration": 5
        }
      ]
    }
  ],
  "metadata": {
    "niche": "motivation",
    "hook_type": "question",
    "created_at": "2026-01-29T10:00:00Z"
  }
}
```

## Prompt Usage (`generate_vid_json_prompt.md`):

To use this prompt:
"Generate a viral video JSON for the [NICHE] niche targeting [PLATFORM]. The topic should be about [SPECIFIC TOPIC OR LEAVE BLANK FOR YOUR CHOICE]."

Example:
"Generate a viral video JSON for the personal finance niche targeting YouTube Shorts. Focus on hidden money leaks people don't notice."

## Helper Scripts (Standalone Usage)

Each helper script can be run independently for testing. **Note**: The `--json` flag takes your VIDEO configuration JSON file (e.g., `test_video_config.json`), NOT the settings file.

### 1. Audio Generator
**Purpose**: Converts script text to speech using Kokoro TTS

```bash
# Helper mode: Generate from video config JSON
python scripts/audio_generator.py --json input_jsons/test_video_config.json --output-dir ./audio

# Standalone mode: Test single line
python scripts/audio_generator.py --text "Hello world!" --voice af_bella --output hello.wav
```

**Available voices:**
- `af_bella` - Female, American English (default)
- `af_heart` - Female, American English (warm)
- `af_sarah` - Female, American English (clear)
- `af_adam` - Male, American English
- `af_michael` - Male, American English (deep)

### 2. B-Roll Fetcher
**Purpose**: Downloads and crops video/image footage from Pexels/Pixabay

```bash
# Helper mode: Fetch for specific segment from video config
python scripts/broll_fetcher.py --json input_jsons/test_video_config.json --segment-id 1 --output-dir ./broll --resolution 1080x1920

# Standalone mode: Test single search
python scripts/broll_fetcher.py --query "sunset beach" --type video --output-dir ./broll --resolution 1080x1920
```

### 3. Subtitle Generator
**Purpose**: Transcribes audio and burns animated subtitles onto videos

```bash
# Helper mode: Process all segments (needs both audio AND video directories)
# --audio-dir: where TTS audio files are
# --video-dir: where b-roll video clips are (to add subtitles to them)
python scripts/subtitle_generator.py --audio-dir ./audio_segments --video-dir ./broll --output-dir ./subtitles --style tiktok

# Standalone mode: Add subtitles to a single existing video
python scripts/subtitle_generator.py --video input.mp4 --output output.mp4 --style youtube_shorts

# SRT only: Generate subtitle file without burning
python scripts/subtitle_generator.py --video input.mp4 --output output.srt --srt-only
```

**Why does it need both audio-dir and video-dir?**
- It transcribes the audio files to get word timestamps
- Then overlays those subtitles onto the corresponding video clips

### 4. Video Assembler
**Purpose**: Combines all segments, adds background music, creates final MP4

```bash
# Combines audio + subtitled videos + background music
python scripts/video_assembler.py --json input_jsons/test_video_config.json --project-dir ./generated_videos/video_name_TIMESTAMP --music-genre lofi
```

**What it does:**
1. Concatenates all video segments
2. Syncs audio with video
3. Adds background music (random track from `music/GENRE/` folder)
4. Mixes audio levels (-22dB for music)
5. Outputs final video ready for upload

## Configuration Options

### Platform Resolutions

| Platform | Resolution | Aspect Ratio |
|----------|-----------|--------------|
| YouTube Shorts | 1080x1920 | 9:16 |
| TikTok | 1080x1920 | 9:16 |
| Instagram Reels | 1080x1920 | 9:16 |
| YouTube Long | 1920x1080 | 16:9 |

### Subtitle Styles

**TikTok Style:**
- Font: Montserrat Bold
- Size: 28px
- Position: Center-bottom (150px from bottom)
- Animation: Word-by-word color change (yellow → white)
- Outline: 3px black

**YouTube Shorts Style:**
- Font: Impact
- Size: 32px
- Position: Center-bottom (150px from bottom)
- Animation: Word-by-word color change (yellow → white)
- Outline: 3px black

### Background Music Settings

Default settings (configurable in `config/settings.json`):
- Volume: -22dB (background level)
- Fade in: 2 seconds
- Fade out: 2 seconds
- Behavior: Loop/trim to match video duration

## Troubleshooting

### "Kokoro-ONNX not found" Error

Make sure you're using Python 3.12 or 3.13:
```bash
python --version  # Should show 3.12 or 3.13
```

Then install:
```bash
pip install kokoro-onnx onnxruntime-gpu --upgrade
```

### "CUDA not available" Warning

Check GPU drivers:
```bash
nvidia-smi
```

Install/update CUDA toolkit 12.x from: https://developer.nvidia.com/cuda-downloads

### "API rate limit exceeded"

Pexels allows 200 requests/hour. The system caches API responses for 24 hours to minimize requests. If you hit the limit:
- Wait 1 hour for rate limit reset
- Use Pixabay as fallback (automatically attempted)
- Check cache: `.cache/` folder contains cached API responses

### "FFmpeg not found"

Verify FFmpeg is in PATH:
```bash
where ffmpeg  # Windows
which ffmpeg  # Linux/Mac
```

Add to PATH or reinstall FFmpeg.

### "No music files found"

The system will generate videos without background music if the `music/` folder is empty. To add music:
1. Create genre folders: `music/lofi/`, `music/trap/`, etc.
2. Add MP3 or WAV files to each folder

### Duration Mismatch Warning

If final video duration differs from target by more than 1 second:
- Check b-roll clip durations (may be too short)
- Adjust `display_duration` in JSON configuration
- Use longer audio segments
- System automatically slows clips (0.8-0.9x) to stretch duration

### Subtitle Font Not Found (Linux)

Install Impact font:
```bash
sudo apt install ttf-mscorefonts-installer
```

Or modify font path in `scripts/subtitle_generator.py`:
```python
fontfile='/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'
```

## Performance Optimization

### GPU Acceleration

Ensure CUDA is properly configured:
```bash
python -c "import torch; print(torch.cuda.is_available())"
```

Should output: `True`

### Faster Generation

1. **Use smaller Whisper model**: Change `model_size` in subtitle generator
   - `tiny`: Fastest, less accurate
   - `base`: Balanced (default)
   - `small`: Better accuracy, slower
   - `medium`: High accuracy, much slower

2. **Lower video quality**: Adjust CRF in video assembler (higher = smaller file)
   - Default: CRF 23 (high quality)
   - Recommended range: 18-28

3. **Reduce resolution**: For testing, use lower resolution
   ```bash
   python scripts/broll_fetcher.py --resolution 720x1280 ...
   ```

## Advanced Usage

### Custom Voice Speed

Modify `kokoro_settings` in `config/settings.json`:
```json
{
  "kokoro_settings": {
    "speed": 1.1,  // 1.0 = normal, 1.1 = 10% faster
    "use_gpu": true
  }
}
```

### Multiple Videos Batch Processing

Create multiple JSON configs and process in loop:
```bash
for config in configs/*.json; do
    python generate_video.py "$config"
done
```

### Custom Subtitle Positioning

Edit `subtitle_styles` in `config/settings.json`:
```json
{
  "position_y": "h-200",  // Move up (default: h-150)
  "fontsize": 36          // Larger text
}
```

## Project Structure

```
content_creation_pipeline/
├── venv/                      # Python virtual environment
├── config/
│   ├── api_keys.json         # API credentials (git ignored)
│   ├── api_keys.json.example # Template for API keys
│   └── settings.json         # Configuration settings
├── music/                    # Background music library (git ignored)
│   ├── lofi/
│   ├── trap/
│   ├── hiphop/
│   ├── edm/
│   └── ambient/
├── generated_videos/         # Output directory (git ignored)
├── input_jsons/              # Input configuration files
│   ├── example_input.json    # Simple example config
│   └── test_video_config.json # Full featured sample
├── scripts/                  # Helper scripts
│   ├── audio_generator.py
│   ├── broll_fetcher.py
│   ├── subtitle_generator.py
│   ├── video_assembler.py
│   └── verify_setup.py       # Setup validation script
├── generate_video.py         # Main orchestrator
├── generate_vid_json_prompt.md # Guide for creating JSON configs
├── requirements.txt          # Python dependencies
├── .gitignore
└── README.md
```

## Development

### Testing Individual Components

**Test TTS generation:**
```bash
python scripts/audio_generator.py --text "Testing one two three" --voice af_bella --output test.wav
```

**Test b-roll fetching:**
```bash
python scripts/broll_fetcher.py --query "coding on laptop" --type video --output-dir ./test_broll --resolution 1080x1920
```

**Test subtitle generation:**
```bash
python scripts/subtitle_generator.py --video test.mp4 --output test_subtitled.mp4 --style tiktok
```

### Logging

All operations are logged to:
- Console (INFO level)
- `{project_dir}/generation.log` (detailed log with timestamps)

Enable verbose logging:
```bash
python generate_video.py config.json --verbose
```

## License

This project is provided as-is for educational and commercial use. Ensure you have proper rights to any background music and comply with Pexels/Pixabay API terms of service.

## API Terms of Service

- **Pexels**: Attribution not required, 200 requests/hour
- **Pixabay**: Attribution not required, 5000 requests/hour
- Both APIs are free but require registration

## Support

For issues, questions, or feature requests:
1. Check this README for troubleshooting
2. Review `generation.log` in your project folder
3. Test helper scripts individually to isolate issues

## Roadmap

Potential future enhancements:
- [ ] Support for more TTS engines (ElevenLabs, Azure TTS)
- [ ] AI-powered b-roll selection based on sentiment analysis
- [ ] Multiple subtitle animation styles
- [ ] Automatic thumbnail generation
- [ ] Direct upload to YouTube/TikTok APIs
- [ ] Web UI for configuration
- [ ] Template library for common video types

## Credits

- **Kokoro-ONNX**: TTS engine
- **faster-whisper**: Subtitle transcription
- **Pexels & Pixabay**: Stock footage APIs
- **FFmpeg**: Video processing backbone

---

**Ready to generate your first video?**

```bash
# First, verify your setup
python scripts/verify_setup.py

# Then generate your video
python generate_video.py input_jsons/test_video_config.json
```
