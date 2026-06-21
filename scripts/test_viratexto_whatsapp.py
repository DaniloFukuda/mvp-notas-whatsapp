import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


DEFAULT_GRAPH_API_VERSION = "v21.0"
SUPPORTED_AUDIO_EXTENSIONS = {".ogg", ".opus", ".mp3", ".m4a"}
AUDIO_MIME_TYPES = {
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    args = parse_args()
    try:
        config = load_config()
        validate_args(args)
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 1

    if args.dry_run:
        print("Dry-run: nenhuma chamada sera enviada para a Meta.")
        print(f"to: {mask_phone(args.to)}")
        print(f"api_version: {config['api_version']}")
        if args.text:
            print("acao: enviar mensagem de texto")
        if args.audio:
            audio_path = Path(args.audio)
            print("acao: upload de audio e envio como mensagem de audio")
            print(f"arquivo: {audio_path}")
            print(f"mime_type: {audio_mime_type(audio_path)}")
        return 0

    try:
        if args.text:
            response = send_text(config, args.to, args.text)
            print_result("envio_texto", response)
            return 0 if response.ok else 1

        media_id, upload_response = upload_audio(config, Path(args.audio))
        print_result("upload_audio", upload_response, media_id=media_id)
        if not upload_response.ok:
            return 1

        send_response = send_audio(config, args.to, media_id)
        print_result("envio_audio", send_response)
        return 0 if send_response.ok else 1
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", "-")
        print(f"erro_rede: status_http={status} resumo={safe_exception_summary(exc)}")
        return 1
    except Exception as exc:
        print(f"erro: {safe_exception_summary(exc)}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="POC: envia texto ou audio para o ViraTexto via WhatsApp Cloud API."
    )
    parser.add_argument("--to", required=True, help="Numero WhatsApp no formato 55DDDNUMERO.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Texto de teste a enviar.")
    group.add_argument("--audio", help="Caminho do audio .ogg, .opus, .mp3 ou .m4a.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que faria sem chamar a API da Meta.",
    )
    return parser.parse_args()


def load_config() -> dict:
    token = (
        os.getenv("WHATSAPP_TOKEN", "").strip()
        or os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    )
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    api_version = (
        os.getenv("WHATSAPP_API_VERSION", "").strip()
        or os.getenv("WHATSAPP_GRAPH_API_VERSION", "").strip()
        or DEFAULT_GRAPH_API_VERSION
    )

    missing = []
    if not token:
        missing.append("WHATSAPP_TOKEN ou WHATSAPP_ACCESS_TOKEN")
    if not phone_number_id:
        missing.append("WHATSAPP_PHONE_NUMBER_ID")
    if missing:
        raise ValueError("variaveis obrigatorias ausentes: " + ", ".join(missing))

    return {
        "token": token,
        "phone_number_id": phone_number_id,
        "api_version": api_version,
    }


def validate_args(args: argparse.Namespace) -> None:
    if not args.to.strip():
        raise ValueError("--to nao pode ficar vazio.")

    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.is_file():
            raise ValueError(f"arquivo de audio nao encontrado: {audio_path}")
        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            extensions = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
            raise ValueError(f"formato de audio nao suportado. Use: {extensions}")


def send_text(config: dict, to: str, text: str) -> requests.Response:
    url = messages_url(config)
    payload = {
        "messaging_product": "whatsapp",
        "to": to.strip(),
        "type": "text",
        "text": {"body": text},
    }
    return requests.post(url, headers=json_headers(config), json=payload, timeout=30)


def upload_audio(config: dict, audio_path: Path) -> tuple[str, requests.Response]:
    url = media_url(config)
    mime_type = audio_mime_type(audio_path)
    with audio_path.open("rb") as audio_file:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {config['token']}"},
            data={
                "messaging_product": "whatsapp",
                "type": mime_type,
            },
            files={"file": (audio_path.name, audio_file, mime_type)},
            timeout=60,
        )
    media_id = ""
    if response.ok:
        media_id = str(response.json().get("id") or "").strip()
    return media_id, response


def send_audio(config: dict, to: str, media_id: str) -> requests.Response:
    if not media_id:
        raise RuntimeError("upload concluido sem id de midia retornado pela Meta.")
    payload = {
        "messaging_product": "whatsapp",
        "to": to.strip(),
        "type": "audio",
        "audio": {"id": media_id},
    }
    return requests.post(
        messages_url(config),
        headers=json_headers(config),
        json=payload,
        timeout=30,
    )


def messages_url(config: dict) -> str:
    return (
        f"https://graph.facebook.com/{config['api_version']}/"
        f"{config['phone_number_id']}/messages"
    )


def media_url(config: dict) -> str:
    return (
        f"https://graph.facebook.com/{config['api_version']}/"
        f"{config['phone_number_id']}/media"
    )


def json_headers(config: dict) -> dict:
    return {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
    }


def audio_mime_type(audio_path: Path) -> str:
    suffix = audio_path.suffix.lower()
    return AUDIO_MIME_TYPES.get(suffix) or mimetypes.guess_type(audio_path.name)[0] or "audio/ogg"


def print_result(action: str, response: requests.Response, media_id: str = "") -> None:
    message_id = extract_message_id(response)
    error = extract_error_summary(response)
    print(f"acao: {action}")
    print(f"status_http: {response.status_code}")
    if media_id:
        print(f"media_id: {mask_sensitive(media_id)}")
    if message_id:
        print(f"message_id: {mask_sensitive(message_id)}")
    if error:
        print(f"erro_resumido: {error}")


def extract_message_id(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    messages = payload.get("messages") or []
    if messages and isinstance(messages[0], dict):
        return str(messages[0].get("id") or "")
    return ""


def extract_error_summary(response: requests.Response) -> str:
    if response.ok:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return str(response.text or "")[:500]
    error = payload.get("error") or {}
    if not isinstance(error, dict):
        return json.dumps(payload, ensure_ascii=False)[:500]
    parts = [
        str(error.get("type") or "").strip(),
        str(error.get("code") or "").strip(),
        str(error.get("message") or "").strip(),
    ]
    return " | ".join(part for part in parts if part)[:500]


def safe_exception_summary(exc: Exception) -> str:
    return str(exc or exc.__class__.__name__).replace("\r", " ").replace("\n", " ")[:500]


def mask_phone(phone: str) -> str:
    phone = str(phone or "")
    if len(phone) <= 4:
        return "***"
    return f"***{phone[-4:]}"


def mask_sensitive(value: str) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-6:]}"


if __name__ == "__main__":
    sys.exit(main())
