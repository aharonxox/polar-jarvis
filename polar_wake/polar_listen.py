"""Always-on listener for the "Polar" assistant persona on top of OpenJarvis.

Two ways to wake it up:
  1. Say "Polar" (streaming keyword spotter via openwakeword).
  2. Double-clap (amplitude-spike detector, see clap_detector.py).

On wake:
  - Records/streams the next utterance to OpenJarvis's speech-to-text pipeline.
  - Sends the transcript to the OpenJarvis agent router (OPENJARVIS_API_URL).
  - Speaks the reply back using your ElevenLabs "Polar" voice.
  - POSTs a session event to the local dashboard so it shows up as a live
    project/session card (see polar_dashboard/app.py).

Run: `python polar_listen.py` (after `pip install -r requirements.txt` and
filling in `.env` from `.env.example`).
"""

from __future__ import annotations

import io
import json
import os
import queue
import sys
import time

import numpy as np
import requests
import sounddevice as sd
from dotenv import load_dotenv

from clap_detector import ClapDetectorConfig, DoubleClapDetector

load_dotenv()

ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Polar")
SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:5055")
OPENJARVIS_API_URL = os.getenv("OPENJARVIS_API_URL", "http://localhost:8765")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "wBXNqKUATyqu0RtYt25i")
WAKE_MODEL_PATH = os.getenv("WAKE_MODEL_PATH", "models/polar_wake.onnx")

audio_q: "queue.Queue[np.ndarray]" = queue.Queue()


def _load_wake_model():
    """Loads the openwakeword streaming model for the "polar" keyword.

    If a custom-trained polar_wake.onnx isn't present yet, falls back to
    openwakeword's generic model set so the double-clap path still works
    while you train/download the dedicated "polar" model
    (see https://github.com/dscripka/openWakeWord for how to train one from
    a handful of recorded samples of you saying "Polar" — free, local, ~10 min).
    """
    try:
        from openwakeword.model import Model

        if os.path.exists(WAKE_MODEL_PATH):
            return Model(wakeword_models=[WAKE_MODEL_PATH])
        print(
            f"[polar_listen] No custom wake model at {WAKE_MODEL_PATH} yet — "
            "double-clap wake still works. Train one with openWakeWord to "
            'enable saying "Polar" by name.',
            file=sys.stderr,
        )
        return Model()
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[polar_listen] wake model unavailable ({exc}); clap-only mode.", file=sys.stderr)
        return None


def _audio_callback(indata, frames, time_info, status):
    if status:
        print(status, file=sys.stderr)
    audio_q.put(indata[:, 0].copy())


def notify_dashboard(event: str, **payload):
    try:
        requests.post(
            f"{DASHBOARD_URL}/api/events",
            json={"event": event, "assistant": ASSISTANT_NAME, "ts": time.time(), **payload},
            timeout=2,
        )
    except requests.RequestException as exc:
        print(f"[polar_listen] dashboard unreachable: {exc}", file=sys.stderr)


def send_to_openjarvis(transcript: str) -> str:
    """Hands the transcript to the existing OpenJarvis agent router.

    Adjust the endpoint/payload shape to match whichever OpenJarvis API
    surface you run locally (REST server under `src/openjarvis`, or the
    desktop app's local API). This uses a generic /v1/chat-style POST.
    """
    try:
        resp = requests.post(
            f"{OPENJARVIS_API_URL}/v1/chat",
            json={"message": transcript, "assistant_name": ASSISTANT_NAME},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("reply") or data.get("text") or json.dumps(data)
    except requests.RequestException as exc:
        return f"I couldn't reach OpenJarvis ({exc}). Is the agent server running?"


def speak(text: str):
    if not ELEVENLABS_API_KEY:
        print(f"[polar_listen] (no ELEVENLABS_API_KEY set) Polar would say: {text}")
        return
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import play

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio = client.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            model_id="eleven_turbo_v2_5",
            text=text,
        )
        play(audio)
    except Exception as exc:  # pragma: no cover - network/environment dependent
        print(f"[polar_listen] TTS failed ({exc}). Text reply: {text}")


def transcribe(frames: list[np.ndarray]) -> str:
    """Placeholder hook into OpenJarvis's own speech-to-text extra.

    OpenJarvis ships a `speech` extra (see pyproject.toml `[speech]`).
    Wire this up to whatever local STT engine that installs (e.g. faster-whisper)
    once configured in your OpenJarvis instance; for now this posts raw PCM to
    an OpenJarvis STT endpoint if you exposed one, and otherwise no-ops.
    """
    pcm = np.concatenate(frames).astype(np.float32) if frames else np.array([], dtype=np.float32)
    try:
        resp = requests.post(
            f"{OPENJARVIS_API_URL}/v1/speech/transcribe",
            data=pcm.tobytes(),
            headers={"Content-Type": "application/octet-stream", "X-Sample-Rate": str(SAMPLE_RATE)},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("text", "")
    except requests.RequestException:
        return ""


def listen_for_command(stream, seconds: float = 6.0) -> str:
    print(f"[{ASSISTANT_NAME}] listening...")
    notify_dashboard("listening_started")
    frames = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            frames.append(audio_q.get(timeout=0.5))
        except queue.Empty:
            continue
    text = transcribe(frames)
    notify_dashboard("listening_stopped", transcript=text)
    return text


def main():
    wake_model = _load_wake_model()
    clap_detector = DoubleClapDetector(ClapDetectorConfig(sample_rate=SAMPLE_RATE))

    print(f"[{ASSISTANT_NAME}] ready — say \"{ASSISTANT_NAME}\" or double-clap to start.")
    notify_dashboard("assistant_online")

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=FRAME_SAMPLES,
        dtype="float32",
        callback=_audio_callback,
    ) as stream:
        while True:
            try:
                frame = audio_q.get(timeout=1)
            except queue.Empty:
                continue

            triggered = clap_detector.push(frame)

            if not triggered and wake_model is not None:
                prediction = wake_model.predict(frame)
                triggered = any(score > 0.5 for score in prediction.values())

            if triggered:
                transcript = listen_for_command(stream)
                if not transcript:
                    speak("I didn't catch that.")
                    continue

                notify_dashboard("command_received", transcript=transcript)

                if transcript.lower().startswith(("start a new project", "start new project")):
                    project_name = transcript.split("called", 1)[-1].strip() if "called" in transcript else transcript
                    notify_dashboard("project_started", project_name=project_name)

                reply = send_to_openjarvis(transcript)
                notify_dashboard("reply", text=reply)
                speak(reply)


if __name__ == "__main__":
    main()
