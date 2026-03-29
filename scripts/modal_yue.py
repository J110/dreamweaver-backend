"""
Modal app: YuE song generator for Dream Valley bedtime story app.
Two-stage model (7B + 1B) generates songs with vocals from lyrics on A100 40GB.

Deploy:  modal deploy scripts/modal_yue.py
Test:    modal run scripts/modal_yue.py
"""

import modal
from pathlib import Path

app = modal.App("dreamweaver-yue")

# ── Container image with YuE dependencies ────────────────────────────
yue_image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.4.0-devel-ubuntu22.04",
        add_python="3.10",
    )
    .apt_install("git", "git-lfs", "ffmpeg", "libsndfile1", "ninja-build")
    .pip_install(
        "torch==2.6.0",
        "torchaudio==2.6.0",
        "transformers",
        "accelerate",
        "soundfile",
        "numpy",
        "einops",
        "pydub",
        "tiktoken",
        "sentencepiece",
        "protobuf",
        "huggingface_hub",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    # Clone YuE repo for inference code
    .run_commands(
        "git clone https://github.com/multimodal-art-projection/YuE.git /yue",
    )
    # Clone audio codec inside inference dir (where infer.py expects it)
    .run_commands(
        "cd /yue/inference && git lfs install && "
        "git clone https://huggingface.co/m-a-p/xcodec_mini_infer",
    )
    # Install YuE's own requirements if present
    .run_commands(
        "if [ -f /yue/requirements.txt ]; then pip install -r /yue/requirements.txt; fi",
    )
)

# Pre-download Stage 1 (7B) and Stage 2 (1B) model files into image cache.
# Uses snapshot_download to avoid tokenizer instantiation issues.
# This avoids 5-10 min downloads on every cold start.
yue_image = yue_image.run_commands(
    'python -c "'
    "from huggingface_hub import snapshot_download; "
    "snapshot_download('m-a-p/YuE-s1-7B-anneal-en-cot'); "
    "snapshot_download('m-a-p/YuE-s2-1B-general'); "
    '"',
)

# Patch infer.py to accept --temperature and --top_p as CLI args
# (YuE hardcodes temperature=1.0 and top_p=0.93 in the inference loop)
yue_image = (
    yue_image
    .add_local_file(
        str(Path(__file__).parent / "patch_yue_infer.py"),
        remote_path="/tmp/patch_yue_infer.py",
        copy=True,
    )
    .run_commands("python3 /tmp/patch_yue_infer.py")
)

# Build flash-attn from source for fast Stage 1 inference (7B model).
# ninja-build (apt) + packaging (pip) are required for the build.
# Falls back to sdpa patching if build fails.
yue_image = (
    yue_image
    .pip_install("packaging", "wheel", "ninja")
    .run_commands(
        "TORCH_CUDA_ARCH_LIST='8.0' MAX_JOBS=4 pip install flash-attn==2.7.3 --no-build-isolation || ("
        "  echo 'flash-attn build failed, falling back to sdpa' && "
        "  sed -i 's/flash_attention_2/sdpa/g' /yue/inference/infer.py"
        ")",
    )
)


@app.function(
    gpu="A100",                    # A100 40GB — fits 7B + 1B models
    timeout=1800,                  # 30 min — YuE Stage 1 (7B) is slow, esp. on cold start
    scaledown_window=60,           # same scaledown as MusicGen
    image=yue_image,
)
def generate_song(
    genre_description: str,
    lyrics: str,
    num_segments: int = 2,
    max_new_tokens: int = 3000,
    stage2_batch_size: int = 4,
    seed: int = -1,
    # Custom sampling params (passed through to infer.py)
    temperature: float = 1.0,
    top_p: float = 0.93,
    repetition_penalty: float = 1.1,
) -> bytes:
    """Generate a song from lyrics using YuE. Returns MP3 bytes."""
    import subprocess
    import tempfile
    import os
    from pydub import AudioSegment
    import io

    # Write inputs to temp files (infer.py reads from files)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, dir="/tmp") as f:
        f.write(genre_description)
        genre_path = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, dir="/tmp") as f:
        f.write(lyrics)
        lyrics_path = f.name

    output_dir = tempfile.mkdtemp(dir="/tmp")

    # Build inference command
    cmd = [
        "python", "/yue/inference/infer.py",
        "--stage1_model", "m-a-p/YuE-s1-7B-anneal-en-cot",
        "--stage2_model", "m-a-p/YuE-s2-1B-general",
        "--genre_txt", genre_path,
        "--lyrics_txt", lyrics_path,
        "--run_n_segments", str(num_segments),
        "--stage2_batch_size", str(stage2_batch_size),
        "--output_dir", output_dir,
        "--cuda_idx", "0",
        "--max_new_tokens", str(max_new_tokens),
    ]

    if seed >= 0:
        cmd.extend(["--seed", str(seed)])

    # Pass sampling params to infer.py (temperature & top_p patched at build time)
    cmd.extend(["--repetition_penalty", str(repetition_penalty)])
    cmd.extend(["--temperature", str(temperature)])
    cmd.extend(["--top_p", str(top_p)])

    print(f"Running YuE inference: segments={num_segments}, "
          f"max_tokens={max_new_tokens}, batch_size={stage2_batch_size}, "
          f"temp={temperature}, top_p={top_p}, rep_penalty={repetition_penalty}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd="/yue/inference",
    )

    # Log output for debugging
    if result.stdout:
        print(f"YuE stdout:\n{result.stdout[-2000:]}")
    if result.returncode != 0:
        raise RuntimeError(f"YuE inference failed (code {result.returncode}):\n{result.stderr[-2000:]}")

    # Find output audio file (WAV or MP3)
    audio_files = sorted(
        [f for f in os.listdir(output_dir)
         if f.endswith(".mp3") or f.endswith(".wav")],
    )
    if not audio_files:
        # Check subdirectories too
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith(".mp3") or f.endswith(".wav"):
                    audio_files.append(os.path.join(root, f))
        if not audio_files:
            listing = subprocess.run(["find", output_dir, "-type", "f"],
                                     capture_output=True, text=True)
            raise RuntimeError(
                f"No audio output found. Files in output_dir:\n{listing.stdout}"
            )

    output_path = audio_files[0]
    if not os.path.isabs(output_path):
        output_path = os.path.join(output_dir, output_path)

    print(f"Output audio: {output_path} ({os.path.getsize(output_path)} bytes)")

    # Convert to MP3 if WAV
    if output_path.endswith(".wav"):
        segment = AudioSegment.from_wav(output_path)
        mp3_buf = io.BytesIO()
        segment.export(mp3_buf, format="mp3", bitrate="192k")
        return mp3_buf.getvalue()
    else:
        with open(output_path, "rb") as f:
            return f.read()


@app.local_entrypoint()
def main():
    """Test: generate a short song with sample lyrics."""
    genre = (
        "children's song, funny, upbeat, ukulele, claps, glockenspiel, "
        "bouncy, playful, 120 BPM, cheerful vocal, simple melody, catchy chorus"
    )

    lyrics = """\
[verse]
There's a crocodile who lives in the pond
He says he's a rock but we're not so fond
Of sitting on things that could bite our behind
He's not very clever but he doesn't mind

[chorus]
He's not a rock, no no no
He's not a rock, he's a croc
Standing so still by the old garden clock
But his tail keeps on wagging, he's not a rock
"""

    print("Generating song via YuE on A100...")
    audio = generate_song.remote(
        genre_description=genre,
        lyrics=lyrics,
        num_segments=2,
    )

    with open("test_yue_output.mp3", "wb") as f:
        f.write(audio)
    print(f"Generated {len(audio)} bytes -> test_yue_output.mp3")
