#!/usr/bin/env python3
"""Voice message transcription — converts Telegram voice audio to text.

Usage:
  voice_transcribe.py <file_path>              # Transcribe a cached audio file
  voice_transcribe.py --google-free <wav>      # Force Google free STT
  voice_transcribe.py --whisper <wav>          # Force local Whisper
  voice_transcribe.py --openai <wav>           # Force OpenAI Whisper
"""
import json, sys, os, subprocess, tempfile, argparse
from pathlib import Path

def convert_to_wav(input_path, output_path=None):
    """Convert any audio format to WAV (16kHz, mono) using ffmpeg."""
    if output_path is None:
        output_path = str(Path(input_path).with_suffix(".wav"))

    result = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", output_path],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        return None, f"ffmpeg error: {result.stderr[:200]}"
    return output_path, None

def transcribe_google_free(wav_path):
    """Transcribe using Google's free (unregistered) STT — limited, no key needed."""
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = r.record(source)
        text = r.recognize_google(audio, language="en-US")
        return text.strip(), None
    except ImportError:
        return None, "speech_recognition not installed"
    except Exception as e:
        return None, str(e)

def transcribe_openai(wav_path):
    """Transcribe using OpenAI Whisper API."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY not set"

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        with open(wav_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en"
            )
        return result.text.strip(), None
    except ImportError:
        return None, "openai package not installed"
    except Exception as e:
        return None, str(e)

def transcribe_local_whisper(wav_path):
    """Transcribe using local Whisper model."""
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(wav_path, language="en")
        return result.get("text", "").strip(), None
    except ImportError:
        return None, "whisper package not installed (pip install openai-whisper)"
    except Exception as e:
        return None, str(e)

def transcribe(input_path, force_backend=None):
    """Full pipeline: convert + transcribe, trying multiple backends."""
    # Convert to WAV if needed
    if input_path.endswith(".wav"):
        wav_path = input_path
    else:
        wav_path, err = convert_to_wav(input_path)
        if err:
            return {"success": False, "error": err}

    # Try backends in priority order
    backends = [
        ("whisper-local", transcribe_local_whisper),
        ("openai", transcribe_openai),
        ("google-free", transcribe_google_free),
    ]

    if force_backend:
        backends = [b for b in backends if b[0] == force_backend]
        if not backends:
            return {"success": False, "error": f"Unknown backend: {force_backend}"}

    for name, func in backends:
        text, err = func(wav_path)
        if text is not None:
            # Backend responded (even if empty transcription)
            text = text.strip()
            # Clean up WAV if we created it
            if wav_path != input_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except:
                    pass
            return {"success": True, "text": text, "backend": name,
                    "wav_path": wav_path if wav_path != input_path else None,
                    "note": "Audio processed but no speech detected" if not text else None}
        if err:
            continue  # Try next backend

    return {"success": False, "error": "No working STT backend found. Install whisper: pip install openai-whisper, or set OPENAI_API_KEY"}

def main():
    parser = argparse.ArgumentParser(description="Voice message transcription")
    parser.add_argument("file", help="Audio file to transcribe")
    parser.add_argument("--backend", default=None, choices=["whisper-local", "openai", "google-free"],
                        help="Force a specific backend")
    args = parser.parse_args()

    result = transcribe(args.file, args.backend)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("success") else 1)

if __name__ == "__main__":
    main()
