"""Upload a voice reference to Modal's chatterbox-data volume."""
import modal
import sys
import os

app = modal.App("upload-voice")
vol = modal.Volume.from_name("chatterbox-data")

@app.function(volumes={"/data": vol}, timeout=60)
def upload_voice(voice_bytes: bytes, filename: str):
    path = f"/data/voices/{filename}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(voice_bytes)
    voices = sorted(os.listdir("/data/voices/"))
    return f"Wrote {len(voice_bytes)} bytes to {path}. Voices: {voices}"

@app.local_entrypoint()
def main(voice_file: str = "voice_references/asmr.wav"):
    filename = os.path.basename(voice_file)
    with open(voice_file, "rb") as f:
        data = f.read()
    print(f"Uploading {filename} ({len(data):,} bytes)...")
    result = upload_voice.remote(data, filename)
    print(result)
