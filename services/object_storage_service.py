import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path


class ObjectStorageError(RuntimeError):
    """Erro de configuracao ou upload do armazenamento de objetos."""


@dataclass(frozen=True)
class SpacesConfig:
    enabled: bool
    region: str
    bucket: str
    endpoint: str
    public_base_url: str
    access_key: str
    secret_key: str


def spaces_enabled() -> bool:
    return _truthy(os.getenv("SPACES_ENABLED", "false"))


def get_spaces_config() -> SpacesConfig:
    return SpacesConfig(
        enabled=spaces_enabled(),
        region=os.getenv("SPACES_REGION", "").strip(),
        bucket=os.getenv("SPACES_BUCKET", "").strip(),
        endpoint=os.getenv("SPACES_ENDPOINT", "").strip(),
        public_base_url=os.getenv("SPACES_PUBLIC_BASE_URL", "").strip(),
        access_key=os.getenv("SPACES_ACCESS_KEY", "").strip(),
        secret_key=os.getenv("SPACES_SECRET_KEY", "").strip(),
    )


def create_spaces_client(config: SpacesConfig | None = None):
    config = config or get_spaces_config()
    _validate_enabled_config(config)
    try:
        import boto3
    except ImportError as exc:
        raise ObjectStorageError(
            "Dependencia boto3 nao instalada. Rode: pip install -r requirements.txt"
        ) from exc

    return boto3.client(
        "s3",
        region_name=config.region or None,
        endpoint_url=config.endpoint,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
    )


def upload_file(
    local_path: str | Path,
    storage_key: str,
    content_type: str | None = None,
) -> dict:
    config = get_spaces_config()
    if not config.enabled:
        raise ObjectStorageError(
            "DigitalOcean Spaces desabilitado. Configure SPACES_ENABLED=true para enviar arquivos."
        )
    _validate_enabled_config(config)

    path = Path(local_path)
    if not path.is_file():
        raise ObjectStorageError(f"Arquivo local nao encontrado para upload: {path}")

    safe_key = str(storage_key or "").strip().lstrip("/")
    if not safe_key:
        raise ObjectStorageError("storage_key e obrigatorio para upload no Spaces.")

    detected_content_type = (
        str(content_type or "").strip()
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )
    client = create_spaces_client(config)
    extra_args = {"ContentType": detected_content_type, "ACL": "public-read"}
    with path.open("rb") as file_obj:
        client.upload_fileobj(
            file_obj,
            config.bucket,
            safe_key,
            ExtraArgs=extra_args,
        )

    return {
        "bucket": config.bucket,
        "storage_key": safe_key,
        "public_url": _build_public_url(config, safe_key),
        "size_bytes": path.stat().st_size,
        "content_type": detected_content_type,
    }


def delete_file(storage_key: str) -> dict:
    config = get_spaces_config()
    if not config.enabled:
        raise ObjectStorageError("DigitalOcean Spaces desabilitado.")
    _validate_enabled_config(config)

    safe_key = str(storage_key or "").strip().lstrip("/")
    if not safe_key:
        raise ObjectStorageError("storage_key e obrigatorio para remover do Spaces.")

    client = create_spaces_client(config)
    client.delete_object(Bucket=config.bucket, Key=safe_key)
    return {"bucket": config.bucket, "storage_key": safe_key}


def _validate_enabled_config(config: SpacesConfig) -> None:
    if not config.enabled:
        raise ObjectStorageError("DigitalOcean Spaces nao esta habilitado.")
    missing = []
    if not config.bucket:
        missing.append("SPACES_BUCKET")
    if not config.endpoint:
        missing.append("SPACES_ENDPOINT")
    if not config.access_key:
        missing.append("SPACES_ACCESS_KEY")
    if not config.secret_key:
        missing.append("SPACES_SECRET_KEY")
    if missing:
        raise ObjectStorageError(
            "DigitalOcean Spaces habilitado, mas faltam variaveis: "
            + ", ".join(missing)
        )


def _build_public_url(config: SpacesConfig, storage_key: str) -> str:
    base_url = config.public_base_url.rstrip("/")
    if not base_url:
        base_url = f"{config.endpoint.rstrip('/')}/{config.bucket}"
    return f"{base_url}/{storage_key.lstrip('/')}"


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "sim", "on"}
