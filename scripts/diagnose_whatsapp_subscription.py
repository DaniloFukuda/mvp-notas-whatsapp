import json
import os
import sys

import requests
from dotenv import load_dotenv


DEFAULT_GRAPH_API_VERSION = "v21.0"


def main() -> int:
    load_dotenv()

    token = os.getenv("WHATSAPP_TOKEN", "").strip()
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION).strip()
    waba_id = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()

    if not token:
        print("WHATSAPP_TOKEN nao encontrado no .env.")
        return 1

    if not waba_id:
        print(
            "WHATSAPP_BUSINESS_ACCOUNT_ID nao encontrado no .env.\n"
            "Preencha com o WhatsApp Business Account ID da tela da Meta e rode novamente."
        )
        return 1

    url = f"https://graph.facebook.com/{api_version}/{waba_id}/subscribed_apps"
    headers = {"Authorization": f"Bearer {token}"}

    print("Consultando apps inscritos na WABA...")
    get_response = requests.get(url, headers=headers, timeout=30)
    print_response(get_response)
    print_subscribed_apps_summary(get_response)
    print_relevant_subscription_fields(get_response)

    answer = input(
        "\nDeseja forçar a inscrição do campo messages usando POST /subscribed_apps? "
        "Digite SIM para continuar. "
    ).strip()

    if answer != "SIM":
        print("POST /subscribed_apps nao executado.")
        return 0

    print("\nForçando inscrição do campo messages na WABA...")
    post_response = requests.post(
        url,
        headers=headers,
        data={"subscribed_fields": "messages"},
        timeout=30,
    )
    print_response(post_response)
    return 0


def print_response(response: requests.Response) -> None:
    print(f"status_code: {response.status_code}")
    print("resposta:")
    print(format_json_response(response))


def print_subscribed_apps_summary(response: requests.Response) -> None:
    try:
        payload = response.json()
    except ValueError:
        print("apps_inscritos: nao foi possivel interpretar a resposta como JSON")
        return

    apps = payload.get("data", []) if isinstance(payload, dict) else []
    has_apps = bool(apps)
    print(f"existe_app_inscrito: {has_apps}")

    if has_apps:
        print(f"quantidade_apps_inscritos: {len(apps)}")


def print_relevant_subscription_fields(response: requests.Response) -> None:
    try:
        payload = response.json()
    except ValueError:
        print("campos_relevantes: nao foi possivel interpretar a resposta como JSON")
        return

    matches = []
    collect_relevant_fields(payload, matches)

    print("campos_relevantes:")
    if not matches:
        print("- nenhum campo relacionado encontrado")
        return

    for path, value in matches:
        print(f"- {path}: {json.dumps(value, ensure_ascii=False)}")


def collect_relevant_fields(value, matches, path="resposta") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if is_relevant_field(key, child, child_path):
                matches.append((child_path, child))
            collect_relevant_fields(child, matches, child_path)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            collect_relevant_fields(child, matches, f"{path}[{index}]")


def is_relevant_field(key: str, value, path: str) -> bool:
    normalized_key = key.lower()
    if normalized_key in {"subscribed_fields", "app_id", "name"}:
        return True

    if normalized_key == "id" and "app" in path.lower():
        return True

    if normalized_key == "messages":
        return True

    if isinstance(value, str) and "messages" in value.lower():
        return True

    if isinstance(value, list):
        return any(
            isinstance(item, str) and item.lower() == "messages"
            for item in value
        )

    return False


def format_json_response(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text

    return json.dumps(payload, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
