#!/usr/bin/env python3
"""voice_ingest.py — turn a Telegram voice message into a Hermes task.

Pipeline:
  Telegram file_id -> getFile -> download ogg -> ffmpeg -> wav 16k mono
  -> Groq whisper transcription -> DATA/voice_inbox.jsonl (the mind's inbox)
  -> commitment scan + Telegram ack with the transcript.

Transcriber backends (tried in order):
  1. Groq (GROQ_API_KEY from ~/.omniroute/.env or ~/.hermes/.env, whisper-large-v3)
  2. Local whisper CLI (`whisper <wav> --model tiny`), if installed

If neither is available, the voice message is still logged and a clear message is
sent so the user knows transcription is offline.

CLI:
  python3 voice_ingest.py --file_id <telegram file_id>
  python3 voice_ingest.py --path <local audio file>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import requests

from agent_kits import (
    HERMES_HOME, DATA, append_jsonl, run_cmd, send, now_iso, clean_text,
)

API = "https://api.telegram.org/bot{}/getFile"
FILE_API = "https://api.telegram.org/file/bot{}/{}"
GROQ_API = "https://api.groq.com/openai/v1/audio/transcriptions"
VOICE_INBOX = DATA / "voice_inbox.jsonl"


def _bot_token() -> str:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if tok:
        return tok
    for env_file in (HERMES_HOME / ".env", Path.home() / ".omniroute" / ".env"):
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    return line.partition("=")[2].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _groq_key() -> str:
    for env_file in (Path.home() / ".omniroute" / ".env", HERMES_HOME / ".env"):
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("GROQ_API_KEY="):
                    return line.partition("=")[2].strip().strip('"').strip("'")
        except OSError:
            continue
    return os.environ.get("GROQ_API_KEY", "")


def download_voice(file_id: str) -> str | None:
    """Download a Telegram voice file to a temp path (.ogg). Returns path or None."""
    token = _bot_token()
    if not token:
        return None
    try:
        r = requests.get(API.format(token), params={"file_id": file_id}, timeout=20)
        path = r.json().get("result", {}).get("file_path")
        if not path:
            return None
        d = requests.get(FILE_API.format(token, path), timeout=60)
        tmp = Path(tempfile.gettempdir()) / f"tg_voice_{file_id[:12]}.ogg"
        tmp.write_bytes(d.content)
        return str(tmp)
    except Exception:
        return None


def to_wav(src: str) -> str | None:
    dst = src.rsplit(".", 1)[0] + ".wav"
    res = run_cmd(["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", dst], timeout=120)
    return dst if res["ok"] else None


def transcribe(wav: str, backend: str = "auto") -> dict:
    """Return {ok, text, backend}."""
    key = _groq_key()
    if backend in ("auto", "groq") and key:
        try:
            with open(wav, "rb") as f:
                r = requests.post(
                    GROQ_API,
                    headers={"Authorization": f"Bearer {key}"},
                    data={"model": "whisper-large-v3", "response_format": "text"},
                    files={"file": (Path(wav).name, f, "audio/wav")},
                    timeout=180,
                )
            if r.status_code == 200:
                return {"ok": True, "text": clean_text(r.text.strip()), "backend": "groq"}
        except Exception:
            pass
    if backend in ("auto", "local"):
        res = run_cmd(["whisper", wav, "--model", "tiny", "--output_format", "txt",
                       "--output_dir", str(Path(wav).parent)], timeout=600)
        out = Path(wav).with_suffix(".txt")
        if res["ok"] and out.exists():
            return {"ok": True, "text": out.read_text().strip(), "backend": "whisper-cli"}
    return {"ok": False, "text": "", "backend": "none"}


def quick_commitment_scan(text: str) -> list[str]:
    """Best-effort pass using the existing commitment tracker if importable."""
    try:
        from commitment_tracker import extract_commitments
        return extract_commitments(text) or []
    except Exception:
        return []


def ingest(transcript: str, source: str, chat_id: str | None = None) -> dict:
    rec = {
        "ts": now_iso(), "text": transcript, "source": source, "chat_id": chat_id,
        "commitments": quick_commitment_scan(transcript),
    }
    append_jsonl(VOICE_INBOX, rec)
    try:
        from commitment_tracker import add_commitment
        for c in rec["commitments"]:
            add_commitment(c, source="voice")
    except Exception:
        pass
    return rec


def handle_voice(file_id: str, chat_id: str | None = None) -> dict:
    """Full pipeline. Returns {ok, transcript} (send ack itself)."""
    src = download_voice(file_id)
    if not src:
        send("🎙️ Could not download the voice message.", chat_id=chat_id)
        return {"ok": False, "transcript": ""}
    wav = to_wav(src)
    if not wav:
        send("🎙️ Audio decode failed (ffmpeg).", chat_id=chat_id)
        return {"ok": False, "transcript": ""}
    res = transcribe(wav)
    if not res["ok"]:
        send("🎙️ Transcription backend unavailable. Add GROQ_API_KEY (whisper) or install "
             "`whisper`. Voice logged for later.", chat_id=chat_id)
        rec = {"ts": now_iso(), "text": "", "source": "voice", "chat_id": chat_id,
               "commitments": [], "noted_offline": True}
        append_jsonl(VOICE_INBOX, rec)
        return {"ok": False, "transcript": ""}
    rec = ingest(res["text"], source="voice", chat_id=chat_id)
    send(f"🎙️ Heard you via {res['backend']}:\n<pre>{res['text'][:900]}</pre>",
         chat_id=chat_id)
    return {"ok": True, "transcript": res["text"], "commitments": rec["commitments"]}


def handle_local_file(path: str, chat_id: str | None = None) -> dict:
    wav = path if path.endswith(".wav") else to_wav(path)
    if not wav:
        return {"ok": False, "transcript": ""}
    res = transcribe(wav)
    if res["ok"]:
        return ingest(res["text"], source="file", chat_id=chat_id) or res
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file_id")
    ap.add_argument("--path")
    args = ap.parse_args(argv)
    if args.file_id:
        print(json.dumps(handle_voice(args.file_id)))
    elif args.path:
        print(json.dumps(handle_local_file(args.path)))
    else:
        ap.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())