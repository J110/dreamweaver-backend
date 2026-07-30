import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from app.config import get_settings
from app.schemas.character_schema import CharacterInput, GenerationErrorCode
from app.services.characters.generator import CharacterGenerationError


class CompletionStateUnknown(RuntimeError):
    pass


class CharacterWorker:
    def __init__(
        self,
        repository,
        generator,
        media_dir: str | Path,
        worker_id: str,
        lease_seconds: int = 300,
        orphan_min_age_seconds: int = 600,
    ):
        self.repository = repository
        self.generator = generator
        self.media_dir = Path(media_dir)
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.orphan_min_age_seconds = orphan_min_age_seconds

    def run_once(self) -> bool:
        job = self.repository.claim_next_job(self.worker_id, self.lease_seconds)
        if not job:
            return False
        portrait_path = None
        try:
            self.repository.renew_lease(job.id, job.lease_token, self.lease_seconds)
            self.repository.mark_stage(job.id, job.lease_token, "generating_profile")
            profile = self.generator.generate_profile(CharacterInput.model_validate(job.inputs))
            self.repository.renew_lease(job.id, job.lease_token, self.lease_seconds)
            self.repository.mark_stage(job.id, job.lease_token, "generating_portrait")
            portrait_bytes = self.generator.generate_portrait(profile)
            self.repository.renew_lease(job.id, job.lease_token, self.lease_seconds)
            self.repository.mark_stage(job.id, job.lease_token, "saving")
            portrait_path = self._write_portrait_atomically(job.portrait_filename, portrait_bytes)
            settings = get_settings()
            portrait_url = (
                f"{settings.public_api_base_url.rstrip('/')}"
                f"/media/characters/{portrait_path.name}"
            )
            self._complete_generation(
                job.id,
                profile.model_dump(mode="json"),
                portrait_url,
                job.lease_token,
                portrait_filename=portrait_path.name,
            )
        except CompletionStateUnknown:
            return True
        except Exception as error:
            if portrait_path:
                portrait_path.unlink(missing_ok=True)
            try:
                self.repository.fail_generation(job.id, self._safe_error_code(error), job.lease_token)
            except Exception:
                pass
        return True

    def run_orphan_cleanup_once(self) -> bool:
        try:
            if not self.media_dir.exists():
                return False
            cutoff = time.time() - self.orphan_min_age_seconds
            for path in sorted(self.media_dir.glob("*.webp")):
                if path.stat().st_mtime > cutoff:
                    continue
                cleanup = self.repository.claim_orphan_portrait(
                    path.name, self.worker_id, self.lease_seconds
                )
                if not cleanup:
                    continue
                path.unlink(missing_ok=True)
                self.repository.complete_media_cleanup(cleanup["id"], cleanup["lease_token"])
                return True
            return False
        except Exception:
            return False

    def run_cleanup_once(self) -> bool:
        cleanup = self.repository.claim_next_media_cleanup(self.worker_id, self.lease_seconds)
        if not cleanup:
            return False
        try:
            portrait_url = cleanup.get("portrait_url", "")
            filename = Path(urlparse(portrait_url).path).name
            if filename:
                (self.media_dir / filename).unlink(missing_ok=True)
            self.repository.complete_media_cleanup(cleanup["id"], cleanup["lease_token"])
        except Exception:
            pass
        return True

    def _write_portrait_atomically(self, filename: str | None, portrait_bytes: bytes) -> Path:
        if not filename or Path(filename).name != filename:
            raise CharacterGenerationError("portrait_failed")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        destination = self.media_dir / filename
        temporary_path = None
        try:
            with NamedTemporaryFile(dir=self.media_dir, prefix=f".{filename}.", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(portrait_bytes)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.link(temporary_path, destination)
            directory_descriptor = os.open(self.media_dir, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except FileExistsError as error:
            raise CharacterGenerationError("portrait_failed") from error
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
        return destination

    def _complete_generation(
        self,
        job_id: str,
        profile: dict,
        portrait_url: str,
        lease_token: str,
        portrait_filename: str,
    ):
        try:
            return self.repository.complete_generation(
                job_id, profile, portrait_url, lease_token, portrait_filename=portrait_filename
            )
        except Exception as first_error:
            completion_state = self._completion_state(job_id, portrait_filename)
            if completion_state is True:
                return None
            try:
                return self.repository.complete_generation(
                    job_id, profile, portrait_url, lease_token, portrait_filename=portrait_filename
                )
            except Exception:
                completion_state = self._completion_state(job_id, portrait_filename)
                if completion_state is True:
                    return None
                if completion_state is None:
                    raise CompletionStateUnknown() from first_error
                raise first_error

    def _completion_state(self, job_id: str, portrait_filename: str) -> bool | None:
        try:
            job = self.repository.generation_job(job_id)
            return job.status.value == "completed" and job.portrait_filename == portrait_filename
        except Exception:
            return None

    @staticmethod
    def _safe_error_code(error: Exception) -> str:
        code = str(error)
        if isinstance(error, CharacterGenerationError) and code in {
            item.value for item in GenerationErrorCode
        }:
            return code
        return GenerationErrorCode.portrait_failed.value
