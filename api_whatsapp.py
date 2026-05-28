import json
import logging
import mimetypes
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from core.database import (
    get_processed_document_by_whatsapp_image_sha256_sender,
    get_processed_document_by_whatsapp_message_id,
)
from core.storage import save_processing_result
from services.document_processing_service import process_document_file


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()
WHATSAPP_UPLOAD_DIR = Path("data/documentos/uploads/whatsapp")
DEFAULT_GRAPH_API_VERSION = "v21.0"


@router.get("/webhook/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> Response:
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    received_token = (hub_verify_token or "").strip()

    print("[WhatsApp Webhook] hub_mode:", hub_mode)
    print("[WhatsApp Webhook] received_token preenchido:", bool(received_token))
    print("[WhatsApp Webhook] expected_token carregado:", bool(expected_token))
    print("[WhatsApp Webhook] token bate:", received_token == expected_token)

    if hub_mode == "subscribe" and received_token == expected_token and hub_challenge:
        return Response(content=hub_challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Token de verificacao invalido.")


@router.post("/webhook/whatsapp")
async def receive_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        logger.warning("Webhook WhatsApp recebido com JSON invalido.")
        return {"status": "ignored"}
    except Exception:
        logger.exception("Webhook WhatsApp recebido, mas nao foi possivel ler o JSON.")
        return {"status": "ignored"}

    try:
        logger.info("Webhook WhatsApp recebido")
        _log_whatsapp_webhook_summary(payload)

        for message in _extract_messages(payload):
            background_tasks.add_task(_handle_whatsapp_message, message)
    except Exception:
        logger.exception("Erro ao interpretar payload do webhook WhatsApp.")

    return {"status": "received"}


def get_media_url(media_id: str) -> str:
    requests = _requests_module()
    token = _required_env("WHATSAPP_TOKEN")
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION)
    response = requests.get(
        f"https://graph.facebook.com/{api_version}/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    response.raise_for_status()
    return str(response.json().get("url") or "")


def download_media(media_id: str, destino: str | Path) -> Path:
    requests = _requests_module()
    token = _required_env("WHATSAPP_TOKEN")
    media_url = get_media_url(media_id)
    if not media_url:
        raise RuntimeError("URL da midia nao retornada pela WhatsApp Cloud API.")

    response = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    response.raise_for_status()

    destination = Path(destino)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def send_whatsapp_text(to: str, message: str) -> None:
    requests = _requests_module()
    token = _required_env("WHATSAPP_TOKEN")
    phone_number_id = _required_env("WHATSAPP_PHONE_NUMBER_ID")
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION)
    message_type = "text"
    recipient, recipient_strategy = _resolve_whatsapp_reply_recipient(to)

    try:
        response = requests.post(
            f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": message_type,
                "text": {"body": message},
            },
            timeout=20,
        )
    except Exception:
        logger.exception(
            "Erro de rede ao enviar resposta WhatsApp: to=%s type=%s estrategia=%s",
            _mask_phone(recipient),
            message_type,
            recipient_strategy,
        )
        return

    logger.info(
        "Resposta da Meta ao envio WhatsApp: status_code=%s to=%s type=%s estrategia=%s",
        response.status_code,
        _mask_phone(recipient),
        message_type,
        recipient_strategy,
    )
    if response.status_code >= 400:
        logger.error(
            "Erro da Meta ao enviar resposta WhatsApp: status_code=%s to=%s type=%s estrategia=%s body=%s",
            response.status_code,
            _mask_phone(recipient),
            message_type,
            recipient_strategy,
            _safe_response_body(response),
        )


def _handle_whatsapp_message(message: dict) -> None:
    # A Meta envia o wa_id normalizado no campo "from"; no sandbox, o numero permitido
    # pode ser diferente e deve ser definido em WHATSAPP_TEST_RECIPIENT_PHONE.
    sender_phone = str(message.get("from") or "")
    message_id = str(message.get("id") or "").strip()
    message_type = str(message.get("type") or "")
    text = _extract_text(message)
    caption = _extract_caption(message, message_type)
    media = message.get(message_type) if message_type in ("image", "document") else {}
    media_id = str((media or {}).get("id") or "")
    image_sha256 = str((media or {}).get("sha256") or "") if message_type == "image" else ""
    mime_type = str((media or {}).get("mime_type") or "")
    whatsapp_timestamp = str(message.get("timestamp") or "").strip()
    data_hora_recebimento = _received_at_from_whatsapp_timestamp(whatsapp_timestamp)
    normalized_caption = _normalize_caption(caption)

    logger.info(
        "Mensagem WhatsApp extraida: from=%s message_id=%s type=%s has_text=%s has_caption=%s media_id=%s image_sha256=%s mime_type=%s",
        _mask_phone(sender_phone),
        _mask_message_id(message_id),
        message_type,
        bool(text),
        bool(caption),
        _mask_media_id(media_id),
        _mask_sha256(image_sha256),
        mime_type,
    )

    if not sender_phone:
        logger.warning("Mensagem WhatsApp sem remetente ignorada.")
        return

    if message_type == "text":
        _safe_send_text(
            sender_phone,
            _text_message_reply(),
        )
        return

    if message_type not in ("image", "document") or not media_id:
        _safe_send_text(
            sender_phone,
            "Recebi sua mensagem, mas por enquanto consigo processar apenas imagem ou documento.",
        )
        return

    if _was_whatsapp_message_processed(message_id):
        logger.info(
            "Mensagem WhatsApp duplicada ignorada: from=%s message_id=%s",
            _mask_phone(sender_phone),
            _mask_message_id(message_id),
        )
        _safe_send_text(
            sender_phone,
            "Esse documento já foi recebido e processado anteriormente ✅",
        )
        return

    if _was_whatsapp_image_processed_for_sender(image_sha256, sender_phone):
        logger.info(
            "Imagem WhatsApp duplicada ignorada: from=%s message_id=%s image_sha256=%s",
            _mask_phone(sender_phone),
            _mask_message_id(message_id),
            _mask_sha256(image_sha256),
        )
        _safe_send_text(
            sender_phone,
            "Essa imagem j\u00e1 foi recebida e processada anteriormente \u2705",
        )
        return

    document_type = _classify_document_type(caption)
    logger.info(
        "Legenda WhatsApp classificada: original=%s normalizada=%s tipo=%s message_id=%s image_sha256=%s",
        _safe_text_for_log(caption),
        _safe_text_for_log(normalized_caption),
        document_type or "-",
        _mask_message_id(message_id),
        _mask_sha256(image_sha256),
    )
    if not document_type:
        _safe_send_text(sender_phone, _missing_type_message())
        return

    destination = _build_media_destination(
        sender_phone=sender_phone,
        media_id=media_id,
        mime_type=mime_type,
    )

    try:
        downloaded_path = download_media(media_id, destination)
    except Exception as exc:
        logger.exception(
            "Falha ao baixar midia do WhatsApp: media_id=%s status_code=%s erro=%s",
            _mask_media_id(media_id),
            _http_status_from_exception(exc) or "-",
            _safe_exception_summary(exc),
        )
        _register_processing_error(
            document_type=document_type,
            caminho_arquivo=str(destination),
            message="N\u00e3o foi poss\u00edvel baixar a m\u00eddia do WhatsApp. Verifique token/permiss\u00e3o da Meta.",
            sender_phone=sender_phone,
            caption=caption,
            whatsapp_message_id=message_id,
            whatsapp_media_id=media_id,
            whatsapp_image_sha256=image_sha256,
            whatsapp_timestamp=whatsapp_timestamp,
            data_hora_recebimento=data_hora_recebimento,
        )
        _safe_send_text(sender_phone, _processing_error_message())
        return

    try:
        result = process_document_file(
            tipo_documento=document_type,
            caminho_arquivo=str(downloaded_path),
            origem="whatsapp",
            telefone_remetente=sender_phone,
            whatsapp_message_id=message_id,
            whatsapp_media_id=media_id,
            whatsapp_image_sha256=image_sha256,
            whatsapp_timestamp=whatsapp_timestamp,
            data_hora_recebimento=data_hora_recebimento,
        )
    except Exception as exc:
        logger.exception("Erro ao processar midia do WhatsApp.")
        _register_processing_error(
            document_type=document_type,
            caminho_arquivo=str(destination),
            message=f"Erro no processamento via WhatsApp: {exc}",
            sender_phone=sender_phone,
            caption=caption,
            whatsapp_message_id=message_id,
            whatsapp_media_id=media_id,
            whatsapp_image_sha256=image_sha256,
            whatsapp_timestamp=whatsapp_timestamp,
            data_hora_recebimento=data_hora_recebimento,
        )
        _safe_send_text(sender_phone, _processing_error_message())
        return

    if result.sucesso:
        _safe_send_text(sender_phone, _success_message(result))
        return

    _safe_send_text(sender_phone, _review_needed_message())


def _extract_messages(payload: dict) -> list[dict]:
    messages: list[dict] = []
    if not isinstance(payload, dict):
        return messages

    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            for message in value.get("messages", []) or []:
                if isinstance(message, dict):
                    messages.append(message)
    return messages


def _log_whatsapp_webhook_summary(payload: dict) -> None:
    if not isinstance(payload, dict):
        logger.info("Webhook WhatsApp payload inesperado: type=%s", type(payload).__name__)
        return

    object_value = str(payload.get("object") or "")
    logger.info("Webhook WhatsApp object recebido: %s", object_value or "-")

    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue

            field = str(change.get("field") or "")
            value = change.get("value") or {}
            if not isinstance(value, dict):
                logger.info("Webhook WhatsApp field recebido: %s", field or "-")
                continue

            metadata = value.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            phone_number_id = str(metadata.get("phone_number_id") or "")

            messages = value.get("messages", []) or []
            if not messages:
                logger.info(
                    "Webhook WhatsApp resumo: field=%s phone_number_id=%s sem mensagem",
                    field or "-",
                    phone_number_id or "-",
                )
                continue

            for message in messages:
                if not isinstance(message, dict):
                    continue

                message_type = str(message.get("type") or "")
                message_id = str(message.get("id") or "")
                sender_phone = str(message.get("from") or "")
                text = _extract_text(message)
                media_id = _extract_media_id(message, message_type)

                logger.info(
                    "Webhook WhatsApp resumo: field=%s phone_number_id=%s message_id=%s type=%s from=%s has_text=%s text=%s media_id=%s",
                    field or "-",
                    phone_number_id or "-",
                    _mask_message_id(message_id),
                    message_type or "-",
                    _mask_phone(sender_phone),
                    bool(text),
                    _safe_text_for_log(text),
                    _mask_media_id(media_id),
                )


def _extract_text(message: dict) -> str:
    text = message.get("text") or {}
    return str(text.get("body") or "").strip()


def _extract_caption(message: dict, message_type: str) -> str:
    if message_type not in ("image", "document"):
        return ""
    media = message.get(message_type) or {}
    return str(media.get("caption") or "").strip()


def _extract_media_id(message: dict, message_type: str) -> str:
    if message_type not in ("image", "document", "audio", "video", "sticker"):
        return ""
    media = message.get(message_type) or {}
    if not isinstance(media, dict):
        return ""
    return str(media.get("id") or "")


def _classify_document_type(caption: str) -> str | None:
    normalized = _normalize_caption(caption)
    if not normalized:
        return None

    compact = normalized.replace(" ", "")
    compact_alnum = re.sub(r"[^a-z0-9]+", "", normalized)
    tokens = set(normalized.split())

    if (
        "nota fiscal" in normalized
        or "nota" in tokens
        or "nf" in tokens
        or "nfce" in tokens
        or "nfce" in compact
        or "nfce" in compact_alnum
    ):
        return "nota_fiscal"

    if any(term in tokens for term in ("recibo", "comprovante", "pix", "pagamento")):
        return "recibo_comprovante"

    return None


def _normalize_caption(caption: str) -> str:
    text = unicodedata.normalize("NFD", str(caption or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _build_media_destination(sender_phone: str, media_id: str, mime_type: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_phone = _safe_filename_part(sender_phone) or "sem_telefone"
    extension = _extension_from_mime_type(mime_type)
    safe_media_id = _safe_filename_part(media_id)[-12:] or "midia"
    return WHATSAPP_UPLOAD_DIR / f"{timestamp}_{safe_phone}_{safe_media_id}{extension}"


def _was_whatsapp_message_processed(message_id: str) -> bool:
    if not message_id:
        return False

    return get_processed_document_by_whatsapp_message_id(message_id) is not None


def _was_whatsapp_image_processed_for_sender(image_sha256: str, sender_phone: str) -> bool:
    if not image_sha256 or not sender_phone:
        return False

    return (
        get_processed_document_by_whatsapp_image_sha256_sender(image_sha256, sender_phone)
        is not None
    )


def _received_at_from_whatsapp_timestamp(timestamp: str) -> str:
    try:
        timestamp_seconds = int(str(timestamp or "").strip())
    except Exception:
        return _format_received_at(datetime.now())

    try:
        received_at = datetime.fromtimestamp(
            timestamp_seconds,
            tz=ZoneInfo("America/Sao_Paulo"),
        )
    except Exception:
        received_at = datetime.fromtimestamp(timestamp_seconds)

    return _format_received_at(received_at)


def _format_received_at(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M")


def _extension_from_mime_type(mime_type: str) -> str:
    extension = mimetypes.guess_extension(mime_type or "")
    if extension == ".jpe":
        return ".jpg"
    return extension or ".bin"


def _safe_filename_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "")).strip("_")


def _success_message(result) -> str:
    if _result_needs_review(result):
        return _review_needed_message()

    document_label = _human_document_type(result.tipo_documento)
    received_line = f"{document_label} recebido ✅"
    if "nota" in str(result.tipo_documento or "").lower():
        received_line = f"{document_label} recebida ✅"

    return "\n".join(
        [
            received_line,
            f"Fornecedor: {result.fornecedor or '-'}",
            f"Valor: {_format_brl_text(result.valor_total)}",
            f"Data: {result.data_documento or '-'}",
            "Registrado no sistema.",
        ]
    )


def _result_needs_review(result) -> bool:
    if bool(getattr(result, "needs_review", False)):
        return True

    required_values = (
        getattr(result, "fornecedor", ""),
        getattr(result, "valor_total", ""),
        getattr(result, "data_documento", ""),
    )
    return any(not str(value or "").strip() for value in required_values)


def _review_needed_message() -> str:
    return "\n".join(
        [
            "Documento recebido, mas precisa de conferência ⚠️",
            "Ele foi salvo para revisão no sistema.",
        ]
    )


def _missing_type_message() -> str:
    return "\n".join(
        [
            "Recebi o arquivo OK",
            "",
            "Mas preciso saber o tipo do documento.",
            "Reenvie com a legenda:",
            "\"nota fiscal\"",
            "ou",
            "\"recibo\"",
        ]
    )


def _processing_error_message() -> str:
    public_url = _base_public_url()
    error_url = f"{public_url}/documentos/erros" if public_url else "/documentos/erros"
    return "\n".join(
        [
            "Recebi o documento, mas nao consegui processar automaticamente.",
            "",
            "Ele foi registrado para conferencia manual.",
            "Verifique depois em:",
            error_url,
        ]
    )


def _text_message_reply() -> str:
    return "\n".join(
        [
            "Recebi sua mensagem ✅",
            "",
            "Para enviar uma nota fiscal, mande a imagem com a legenda: nota fiscal.",
            "Para recibo ou comprovante, mande a imagem com a legenda: recibo.",
        ]
    )


def _human_document_type(tipo_documento: str) -> str:
    normalized = str(tipo_documento or "").lower()
    if "nota" in normalized:
        return "Nota fiscal"
    if "recibo" in normalized or "comprovante" in normalized:
        return "Recibo/comprovante"
    return tipo_documento or "-"


def _format_brl_text(value: object) -> str:
    if value in (None, ""):
        return "-"

    try:
        formatted = f"{float(str(value).replace(',', '.')):,.2f}"
    except (TypeError, ValueError):
        return str(value)

    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _register_processing_error(
    document_type: str,
    caminho_arquivo: str,
    message: str,
    sender_phone: str,
    caption: str = "",
    whatsapp_message_id: str = "",
    whatsapp_media_id: str = "",
    whatsapp_image_sha256: str = "",
    whatsapp_timestamp: str = "",
    data_hora_recebimento: str = "",
) -> None:
    try:
        observation_parts = ["origem: whatsapp"]
        if sender_phone:
            observation_parts.append(f"telefone_remetente: {sender_phone}")
        if caption:
            observation_parts.append(f"legenda: {_safe_text_for_log(caption)}")

        save_processing_result(
            tipo_documento=_storage_document_type(document_type),
            caminho_imagem=caminho_arquivo,
            sucesso=False,
            mensagem=message,
            responsavel="whatsapp",
            observacao=" | ".join(observation_parts),
            needs_review=True,
            whatsapp_message_id=whatsapp_message_id,
            whatsapp_media_id=whatsapp_media_id,
            whatsapp_image_sha256=whatsapp_image_sha256,
            whatsapp_timestamp=whatsapp_timestamp,
            data_hora_recebimento=data_hora_recebimento,
        )
    except Exception:
        logger.exception("Erro ao registrar documento do WhatsApp para revisao manual.")


def _storage_document_type(document_type: str) -> str:
    if document_type == "nota_fiscal":
        return "nota_fiscal"
    if document_type == "recibo_comprovante":
        return "recibo_comprovante"
    return str(document_type or "tipo_invalido")


def _base_public_url() -> str:
    return os.getenv("BASE_PUBLIC_URL", "").rstrip("/")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Variavel de ambiente obrigatoria nao configurada: {name}")
    return value


def _resolve_whatsapp_reply_recipient(webhook_from: str) -> tuple[str, str]:
    test_recipient = os.getenv("WHATSAPP_TEST_RECIPIENT_PHONE", "").strip()
    if test_recipient:
        return test_recipient, "destinatario via WHATSAPP_TEST_RECIPIENT_PHONE"

    return str(webhook_from or "").strip(), "destinatario via from/wa_id do webhook"


def _requests_module():
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "Dependencia requests nao instalada. Rode: pip install -r requirements.txt"
        ) from exc

    return requests


def _safe_send_text(to: str, message: str) -> None:
    try:
        send_whatsapp_text(to, message)
    except Exception:
        logger.exception("Erro ao enviar resposta de WhatsApp para %s", _mask_phone(to))


def _safe_payload_for_log(payload: dict) -> str:
    redacted = _redact_sensitive_payload(payload)
    return json.dumps(redacted, ensure_ascii=False, default=str)[:5000]


def _safe_text_for_log(text: str) -> str:
    return str(text or "").replace("\r", " ").replace("\n", " ")[:500]


def _safe_response_body(response) -> str:
    try:
        return str(response.text or "")[:2000]
    except Exception:
        return "<corpo indisponivel>"


def _http_status_from_exception(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        return None

    try:
        return int(status_code)
    except (TypeError, ValueError):
        return None


def _safe_exception_summary(exc: Exception) -> str:
    text = str(exc or exc.__class__.__name__)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", text)
    return text[:500]


def _redact_sensitive_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key in {"wa_id", "from", "phone_number_id", "display_phone_number"}:
                redacted[key] = _mask_phone(str(item))
            elif key == "id" and isinstance(item, str):
                redacted[key] = _mask_media_id(item)
            else:
                redacted[key] = _redact_sensitive_payload(item)
        return redacted

    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]

    return value


def _mask_phone(phone: str) -> str:
    phone = str(phone or "")
    if len(phone) <= 4:
        return "***"
    return f"***{phone[-4:]}"


def _mask_media_id(media_id: str) -> str:
    media_id = str(media_id or "")
    if len(media_id) <= 8:
        return "***"
    return f"{media_id[:4]}...{media_id[-4:]}"


def _mask_message_id(message_id: str) -> str:
    message_id = str(message_id or "")
    if len(message_id) <= 12:
        return "***"
    return f"{message_id[:6]}...{message_id[-6:]}"


def _mask_sha256(value: str) -> str:
    value = str(value or "")
    if not value:
        return "-"
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-6:]}"
