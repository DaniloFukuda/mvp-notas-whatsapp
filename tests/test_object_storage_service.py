import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services import object_storage_service
from services.object_storage_service import ObjectStorageError


def _set_spaces_env(monkeypatch, **overrides):
    values = {
        "SPACES_ENABLED": "true",
        "SPACES_REGION": "sfo3",
        "SPACES_BUCKET": "lucre-agro-midias",
        "SPACES_ENDPOINT": "https://sfo3.digitaloceanspaces.com",
        "SPACES_PUBLIC_BASE_URL": (
            "https://lucre-agro-midias.sfo3.digitaloceanspaces.com"
        ),
        "SPACES_ACCESS_KEY": "test-access",
        "SPACES_SECRET_KEY": "test-secret",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_spaces_disabled_does_not_try_boto3_upload(monkeypatch, tmp_path):
    monkeypatch.setenv("SPACES_ENABLED", "false")
    monkeypatch.setitem(sys.modules, "boto3", _FailingBoto3())
    local_file = tmp_path / "sample.txt"
    local_file.write_text("sample", encoding="utf-8")

    with pytest.raises(ObjectStorageError, match="desabilitado"):
        object_storage_service.upload_file(local_file, "tests/sample.txt")


def test_missing_config_raises_clear_error(monkeypatch, tmp_path):
    _set_spaces_env(monkeypatch, SPACES_BUCKET="", SPACES_SECRET_KEY="")
    local_file = tmp_path / "sample.txt"
    local_file.write_text("sample", encoding="utf-8")

    with pytest.raises(ObjectStorageError) as exc_info:
        object_storage_service.upload_file(local_file, "tests/sample.txt")

    message = str(exc_info.value)
    assert "SPACES_BUCKET" in message
    assert "SPACES_SECRET_KEY" in message


def test_upload_creates_boto3_client_with_endpoint(monkeypatch, tmp_path):
    _set_spaces_env(monkeypatch)
    fake_boto3 = _FakeBoto3()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    local_file = tmp_path / "sample.txt"
    local_file.write_text("sample", encoding="utf-8")

    object_storage_service.upload_file(local_file, "tests/sample.txt")

    assert fake_boto3.client_calls == [
        {
            "service_name": "s3",
            "region_name": "sfo3",
            "endpoint_url": "https://sfo3.digitaloceanspaces.com",
            "aws_access_key_id": "test-access",
            "aws_secret_access_key": "test-secret",
        }
    ]


def test_upload_sends_file_to_bucket_and_key(monkeypatch, tmp_path):
    _set_spaces_env(monkeypatch)
    fake_boto3 = _FakeBoto3()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    local_file = tmp_path / "sample.txt"
    local_file.write_text("sample", encoding="utf-8")

    object_storage_service.upload_file(
        local_file,
        "/tests/sample.txt",
        content_type="text/plain",
    )

    assert fake_boto3.created_client.uploads == [
        {
            "bucket": "lucre-agro-midias",
            "key": "tests/sample.txt",
            "content": b"sample",
            "extra_args": {"ContentType": "text/plain", "ACL": "public-read"},
        }
    ]


def test_upload_usa_acl_publica_para_evitar_access_denied(monkeypatch, tmp_path):
    _set_spaces_env(monkeypatch)
    fake_boto3 = _FakeBoto3()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    local_file = tmp_path / "video.mp4"
    local_file.write_bytes(b"video")

    result = object_storage_service.upload_file(
        local_file,
        "visitas/2026/07/08/31/videos/video.mp4",
        content_type="video/mp4",
    )

    assert fake_boto3.created_client.uploads[0]["extra_args"] == {
        "ContentType": "video/mp4",
        "ACL": "public-read",
    }
    assert result["public_url"] == (
        "https://lucre-agro-midias.sfo3.digitaloceanspaces.com/"
        "visitas/2026/07/08/31/videos/video.mp4"
    )


def test_upload_returns_metadata(monkeypatch, tmp_path):
    _set_spaces_env(monkeypatch)
    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3())
    local_file = tmp_path / "sample.txt"
    local_file.write_text("sample", encoding="utf-8")

    result = object_storage_service.upload_file(local_file, "tests/sample.txt")

    assert result["bucket"] == "lucre-agro-midias"
    assert result["storage_key"] == "tests/sample.txt"
    assert (
        result["public_url"]
        == "https://lucre-agro-midias.sfo3.digitaloceanspaces.com/tests/sample.txt"
    )
    assert result["size_bytes"] == 6
    assert result["content_type"] == "text/plain"


class _FakeBoto3:
    def __init__(self):
        self.client_calls = []
        self.created_client = _FakeS3Client()

    def client(self, service_name, **kwargs):
        kwargs["service_name"] = service_name
        self.client_calls.append(kwargs)
        return self.created_client


class _FailingBoto3:
    def client(self, **kwargs):
        raise AssertionError("boto3 client should not be created")


class _FakeS3Client:
    def __init__(self):
        self.uploads = []

    def upload_fileobj(self, file_obj, bucket, key, ExtraArgs=None):
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "content": file_obj.read(),
                "extra_args": ExtraArgs,
            }
        )
