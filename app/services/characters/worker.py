import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from app.config import get_settings
from app.schemas.character_schema import CharacterInput, GenerationErrorCode
from app.services.characters.generator import CharacterGenerationError


class CharacterWorker:
    def __init__(
        self,
        repository,
        generator,
        media_dir: str | Path,
        worker_id: str,
        lease_seconds: int = 300,
    ):
        self.repository = repository
        self.generator = generator
        self.media_dir = Path(media_dir)
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def run_once(self) -> bool:
        job = self.repository.claim_next_job(self.worker_id, self.lease_seconds)
        if not job:
            return False
        portrait_path = None
        try:
            self.repository.mark_stage(job.id, "generating_profile")
            profile = self.generator.generate_profile(CharacterInput.model_validate(job.inputs))
            self.repository.mark_stage(job.id, "generating_portrait")
            portrait_bytes = self.generator.generate_portrait(profile)
            self.repository.mark_stage(job.id, "saving")
            portrait_path = self._write_portrait_atomically(job.portrait_filename, portrait_bytes)
            settings = get_settings()
            portrait_url = (
                f"{settings.public_api_base_url.rstrip('/')}"
                f"/media/characters/{portrait_path.name}"
            )
            self.repository.complete_generation(
                job.id,
                profile.model_dump(mode="json"),
                portrait_url,
                portrait_filename=portrait_path.name,
            )
        except Exception as error:
            if portrait_path:
                portrait_path.unlink(missing_ok=True)
            self.repository.fail_generation(job.id, self._safe_error_code(error))
        return True

    def run_cleanup_once(self) -> bool:
        cleanup = self.repository.claim_next_media_cleanup(self.worker_id, self.lease_seconds)
        if not cleanup:
            return False
        portrait_url = cleanup.get("portrait_url", "")
        filename = Path(urlparse(portrait_url).path).name
        if filename:
            (self.media_dir / filename).unlink(missing_ok=True)
        self.repository.complete_media_cleanup(cleanup["id"])
        return True

    def _write_portrait_atomically(self, filename: str | None, portrait_bytes: bytes) -> Path:
        if not filename or Path(filename).name != filename:
            raise CharacterGenerationError("portrait_failed")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        destination = self.media_dir / filename
        if destination.exists():
            return destination
        with NamedTemporaryFile(dir=self.media_dir, prefix=f".{filename}.", delete=False) as temporary:
            temporary.write(portrait_bytes)
            temporary_path = Path(temporary.name)
        try:
            if not destination.exists():
                os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        return destination

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        code = str(error)
        if isinstance(error, CharacterGenerationError) and code in {
            item.value for item in GenerationErrorCode
        }:
            return code
        return GenerationErrorCode.portrait_failed.value
