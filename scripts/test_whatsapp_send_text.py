import json
import os
import sys

import requests
from dotenv import load_dotenv


MESSAGE_BODY = "Teste enviado pelo backend do MVP \u2705"


def main() -> int:
    load_dotenv()

    token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
        or os.getenv("WHATSAPP_TOKEN", "").strip()
    )
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", "").strip()
    recipient = os.getenv("WHATSAPP_TEST_RECIPIENT_PHONE", "").strip()
    recipient_strategy = "destinatario via WHATSAPP_TEST_RECIPIENT_PHONE"

    missing_vars = []
    if not token:
        missing_vars.append("WHATSAPP_ACCESS_TOKEN")
    if not phone_number_id:
        missing_vars.append("WHATSAPP_PHONE_NUMBER_ID")
    if not api_version:
        missing_vars.append("WHATSAPP_GRAPH_API_VERSION")
    if not recipient:
        missing_vars.append("WHATSAPP_TEST_RECIPIENT_PHONE")

    if missing_vars:
        print("Variaveis ausentes no .env:")
        for var_name in missing_vars:
            print(f"- {var_name}")
        return 1

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {
            "body": MESSAGE_BODY,
        },
    }

    print(
        "Enviando mensagem de teste: "
        f"to={mask_phone(recipient)} estrategia={recipient_strategy}"
    )
    if recipient != TEST_WA_ID_FROM_REAL_PAYLOAD:
        print(
            "Observacao: no ambiente de teste da Meta, o numero permitido pode ser "
            f"diferente do wa_id/from normalizado ({mask_phone(TEST_WA_ID_FROM_REAL_PAYLOAD)})."
        )

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    print(f"status_code: {response.status_code}")
    print("resposta:")
    print(format_json_response(response))

    return 0 if response.ok else 1


def format_json_response(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        body = response.text
    else:
        body = json.dumps(payload, indent=2, ensure_ascii=False)

    sensitive_values = (
        os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip(),
        os.getenv("WHATSAPP_TOKEN", "").strip(),
        os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        os.getenv("WHATSAPP_TEST_RECIPIENT_PHONE", "").strip(),
    )
    for value in sensitive_values:
        if value:
            body = body.replace(value, mask_sensitive(value))
    return body


def mask_phone(phone: str) -> str:
    phone = str(phone or "")
    if len(phone) <= 4:
        return "***"
    return f"***{phone[-4:]}"


def mask_sensitive(value: str) -> str:
    if len(value) > 40:
        return f"{value[:6]}...{value[-4:]}"
    return mask_phone(value)


if __name__ == "__main__":
    sys.exit(main())
