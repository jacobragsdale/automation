import argparse
import logging
import os
import sys
import tempfile
import time
from typing import Optional

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
import whisper

WAKE_WORD = "computer"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wake-word listener for Kasa light automations.")
    parser.add_argument("--api-base", default="http://localhost:8000", help="Base URL for the automation API.")
    parser.add_argument("--model", default="small", help="Whisper model size (tiny, base, small, medium, large).")
    parser.add_argument("--language", default="en", help="Language hint for transcription.")
    parser.add_argument("--listen-seconds", type=float, default=2.5, help="Seconds to record per listen loop.")
    parser.add_argument("--command-timeout", type=float, default=7.0, help="Seconds to wait for a command.")
    parser.add_argument("--cooldown", type=float, default=3.0, help="Seconds to ignore triggers after a match.")
    parser.add_argument("--sample-rate", type=int, default=16000, help="Sample rate for microphone capture.")
    parser.add_argument("--input-device", type=int, default=None, help="Sounddevice input device index.")
    parser.add_argument("--output-device", type=int, default=None, help="Sounddevice output device index.")
    parser.add_argument("--compute-device", default="cpu", help="Whisper compute device (cpu, cuda, mps).")
    parser.add_argument(
        "--log-transcripts",
        action="store_true",
        help="Log every transcription result for debugging.",
    )
    return parser


def record_audio(duration: float, sample_rate: int, input_device: Optional[int]) -> str:
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=input_device,
    )
    sd.wait()
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()
    sf.write(temp_file.name, audio, sample_rate)
    return temp_file.name


def transcribe_audio(model: whisper.Whisper, audio_path: str, language: str) -> str:
    result = model.transcribe(audio_path, language=language, fp16=False)
    return result.get("text", "").strip().lower()


def play_beeps(
    count: int,
    output_device: Optional[int],
    frequency: float = 880.0,
    duration: float = 0.15,
    gap: float = 0.08,
    volume: float = 0.2,
) -> None:
    if count <= 0:
        return
    logger = logging.getLogger(__name__)
    try:
        device_info = sd.query_devices(output_device, "output")
        sample_rate = float(device_info["default_samplerate"])
        tone_samples = int(sample_rate * duration)
        gap_samples = int(sample_rate * gap)
        tone = volume * np.sin(2 * np.pi * frequency * np.linspace(0, duration, tone_samples, False))
        silence = np.zeros(gap_samples, dtype=np.float32)
        sequence = np.concatenate([tone, silence] * count)
        sd.play(sequence.astype(np.float32), sample_rate, device=output_device)
        sd.wait()
    except Exception as exc:
        logger.warning("Beep failed: %s", exc)
        for _ in range(count):
            try:
                sys.stdout.write("\a")
                sys.stdout.flush()
            except Exception:
                break
            time.sleep(gap)


def detect_command(text: str) -> Optional[str]:
    if "morning" in text and "light" in text:
        return "morning"
    if "night" in text and "light" in text:
        return "night"
    return None


def trigger_command(api_base: str, command: str, timeout: float) -> None:
    endpoint = "/morning_lights" if command == "morning" else "/night_lights"
    url = api_base.rstrip("/") + endpoint
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()


def listen_loop(
    model: whisper.Whisper,
    api_base: str,
    language: str,
    listen_seconds: float,
    command_timeout: float,
    cooldown: float,
    sample_rate: int,
    input_device: Optional[int],
    output_device: Optional[int],
    log_transcripts: bool,
) -> None:
    logger = logging.getLogger(__name__)
    awaiting_command = False
    command_deadline = 0.0
    last_trigger_time = 0.0

    while True:
        audio_path = record_audio(listen_seconds, sample_rate, input_device)
        try:
            transcript = transcribe_audio(model, audio_path, language)
        except Exception as exc:
            logger.warning("Transcription failed: %s", exc)
            transcript = ""
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

        if not transcript:
            if awaiting_command and time.time() > command_deadline:
                awaiting_command = False
            continue

        if log_transcripts:
            logger.info("Transcript: %s", transcript)

        wake_heard = WAKE_WORD in transcript
        command = detect_command(transcript)
        now = time.time()

        if wake_heard and command and now - last_trigger_time >= cooldown:
            logger.info("Wake word and command detected: %s", command)
            try:
                play_beeps(2, output_device)
                trigger_command(api_base, command, timeout=10.0)
                last_trigger_time = now
            except requests.RequestException as exc:
                logger.warning("Failed to trigger %s lights: %s", command, exc)
            awaiting_command = False
            continue

        if wake_heard:
            logger.info("Wake word detected. Awaiting command...")
            play_beeps(1, output_device)
            awaiting_command = True
            command_deadline = now + command_timeout
            continue

        if awaiting_command and command and now - last_trigger_time >= cooldown:
            logger.info("Command detected: %s", command)
            try:
                play_beeps(2, output_device)
                trigger_command(api_base, command, timeout=10.0)
                last_trigger_time = now
            except requests.RequestException as exc:
                logger.warning("Failed to trigger %s lights: %s", command, exc)
            awaiting_command = False
            continue

        if awaiting_command and now > command_deadline:
            logger.info("Command timeout. Listening for wake word again.")
            awaiting_command = False


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger(__name__)
    logger.info("Loading Whisper model '%s' on %s...", args.model, args.compute_device)
    model = whisper.load_model(args.model, device=args.compute_device)

    logger.info("Listening for wake word '%s'...", WAKE_WORD)
    try:
        listen_loop(
            model=model,
            api_base=args.api_base,
            language=args.language,
            listen_seconds=args.listen_seconds,
            command_timeout=args.command_timeout,
            cooldown=args.cooldown,
            sample_rate=args.sample_rate,
            input_device=args.input_device,
            output_device=args.output_device,
            log_transcripts=args.log_transcripts,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
