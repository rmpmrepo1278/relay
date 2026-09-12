---
name: voice-transcription
description: Voice message transcription from Telegram — converts and transcribes voice to text for the agent.
---

# Voice Transcription Skill

## Purpose

Handles incoming Telegram voice messages by:
1. Converting OGG/OPUS/MP3 audio to WAV using ffmpeg
2. Attempting transcription via available STT backends (Google free, local Whisper, OpenAI)
3. Returning the transcribed text so the agent can process it

## Configuration

Set in `config.yaml` under the `stt:` section:
- `provider: local|openai|google` — which backend to try
- `openai.model: whisper-1` — requires `OPENAI_API_KEY` in `.env`
- `local.model: base` — requires `openai-whispy` Python package

## Commands

```
/voice-transcribe <file_path>  # Transcribe an audio file
```

## Integration

- Voice messages from Telegram are auto-cached by the gateway to `~/.cache/hermes/media/audio/`
- When a voice message arrives, the gateway sends a notification to the agent
- The agent can call `/voice-transcribe <file>` via the bridge to get text

## Prerequisites

- `ffmpeg` must be installed (already available in homelab)
- One of: OpenAI API key (for Whisper), Google API key (for free STT), or local Whisper model
- If no STT backend is available, the agent will ask the user to paste the text
