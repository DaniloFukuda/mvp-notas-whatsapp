from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import requests as default_requests

from services.whatsapp_meta_error_service import (
    WhatsAppSendError,
    classify_meta_response,
    network_error,
    timeout_error,
)


logger = logging.getLogger(__name__)


def reliability_diagnostics_enabled() -> bool:
    return os.getenv("WHATSAPP_RELIABILITY_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def recipient_key(value: str) -> str:
    recipient = str(value or "").strip()
    if not recipient:
        return ""
    return hashlib.sha256(recipient.encode()).hexdigest()[:10]


def send_payload(
    payload: dict,
    *,
    token: str,
    phone_number_id: str,
    api_version: str,
    timeout: int = 20,
    requests_module: Any = None,
    message_kind: str = "",
) -> dict:
    requests_module = requests_module or default_requests
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    kind = message_kind or str(payload.get("type") or "unknown")
    recipient = str(payload.get("to") or "")
    try:
        response = requests_module.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except Exception as exc:
        send_error = timeout_error(kind) if _looks_like_timeout(exc, requests_module) else network_error(kind)
        _log_failure(send_error, recipient)
        raise send_error from exc

    body = _response_json(response)
    send_error = classify_meta_response(
        response.status_code,
        body,
        retry_after=_header_value(response, "Retry-After"),
        message_kind=kind,
    )
    if send_error is not None:
        _log_failure(send_error, recipient)
        raise send_error
    _log_success(response.status_code, kind, recipient)
    return body if isinstance(body, dict) else {}


def _response_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _header_value(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None) or {}
    try:
        return headers.get(name) or headers.get(name.lower())
    except AttributeError:
        return None


def _looks_like_timeout(exc: Exception, requests_module: Any) -> bool:
    timeout_types = []
    exceptions = getattr(requests_module, "exceptions", None)
    timeout_type = getattr(exceptions, "Timeout", None) if exceptions is not None else None
    if isinstance(timeout_type, type):
        timeout_types.append(timeout_type)
    timeout_types.append(TimeoutError)
    if any(isinstance(exc, item) for item in timeout_types):
        return True
    return "timeout" in exc.__class__.__name__.lower()


def _log_success(status_code: int, message_kind: str, recipient: str) -> None:
    logger.info(
        "event=whatsapp_send_succeeded message_kind=%s http_status=%s recipient_key=%s",
        message_kind,
        status_code,
        recipient_key(recipient),
    )


def _log_failure(exc: WhatsAppSendError, recipient: str) -> None:
    if reliability_diagnostics_enabled():
        logger.error(
            "event=whatsapp_send_failed message_kind=%s http_status=%s meta_code=%s meta_subcode=%s category=%s retryable=%s fallback_allowed=%s recipient_key=%s fbtrace_id=%s retry_after_seconds=%s",
            exc.message_kind,
            exc.http_status,
            exc.meta_code,
            exc.meta_subcode,
            exc.category,
            str(exc.retryable).lower(),
            str(exc.fallback_allowed).lower(),
            recipient_key(recipient),
            exc.fbtrace_id,
            exc.retry_after_seconds,
        )
        return
    logger.error(
        "event=whatsapp_send_failed message_kind=%s http_status=%s category=%s retryable=%s fallback_allowed=%s recipient_key=%s",
        exc.message_kind,
        exc.http_status,
        exc.category,
        str(exc.retryable).lower(),
        str(exc.fallback_allowed).lower(),
        recipient_key(recipient),
    )
