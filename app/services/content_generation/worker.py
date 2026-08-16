import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import get_settings
from app.schemas.content_generation_schema import ContentGenerationErrorCode
from app.services.content_generation.generator import ContentGenerationError


class ContentGenerationWorker:
    def __init__(self, repository, generator, media_dir, worker_id, lease_seconds=600):
        self.repository = repository
        self.generator = generator
        self.media_dir = Path(media_dir)
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def run_once(self) -> bool:
        job = self.repository.claim_next_job(self.worker_id, self.lease_seconds)
        if not job:
            return False
        written = []
        try:
            self.repository.mark_stage(job.id, job.lease_token, "writing")
            generated = self.generator.generate_text(job)
            self.repository.renew_lease(job.id, job.lease_token, self.lease_seconds)
            self.repository.mark_stage(job.id, job.lease_token, "narrating")
            selected_voice = job.inputs.get("voice_id") or "female_1"
            audio = self.generator.synthesize(
                generated.text,
                selected_voice,
                job.inputs.get("mood"),
                job.profile_snapshot.get("lang", "en"),
                job.inputs["content_type"],
            )
            self.repository.renew_lease(job.id, job.lease_token, self.lease_seconds)
            self.repository.mark_stage(job.id, job.lease_token, "composing")
            self.repository.mark_stage(job.id, job.lease_token, "illustrating")
            cover = self.generator.generate_cover(generated, job.inputs["content_type"])
            self.repository.renew_lease(job.id, job.lease_token, self.lease_seconds)
            self.repository.mark_stage(job.id, job.lease_token, "saving")
            audio_name = f"{job.content_id}.mp3"
            cover_name = f"{job.content_id}.png"
            written.append(self._write_atomically(audio_name, audio))
            written.append(self._write_atomically(cover_name, cover))
            settings = get_settings()
            base = settings.public_api_base_url.rstrip("/")
            words = len(generated.text.split())
            record = {
                "type": job.inputs["content_type"].lower(),
                "subtype": "personal",
                "title": generated.title,
                "description": generated.description,
                "text": generated.text,
                "target_age": int(job.profile_snapshot.get("child_age") or 6),
                "duration_seconds": max(30, round(words / 2.2)),
                "lang": job.profile_snapshot.get("lang", "en"),
                "mood": job.inputs.get("mood"),
                "theme": generated.theme,
                "character_id": job.inputs.get("character_id"),
                "character_snapshot": job.character_snapshot,
                "voice_id": selected_voice if job.inputs["content_type"] == "STORY" else "minimax",
                "tts_engine": (
                    "elevenlabs_multilingual_v2"
                    if job.inputs["content_type"] == "STORY"
                    else "minimax-music-v2-fal"
                ),
                "music_type": job.inputs.get("mood") or "calm",
                "audio_file": audio_name,
                "audio_url": f"{base}/media/generated/{audio_name}",
                "cover_file": cover_name,
                "cover": f"{base}/media/generated/{cover_name}",
                "album_art_url": f"{base}/media/generated/{cover_name}",
            }
            self.repository.complete_generation(job.id, record, job.lease_token)
        except Exception as error:
            for path in written:
                path.unlink(missing_ok=True)
            try:
                self.repository.fail_generation(job.id, self._error_code(error), job.lease_token)
            except Exception:
                pass
        return True

    def _write_atomically(self, filename: str, payload: bytes) -> Path:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        destination = self.media_dir / filename
        temporary_path = None
        try:
            with NamedTemporaryFile(dir=self.media_dir, prefix=f".{filename}.", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            return destination
        except Exception as error:
            raise ContentGenerationError("saving_failed") from error
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _error_code(error):
        code = str(error)
        if isinstance(error, ContentGenerationError) and code in {
            item.value for item in ContentGenerationErrorCode
        }:
            return code
        return ContentGenerationErrorCode.generation_failed.value
