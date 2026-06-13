import json
import logging
import mimetypes
import os
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from core.database import (
    get_processed_document_by_whatsapp_image_sha256_sender,
    get_processed_document_by_whatsapp_message_id,
)
from core.storage import save_processing_result
from services.rdv_service import (
    CATEGORIES as RDV_CATEGORIES,
    RDVService,
    calculate_week_reference,
)
from services.rdv_excel_service import build_weekly_rdv_workbook
from services.rdv_receipt_analysis_service import RDVReceiptAnalysisService


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()
WHATSAPP_UPLOAD_DIR = Path("data/documentos/uploads/whatsapp")
DEFAULT_GRAPH_API_VERSION = "v21.0"
RDV_EXCEL_FILENAME = "rdv_ciclus_relatorio_semanal.xlsx"
RDV_EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
RDV_EXCEL_COMMANDS = {
    "planilha",
    "planilha semanal",
    "excel",
    "relatorio",
    "relatorio semanal",
    "rdv",
}
RDV_SUMMARY_COMMANDS = {
    "resumo",
    "resumo semanal",
}
RDV_EXCEL_CAPTION = "Segue a planilha semanal do RDV da Ciclus Agro."
KM_START_COMMANDS = {
    "km",
    "quilometragem",
    "iniciar km",
    "iniciar viagem",
    "nova viagem",
}
KM_END_COMMANDS = {
    "fim km",
    "finalizar km",
    "cheguei",
    "encerrar viagem",
    "terminar viagem",
}
KM_STATUS_COMMANDS = {"status km"}
KM_CANCEL_COMMANDS = {"cancelar km"}
KM_CLEAR_REQUEST_COMMANDS = {
    "limpar km",
    "limpar quilometragem",
    "limpar quilometragens",
}
KM_CLEAR_CONFIRM_COMMANDS = {"confirmar limpar km"}
KM_CLEAR_WARNING = (
    "Atenção: isso vai apagar as viagens de KM registradas neste ambiente e "
    "deixar o resumo de KM zerado.\n"
    "Para confirmar, envie: confirmar limpar km"
)
KM_CLEAR_SUCCESS = (
    "Quilometragens limpas com sucesso. Nenhuma viagem está em aberto."
)
RDV_MENU = "\n".join(
    [
        "Ciclus Agro - RDV por WhatsApp",
        "",
        "Envie uma foto ou documento do comprovante para iniciar.",
        "Depois vou pedir apenas os dados que nao forem detectados.",
        "",
        "Digite resumo para consultar a semana atual.",
        "Digite planilha para receber o relatorio semanal em Excel.",
        "Digite km para registrar inicio/fim de viagem.",
    ]
)
rdv_service = RDVService()
rdv_receipt_analysis_service = RDVReceiptAnalysisService()


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

        messages = _extract_messages(payload)
        status_count = _count_status_events(payload)
        logger.info(
            "Webhook WhatsApp interpretado: mensagens=%s status=%s",
            len(messages),
            status_count,
        )
        for message in messages:
            background_tasks.add_task(_handle_whatsapp_message, message)
    except Exception:
        logger.exception("Erro ao interpretar payload do webhook WhatsApp.")

    return {"status": "received"}


def get_media_url(media_id: str) -> str:
    requests = _requests_module()
    token = _whatsapp_access_token()
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
    token = _whatsapp_access_token()
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
    token = _whatsapp_access_token()
    phone_number_id = _required_env("WHATSAPP_PHONE_NUMBER_ID")
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION)
    message_type = "text"
    recipient = str(to or "").strip()
    recipient_strategy = "destinatario via from/wa_id do webhook"
    if not recipient:
        raise RuntimeError("Destinatario WhatsApp nao informado.")

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
        raise

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
        response.raise_for_status()
        return

    logger.info(
        "Mensagem WhatsApp enviada com sucesso: status_code=%s to=%s",
        response.status_code,
        _mask_phone(recipient),
    )


def upload_whatsapp_document(
    content: bytes,
    filename: str = RDV_EXCEL_FILENAME,
    mime_type: str = RDV_EXCEL_MIME_TYPE,
) -> str:
    if not content:
        raise RuntimeError("Conteudo do documento WhatsApp nao informado.")

    requests = _requests_module()
    token = _whatsapp_access_token()
    phone_number_id = _required_env("WHATSAPP_PHONE_NUMBER_ID")
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION)
    response = requests.post(
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/media",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "messaging_product": "whatsapp",
            "type": mime_type,
        },
        files={"file": (filename, content, mime_type)},
        timeout=60,
    )
    if response.status_code >= 400:
        logger.error(
            "Erro da Meta no upload do Excel RDV: status_code=%s body=%s",
            response.status_code,
            _safe_response_body(response),
        )
        response.raise_for_status()

    media_id = str(response.json().get("id") or "").strip()
    if not media_id:
        raise RuntimeError("ID da midia nao retornado no upload do Excel RDV.")
    return media_id


def send_whatsapp_document(
    to: str,
    content: bytes,
    filename: str = RDV_EXCEL_FILENAME,
    caption: str = RDV_EXCEL_CAPTION,
    mime_type: str = RDV_EXCEL_MIME_TYPE,
) -> None:
    recipient = str(to or "").strip()
    if not recipient:
        raise RuntimeError("Destinatario WhatsApp nao informado.")

    media_id = upload_whatsapp_document(content, filename, mime_type)
    requests = _requests_module()
    token = _whatsapp_access_token()
    phone_number_id = _required_env("WHATSAPP_PHONE_NUMBER_ID")
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION)
    response = requests.post(
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {
                "id": media_id,
                "caption": caption,
                "filename": filename,
            },
        },
        timeout=20,
    )
    if response.status_code >= 400:
        logger.error(
            "Erro da Meta ao enviar Excel RDV: status_code=%s to=%s body=%s",
            response.status_code,
            _mask_phone(recipient),
            _safe_response_body(response),
        )
        response.raise_for_status()

    logger.info(
        "Excel RDV enviado pelo WhatsApp: status_code=%s to=%s",
        response.status_code,
        _mask_phone(recipient),
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

    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        logger.info(
            "Remetente WhatsApp nao cadastrado no RDV: from=%s",
            _mask_phone(sender_phone),
        )
        _safe_send_text(
            sender_phone,
            "Seu telefone ainda nao esta cadastrado no RDV da Ciclus Agro. "
            "Procure o responsavel pelo cadastro.",
        )
        return

    if message_type == "text":
        reply = handle_rdv_text_message(sender_phone, text)
        if reply:
            _safe_send_text(sender_phone, reply)
        return

    if message_type not in ("image", "document") or not media_id:
        _safe_send_text(
            sender_phone,
            "Recebi sua mensagem, mas por enquanto consigo processar apenas imagem ou documento.",
        )
        return

    if (
        _was_whatsapp_message_processed(message_id)
        or rdv_service.get_by_whatsapp_message_id(message_id) is not None
    ):
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

    destination = _build_media_destination(
        sender_phone=sender_phone,
        media_id=media_id,
        mime_type=mime_type,
    )
    document_type = _classify_document_type(caption)

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
        rdv_expense = _register_received_media_as_rdv(
            sender_phone=sender_phone,
            caminho_arquivo=str(downloaded_path),
            whatsapp_message_id=message_id,
            message_type=message_type,
            received_at=data_hora_recebimento,
        )
    except Exception:
        logger.exception(
            "Erro ao registrar despesa RDV recebida pelo WhatsApp: message_id=%s",
            _mask_message_id(message_id),
        )
        _safe_send_text(
            sender_phone,
            "Recebi o arquivo, mas nao consegui registrar a despesa. Tente novamente.",
        )
        return
    logger.info(
        "Comprovante RDV registrado: from=%s message_id=%s rdv_id=%s",
        _mask_phone(sender_phone),
        _mask_message_id(message_id),
        rdv_expense.get("id"),
    )
    _safe_send_text(sender_phone, _rdv_received_message(rdv_expense))


def handle_rdv_text_message(sender_phone: str, text: str) -> str | None:
    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        return (
            "Seu telefone ainda nao esta cadastrado no RDV da Ciclus Agro. "
            "Procure o responsavel pelo cadastro."
        )

    normalized = _normalize_caption(text)
    global_command_handled, global_reply = _handle_global_rdv_command(
        sender_phone,
        collaborator,
        normalized,
    )
    if global_command_handled:
        return global_reply

    pending = rdv_service.get_open_launch_by_phone(sender_phone)
    open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)

    if normalized in KM_CLEAR_REQUEST_COMMANDS:
        return KM_CLEAR_WARNING

    if normalized in KM_CLEAR_CONFIRM_COMMANDS:
        rdv_service.clear_km_trips()
        return KM_CLEAR_SUCCESS

    if normalized in KM_STATUS_COMMANDS:
        if open_km is None:
            return _no_open_trip_message()
        return _open_trip_message(open_km)

    if normalized in KM_CANCEL_COMMANDS:
        if open_km is None:
            return _no_open_trip_message()
        cancelled = rdv_service.cancel_km_launch(open_km["id"])
        return "\n".join(
            [
                "Viagem cancelada com sucesso.",
                (
                    f"Trajeto: {cancelled.get('cidade_origem') or '-'} "
                    f"\u2192 {cancelled.get('cidade_destino') or '-'}"
                ),
                "O lancamento foi mantido no historico como cancelado.",
            ]
        )

    if normalized in KM_END_COMMANDS:
        if open_km is None:
            return _no_open_trip_message()
        if open_km.get("status_fluxo") == "viagem_em_andamento":
            rdv_service.request_km_end(open_km["id"])
            return "Qual a quilometragem final do carro?"
        if open_km.get("status_fluxo") == "aguardando_km_fim":
            return "Qual a quilometragem final do carro?"
        return _open_trip_message(open_km)

    if (
        pending is not None
        and pending.get("status_fluxo") == "viagem_em_andamento"
    ):
        if normalized == "3":
            return _weekly_summary_message()
        if normalized in {"meu resumo", "meuresumo", "individual"}:
            return _weekly_summary_message(collaborator["id"])

    if pending is None:
        if normalized == "3":
            return _weekly_summary_message()
        if normalized in {"meu resumo", "meuresumo", "individual"}:
            return _weekly_summary_message(collaborator["id"])
        if normalized in {"menu", "oi", "ola", "rdv", "despesa"}:
            return f"Ola, {collaborator['nome']}.\n\n{RDV_MENU}"
        return RDV_MENU

    state = pending.get("status_fluxo")
    if state == "aguardando_valor":
        value = _parse_rdv_value(text)
        if value is None:
            return "Valor invalido. Informe somente o valor, por exemplo: 125,50"
        saved = rdv_service.save_launch_value(pending["id"], value)
        return _category_prompt(
            f"Valor registrado manualmente: {_format_brl_text(saved['valor'])}."
        )

    if state == "aguardando_categoria":
        category = _match_numbered_choice(text, RDV_CATEGORIES)
        if category is None:
            return _category_prompt("Categoria invalida.")
        completed = rdv_service.complete_launch_category(
            pending["id"],
            category,
        )
        lines = [
            "RDV registrado com sucesso.",
            f"Lancamento #{completed['id']}.",
            f"Valor: {_format_brl_text(completed['valor'])}.",
            f"Categoria: {_category_label(completed['categoria'])}.",
            "Status: completo.",
        ]
        if completed.get("origem_valor") == "manual":
            lines.append("Valor informado manualmente.")
        lines.append("Para receber a planilha semanal, envie: planilha.")
        return " ".join(lines)

    if state == "aguardando_km_origem":
        if not str(text or "").strip():
            return "Informe a origem da viagem. Saindo de onde?"
        rdv_service.save_km_origin(pending["id"], text)
        return "Indo para onde?"

    if state == "aguardando_km_destino":
        if not str(text or "").strip():
            return "Informe o destino da viagem. Indo para onde?"
        rdv_service.save_km_destination(pending["id"], text)
        return "Qual a quilometragem inicial do carro?"

    if state == "aguardando_km_inicio":
        km_start = _parse_km_value(text)
        if km_start is None:
            return (
                "Quilometragem inicial invalida. "
                "Informe um numero, por exemplo: 120350."
            )
        started = rdv_service.save_km_start(pending["id"], km_start)
        return "\n".join(
            [
                "Viagem iniciada com sucesso.",
                (
                    f"Trajeto previsto: {started['cidade_origem']} "
                    f"\u2192 {started['cidade_destino']}"
                ),
                f"KM inicial: {_format_km_text(started['km_inicio'])}",
                "Quando chegar, envie: fim km",
            ]
        )

    if state == "viagem_em_andamento":
        return _open_trip_message(pending)

    if state == "aguardando_km_fim":
        km_end = _parse_km_value(text)
        if km_end is None:
            return (
                "Quilometragem final invalida. "
                "Informe um numero, por exemplo: 120500."
            )
        km_start = float(pending.get("km_inicio") or 0)
        if km_end < km_start:
            return (
                "A quilometragem final nao pode ser menor que a inicial. "
                "Informe novamente a quilometragem final do carro."
            )
        completed = rdv_service.complete_km_end(pending["id"], km_end)
        return "\n".join(
            [
                "Viagem finalizada com sucesso.",
                (
                    f"Trajeto: {completed['cidade_origem']} "
                    f"\u2192 {completed['cidade_destino']}"
                ),
                f"KM inicial: {_format_km_text(completed['km_inicio'])}",
                f"KM final: {_format_km_text(completed['km_fim'])}",
                f"KM rodado: {_format_km_text(completed['km_rodado'])} km",
            ]
        )

    return RDV_MENU


def clear_rdv_sessions() -> None:
    """Compatibilidade com os testes da etapa anterior; o fluxo agora e persistente."""


def _no_open_trip_message() -> str:
    return (
        "Não encontrei viagem em andamento. "
        "Para iniciar uma nova viagem, envie: km"
    )


def _open_trip_message(expense: dict) -> str:
    state = expense.get("status_fluxo")
    origin = expense.get("cidade_origem") or "-"
    destination = expense.get("cidade_destino") or "-"
    if state == "aguardando_km_origem":
        return "Cadastro de viagem em andamento.\nSaindo de onde?"
    if state == "aguardando_km_destino":
        return "\n".join(
            [
                "Cadastro de viagem em andamento.",
                f"Origem: {origin}",
                "Indo para onde?",
            ]
        )
    if state == "aguardando_km_inicio":
        return "\n".join(
            [
                "Cadastro de viagem em andamento.",
                f"Trajeto previsto: {origin} \u2192 {destination}",
                "Qual a quilometragem inicial do carro?",
            ]
        )

    lines = [
        "Viagem em andamento.",
        f"Trajeto previsto: {origin} \u2192 {destination}",
        f"KM inicial: {_format_km_text(expense.get('km_inicio'))}",
    ]
    if state == "aguardando_km_fim":
        lines.append("Informe a quilometragem final do carro.")
    else:
        lines.append("Para finalizar, envie: fim km")
    lines.append("Para cancelar, envie: cancelar km")
    return "\n".join(lines)


def _is_rdv_excel_command(text: str) -> bool:
    return _normalize_caption(text) in RDV_EXCEL_COMMANDS


def _handle_global_rdv_command(
    sender_phone: str,
    collaborator: dict,
    normalized_text: str,
) -> tuple[bool, str | None]:
    if normalized_text in RDV_SUMMARY_COMMANDS:
        return True, _weekly_summary_message()

    if normalized_text in RDV_EXCEL_COMMANDS:
        try:
            _send_weekly_rdv_excel(sender_phone)
        except Exception as exc:
            logger.exception(
                "Falha ao enviar Excel RDV pelo WhatsApp: to=%s erro=%s",
                _mask_phone(sender_phone),
                _safe_exception_summary(exc),
            )
            return True, _rdv_excel_fallback_message()
        return True, None

    if normalized_text in KM_START_COMMANDS:
        open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)
        if open_km is not None:
            return True, _open_trip_message(open_km)
        rdv_service.create_whatsapp_km_launch(
            collaborator_id=collaborator["id"],
            phone=sender_phone,
        )
        return True, "Saindo de onde?"

    return False, None


def _send_weekly_rdv_excel(sender_phone: str) -> None:
    report_data = rdv_service.weekly_report_data(
        week=calculate_week_reference(date.today()),
    )
    content = build_weekly_rdv_workbook(report_data)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=RDV_EXCEL_FILENAME,
        caption=RDV_EXCEL_CAPTION,
        mime_type=RDV_EXCEL_MIME_TYPE,
    )


def _rdv_excel_fallback_message() -> str:
    public_url = _base_public_url()
    if public_url:
        download_url = f"{public_url}/ciclus/rdv/relatorio-semanal.xlsx"
        return (
            "Nao consegui enviar o arquivo agora. "
            f"Voce pode baixar pelo painel: {download_url}"
        )
    return (
        "Nao consegui enviar o arquivo agora. "
        "Tente novamente mais tarde ou baixe pelo painel."
    )


def _register_received_media_as_rdv(
    sender_phone: str,
    caminho_arquivo: str,
    whatsapp_message_id: str,
    message_type: str = "document",
    received_at: str | datetime | None = None,
) -> dict:
    existing = rdv_service.get_by_whatsapp_message_id(whatsapp_message_id)
    if existing is not None:
        return existing

    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        raise ValueError("Remetente nao cadastrado como colaborador RDV.")

    input_type = message_type if message_type in {"image", "document"} else "document"
    input_type = {"image": "imagem", "document": "documento"}[input_type]
    try:
        analysis = rdv_receipt_analysis_service.analyze_file(caminho_arquivo).to_dict()
    except Exception:
        logger.exception(
            "Falha controlada ao analisar comprovante RDV: message_id=%s",
            _mask_message_id(whatsapp_message_id),
        )
        analysis = {}
    pending = rdv_service.get_open_launch_by_phone(sender_phone)
    if pending is not None and pending.get("status_fluxo") == "aguardando_valor":
        retried = rdv_service.retry_whatsapp_receipt(
            expense_id=pending["id"],
            input_type=input_type,
            file_path=caminho_arquivo,
            whatsapp_message_id=whatsapp_message_id,
            analysis=analysis,
        )
        retried["_retry_attempt"] = True
        return retried
    try:
        return rdv_service.create_whatsapp_receipt(
            collaborator_id=collaborator["id"],
            phone=sender_phone,
            input_type=input_type,
            file_path=caminho_arquivo,
            whatsapp_message_id=whatsapp_message_id,
            received_at=received_at,
            analysis=analysis,
        )
    except Exception:
        existing = rdv_service.get_by_whatsapp_message_id(whatsapp_message_id)
        if existing is not None:
            return existing
        raise


def _rdv_received_message(expense: dict) -> str:
    if expense.get("status_fluxo") == "aguardando_categoria":
        return "\n".join(
            [
                "Comprovante recebido. "
                f"Detectei o valor {_format_brl_text(expense.get('valor'))}.",
                _category_prompt(),
            ]
        )
    if expense.get("_retry_attempt"):
        return (
            "Ainda não consegui detectar o valor. "
            "Envie outra foto mais nítida, com o comprovante inteiro e o QR Code "
            "visível, ou informe o valor manualmente. Exemplo: 64,00"
        )
    return (
        "Comprovante recebido, mas não consegui detectar o valor automaticamente. "
        "Você pode enviar uma nova foto mais nítida, com o comprovante inteiro e "
        "o QR Code visível, ou informar o valor manualmente. Exemplo: 64,00"
    )


def _weekly_summary_message(collaborator_id: int | str = "") -> str:
    week = calculate_week_reference(date.today())
    summary = rdv_service.weekly_report(
        week=week,
        collaborator_id=collaborator_id,
    )

    title = (
        f"Meu resumo da semana {week}"
        if collaborator_id
        else f"Resumo geral da semana {week}"
    )

    lines = [
        title,
        f"Lancamentos: {summary['quantidade_lancamentos']}",
        f"Comprovantes: {summary['quantidade_comprovantes']}",
        f"Total: {_format_brl_text(summary['total_geral'])}",
        f"KM rodado: {_format_km_text(summary.get('quilometragem_total'))} km",
        f"Viagens em aberto: {summary.get('viagens_em_aberto', 0)}",
        f"Pendentes: {summary.get('pendentes_revisao', 0)}",
    ]

    by_collaborator = summary.get("por_colaborador") or {}
    if by_collaborator:
        lines.append("")
        lines.append("Por colaborador:")
        for name, total in sorted(by_collaborator.items()):
            lines.append(f"- {name}: {_format_brl_text(total)}")

    by_category = summary.get("por_categoria") or {}
    if by_category:
        lines.append("")
        lines.append("Por categoria:")
        for category, total in sorted(by_category.items()):
            lines.append(f"- {_category_label(category)}: {_format_brl_text(total)}")

    return "\n".join(lines)


def _category_prompt(prefix: str = "") -> str:
    lines = [
        f"{prefix} Qual a categoria?" if prefix else "Qual a categoria?"
    ]
    lines.extend(
        f"{index}. {_category_label(category)}"
        for index, category in enumerate(RDV_CATEGORIES, start=1)
    )
    return "\n".join(lines)


def _category_label(category: str) -> str:
    labels = {
        "combustivel": "Combustivel",
        "alimentacao": "Alimentacao",
        "pedagio": "Pedagio",
        "hospedagem": "Hospedagem",
        "manutencao": "Manutencao",
        "outro": "Outro",
    }
    return labels.get(str(category or ""), str(category or "").title())


def _match_numbered_choice(value: str, choices: tuple[str, ...]) -> str | None:
    normalized = _normalize_caption(value)
    if normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(choices):
            return choices[index]

    for choice in choices:
        if normalized == _normalize_caption(choice):
            return choice
    return None


def _parse_rdv_value(value: str) -> float | None:
    normalized = str(value or "").strip().lower().replace("r$", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _parse_km_value(value: str) -> float | None:
    match = re.search(r"[-+]?\d[\d.,]*", str(value or "").strip())
    if match is None:
        return None

    normalized = match.group(0)
    if normalized.startswith("-"):
        return None
    normalized = normalized.lstrip("+")
    if not normalized:
        return None

    if "." in normalized and "," in normalized:
        decimal_separator = "." if normalized.rfind(".") > normalized.rfind(",") else ","
        thousands_separator = "," if decimal_separator == "." else "."
        normalized = normalized.replace(thousands_separator, "")
        normalized = normalized.replace(decimal_separator, ".")
    elif "." in normalized or "," in normalized:
        separator = "." if "." in normalized else ","
        parts = normalized.split(separator)
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            normalized = "".join(parts)
        else:
            normalized = ".".join(parts)

    try:
        parsed = float(normalized)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


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


def _count_status_events(payload: dict) -> int:
    count = 0
    if not isinstance(payload, dict):
        return count

    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if isinstance(value, dict):
                count += sum(
                    1 for status in value.get("statuses", []) or [] if isinstance(status, dict)
                )
    return count


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


def _format_km_text(value: object) -> str:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return str(value or 0)
    if parsed.is_integer():
        return str(int(parsed))
    return f"{parsed:.2f}".rstrip("0").rstrip(".").replace(".", ",")


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


def _whatsapp_access_token() -> str:
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    if token:
        return token

    legacy_token = os.getenv("WHATSAPP_TOKEN", "").strip()
    if legacy_token:
        logger.warning(
            "WHATSAPP_TOKEN esta obsoleto; renomeie para WHATSAPP_ACCESS_TOKEN no .env."
        )
        return legacy_token

    raise RuntimeError(
        "Variavel de ambiente obrigatoria nao configurada: WHATSAPP_ACCESS_TOKEN"
    )


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
