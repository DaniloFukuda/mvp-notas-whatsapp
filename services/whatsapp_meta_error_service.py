from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class WhatsAppSendErrorCategory(str, Enum):
    SUCCESS = "SUCCESS"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    UNSUPPORTED_MESSAGE_TYPE = "UNSUPPORTED_MESSAGE_TYPE"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    RATE_LIMIT = "RATE_LIMIT"
    TEMPORARY_META = "TEMPORARY_META"
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    RECIPIENT_PERMANENT = "RECIPIENT_PERMANENT"
    WINDOW_OR_TEMPLATE = "WINDOW_OR_TEMPLATE"
    UNKNOWN = "UNKNOWN"


@dataclass
class WhatsAppSendError(Exception):
    category: str
    http_status: int | None = None
    meta_code: int | None = None
    meta_subcode: int | None = None
    retryable: bool = False
    fallback_allowed: bool = False
    retry_after_seconds: int | None = None
    fbtrace_id: str = ""
    message_kind: str = ""

    def __str__(self) -> str:
        parts = [f"category={self.category}"]
        if self.http_status is not None:
            parts.append(f"http_status={self.http_status}")
        if self.meta_code is not None:
            parts.append(f"meta_code={self.meta_code}")
        if self.meta_subcode is not None:
            parts.append(f"meta_subcode={self.meta_subcode}")
        return "WhatsAppSendError(" + " ".join(parts) + ")"


def classify_meta_response(
    http_status: int,
    body: Any,
    retry_after: str | None = None,
    message_kind: str = "",
) -> WhatsAppSendError | None:
    if 200 <= int(http_status) <= 299:
        return None

    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    meta_code = _optional_int(error.get("code"))
    meta_subcode = _optional_int(error.get("error_subcode"))
    error_type = str(error.get("type") or "").lower()
    error_message = str(error.get("message") or "").lower()
    fbtrace_id = str(error.get("fbtrace_id") or "")
    retry_after_seconds = _parse_retry_after(retry_after)
    category = _classify_category(
        http_status=int(http_status),
        meta_code=meta_code,
        meta_subcode=meta_subcode,
        error_type=error_type,
        error_message=error_message,
    )
    retryable = category in {
        WhatsAppSendErrorCategory.RATE_LIMIT,
        WhatsAppSendErrorCategory.TEMPORARY_META,
        WhatsAppSendErrorCategory.NETWORK,
        WhatsAppSendErrorCategory.TIMEOUT,
    }
    fallback_allowed = category in {
        WhatsAppSendErrorCategory.INVALID_PAYLOAD,
        WhatsAppSendErrorCategory.UNSUPPORTED_MESSAGE_TYPE,
    }
    return WhatsAppSendError(
        category=category.value,
        http_status=int(http_status),
        meta_code=meta_code,
        meta_subcode=meta_subcode,
        retryable=retryable,
        fallback_allowed=fallback_allowed,
        retry_after_seconds=retry_after_seconds,
        fbtrace_id=fbtrace_id,
        message_kind=message_kind,
    )


def network_error(message_kind: str = "") -> WhatsAppSendError:
    return WhatsAppSendError(
        category=WhatsAppSendErrorCategory.NETWORK.value,
        retryable=True,
        fallback_allowed=False,
        message_kind=message_kind,
    )


def timeout_error(message_kind: str = "") -> WhatsAppSendError:
    return WhatsAppSendError(
        category=WhatsAppSendErrorCategory.TIMEOUT.value,
        retryable=True,
        fallback_allowed=False,
        message_kind=message_kind,
    )


def _classify_category(
    http_status: int,
    meta_code: int | None,
    meta_subcode: int | None,
    error_type: str,
    error_message: str,
) -> WhatsAppSendErrorCategory:
    text = f"{error_type} {error_message}"
    if http_status == 429 or meta_code in {4, 17, 32, 613} or "rate limit" in text or "too many" in text:
        return WhatsAppSendErrorCategory.RATE_LIMIT
    if http_status == 401 or meta_code in {190, 102} or "token" in text and ("invalid" in text or "expired" in text):
        return WhatsAppSendErrorCategory.AUTHENTICATION
    if http_status == 403 or meta_code in {10, 200, 201, 368} or "permission" in text or "not authorized" in text:
        return WhatsAppSendErrorCategory.PERMISSION
    if _is_window_or_template(meta_code, meta_subcode, text):
        return WhatsAppSendErrorCategory.WINDOW_OR_TEMPLATE
    if _is_recipient_permanent(meta_code, meta_subcode, text):
        return WhatsAppSendErrorCategory.RECIPIENT_PERMANENT
    if _is_unsupported_message_type(meta_code, text):
        return WhatsAppSendErrorCategory.UNSUPPORTED_MESSAGE_TYPE
    if http_status == 400 or "invalid parameter" in text or "payload" in text:
        return WhatsAppSendErrorCategory.INVALID_PAYLOAD
    if http_status in {500, 502, 503, 504}:
        return WhatsAppSendErrorCategory.TEMPORARY_META
    return WhatsAppSendErrorCategory.UNKNOWN


def _is_window_or_template(meta_code: int | None, meta_subcode: int | None, text: str) -> bool:
    if meta_code in {131047, 132001, 132005, 132007, 132012, 132015, 132016}:
        return True
    if meta_subcode in {2494002, 2494010}:
        return True
    return "template" in text or "24 hour" in text or "24-hour" in text or "outside" in text and "window" in text


def _is_recipient_permanent(meta_code: int | None, meta_subcode: int | None, text: str) -> bool:
    if meta_code in {131026, 131030, 131031}:
        return True
    if meta_subcode in {2018001}:
        return True
    return "recipient" in text and ("invalid" in text or "unavailable" in text)


def _is_unsupported_message_type(meta_code: int | None, text: str) -> bool:
    if meta_code in {131051, 131052}:
        return True
    return "unsupported" in text and ("message" in text or "type" in text or "interactive" in text)


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_retry_after(value: str | None) -> int | None:
    try:
        if value in (None, ""):
            return None
        seconds = int(str(value).strip())
        return seconds if seconds >= 0 else None
    except (TypeError, ValueError):
        return None
