import logging
import os

import pytest

import api_whatsapp
from services.whatsapp_meta_client import send_payload
from services.whatsapp_meta_error_service import (
    WhatsAppSendError,
    WhatsAppSendErrorCategory,
    classify_meta_response,
)


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None, json_error=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = str(body)
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._body


class FakeRequests:
    class exceptions:
        class Timeout(Exception):
            pass

        class ConnectionError(Exception):
            pass

    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(
            {"url": url, "headers": headers or {}, "json": json, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def _payload(to="5511999999999", body="mensagem sensivel"):
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }


def _meta_error(code=None, subcode=None, message="erro", error_type="OAuthException", fbtrace_id="fb123"):
    error = {"message": message, "type": error_type, "fbtrace_id": fbtrace_id}
    if code is not None:
        error["code"] = code
    if subcode is not None:
        error["error_subcode"] = subcode
    return {"error": error}


def _assert_category(status, body, expected, retryable=False, fallback_allowed=False):
    exc = classify_meta_response(status, body)
    assert exc is not None
    assert exc.category == expected.value
    assert exc.retryable is retryable
    assert exc.fallback_allowed is fallback_allowed
    return exc


def test_meta_client_returns_json_on_http_200():
    fake = FakeRequests([FakeResponse(200, {"messages": [{"id": "wamid.ok"}]})])
    result = send_payload(
        _payload(),
        token="token-ficticio",
        phone_number_id="phone-id",
        api_version="v99.0",
        requests_module=fake,
    )
    assert result["messages"][0]["id"] == "wamid.ok"
    assert fake.calls[0]["timeout"] == 20
    assert fake.calls[0]["url"].endswith("/v99.0/phone-id/messages")


def test_classifier_covers_meta_http_and_body_categories():
    _assert_category(
        400,
        _meta_error(100, message="Invalid parameter in payload"),
        WhatsAppSendErrorCategory.INVALID_PAYLOAD,
        fallback_allowed=True,
    )
    _assert_category(
        400,
        _meta_error(131051, message="Unsupported message type"),
        WhatsAppSendErrorCategory.UNSUPPORTED_MESSAGE_TYPE,
        fallback_allowed=True,
    )
    _assert_category(401, _meta_error(190, message="Invalid OAuth token"), WhatsAppSendErrorCategory.AUTHENTICATION)
    _assert_category(403, _meta_error(10, message="Permission denied"), WhatsAppSendErrorCategory.PERMISSION)
    _assert_category(429, _meta_error(4, message="Rate limit"), WhatsAppSendErrorCategory.RATE_LIMIT, retryable=True)
    for status in (500, 502, 503, 504):
        _assert_category(status, {}, WhatsAppSendErrorCategory.TEMPORARY_META, retryable=True)
    _assert_category(
        400,
        _meta_error(131026, message="Recipient unavailable"),
        WhatsAppSendErrorCategory.RECIPIENT_PERMANENT,
    )
    _assert_category(
        400,
        _meta_error(131047, message="Re-engagement message outside 24-hour window"),
        WhatsAppSendErrorCategory.WINDOW_OR_TEMPLATE,
    )


def test_classifier_preserves_meta_code_subcode_fbtrace_and_retry_after():
    exc = classify_meta_response(
        429,
        _meta_error(4, 99, "rate limit", fbtrace_id="trace-abc"),
        retry_after="17",
    )
    assert exc.meta_code == 4
    assert exc.meta_subcode == 99
    assert exc.fbtrace_id == "trace-abc"
    assert exc.retry_after_seconds == 17


def test_client_classifies_timeout_connection_non_json_missing_error_and_unknown():
    timeout_requests = FakeRequests(error=FakeRequests.exceptions.Timeout("timeout"))
    with pytest.raises(WhatsAppSendError) as timeout_exc:
        send_payload(
            _payload(),
            token="token-ficticio",
            phone_number_id="phone-id",
            api_version="v99.0",
            requests_module=timeout_requests,
        )
    assert timeout_exc.value.category == WhatsAppSendErrorCategory.TIMEOUT.value

    network_requests = FakeRequests(error=FakeRequests.exceptions.ConnectionError("down"))
    with pytest.raises(WhatsAppSendError) as network_exc:
        send_payload(
            _payload(),
            token="token-ficticio",
            phone_number_id="phone-id",
            api_version="v99.0",
            requests_module=network_requests,
        )
    assert network_exc.value.category == WhatsAppSendErrorCategory.NETWORK.value

    for response in (
        FakeResponse(418, json_error=ValueError("no json")),
        FakeResponse(418, {"detail": "sem campo error"}),
    ):
        with pytest.raises(WhatsAppSendError) as unknown_exc:
            send_payload(
                _payload(),
                token="token-ficticio",
                phone_number_id="phone-id",
                api_version="v99.0",
                requests_module=FakeRequests([response]),
            )
        assert unknown_exc.value.category == WhatsAppSendErrorCategory.UNKNOWN.value


def test_failure_log_omits_full_phone_token_and_message_content(caplog):
    os.environ["WHATSAPP_RELIABILITY_ENABLED"] = "true"
    fake = FakeRequests([FakeResponse(429, _meta_error(4, message="Rate limit"))])
    caplog.set_level(logging.ERROR, logger="services.whatsapp_meta_client")
    with pytest.raises(WhatsAppSendError):
        send_payload(
            _payload(to="5511987654321", body="conteudo financeiro secreto"),
            token="token-super-secreto",
            phone_number_id="phone-id",
            api_version="v99.0",
            requests_module=fake,
        )
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "5511987654321" not in logs
    assert "token-super-secreto" not in logs
    assert "conteudo financeiro secreto" not in logs
    assert "recipient_key=" in logs
    os.environ.pop("WHATSAPP_RELIABILITY_ENABLED", None)


@pytest.mark.parametrize(
    ("category", "fallback_allowed", "should_fallback"),
    [
        (WhatsAppSendErrorCategory.INVALID_PAYLOAD, True, True),
        (WhatsAppSendErrorCategory.UNSUPPORTED_MESSAGE_TYPE, True, True),
        (WhatsAppSendErrorCategory.TIMEOUT, False, False),
        (WhatsAppSendErrorCategory.RATE_LIMIT, False, False),
        (WhatsAppSendErrorCategory.AUTHENTICATION, False, False),
        (WhatsAppSendErrorCategory.TEMPORARY_META, False, False),
        (WhatsAppSendErrorCategory.UNKNOWN, False, False),
    ],
)
def test_interactive_list_fallback_rules(monkeypatch, category, fallback_allowed, should_fallback):
    sent_texts = []

    def fake_post(payload, recipient, message_type):
        raise WhatsAppSendError(
            category=category.value,
            retryable=category
            in {
                WhatsAppSendErrorCategory.TIMEOUT,
                WhatsAppSendErrorCategory.RATE_LIMIT,
                WhatsAppSendErrorCategory.TEMPORARY_META,
            },
            fallback_allowed=fallback_allowed,
            message_kind=message_type,
        )

    monkeypatch.setattr(api_whatsapp, "_post_whatsapp_message_payload", fake_post)
    monkeypatch.setattr(
        api_whatsapp,
        "send_whatsapp_text",
        lambda to, message: sent_texts.append((to, message)),
    )

    call = lambda: api_whatsapp.send_whatsapp_list_message(
        to="5511000000000",
        header="Header",
        body="Body",
        button_text="Abrir",
        sections=[{"title": "Opcoes", "rows": [{"id": "a", "title": "A"}]}],
        fallback_text="texto fallback seguro",
    )
    if should_fallback:
        call()
        assert sent_texts == [("5511000000000", "texto fallback seguro")]
    else:
        with pytest.raises(WhatsAppSendError):
            call()
        assert sent_texts == []


def test_timeout_after_post_is_uncertain_and_does_not_send_fallback(monkeypatch):
    fake = FakeRequests(error=FakeRequests.exceptions.Timeout("response timeout"))
    sent_texts = []
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token-ficticio")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v99.0")
    monkeypatch.setattr(api_whatsapp, "_requests_module", lambda: fake)
    monkeypatch.setattr(
        api_whatsapp,
        "send_whatsapp_text",
        lambda to, message: sent_texts.append((to, message)),
    )

    with pytest.raises(WhatsAppSendError) as exc:
        api_whatsapp.send_whatsapp_list_message(
            to="5511000000000",
            header="Header",
            body="Body",
            button_text="Abrir",
            sections=[{"title": "Opcoes", "rows": [{"id": "a", "title": "A"}]}],
            fallback_text="texto fallback seguro",
        )

    assert fake.calls
    assert exc.value.category == WhatsAppSendErrorCategory.TIMEOUT.value
    assert sent_texts == []


def test_rdv_report_send_error_does_not_return_textual_fallback(monkeypatch):
    error = WhatsAppSendError(
        category=WhatsAppSendErrorCategory.TIMEOUT.value,
        retryable=True,
        fallback_allowed=False,
        message_kind="document",
    )
    monkeypatch.setattr(
        api_whatsapp,
        "_send_monthly_rdv_excel",
        lambda sender_phone, month="": (_ for _ in ()).throw(error),
    )

    with pytest.raises(WhatsAppSendError):
        api_whatsapp._handle_global_rdv_command(
            "5511000000000",
            {"id": 1},
            "planilha",
        )
