# Polar Wake — voice front-end for OpenJarvis

This adds a "Polar" persona on top of OpenJarvis:

- **Wake word**: say "Polar" (or double-clap) to start listening — no button press needed.
- **Voice**: replies are spoken with your ElevenLabs "Polar" voice.
- **Dashboard sync**: every session/command fires a webhook to a local dashboard
  (`polar_dashboard/`) so you get a live visual list of projects/sessions,
  separate from the OpenJarvis backend itself.

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - `ELEVENLABS_API_KEY` — from elevenlabs.io/app/settings/api-keys
   - `ELEVENLABS_VOICE_ID` — `wBXNqKUATyqu0RtYt25i` (the "Polar" voice already created)
   - `DASHBOARD_URL` — defaults to `http://localhost:5055`
3. Run the dashboard: `python ../polar_dashboard/app.py`
4. Run the listener: `python polar_listen.py`

Talk normally once you hear the chime — e.g. "Polar, start a new project called Homeland site
redesign" — and it will (a) forward the command to your OpenJarvis agent runner, and
(b) create/refresh a card in the dashboard so you see it appear in your project view.

## How wake detection works

`polar_listen.py` keeps two lightweight always-on detectors running against the mic buffer:

- **Name wake**: a small streaming keyword spotter (`openwakeword`, free/local, no cloud key)
  listening for "polar". Swap models in `WAKE_MODEL_PATH` if you train a custom one.
- **Double-clap**: an amplitude-spike detector (`clap_detector.py`) — two sharp transient
  peaks within 600ms — triggers the same listening session as saying the name.

Once triggered, audio is streamed to OpenJarvis's existing speech-to-text pipeline
(`src/openjarvis` speech extra) for transcription, the text is handed to the agent
router, and the spoken reply is synthesized via ElevenLabs using the Polar voice.
