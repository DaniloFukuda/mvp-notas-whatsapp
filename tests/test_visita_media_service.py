import sys
from datetime import date
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services import visita_media_service
from services.object_storage_service import ObjectStorageError
from services.visita_media_service import (
    VideoTooLargeError,
    VideoUploadError,
    VisitaMediaService,
)


def test_build_video_storage_key_organiza_por_data_visita():
    service = VisitaMediaService()

    key = service.build_video_storage_key(
        visita_id=42,
        video_id="wamid.video/123",
        local_path="video.mp4",
        today=date(2026, 7, 6),
    )

    assert key == "visitas/2026/07/06/42/videos/wamid_video_123.mp4"


def test_validate_video_file_rejeita_acima_do_limite(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_MAX_MB", "0.000001")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video grande")

    with pytest.raises(VideoTooLargeError):
        VisitaMediaService().validate_video_file(video)


def test_upload_visit_video_chama_object_storage(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    calls = []

    def fake_upload_file(local_path, storage_key, content_type=None):
        calls.append(
            {
                "local_path": Path(local_path),
                "storage_key": storage_key,
                "content_type": content_type,
            }
        )
        return {
            "bucket": "lucre-agro-midias",
            "storage_key": storage_key,
            "public_url": f"https://cdn.example/{storage_key}",
            "size_bytes": 0,
            "content_type": content_type,
        }

    monkeypatch.setattr(visita_media_service, "upload_file", fake_upload_file)

    result = VisitaMediaService().upload_visit_video(
        visita_id=7,
        local_path=video,
        video_id="video-1",
        mime_type="video/mp4",
    )

    assert calls[0]["local_path"] == video
    assert calls[0]["storage_key"].endswith("/7/videos/video-1.mp4")
    assert calls[0]["content_type"] == "video/mp4"
    assert result["size_bytes"] == 5
    assert result["content_type"] == "video/mp4"


def test_upload_visit_video_converte_erro_storage(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    def fake_upload_file(local_path, storage_key, content_type=None):
        raise ObjectStorageError("spaces desabilitado")

    monkeypatch.setattr(visita_media_service, "upload_file", fake_upload_file)

    with pytest.raises(VideoUploadError):
        VisitaMediaService().upload_visit_video(
            visita_id=7,
            local_path=video,
            video_id="video-1",
            mime_type="video/mp4",
        )
