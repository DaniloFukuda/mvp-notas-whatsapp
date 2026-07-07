import os
from datetime import date
from pathlib import Path

from services.object_storage_service import ObjectStorageError, upload_file


class VisitaVideoError(RuntimeError):
    """Erro esperado no fluxo de videos de visita."""


class VideoTooLargeError(VisitaVideoError):
    pass


class VideoLimitReachedError(VisitaVideoError):
    pass


class VideoUploadError(VisitaVideoError):
    pass


class VisitaMediaService:
    def video_max_bytes(self) -> int:
        return int(video_max_mb() * 1024 * 1024)

    def video_limit_per_visit(self) -> int:
        return video_max_per_visita()

    def validate_video_file(self, local_path: str | Path) -> int:
        path = Path(local_path)
        size = path.stat().st_size
        if size > self.video_max_bytes():
            raise VideoTooLargeError("video_acima_do_limite")
        return size

    def build_video_storage_key(
        self,
        visita_id: int,
        video_id: str,
        local_path: str | Path,
        *,
        today: date | None = None,
    ) -> str:
        current_date = today or date.today()
        safe_video_id = _safe_key_part(video_id) or Path(local_path).stem or "video"
        suffix = Path(local_path).suffix.lower() or ".mp4"
        if suffix == ".bin":
            suffix = ".mp4"
        return (
            f"visitas/{current_date:%Y/%m/%d}/{int(visita_id)}/"
            f"videos/{safe_video_id}{suffix}"
        )

    def upload_visit_video(
        self,
        visita_id: int,
        local_path: str | Path,
        video_id: str,
        mime_type: str = "",
    ) -> dict:
        size = self.validate_video_file(local_path)
        storage_key = self.build_video_storage_key(visita_id, video_id, local_path)
        content_type = str(mime_type or "").strip() or "video/mp4"
        try:
            result = upload_file(
                local_path=local_path,
                storage_key=storage_key,
                content_type=content_type,
            )
        except ObjectStorageError as exc:
            raise VideoUploadError(str(exc)) from exc
        result["size_bytes"] = size
        result["content_type"] = content_type
        return result


def video_max_mb() -> float:
    return _positive_float(os.getenv("VIDEO_MAX_MB"), 15.0)


def video_max_seconds() -> int:
    return int(_positive_float(os.getenv("VIDEO_MAX_SECONDS"), 15.0))


def video_max_per_visita() -> int:
    return int(_positive_float(os.getenv("VIDEO_MAX_PER_VISITA"), 3.0))


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(str(value or "").replace(",", "."))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _safe_key_part(value: object) -> str:
    safe = []
    for character in str(value or "").strip():
        if character.isalnum() or character in {"-", "_"}:
            safe.append(character)
        else:
            safe.append("_")
    return "".join(safe).strip("_")[:80]
