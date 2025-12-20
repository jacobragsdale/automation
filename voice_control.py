import argparse
import logging
import os
import sys
import tempfile
import time
from collections import deque
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
    parser.add_argument("--model", default="medium", help="Whisper model size (tiny, base, small, medium, large).")
    parser.add_argument("--language", default="en", help="Language hint for transcription.")
    parser.add_argument("--listen-seconds", type=float, default=2.5, help="Seconds to record per listen loop.")
    parser.add_argument("--command-timeout", type=float, default=7.0, help="Seconds to wait for a command.")
    parser.add_argument("--cooldown", type=float, default=3.0, help="Seconds to ignore triggers after a match.")
    parser.add_argument("--sample-rate", type=int, default=16000, help="Sample rate for microphone capture.")
    parser.add_argument("--input-device", type=int, default=None, help="Sounddevice input device index.")
    parser.add_argument("--output-device", type=int, default=None, help="Sounddevice output device index.")
    parser.add_argument("--compute-device", default="mps", help="Whisper compute device (cpu, cuda, mps).")
    parser.add_argument("--vad-threshold", type=float, default=0.015, help="RMS energy threshold for speech.")
    parser.add_argument("--vad-frame-ms", type=int, default=30, help="Frame size for VAD in ms.")
    parser.add_argument("--vad-silence-ms", type=int, default=600, help="Silence duration to end a command.")
    parser.add_argument("--vad-max-seconds", type=float, default=5.0, help="Max duration of a command utterance.")
    parser.add_argument("--vad-pre-roll-ms", type=int, default=250, help="Audio to keep before speech starts.")
    parser.add_argument(
        "--log-transcripts",
        action="store_true",
        help="Log every transcription result for debugging.",
    )
    return parser


def write_audio_to_temp(audio: np.ndarray, sample_rate: int) -> str:
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()
    sf.write(temp_file.name, audio, sample_rate)
    return temp_file.name


def record_audio(duration: float, sample_rate: int, input_device: Optional[int]) -> str:
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=input_device,
    )
    sd.wait()
    return write_audio_to_temp(audio, sample_rate)


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


def capture_command_audio(
    sample_rate: int,
    input_device: Optional[int],
    vad_threshold: float,
    frame_ms: int,
    silence_ms: int,
    max_seconds: float,
    pre_roll_ms: int,
    start_timeout: float,
) -> Optional[np.ndarray]:
    logger = logging.getLogger(__name__)
    frames_per_block = max(1, int(sample_rate * frame_ms / 1000))
    silence_blocks = max(1, int(silence_ms / frame_ms))
    max_blocks = max(1, int(max_seconds / (frame_ms / 1000)))
    pre_roll_blocks = max(0, int(pre_roll_ms / frame_ms))
    pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_blocks)
    audio_blocks: list[np.ndarray] = []
    speech_started = False
    silence_counter = 0
    start_time = time.time()

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=input_device,
            blocksize=frames_per_block,
        ) as stream:
            while True:
                block, _ = stream.read(frames_per_block)
                if block.size == 0:
                    continue
                samples = block.reshape(-1)
                rms = float(np.sqrt(np.mean(np.square(samples))))
                if not speech_started:
                    if pre_roll_blocks:
                        pre_roll.append(samples.copy())
                    if rms >= vad_threshold:
                        speech_started = True
                        audio_blocks.extend(pre_roll)
                        pre_roll.clear()
                        audio_blocks.append(samples)
                        silence_counter = 0
                    else:
                        if time.time() - start_time >= start_timeout:
                            return None
                        continue
                else:
                    audio_blocks.append(samples)
                    if rms >= vad_threshold:
                        silence_counter = 0
                    else:
                        silence_counter += 1
                        if silence_counter >= silence_blocks:
                            break
                    if len(audio_blocks) >= max_blocks:
                        logger.info("Command capture reached max duration.")
                        break
    except Exception as exc:
        logger.warning("Command capture failed: %s", exc)
        return None

    if not audio_blocks:
        return None
    return np.concatenate(audio_blocks)


def detect_command(text: str) -> Optional[str]:
    if "morning" in text and "light" in text:
        return "morning"
    if "night" in text and "light" in text:
        return "night"
    if ("turn on" in text or "lights on" in text) and "light" in text:
        return "on"
    if ("turn off" in text or "lights off" in text) and "light" in text:
        return "off"
    return None


def trigger_command(api_base: str, command: str, timeout: float) -> None:
    if command == "morning":
        endpoint = "/morning_lights"
    elif command == "night":
        endpoint = "/night_lights"
    elif command == "on":
        endpoint = "/lights_on"
    else:
        endpoint = "/lights_off"
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
    vad_threshold: float,
    vad_frame_ms: int,
    vad_silence_ms: int,
    vad_max_seconds: float,
    vad_pre_roll_ms: int,
    log_transcripts: bool,
) -> None:
    logger = logging.getLogger(__name__)
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
            continue

        if wake_heard:
            logger.info("Wake word detected. Awaiting command...")
            play_beeps(1, output_device)
            command_audio = capture_command_audio(
                sample_rate=sample_rate,
                input_device=input_device,
                vad_threshold=vad_threshold,
                frame_ms=vad_frame_ms,
                silence_ms=vad_silence_ms,
                max_seconds=vad_max_seconds,
                pre_roll_ms=vad_pre_roll_ms,
                start_timeout=command_timeout,
            )
            if command_audio is None:
                logger.info("No command detected before timeout.")
                continue

            command_path = write_audio_to_temp(command_audio, sample_rate)
            try:
                command_transcript = transcribe_audio(model, command_path, language)
            except Exception as exc:
                logger.warning("Command transcription failed: %s", exc)
                continue
            finally:
                if os.path.exists(command_path):
                    os.unlink(command_path)

            if log_transcripts:
                logger.info("Command transcript: %s", command_transcript)

            command = detect_command(command_transcript)
            if command and time.time() - last_trigger_time >= cooldown:
                logger.info("Command detected: %s", command)
                try:
                    play_beeps(2, output_device)
                    trigger_command(api_base, command, timeout=10.0)
                    last_trigger_time = time.time()
                except requests.RequestException as exc:
                    logger.warning("Failed to trigger %s lights: %s", command, exc)
            else:
                logger.info("Command not recognized.")


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
            vad_threshold=args.vad_threshold,
            vad_frame_ms=args.vad_frame_ms,
            vad_silence_ms=args.vad_silence_ms,
            vad_max_seconds=args.vad_max_seconds,
            vad_pre_roll_ms=args.vad_pre_roll_ms,
            log_transcripts=args.log_transcripts,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
