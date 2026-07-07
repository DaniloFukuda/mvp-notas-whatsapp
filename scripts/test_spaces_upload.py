import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.object_storage_service import ObjectStorageError, upload_file


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_simple(PROJECT_ROOT / ".env")
        return
    load_dotenv(PROJECT_ROOT / ".env")


def _load_env_simple(path: Path) -> None:
    if not path.is_file():
        return
    import os

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    storage_key = "tests/manual/spaces-upload-test.txt"
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".txt",
            delete=False,
        ) as temp_file:
            temp_file.write("Teste manual de upload para DigitalOcean Spaces.\n")
            temp_path = Path(temp_file.name)
        try:
            result = upload_file(
                local_path=temp_path,
                storage_key=storage_key,
                content_type="text/plain",
            )
        finally:
            temp_path.unlink(missing_ok=True)
    except ObjectStorageError as exc:
        print(f"Erro no upload para Spaces: {exc}")
        return 1
    except Exception as exc:
        print(f"Erro inesperado no upload para Spaces: {exc}")
        return 1

    print("Upload para DigitalOcean Spaces concluido com sucesso.")
    print(f"bucket: {result['bucket']}")
    print(f"storage_key: {result['storage_key']}")
    print(f"public_url: {result['public_url']}")
    print(f"size_bytes: {result['size_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
