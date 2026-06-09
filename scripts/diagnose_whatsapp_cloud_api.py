import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_GRAPH_API_VERSION = "v21.0"
MESSAGE_BODY = "Diagnostico seguro da integracao WhatsApp Cloud API."


def main() -> int:
    load_dotenv(dotenv_path=ENV_PATH)

    canonical_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    legacy_token = os.getenv("WHATSAPP_TOKEN", "").strip()
    token = canonical_token or legacy_token
    values = {
        "WHATSAPP_ACCESS_TOKEN": canonical_token,
        "WHATSAPP_PHONE_NUMBER_ID": os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "WHATSAPP_BUSINESS_ACCOUNT_ID": os.getenv(
            "WHATSAPP_BUSINESS_ACCOUNT_ID", ""
        ).strip(),
        "WHATSAPP_VERIFY_TOKEN": os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip(),
        "WHATSAPP_GRAPH_API_VERSION": os.getenv(
            "WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION
        ).strip(),
        "WHATSAPP_TEST_RECIPIENT_PHONE": os.getenv(
            "WHATSAPP_TEST_RECIPIENT_PHONE", ""
        ).strip(),
        "BASE_PUBLIC_URL": os.getenv("BASE_PUBLIC_URL", "").strip(),
    }

    print("Configuracao WhatsApp Cloud API:")
    for name, value in values.items():
        print(f"- {name}: {_display_value(name, value)}")

    configuration_error = False
    if not canonical_token and legacy_token:
        configuration_error = True
        print(
            "- AVISO: usando WHATSAPP_TOKEN legado. "
            f"Token: {_mask_token(legacy_token)}. "
            "Renomeie a chave local para WHATSAPP_ACCESS_TOKEN."
        )

    required = (
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_BUSINESS_ACCOUNT_ID",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_GRAPH_API_VERSION",
        "WHATSAPP_TEST_RECIPIENT_PHONE",
        "BASE_PUBLIC_URL",
    )
    missing = [name for name in required if not values[name]]
    if not token:
        missing.insert(0, "WHATSAPP_ACCESS_TOKEN")
    if missing:
        print("Variaveis obrigatorias ausentes:")
        for name in missing:
            print(f"- {name}")
        return 1

    api_version = values["WHATSAPP_GRAPH_API_VERSION"]
    phone_number_id = values["WHATSAPP_PHONE_NUMBER_ID"]
    recipient = values["WHATSAPP_TEST_RECIPIENT_PHONE"]
    headers = {"Authorization": f"Bearer {token}"}
    sensitive_values = [
        token,
        phone_number_id,
        values["WHATSAPP_BUSINESS_ACCOUNT_ID"],
        recipient,
    ]

    get_url = f"https://graph.facebook.com/{api_version}/{phone_number_id}"
    print("\n1. Consultando o objeto WHATSAPP_PHONE_NUMBER_ID...")
    get_ok = False
    try:
        get_response = requests.get(
            get_url,
            headers=headers,
            params={"fields": "id,display_phone_number,verified_name"},
            timeout=30,
        )
        print_response(get_response, sensitive_values)
        get_ok = get_response.ok
    except requests.RequestException as exc:
        print(f"erro_rede: {_sanitize_text(str(exc), sensitive_values)}")

    send_url = f"{get_url}/messages"
    print("\n2. Enviando mensagem para WHATSAPP_TEST_RECIPIENT_PHONE...")
    send_ok = False
    try:
        send_response = requests.post(
            send_url,
            headers={
                **headers,
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": MESSAGE_BODY},
            },
            timeout=30,
        )
        print(f"destinatario: {_mask_value(recipient)}")
        print_response(send_response, sensitive_values)
        send_ok = send_response.ok
    except requests.RequestException as exc:
        print(f"erro_rede: {_sanitize_text(str(exc), sensitive_values)}")

    if configuration_error:
        print("\nDiagnostico concluido com configuracao legada do token.")
    if get_ok and send_ok and not configuration_error:
        print("\nOK: objeto acessivel e mensagem aceita pela Meta.")
        return 0

    print("\nERRO: a integracao ainda requer correcao.")
    return 1


def print_response(response: requests.Response, sensitive_values: list[str]) -> None:
    print(f"status_code: {response.status_code}")
    print("resposta:")
    try:
        body = json.dumps(response.json(), indent=2, ensure_ascii=False)
    except ValueError:
        body = response.text
    print(_sanitize_text(body, sensitive_values)[:4000])


def _display_value(name: str, value: str) -> str:
    if not value:
        return "ausente"
    if name == "WHATSAPP_ACCESS_TOKEN":
        return _mask_token(value)
    if name in {
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_BUSINESS_ACCOUNT_ID",
        "WHATSAPP_TEST_RECIPIENT_PHONE",
    }:
        return _mask_value(value)
    if name == "WHATSAPP_VERIFY_TOKEN":
        return "configurado"
    return value


def _mask_token(value: str) -> str:
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def _mask_value(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


def _sanitize_text(text: str, sensitive_values: list[str]) -> str:
    sanitized = str(text or "")
    for value in sensitive_values:
        if value:
            replacement = _mask_token(value) if len(value) > 40 else _mask_value(value)
            sanitized = sanitized.replace(value, replacement)
    return re.sub(
        r"Bearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer ***",
        sanitized,
        flags=re.IGNORECASE,
    )


if __name__ == "__main__":
    sys.exit(main())
