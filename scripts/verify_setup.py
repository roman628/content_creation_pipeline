#!/usr/bin/env python3
"""
Setup Verification Script
Checks if all dependencies and configurations are properly set up
"""

import sys
import os
import subprocess
from pathlib import Path


def check_python_version():
    """Check Python version."""
    print("Checking Python version...", end=" ")
    version = sys.version_info
    if version.major == 3 and version.minor >= 10:
        print(f"[OK] Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"[FAIL] Python {version.major}.{version.minor}.{version.micro} (need 3.10+)")
        return False


def check_package(package_name, import_name=None):
    """Check if a Python package is installed."""
    if import_name is None:
        import_name = package_name

    print(f"Checking {package_name}...", end=" ")
    try:
        __import__(import_name)
        print("[OK]")
        return True
    except ImportError:
        print(f"[FAIL] Not installed")
        return False


def check_ffmpeg():
    """Check if FFmpeg is installed and in PATH."""
    print("Checking FFmpeg...", end=" ")
    try:
        result = subprocess.run(['ffmpeg', '-version'],
                              capture_output=True,
                              text=True,
                              timeout=5)
        if result.returncode == 0:
            # Extract version from output
            version_line = result.stdout.split('\n')[0]
            print(f"[OK] {version_line}")
            return True
        else:
            print("[FAIL] FFmpeg found but returned error")
            return False
    except FileNotFoundError:
        print("[FAIL] Not found in PATH")
        return False
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def check_cuda():
    """Check if CUDA is available for GPU acceleration."""
    print("Checking CUDA/GPU support...", end=" ")
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            print(f"[OK] Available ({gpu_name})")
            return True
        else:
            print("[WARN] Not available (will use CPU)")
            return None  # Not critical
    except ImportError:
        print("[WARN] PyTorch not installed (can't verify CUDA)")
        return None
    except Exception as e:
        print(f"[WARN] {e}")
        return None


def check_api_keys():
    """Check if API keys are configured."""
    print("Checking API keys...", end=" ")
    api_keys_path = Path("config/api_keys.json")

    if not api_keys_path.exists():
        print("[FAIL] config/api_keys.json not found")
        return False

    try:
        import json
        with open(api_keys_path, 'r') as f:
            keys = json.load(f)

        pexels_ok = keys.get('pexels', '').startswith('YOUR_') == False and len(keys.get('pexels', '')) > 10
        pixabay_ok = keys.get('pixabay', '').startswith('YOUR_') == False and len(keys.get('pixabay', '')) > 10

        if pexels_ok and pixabay_ok:
            print("[OK] Both keys configured")
            return True
        elif pexels_ok or pixabay_ok:
            print("[WARN] Only one key configured (still usable)")
            return None
        else:
            print("[FAIL] Keys not configured (need at least one)")
            return False
    except Exception as e:
        print(f"[FAIL] Error reading: {e}")
        return False


def check_directories():
    """Check if required directories exist."""
    print("Checking project structure...", end=" ")

    required_dirs = ['scripts', 'config']
    required_files = ['generate_video.py', 'requirements.txt']

    missing = []

    for d in required_dirs:
        if not Path(d).exists():
            missing.append(d)

    for f in required_files:
        if not Path(f).exists():
            missing.append(f)

    if not missing:
        print("[OK] All required files/folders present")
        return True
    else:
        print(f"[FAIL] Missing: {', '.join(missing)}")
        return False


def check_scripts():
    """Check if helper scripts exist."""
    print("Checking helper scripts...", end=" ")

    scripts = [
        'scripts/audio_generator.py',
        'scripts/broll_fetcher.py',
        'scripts/subtitle_generator.py',
        'scripts/video_assembler.py'
    ]

    missing = [s for s in scripts if not Path(s).exists()]

    if not missing:
        print("[OK] All 4 helper scripts present")
        return True
    else:
        print(f"[FAIL] Missing: {', '.join(missing)}")
        return False


def main():
    # Change to project root directory (parent of scripts/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    os.chdir(project_root)

    print("""
===========================================================
        Setup Verification for Video Pipeline
===========================================================
    """)

    results = {}

    # Critical checks
    print("\n[CRITICAL REQUIREMENTS]")
    results['python'] = check_python_version()
    results['ffmpeg'] = check_ffmpeg()
    results['structure'] = check_directories()
    results['scripts'] = check_scripts()

    # Package checks
    print("\n[PYTHON PACKAGES]")
    results['requests'] = check_package('requests')
    results['pillow'] = check_package('pillow', 'PIL')
    results['pydub'] = check_package('pydub')
    results['ffmpeg-python'] = check_package('ffmpeg-python', 'ffmpeg')
    results['faster-whisper'] = check_package('faster-whisper', 'faster_whisper')
    results['kokoro'] = check_package('kokoro')

    # Optional checks
    print("\n[OPTIONAL FEATURES]")
    results['cuda'] = check_cuda()
    results['api_keys'] = check_api_keys()

    # Music library (optional)
    music_dir = Path("music")
    if music_dir.exists():
        genres = [d.name for d in music_dir.iterdir() if d.is_dir()]
        if genres:
            print(f"Music library... [OK] Found {len(genres)} genre(s): {', '.join(genres[:3])}")
        else:
            print("Music library... [WARN] Folder exists but empty")
    else:
        print("Music library... [WARN] Not created (videos will have no background music)")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    critical_passed = all([
        results['python'],
        results['ffmpeg'],
        results['structure'],
        results['scripts']
    ])

    packages_passed = all([
        results['requests'],
        results['pillow'],
        results['pydub'],
        results['ffmpeg-python'],
        results['faster-whisper'],
        results['kokoro']
    ])

    if critical_passed and packages_passed:
        print("[OK] All critical requirements met!")
        print("\nYou're ready to generate videos:")
        print("  python generate_video.py input_jsons/test_video_config.json")

        if results['api_keys'] == False:
            print("\n[WARN] WARNING: API keys not configured")
            print("  B-roll fetching will fail without API keys")
            print("  Configure them in config/api_keys.json")

        if results['cuda'] != True:
            print("\n[WARN] NOTE: GPU acceleration not available")
            print("  Generation will be slower but still functional")

        return 0
    else:
        print("[FAIL] Some requirements are missing\n")

        if not critical_passed:
            print("CRITICAL ISSUES:")
            if not results['python']:
                print("  - Python 3.10+ required")
            if not results['ffmpeg']:
                print("  - FFmpeg not found (install: winget install FFmpeg)")
            if not results['structure'] or not results['scripts']:
                print("  - Project files missing or corrupted")

        if not packages_passed:
            print("\nPACKAGE ISSUES:")
            print("  Run: pip install -r requirements.txt")

        print("\nRefer to README.md for setup instructions")
        return 1


if __name__ == "__main__":
    sys.exit(main())
