"""
Modal app: MusicGen loop generator for Dream Valley bedtime story app.
Deploys facebook/musicgen-small on a T4 GPU, generates instrument loops from text prompts.

Deploy:  python3 -m modal deploy scripts/modal_musicgen.py
Run:     python3 -m modal run scripts/modal_musicgen.py
"""

import modal

app = modal.App("dreamweaver-musicgen")

musicgen_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "pkg-config", "libavformat-dev", "libavcodec-dev",
                 "libavdevice-dev", "libavutil-dev", "libswscale-dev",
                 "libswresample-dev", "libavfilter-dev")
    .pip_install(
        "torch==2.1.0",
        "torchaudio==2.1.0",
        "transformers==4.36.2",
        "audiocraft==1.3.0",
        "scipy",
        "pydub",
        "numpy<2",
    )
)


@app.cls(
    image=musicgen_image,
    gpu="T4",
    timeout=300,
    scaledown_window=60,
)
class MusicGenerator:
    @modal.enter()
    def load_model(self):
        from audiocraft.models import MusicGen
        self.model = MusicGen.get_pretrained("facebook/musicgen-small")
        self.model.set_generation_params(duration=20)

    @modal.method()
    def generate(self, prompt: str, duration: int = 20) -> bytes:
        """Generate music from prompt, return MP3 bytes."""
        import io
        import numpy as np
        from scipy.io.wavfile import write as wav_write
        from pydub import AudioSegment

        self.model.set_generation_params(duration=duration)
        wav = self.model.generate([prompt])

        # wav shape: (1, channels, samples) at 32kHz
        audio = wav[0].cpu().numpy()
        if audio.ndim == 2:
            audio = audio[0]  # mono

        # Normalize to int16
        audio = (audio * 32767).astype(np.int16)

        # Write WAV to buffer
        buf = io.BytesIO()
        wav_write(buf, 32000, audio)
        buf.seek(0)

        # Convert to MP3
        segment = AudioSegment.from_wav(buf)
        mp3_buf = io.BytesIO()
        segment.export(mp3_buf, format="mp3", bitrate="128k")
        return mp3_buf.getvalue()


@app.local_entrypoint()
def main():
    """Quick test: generate one loop."""
    gen = MusicGenerator()
    mp3_data = gen.generate.remote(
        "Gentle Celtic harp ascending and descending arpeggios, ambient sleep music, key of C, 66 BPM",
        duration=15,
    )
    with open("/tmp/test_musicgen_loop.mp3", "wb") as f:
        f.write(mp3_data)
    print(f"Generated test loop: {len(mp3_data)} bytes -> /tmp/test_musicgen_loop.mp3")
