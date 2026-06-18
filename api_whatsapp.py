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
    calculate_month_reference,
    calculate_week_reference,
)
from services.rdv_excel_service import (
    build_monthly_rdv_workbook,
    build_weekly_rdv_workbook,
)
from services.rdv_receipt_analysis_service import RDVReceiptAnalysisService
from services.visitas_excel_service import build_visitas_workbook
from services.visitas_pdf_service import build_visita_pdf
from services.visitas_service import VisitasTecnicasService, normalize_phone


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
RDV_MONTHLY_EXCEL_FILENAME = "rdv_ciclus_relatorio_mensal.xlsx"
RDV_WEEKLY_EXCEL_FILENAME = "rdv_ciclus_relatorio_semanal.xlsx"
RDV_EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
RDV_MONTHLY_EXCEL_CAPTION = "Segue a planilha mensal do RDV da Ciclus Agro."
RDV_WEEKLY_EXCEL_CAPTION = "Segue a planilha semanal do RDV da Ciclus Agro."
VISITAS_EXCEL_FILENAME = "visitas_tecnicas_ciclus.xlsx"
VISITAS_EXCEL_CAPTION = "Segue a planilha de visitas técnicas da Ciclus Agro."
VISITA_PDF_CAPTION = "Segue o relatório da visita técnica da Ciclus Agro."
VISITA_PDF_MIME_TYPE = "application/pdf"
VISITA_START_COMMANDS = {"visita", "iniciar visita"}
VISITA_NEW_COMMANDS = {"nova visita", "iniciar nova visita", "outra visita"}
VISITA_EDITABLE_FIELDS = {
    "fazenda": "Fazenda",
    "proprietario": "Proprietário",
    "gerente": "Gerente/responsável",
    "area_hectares": "Área em hectares",
    "area_alqueires": "Área em alqueires",
    "safra": "Safra",
    "tipo_visita": "Tipo de visita",
    "objetivo": "Objetivo",
    "observacoes": "Observações",
    "data_visita": "Data da visita",
}
VISITA_FLOW_STEPS = {
    "aguardando_fazenda": ("fazenda", "Qual o nome do proprietário?"),
    "aguardando_proprietario": ("proprietario", "Qual o gerente/responsável?"),
    "aguardando_gerente": ("gerente", "Qual a área da fazenda?"),
    "aguardando_area": ("area_hectares", "Qual a safra?"),
    "aguardando_safra": ("safra", "Qual o tipo de visita?"),
    "aguardando_tipo_visita": ("tipo_visita", ""),
}
MENU_OPEN_COMMANDS = {"menu", "iniciar", "inicio", "ajuda", "oi", "ola"}
MAIN_MENU_MESSAGE = "\n".join(
    [
        "Olá! Sou o assistente da Ciclus Agro.",
        "",
        "Veja o que posso fazer:",
        "",
        "📌 RDV / Comprovantes",
        "Registra despesas por foto, PDF ou imagem de comprovante.",
        "Comandos:",
        "",
        "* Envie uma foto/PDF do comprovante",
        "* resumo — mostra o resumo mensal do RDV",
        "* planilha — envia a planilha mensal do RDV",
        "* resumo semanal — mostra o resumo da semana",
        "* planilha semanal — envia a planilha da semana",
        "",
        "🚗 KM / Viagens",
        "Registra deslocamentos com KM inicial, origem, destino e KM final.",
        "Comandos:",
        "",
        "* km inicio 120350 — inicia uma viagem",
        "* km termino 120500 — finaliza a viagem",
        "* km cancelar — cancela uma viagem aberta",
        "",
        "🌱 Visitas técnicas",
        "Registra fazendas visitadas, gerente, área, fotos, localização e relatório.",
        "Comandos:",
        "",
        "* visita — inicia uma visita técnica",
        "* visita status — mostra sua visita em andamento",
        "* ver visita 12 — mostra dados da visita",
        "* editar visita 12 — corrige dados da visita",
        "* fechar edição — encerra modo edição",
        "* cancelar edição — sai do modo edição",
        "* visitas — lista visitas/fazendas registradas",
        "* visitas abertas — lista visitas abertas da equipe",
        "* fechar visita — finaliza a visita",
        "* cancelar visita — cancela a visita em andamento",
        "* localização visita 12 — mostra GPS de uma visita pelo ID",
        "* planilha visitas — envia a planilha com fazendas visitadas",
        "* relatório visita 12 — gera PDF pelo ID da visita",
        "* relatório fazenda Nome da Fazenda — busca relatório pelo nome da fazenda",
        "",
        "📊 Relatórios",
        "Lista as opções de relatórios disponíveis.",
        "Comando:",
        "",
        "* relatórios",
        "",
        "Digite qualquer comando acima para começar.",
    ]
)
REPORTS_MENU_MESSAGE = "\n".join(
    [
        "Relatórios disponíveis:",
        "",
        "📌 RDV",
        "",
        "* resumo — resumo mensal de despesas",
        "* planilha — planilha mensal de despesas",
        "* resumo semanal — resumo semanal de despesas",
        "* planilha semanal — planilha semanal de despesas",
        "",
        "🌱 Visitas técnicas",
        "",
        "* planilha visitas — planilha com todas as visitas/fazendas registradas",
        "* fazendas visitadas — atalho para a planilha de visitas",
        "* visitas — lista visitas/fazendas registradas",
        "* visitas abertas — lista visitas abertas da equipe",
        "* ver visita 12 — mostra dados da visita",
        "* editar visita 12 — corrige dados da visita",
        "* relatório visita 12 — gera PDF pelo ID da visita",
        "* relatório fazenda Nome da Fazenda — busca relatório pelo nome da fazenda",
        "* localização visita 12 — mostra GPS de uma visita pelo ID",
        "",
        "🚗 KM",
        "Os lançamentos de KM aparecem nas planilhas do RDV.",
        "Comandos:",
        "",
        "* km inicio 120350",
        "* km termino 120500",
        "* km cancelar",
    ]
)
MENU_NUMBER_MESSAGE = 'Digite "menu" para ver os comandos disponíveis.'
VISITA_NUMBER_MESSAGE = (
    'Digite uma observação, envie foto/localização ou use "fechar visita" ou "cancelar visita".'
)
NO_VALID_VISITA_MESSAGE = (
    'Nenhuma visita técnica válida encontrada.\n'
    'Envie "visita" para iniciar uma nova visita.'
)
CANCELED_VISITA_REPORT_MESSAGE = (
    "Essa visita foi cancelada e não pode gerar relatório.\n"
    'Envie "visitas" para listar visitas válidas.'
)
NO_OPEN_VISITA_MESSAGE = (
    'Nenhuma visita técnica em andamento.\n'
    'Envie "visita" para iniciar uma nova visita.'
)
KM_STATUS_COMMANDS = {"status km"}
KM_CANCEL_COMMANDS = {"cancelar km", "km cancelar"}
KM_HELP_MESSAGE = "\n".join(
    [
        "Para registrar uma viagem, envie:",
        "",
        "km inicio 120350",
        "",
        "Quando terminar, envie:",
        "",
        "km termino 120500",
    ]
)
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
        "Digite resumo para consultar o mes atual.",
        "Digite planilha para receber o relatorio mensal em Excel.",
        "Digite km para ver como registrar uma viagem.",
    ]
)
rdv_service = RDVService()
rdv_receipt_analysis_service = RDVReceiptAnalysisService()
visitas_service = VisitasTecnicasService()
whatsapp_menu_states: dict[str, str] = {}
visita_edit_states: dict[str, int] = {}
visita_active_states: dict[str, int] = {}
visita_new_visit_states: set[str] = set()


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
    filename: str = RDV_MONTHLY_EXCEL_FILENAME,
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
    filename: str = RDV_MONTHLY_EXCEL_FILENAME,
    caption: str = RDV_MONTHLY_EXCEL_CAPTION,
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

    if message_type == "location":
        reply = handle_visitas_location_message(sender_phone, message.get("location") or {})
        if reply:
            _safe_send_text(sender_phone, reply)
            return

    if message_type not in ("image", "document") or not media_id:
        _safe_send_text(
            sender_phone,
            "Recebi sua mensagem, mas por enquanto consigo processar apenas imagem ou documento.",
        )
        return

    active_visit = _get_active_visita_for_phone(sender_phone)
    if active_visit is not None and active_visit.get("estado_fluxo") == "visita_aberta":
        destination = _build_media_destination(
            sender_phone=sender_phone,
            media_id=media_id,
            mime_type=mime_type,
        )
        try:
            downloaded_path = download_media(media_id, destination)
        except Exception as exc:
            logger.exception(
                "Falha ao baixar foto da visita tecnica: media_id=%s status_code=%s erro=%s",
                _mask_media_id(media_id),
                _http_status_from_exception(exc) or "-",
                _safe_exception_summary(exc),
            )
            _safe_send_text(sender_phone, "Nao consegui salvar a foto da visita. Tente novamente.")
            return
        reply = handle_visitas_media_message(
            sender_phone=sender_phone,
            message_type=message_type,
            media_id=media_id,
            file_path=str(downloaded_path),
            caption=caption,
        )
        _safe_send_text(sender_phone, reply)
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
    rdv_service.cancel_legacy_km_launches_by_phone(sender_phone)
    global_command_handled, global_reply = _handle_global_rdv_command(
        sender_phone,
        collaborator,
        normalized,
    )
    if global_command_handled:
        return global_reply

    if normalized in MENU_OPEN_COMMANDS:
        return _open_main_menu(sender_phone)

    if normalized == "relatorios":
        return REPORTS_MENU_MESSAGE

    open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)
    pending = rdv_service.get_open_launch_by_phone(sender_phone)

    visita_handled, visita_reply = handle_visitas_text_message(
        sender_phone,
        text,
        collaborator,
        normalized,
    )
    if visita_handled:
        return visita_reply

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
        rdv_service.cancel_km_launch(open_km["id"])
        return "Viagem cancelada com sucesso."

    if open_km is not None and pending is None:
        km_state = open_km.get("status_fluxo")
        if km_state == "aguardando_km_origem":
            saved = rdv_service.save_km_origin(open_km["id"], text)
            return "\n".join(
                [
                    f"Origem registrada: {saved['cidade_origem']}.",
                    "Qual a cidade/local de destino?",
                ]
            )
        if km_state == "aguardando_km_destino":
            saved = rdv_service.save_km_destination(open_km["id"], text)
            return "\n".join(
                [
                    f"Destino registrado: {saved['cidade_destino']}.",
                    "Quando terminar, envie:",
                    "km termino 120500",
                ]
            )

    if pending is None:
        if normalized in {"meu resumo", "meuresumo", "individual"}:
            return _monthly_summary_message(collaborator["id"])
        if normalized in {"rdv", "despesa"}:
            return f"Ola, {collaborator['nome']}.\n\n{RDV_MENU}"
        if _is_standalone_number(normalized):
            return MENU_NUMBER_MESSAGE
        if normalized.startswith("km "):
            return KM_HELP_MESSAGE
        return RDV_MENU

    state = pending.get("status_fluxo")
    if state == "aguardando_valor":
        value = _parse_rdv_value(text)
        if value is None:
            return "Valor invalido. Informe somente o valor, por exemplo: 125,50"
        saved = rdv_service.save_launch_value(pending["id"], value)
        if saved.get("status_fluxo") == "aguardando_data_comprovante":
            return (
                f"Valor registrado manualmente: {_format_brl_text(saved['valor'])}. "
                "Informe a data do comprovante no formato 11/06/2026."
            )
        return _category_prompt(
            f"Valor registrado manualmente: {_format_brl_text(saved['valor'])}."
        )

    if state == "aguardando_data_comprovante":
        try:
            saved = rdv_service.save_launch_receipt_date(pending["id"], text)
        except ValueError:
            return "Data invalida. Informe a data do comprovante no formato 11/06/2026."
        return _category_prompt(
            f"Data registrada: {_format_date_br(saved['data_despesa'])}."
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
            f"Data do comprovante: {_format_date_br(completed['data_despesa'])}.",
            f"Enviado no WhatsApp: {_format_datetime_br(completed.get('recebido_em'))}.",
            f"Mes: {calculate_month_reference(completed['data_despesa'])}.",
            f"Semana: {completed['semana_referencia']}.",
            f"Valor: {_format_brl_text(completed['valor'])}.",
            f"Categoria: {_category_label(completed['categoria'])}.",
            "Status: completo.",
        ]
        if completed.get("origem_valor") == "manual":
            lines.append("Valor informado manualmente.")
        if completed.get("semana_referencia") != calculate_week_reference(date.today()):
            lines.append(
                "Este comprovante entrou pela data real do documento, "
                "nao pela data de envio no WhatsApp."
            )
        month = calculate_month_reference(completed["data_despesa"])
        lines.extend(
            [
                "",
                "Para receber a planilha do mes, envie:",
                f"planilha {month}",
            ]
        )
        return "\n".join(lines)

    return RDV_MENU


def _open_main_menu(sender_phone: str) -> str:
    return MAIN_MENU_MESSAGE


def handle_visitas_text_message(
    sender_phone: str,
    text: str,
    collaborator: dict | None = None,
    normalized: str | None = None,
) -> tuple[bool, str | None]:
    normalized_text = normalized if normalized is not None else _normalize_caption(text)
    collaborator = collaborator or rdv_service.get_collaborator_by_phone(sender_phone)
    open_visit = _get_active_visita_for_phone(sender_phone)
    phone = normalize_phone(sender_phone)

    if normalized_text in {"fechar edicao", "finalizar edicao"}:
        return True, _close_visita_edit(sender_phone)

    if normalized_text in {"cancelar edicao", "sair edicao"}:
        return True, _cancel_visita_edit(sender_phone)

    if _is_ver_visita_command(normalized_text):
        return True, _handle_ver_visita(normalized_text)

    if _is_editar_visita_command(normalized_text):
        return True, _start_visita_edit(sender_phone, normalized_text)

    if _is_continuar_visita_command(normalized_text):
        return True, _continue_visita(sender_phone, normalized_text)

    if normalized_text in VISITA_NEW_COMMANDS:
        return True, _start_new_visita_flow(sender_phone)

    if phone in visita_new_visit_states:
        return True, _create_new_visita_from_farm(sender_phone, text, collaborator)

    if normalized_text in VISITA_START_COMMANDS:
        existing_visit = visitas_service.obter_visita_aberta(sender_phone)
        if existing_visit is not None:
            return True, _existing_open_visita_choice_message(existing_visit)
        visit = visitas_service.iniciar_visita(
            sender_phone,
            tecnico_nome=(collaborator or {}).get("nome"),
        )
        visita_active_states[phone] = int(visit["id"])
        return True, "\n".join(
            [
                "Vamos iniciar uma visita técnica.",
                "Qual o nome da fazenda?",
            ]
        )

    if _is_planilha_visitas_command(normalized_text):
        try:
            _send_visitas_excel(sender_phone, normalized_text)
        except Exception as exc:
            logger.exception(
                "Falha ao enviar Excel de visitas pelo WhatsApp: to=%s erro=%s",
                _mask_phone(sender_phone),
                _safe_exception_summary(exc),
            )
            return True, "Não consegui enviar a planilha de visitas agora. Tente novamente mais tarde."
        return True, None

    if _is_listar_visitas_command(normalized_text):
        return True, _listar_visitas_message(normalized_text)

    if _is_relatorio_visita_command(normalized_text):
        try:
            reply = _handle_relatorio_visita(sender_phone, text, normalized_text)
        except ValueError as exc:
            if str(exc) == "visita_cancelada":
                return True, CANCELED_VISITA_REPORT_MESSAGE
            raise
        except Exception as exc:
            logger.exception(
                "Falha ao enviar PDF de visita pelo WhatsApp: to=%s erro=%s",
                _mask_phone(sender_phone),
                _safe_exception_summary(exc),
            )
            return True, "Não consegui enviar o relatório da visita agora. Tente novamente mais tarde."
        return True, reply

    if normalized_text in {"visita status", "status visita"}:
        if open_visit is None:
            return True, NO_OPEN_VISITA_MESSAGE
        return True, _visita_status_message(open_visit)

    if _is_localizacao_visita_command(normalized_text):
        return True, _handle_localizacao_visita(normalized_text)

    if phone in visita_edit_states:
        return True, _handle_visita_edit_message(sender_phone, text)

    if normalized_text == "fechar visita":
        if open_visit is None:
            return True, NO_OPEN_VISITA_MESSAGE
        closed = visitas_service.fechar_visita(open_visit["id"])
        _clear_active_visita(sender_phone, open_visit["id"])
        return True, _visita_fechada_message(closed)

    if normalized_text == "cancelar visita":
        if open_visit is None:
            return True, NO_OPEN_VISITA_MESSAGE
        visitas_service.cancelar_visita(open_visit["id"])
        _clear_active_visita(sender_phone, open_visit["id"])
        return True, "Visita cancelada com sucesso."

    if open_visit is None:
        return False, None

    state = str(open_visit.get("estado_fluxo") or "")
    if state in VISITA_FLOW_STEPS:
        field, next_question = VISITA_FLOW_STEPS[state]
        value = _parse_visita_area(text) if field == "area_hectares" else text
        updates = {field: value}
        if field == "area_hectares" and _mentions_alqueires(text):
            updates = {"area_alqueires": value}
        next_state = _next_visita_state(state)
        updates["estado_fluxo"] = next_state
        saved = open_visit
        for update_field, update_value in updates.items():
            saved = visitas_service.atualizar_campo(saved["id"], update_field, update_value)
        visita_active_states[phone] = int(saved["id"])
        if next_state == "visita_aberta":
            return True, "\n".join(
                [
                    "Visita aberta.",
                    "Envie foto, observação, localização ou \"fechar visita\".",
                ]
            )
        return True, next_question

    if state != "visita_aberta":
        return True, "Continue preenchendo a visita técnica atual."

    if normalized_text in {"1", "2", "3", "4", "5", "6", "7"}:
        return True, VISITA_NUMBER_MESSAGE

    direct_reply = _handle_visita_direct_command(open_visit, text, normalized_text)
    if direct_reply is not None:
        return True, direct_reply

    return True, (
        "Visita em andamento. Envie foto, observação, localização, dado coletado "
        "ou \"fechar visita\"."
    )


def handle_visitas_location_message(sender_phone: str, location: dict) -> str | None:
    open_visit = _get_active_visita_for_phone(sender_phone)
    if open_visit is None or open_visit.get("estado_fluxo") != "visita_aberta":
        return None
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return "Não consegui ler a localização enviada. Tente enviar o ponto novamente."
    description = location.get("name") or location.get("address") or ""
    saved = visitas_service.adicionar_localizacao(
        open_visit["id"],
        float(latitude),
        float(longitude),
        descricao=description,
    )
    return "\n".join(
        [
            "📍 Localização salva.",
            "Abrir no GPS:",
            saved["maps_url"],
        ]
    )


def handle_visitas_media_message(
    sender_phone: str,
    message_type: str,
    media_id: str,
    file_path: str,
    caption: str = "",
) -> str:
    open_visit = _get_active_visita_for_phone(sender_phone)
    if open_visit is None:
        return "Nenhuma visita em andamento encontrada."
    visitas_service.adicionar_midia(
        open_visit["id"],
        tipo="foto" if message_type == "image" else message_type,
        media_id_whatsapp=media_id,
        caminho_arquivo=file_path,
        legenda=caption,
    )
    fazenda = open_visit.get("fazenda") or "visita em andamento"
    return "\n".join(
        [
            f"Foto salva na visita {fazenda}.",
            "Envie outra foto, observação, localização ou \"fechar visita\".",
        ]
    )


def _handle_visita_direct_command(
    open_visit: dict,
    text: str,
    normalized_text: str,
) -> str | None:
    direct_patterns = (
        ("fazenda", "fazenda"),
        ("proprietario", "proprietario"),
        ("proprietario", "proprietario"),
        ("gerente", "gerente"),
        ("safra", "safra"),
        ("tipo_visita", "tipo"),
        ("area_hectares", "hectares"),
        ("area_alqueires", "alqueires"),
        ("area_hectares", "area"),
    )
    for field, prefix in direct_patterns:
        if normalized_text == prefix or normalized_text.startswith(prefix + " "):
            value = text[len(text.split(maxsplit=1)[0]):].strip()
            if not value:
                return "Informe o valor junto com o comando."
            if field in {"area_hectares", "area_alqueires"}:
                value = _parse_visita_area(value)
            visitas_service.atualizar_campo(open_visit["id"], field, value)
            return "Campo salvo na visita."

    for prefix in ("obs ", "observacao "):
        if normalized_text.startswith(prefix):
            observation = text[len(text.split(maxsplit=1)[0]):].strip()
            visitas_service.adicionar_observacao(open_visit["id"], observation)
            return "Observacao salva na visita."

    if normalized_text.startswith("dado "):
        payload = text.split(maxsplit=2)
        if len(payload) < 3:
            return "Informe o dado no formato: dado chave valor"
        visitas_service.adicionar_dado_coletado(
            open_visit["id"],
            payload[1],
            payload[2],
        )
        return "Dado coletado salvo na visita."

    return None


def _next_visita_state(state: str) -> str:
    order = (
        "aguardando_fazenda",
        "aguardando_proprietario",
        "aguardando_gerente",
        "aguardando_area",
        "aguardando_safra",
        "aguardando_tipo_visita",
    )
    try:
        index = order.index(state)
    except ValueError:
        return "visita_aberta"
    if index + 1 >= len(order):
        return "visita_aberta"
    return order[index + 1]


def _parse_visita_area(text: str) -> float | None:
    match = re.search(r"[-+]?\d[\d.,]*", str(text or ""))
    if match is None:
        return None
    normalized = match.group(0)
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    return float(normalized)


def _mentions_alqueires(text: str) -> bool:
    return "alqueir" in _normalize_caption(text)


def _get_active_visita_for_phone(sender_phone: str) -> dict | None:
    phone = normalize_phone(sender_phone)
    visita_id = visita_active_states.get(phone)
    if visita_id is not None:
        visita = visitas_service.obter_visita_por_id(visita_id)
        if visita is not None and visita.get("status") == "aberta":
            return visita
        visita_active_states.pop(phone, None)
    visita = visitas_service.obter_visita_aberta(sender_phone)
    if visita is not None and visita.get("status") == "aberta":
        visita_active_states[phone] = int(visita["id"])
        return visita
    return None


def _clear_active_visita(sender_phone: str, visita_id: int | None = None) -> None:
    phone = normalize_phone(sender_phone)
    current = visita_active_states.get(phone)
    if visita_id is None or current == int(visita_id):
        visita_active_states.pop(phone, None)
    visita_new_visit_states.discard(phone)


def _existing_open_visita_choice_message(visita: dict) -> str:
    return "\n".join(
        [
            "Você já possui uma visita aberta:",
            "",
            f"#{visita.get('id')} - {visita.get('fazenda') or '-'}",
            f"Status: {visita.get('status') or '-'}",
            "",
            "Para continuar nela, envie:",
            f"continuar visita {visita.get('id')}",
            "",
            "Para iniciar uma nova visita, envie:",
            "nova visita",
            "",
            "Para fechar a atual, envie:",
            "fechar visita",
        ]
    )


def _start_new_visita_flow(sender_phone: str) -> str:
    phone = normalize_phone(sender_phone)
    visita_active_states.pop(phone, None)
    visita_new_visit_states.add(phone)
    return "\n".join(
        [
            "Vamos iniciar uma nova visita técnica.",
            "Qual o nome da fazenda?",
        ]
    )


def _create_new_visita_from_farm(
    sender_phone: str,
    text: str,
    collaborator: dict | None,
) -> str:
    farm = str(text or "").strip()
    if not farm:
        return "Informe o nome da fazenda para iniciar a nova visita."
    phone = normalize_phone(sender_phone)
    visita = visitas_service.criar_visita(
        sender_phone,
        tecnico_nome=(collaborator or {}).get("nome"),
        fazenda=farm,
        estado_fluxo="visita_aberta",
    )
    visita_active_states[phone] = int(visita["id"])
    visita_new_visit_states.discard(phone)
    return "\n".join(
        [
            f"Visita criada para {farm.upper()}.",
            'Envie foto, observação, localização, dado coletado ou "fechar visita".',
        ]
    )


def _is_continuar_visita_command(normalized_text: str) -> bool:
    return re.fullmatch(r"continuar visitas?\s+\d+", normalized_text) is not None


def _continue_visita(sender_phone: str, normalized_text: str) -> str:
    match = re.fullmatch(r"continuar visitas?\s+(\d+)", normalized_text)
    visita_id = int(match.group(1)) if match else 0
    visita = visitas_service.obter_visita_por_id(visita_id)
    if visita is None:
        return (
            "Não encontrei essa visita técnica.\n"
            'Envie "visitas" para listar visitas válidas.'
        )
    if visita.get("status") != "aberta":
        return "Essa visita não está aberta e não pode ser continuada."
    phone = normalize_phone(sender_phone)
    visita_active_states[phone] = visita_id
    visita_new_visit_states.discard(phone)
    return "\n".join(
        [
            f"Você voltou para a visita #{visita_id} - {visita.get('fazenda') or '-'}.",
            'Envie foto, observação, localização, dado coletado ou "fechar visita".',
        ]
    )


def _is_ver_visita_command(normalized_text: str) -> bool:
    return re.fullmatch(r"ver visitas?\s+\d+", normalized_text) is not None


def _is_editar_visita_command(normalized_text: str) -> bool:
    return re.fullmatch(r"editar visitas?\s+\d+", normalized_text) is not None


def _handle_ver_visita(normalized_text: str) -> str:
    match = re.fullmatch(r"ver visitas?\s+(\d+)", normalized_text)
    visita_id = int(match.group(1)) if match else 0
    visita = visitas_service.obter_visita_por_id(visita_id)
    if visita is None:
        return (
            "Não encontrei essa visita técnica.\n"
            'Envie "visitas" para listar visitas válidas.'
        )
    if visita.get("status") == "cancelada":
        return (
            "Essa visita foi cancelada.\n"
            'Envie "visitas" para listar visitas válidas.'
        )
    return _ver_visita_message(visita)


def _ver_visita_message(visita: dict) -> str:
    area = _format_visita_area_message(visita)
    return "\n".join(
        [
            f"Visita #{visita.get('id')} - {visita.get('fazenda') or '-'}",
            "",
            f"Status: {visita.get('status') or '-'}",
            f"Técnico: {visita.get('tecnico_nome') or '-'}",
            f"Data: {_format_date_br(visita.get('data_visita')) or '-'}",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Proprietário: {visita.get('proprietario') or '-'}",
            f"Gerente/responsável: {visita.get('gerente') or '-'}",
            f"Área: {area}",
            f"Safra: {visita.get('safra') or '-'}",
            f"Tipo: {visita.get('tipo_visita') or visita.get('objetivo') or '-'}",
            f"Observações: {visita.get('observacoes') or '-'}",
            "",
            "Para editar:",
            f"editar visita {visita.get('id')}",
            "",
            "Para gerar PDF:",
            f"relatório visita {visita.get('id')}",
        ]
    )


def _start_visita_edit(sender_phone: str, normalized_text: str) -> str:
    match = re.fullmatch(r"editar visitas?\s+(\d+)", normalized_text)
    visita_id = int(match.group(1)) if match else 0
    visita = visitas_service.obter_visita_por_id(visita_id)
    if visita is None:
        return (
            "Não encontrei essa visita técnica.\n"
            'Envie "visitas" para listar visitas válidas.'
        )
    if visita.get("status") == "cancelada":
        return "Essa visita foi cancelada e não pode ser editada."
    if visita.get("status") not in {"aberta", "fechada"}:
        return "Essa visita não pode ser editada."
    visita_edit_states[normalize_phone(sender_phone)] = visita_id
    return "\n".join(
        [
            f"Você está editando a visita #{visita_id} - {visita.get('fazenda') or '-'}.",
            "",
            "Envie uma alteração por mensagem no formato:",
            "campo = valor",
            "",
            "Campos que posso editar:",
            "",
            "* fazenda",
            "* proprietário",
            "* gerente",
            "* área",
            "* safra",
            "* tipo",
            "* observações",
            "* data",
            "",
            "Exemplos:",
            "gerente = Marcos Silva",
            "área = 250 hectares",
            "observações = Cliente solicitou orçamento para aplicação.",
            "",
            "Quando terminar, envie:",
            "fechar edição",
            "",
            "Para cancelar, envie:",
            "cancelar edição",
        ]
    )


def _handle_visita_edit_message(sender_phone: str, text: str) -> str:
    phone = normalize_phone(sender_phone)
    visita_id = visita_edit_states.get(phone)
    if visita_id is None:
        return "Nenhuma edição de visita em andamento."
    visita = visitas_service.obter_visita_por_id(visita_id)
    if visita is None:
        visita_edit_states.pop(phone, None)
        return "Não encontrei mais essa visita técnica. Edição encerrada."
    if visita.get("status") == "cancelada":
        visita_edit_states.pop(phone, None)
        return "Essa visita foi cancelada e não pode ser editada."

    if "=" not in str(text or ""):
        return _visita_edit_help()
    raw_field, raw_value = str(text).split("=", 1)
    field = _resolve_visita_edit_field(raw_field, raw_value)
    value_text = raw_value.strip()
    if field is None:
        return _visita_edit_help()
    if not value_text:
        return "Informe um valor para atualizar esse campo."

    value = _prepare_visita_edit_value(field, value_text)
    before = visita.get(field)
    result = visitas_service.editar_campo(
        visita_id,
        field,
        value,
        telefone_editor=sender_phone,
    )
    after = result.get("valor_novo")
    return "\n".join(
        [
            "Campo atualizado:",
            VISITA_EDITABLE_FIELDS.get(field, field),
            f"Antes: {_format_edit_value(before)}",
            f"Depois: {_format_edit_value(after)}",
            "",
            "Para gerar PDF atualizado:",
            f"relatório visita {visita_id}",
        ]
    )


def _close_visita_edit(sender_phone: str) -> str:
    visita_id = visita_edit_states.pop(normalize_phone(sender_phone), None)
    if visita_id is None:
        return "Nenhuma edição de visita em andamento."
    return "\n".join(
        [
            "Edição finalizada.",
            "Para ver os dados atualizados:",
            f"ver visita {visita_id}",
            "Para gerar o PDF:",
            f"relatório visita {visita_id}",
        ]
    )


def _cancel_visita_edit(sender_phone: str) -> str:
    visita_id = visita_edit_states.pop(normalize_phone(sender_phone), None)
    if visita_id is None:
        return "Nenhuma edição de visita em andamento."
    return "\n".join(
        [
            "Edição encerrada.",
            "Alterações já salvas foram mantidas.",
        ]
    )


def _visita_edit_help() -> str:
    return "\n".join(
        [
            "Não reconheci esse campo.",
            "Envie no formato: campo = valor",
            "",
            "Campos aceitos: fazenda, proprietário, gerente, área, safra, tipo, observações, data.",
        ]
    )


def _resolve_visita_edit_field(raw_field: str, raw_value: str = "") -> str | None:
    normalized = _normalize_caption(raw_field)
    aliases = {
        "fazenda": "fazenda",
        "propriedade": "fazenda",
        "nome da fazenda": "fazenda",
        "proprietario": "proprietario",
        "dono": "proprietario",
        "gerente": "gerente",
        "responsavel": "gerente",
        "safra": "safra",
        "tipo": "tipo_visita",
        "tipo visita": "tipo_visita",
        "objetivo": "objetivo",
        "objetivo visita": "objetivo",
        "observacoes": "observacoes",
        "observacao": "observacoes",
        "obs": "observacoes",
        "data": "data_visita",
        "data visita": "data_visita",
        "area": "area_hectares",
        "area hectares": "area_hectares",
        "hectares": "area_hectares",
        "area alqueires": "area_alqueires",
        "alqueires": "area_alqueires",
    }
    field = aliases.get(normalized)
    if field == "area_hectares" and _mentions_alqueires(raw_value):
        return "area_alqueires"
    return field


def _prepare_visita_edit_value(field: str, value: str):
    if field in {"area_hectares", "area_alqueires"}:
        return _parse_visita_area(value)
    if field == "data_visita":
        return _parse_visita_date(value)
    return value


def _parse_visita_date(value: str) -> str:
    text = str(value or "").strip()
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            pass
    return text


def _format_edit_value(value: object) -> str:
    if value in (None, ""):
        return "-"
    return str(value)


def _format_visita_area_message(visita: dict) -> str:
    hectares = visita.get("area_hectares")
    alqueires = visita.get("area_alqueires")
    if hectares not in (None, ""):
        return f"{_format_optional_number(hectares)} ha"
    if alqueires not in (None, ""):
        return f"{_format_optional_number(alqueires)} alqueires"
    return "-"


def _visita_status_message(visita: dict) -> str:
    return "\n".join(
        [
            "Visita em andamento.",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Gerente: {visita.get('gerente') or '-'}",
            f"Safra: {visita.get('safra') or '-'}",
            f"Tipo: {visita.get('tipo_visita') or '-'}",
        ]
    )


def _visita_fechada_message(visita: dict) -> str:
    resumo = visitas_service.visita_resumo(visita["id"])
    fotos = len(resumo.get("midias") or [])
    localizacoes = len(resumo.get("localizacoes") or [])
    area = _format_optional_number(visita.get("area_hectares"))
    return "\n".join(
        [
            "Visita fechada com sucesso.",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Gerente: {visita.get('gerente') or '-'}",
            f"Área: {area} ha",
            f"Fotos: {fotos}",
            f"Localizações: {localizacoes}",
            "",
            "Comandos disponíveis:",
            "relatório visita",
            "planilha visitas",
            "localização visita",
        ]
    )


def _visita_localizacoes_message(visita_id: int) -> str:
    resumo = visitas_service.visita_resumo(visita_id)
    locations = resumo.get("localizacoes") or []
    if not locations:
        return "Nenhuma localização foi salva nesta visita."
    fazenda = resumo.get("fazenda") or "visita em andamento"
    lines = []
    for index, location in enumerate(locations):
        description = location.get("descricao") or (
            "ponto principal" if index == 0 else f"ponto {index + 1}"
        )
        lines.extend(
            [
                f"{fazenda} - {description}",
                location.get("maps_url") or "",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _is_listar_visitas_command(normalized_text: str) -> bool:
    return normalized_text in {
        "visitas",
        "listar visitas",
        "visitas hoje",
        "visitas abertas",
        "fazendas",
    }


def _listar_visitas_message(normalized_text: str) -> str:
    filters = {"limite": 10}
    if normalized_text == "visitas hoje":
        filters["periodo"] = "hoje"
    if normalized_text == "visitas abertas":
        filters["status"] = "aberta"
    data = visitas_service.listar_visitas_validas(**filters)
    visitas = data.get("visitas") or []
    if not visitas:
        return NO_VALID_VISITA_MESSAGE

    title = (
        "Visitas abertas encontradas:"
        if normalized_text == "visitas abertas"
        else "Visitas técnicas encontradas:"
    )
    lines = [title, ""]
    for visita in visitas:
        lines.extend(_format_visita_list_item(visita, detailed=True))
        lines.append("")
    lines.extend(
        [
            "Para gerar relatório, envie:",
            f"relatório visita {visitas[0]['id']}",
            "",
            "Para buscar por fazenda, envie:",
            f"relatório fazenda {visitas[0].get('fazenda') or 'Nome da Fazenda'}",
        ]
    )
    return "\n".join(lines).strip()


def _format_visita_list_item(visita: dict, detailed: bool = False) -> list[str]:
    date_text = _format_date_br(visita.get("data_visita"))
    header = f"#{visita.get('id')} - {visita.get('fazenda') or '-'}"
    if not detailed:
        return [
            f"{header} - {visita.get('status') or '-'} - {date_text}",
        ]
    return [
        header,
        f"Status: {visita.get('status') or '-'}",
        f"Técnico: {visita.get('tecnico_nome') or '-'}",
        f"Data: {date_text}",
        f"Gerente: {visita.get('gerente') or '-'}",
    ]


def _is_planilha_visitas_command(normalized_text: str) -> bool:
    if normalized_text == "fazendas visitadas":
        return True
    return re.fullmatch(r"planilha visitas(?:\s+.+)?", normalized_text) is not None


def _is_relatorio_visita_command(normalized_text: str) -> bool:
    return (
        re.fullmatch(r"relatorio visitas?(?:\s+\d+)?", normalized_text) is not None
        or re.fullmatch(r"relatorio fazenda\s+.+", normalized_text) is not None
    )


def _is_localizacao_visita_command(normalized_text: str) -> bool:
    return re.fullmatch(
        r"localizac(?:ao|oes) visitas?(?:\s+\d+)?",
        normalized_text,
    ) is not None


def _send_visitas_excel(sender_phone: str, normalized_text: str = "") -> None:
    selected = _parse_visitas_excel_reference(normalized_text)
    data = visitas_service.listar_visitas(**selected)
    content = build_visitas_workbook(data)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=VISITAS_EXCEL_FILENAME,
        caption=VISITAS_EXCEL_CAPTION,
        mime_type=RDV_EXCEL_MIME_TYPE,
    )


def _send_visita_pdf(sender_phone: str, normalized_text: str = "") -> bool:
    visita = _select_visita_for_pdf(normalized_text)
    if visita is None:
        return False
    _send_visita_pdf_data(sender_phone, visita)
    return True


def _send_visita_pdf_data(sender_phone: str, visita: dict) -> None:
    content = build_visita_pdf(visita)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=f"relatorio_visita_{visita['id']}.pdf",
        caption=VISITA_PDF_CAPTION,
        mime_type=VISITA_PDF_MIME_TYPE,
    )


def _handle_relatorio_visita(sender_phone: str, text: str, normalized_text: str) -> str | None:
    fazenda_match = re.fullmatch(r"relatorio fazenda\s+(.+)", normalized_text)
    if fazenda_match is not None:
        query = _extract_relatorio_fazenda_query(text)
        data = visitas_service.buscar_visitas_por_fazenda(query)
        visitas = data.get("visitas") or []
        if not visitas:
            return (
                f'Não encontrei visita técnica válida para "{query}".\n'
                'Envie "visitas" para listar visitas válidas.'
            )
        if len(visitas) > 1:
            return _multiple_fazenda_visitas_message(query, visitas)
        visita = visitas_service.obter_visita_completa(visitas[0]["id"])
        if visita is None:
            return NO_VALID_VISITA_MESSAGE
        _send_visita_pdf_data(sender_phone, visita)
        return None

    id_match = re.fullmatch(r"relatorio visitas?\s+(\d+)", normalized_text)
    if id_match is not None:
        visita = _select_visita_for_pdf(normalized_text)
        if visita is None:
            return (
                "Não encontrei essa visita técnica.\n"
                'Envie "visitas" para listar visitas válidas.'
            )
        _send_visita_pdf_data(sender_phone, visita)
        return None

    data = visitas_service.listar_visitas_validas(limite=10)
    visitas = data.get("visitas") or []
    if not visitas:
        return NO_VALID_VISITA_MESSAGE
    if len(visitas) == 1:
        visita = visitas_service.obter_visita_completa(visitas[0]["id"])
        if visita is None:
            return NO_VALID_VISITA_MESSAGE
        _send_visita_pdf_data(sender_phone, visita)
        return None
    return _multiple_visitas_report_message(visitas)


def _select_visita_for_pdf(normalized_text: str) -> dict | None:
    match = re.fullmatch(r"relatorio visitas?(?:\s+(\d+))?", normalized_text)
    if match is not None and match.group(1):
        visita_id = int(match.group(1))
        raw_visita = visitas_service.obter_visita_por_id(visita_id)
        if raw_visita is None:
            return None
        if raw_visita.get("status") == "cancelada":
            raise ValueError("visita_cancelada")
        visita = visitas_service.obter_visita_completa(visita_id)
        if visita is None:
            return None
        if visita.get("status") not in {"aberta", "fechada"}:
            return None
        return visita
    return visitas_service.obter_ultima_visita()


def _extract_relatorio_fazenda_query(text: str) -> str:
    match = re.match(r"(?is)\s*relat[oó]rio\s+fazenda\s+(.+?)\s*$", str(text or ""))
    if match is not None:
        return match.group(1).strip()
    return re.sub(r"(?i)^relatorio\s+fazenda\s+", "", _normalize_caption(text)).strip()


def _multiple_fazenda_visitas_message(query: str, visitas: list[dict]) -> str:
    lines = [f'Encontrei mais de uma visita para "{query}":', ""]
    for visita in visitas[:10]:
        lines.append(
            f"#{visita.get('id')} - {visita.get('fazenda') or '-'} - "
            f"{_format_date_br(visita.get('data_visita'))} - {visita.get('status') or '-'}"
        )
    lines.extend(["", "Envie:", f"relatório visita {visitas[0]['id']}"])
    return "\n".join(lines)


def _multiple_visitas_report_message(visitas: list[dict]) -> str:
    lines = [
        "Existem várias visitas técnicas registradas.",
        "Escolha uma pelo ID:",
        "",
    ]
    for visita in visitas[:10]:
        lines.extend(_format_visita_list_item(visita))
    lines.extend(["", "Envie:", f"relatório visita {visitas[0]['id']}"])
    return "\n".join(lines)


def _handle_localizacao_visita(normalized_text: str) -> str:
    match = re.fullmatch(r"localizac(?:ao|oes) visitas?\s+(\d+)", normalized_text)
    if match is not None:
        visita_id = int(match.group(1))
        visita = visitas_service.obter_visita_por_id(visita_id)
        if visita is None:
            return (
                "Não encontrei essa visita técnica.\n"
                'Envie "visitas" para listar visitas válidas.'
            )
        if visita.get("status") == "cancelada":
            return (
                "Essa visita foi cancelada e não pode mostrar localização.\n"
                'Envie "visitas" para listar visitas válidas.'
            )
        return _visita_localizacoes_message(visita_id)

    data = visitas_service.listar_visitas_validas(limite=10)
    visitas = data.get("visitas") or []
    if not visitas:
        return NO_VALID_VISITA_MESSAGE
    abertas = [visita for visita in visitas if visita.get("status") == "aberta"]
    if len(abertas) == 1:
        return _visita_localizacoes_message(abertas[0]["id"])
    if len(visitas) == 1:
        return _visita_localizacoes_message(visitas[0]["id"])
    lines = [
        "Existem várias visitas técnicas registradas.",
        "Escolha uma pelo ID:",
        "",
    ]
    for visita in visitas[:10]:
        lines.extend(_format_visita_list_item(visita))
    lines.extend(["", "Envie:", f"localização visita {visitas[0]['id']}"])
    return "\n".join(lines)


def _parse_visitas_excel_reference(normalized_text: str) -> dict:
    if normalized_text == "fazendas visitadas":
        return {}
    match = re.fullmatch(r"planilha visitas(?:\s+(.+))?", normalized_text)
    argument = str((match.group(1) if match else "") or "").strip()
    if argument == "hoje":
        return {"periodo": "hoje"}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", argument):
        return {"data": argument}
    if re.fullmatch(r"\d{4}-\d{2}", argument):
        return {"mes": argument}
    return {}


def _format_optional_number(value: object) -> str:
    if value in (None, ""):
        return "-"
    parsed = float(value)
    if parsed.is_integer():
        return str(int(parsed))
    return f"{parsed:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def clear_rdv_sessions() -> None:
    """Compatibilidade com os testes da etapa anterior; o fluxo agora e persistente."""
    whatsapp_menu_states.clear()
    visita_edit_states.clear()
    visita_active_states.clear()
    visita_new_visit_states.clear()


def _no_open_trip_message() -> str:
    return "\n".join(
        [
            "Nenhuma viagem em andamento encontrada.",
            "Para iniciar uma nova viagem, envie:",
            "km inicio 120350",
        ]
    )


def _open_trip_message(expense: dict) -> str:
    lines = [
        "Ja existe uma viagem em andamento.",
        f"KM inicial: {_format_km_text(expense.get('km_inicio'))}",
    ]
    if expense.get("cidade_origem"):
        lines.append(f"Origem: {expense['cidade_origem']}")
    if expense.get("cidade_destino"):
        lines.append(f"Destino: {expense['cidade_destino']}")
    state = expense.get("status_fluxo")
    if state == "aguardando_km_origem":
        lines.append("Informe a cidade/local de origem.")
    elif state == "aguardando_km_destino":
        lines.append("Informe a cidade/local de destino.")
    else:
        lines.append("Para finalizar, envie: km termino 120500")
    lines.append("Para cancelar, envie: cancelar km")
    return "\n".join(lines)


def _is_rdv_excel_command(text: str) -> bool:
    request = _parse_rdv_report_command(_normalize_caption(text))
    return request is not None and request["kind"] == "excel"


def _handle_global_rdv_command(
    sender_phone: str,
    collaborator: dict,
    normalized_text: str,
) -> tuple[bool, str | None]:
    report_request = _parse_rdv_report_command(normalized_text)
    if report_request is not None and report_request["kind"] == "summary":
        if report_request["period"] == "week":
            return True, _weekly_summary_message(week=report_request["reference"])
        return True, _monthly_summary_message(
            collaborator_id=collaborator["id"] if report_request["scope"] == "mine" else "",
            month=report_request["reference"],
        )

    if report_request is not None and report_request["kind"] == "excel":
        try:
            if report_request["period"] == "week":
                _send_weekly_rdv_excel(sender_phone, week=report_request["reference"])
            else:
                _send_monthly_rdv_excel(sender_phone, month=report_request["reference"])
        except Exception as exc:
            logger.exception(
                "Falha ao enviar Excel RDV pelo WhatsApp: to=%s erro=%s",
                _mask_phone(sender_phone),
                _safe_exception_summary(exc),
            )
            return True, _rdv_excel_fallback_message()
        return True, None

    km_command = _parse_km_command(normalized_text)
    if km_command is not None:
        action, raw_value = km_command
        if action == "help":
            return True, KM_HELP_MESSAGE
        if not raw_value:
            example_action = "inicio" if action == "start" else "termino"
            example_value = "120350" if action == "start" else "120500"
            return True, "\n".join(
                [
                    "Informe a quilometragem junto com o comando.",
                    "",
                    "Exemplo:",
                    f"km {example_action} {example_value}",
                ]
            )
        km_value = _parse_km_value(raw_value)
        if km_value is None:
            return True, (
                "Quilometragem invalida. Informe um numero junto com o comando."
            )
        open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)
        if action == "start":
            if open_km is not None:
                return True, _open_trip_message(open_km)
            started = rdv_service.create_whatsapp_km_launch(
                collaborator_id=collaborator["id"],
                phone=sender_phone,
                km_start=km_value,
            )
            return True, "\n".join(
                [
                    f"KM inicial: {_format_km_text(started['km_inicio'])}",
                    "Qual a cidade/local de origem?",
                ]
            )
        if open_km is None:
            return True, _no_open_trip_message()
        if open_km.get("status_fluxo") == "aguardando_km_origem":
            return True, (
                "Antes de finalizar, informe a cidade/local de origem da viagem."
            )
        if open_km.get("status_fluxo") == "aguardando_km_destino":
            return True, (
                "Antes de finalizar, informe a cidade/local de destino da viagem."
            )
        km_start = float(open_km.get("km_inicio") or 0)
        if km_value <= km_start:
            return True, (
                "A quilometragem final deve ser maior que a inicial. "
                "A viagem continua em andamento."
            )
        completed = rdv_service.complete_km_end(open_km["id"], km_value)
        return True, "\n".join(
            [
                "Viagem finalizada com sucesso.",
                f"Origem: {completed.get('cidade_origem') or '-'}",
                f"Destino: {completed.get('cidade_destino') or '-'}",
                f"KM inicial: {_format_km_text(completed['km_inicio'])}",
                f"KM final: {_format_km_text(completed['km_fim'])}",
                f"KM rodado: {_format_km_text(completed['km_rodado'])} km",
            ]
        )

    return False, None


def _parse_km_command(normalized_text: str) -> tuple[str, str] | None:
    if normalized_text == "km":
        return "help", ""

    patterns = (
        ("start", r"^(?:km inicio|inicio km|iniciar km)(?:\s+(.*))?$"),
        ("end", r"^(?:km termino|km fim|km final|fim km|finalizar km)(?:\s+(.*))?$"),
    )
    for action, pattern in patterns:
        match = re.fullmatch(pattern, normalized_text)
        if match:
            return action, str(match.group(1) or "").strip()
    return None


def _is_standalone_number(text: str) -> bool:
    return re.fullmatch(r"\d+(?:[.,]\d+)?", str(text or "").strip()) is not None


def _parse_rdv_report_command(normalized_text: str) -> dict | None:
    text = str(normalized_text or "").strip()
    match = re.fullmatch(r"(resumo|planilha|relatorio|excel)(?:\s+(.+))?", text)
    if match is None:
        return None

    command = match.group(1)
    argument = str(match.group(2) or "").strip()
    kind = "summary" if command == "resumo" else "excel"

    if re.fullmatch(r"\d{4}-W\d{2}", argument, flags=re.IGNORECASE):
        return {
            "kind": kind,
            "period": "week",
            "reference": argument.upper(),
            "scope": "all",
        }
    if re.fullmatch(r"\d{4}-\d{2}", argument):
        return {
            "kind": kind,
            "period": "month",
            "reference": argument,
            "scope": "all",
        }
    if argument in {"semanal", "semana"}:
        return {
            "kind": kind,
            "period": "week",
            "reference": calculate_week_reference(date.today()),
            "scope": "all",
        }
    if argument in {"anterior", "mes anterior"}:
        return {
            "kind": kind,
            "period": "month",
            "reference": _previous_month_reference(date.today()),
            "scope": "all",
        }
    if argument in {"", "mensal", "mes"}:
        return {
            "kind": kind,
            "period": "month",
            "reference": calculate_month_reference(date.today()),
            "scope": "all",
        }
    return None


def _previous_month_reference(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"


def _send_monthly_rdv_excel(sender_phone: str, month: str = "") -> None:
    selected_month = month or calculate_month_reference(date.today())
    report_data = rdv_service.monthly_report_data(month=selected_month)
    content = build_monthly_rdv_workbook(report_data)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=RDV_MONTHLY_EXCEL_FILENAME,
        caption=RDV_MONTHLY_EXCEL_CAPTION,
        mime_type=RDV_EXCEL_MIME_TYPE,
    )


def _send_weekly_rdv_excel(sender_phone: str, week: str = "") -> None:
    selected_week = week or calculate_week_reference(date.today())
    report_data = rdv_service.weekly_report_data(
        week=selected_week,
    )
    content = build_weekly_rdv_workbook(report_data)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=RDV_WEEKLY_EXCEL_FILENAME,
        caption=RDV_WEEKLY_EXCEL_CAPTION,
        mime_type=RDV_EXCEL_MIME_TYPE,
    )


def _rdv_excel_fallback_message() -> str:
    public_url = _base_public_url()
    if public_url:
        download_url = f"{public_url}/ciclus/rdv/relatorio-mensal.xlsx"
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
    if expense.get("status_fluxo") == "aguardando_data_comprovante":
        return (
            f"Detectei o valor {_format_brl_text(expense.get('valor'))}, "
            "mas nao consegui identificar a data do comprovante. "
            "Informe a data do comprovante no formato 11/06/2026."
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


def _monthly_summary_message(
    collaborator_id: int | str = "",
    month: str = "",
) -> str:
    selected_month = month or calculate_month_reference(date.today())
    summary = rdv_service.monthly_report(
        month=selected_month,
        collaborator_id=collaborator_id,
    )

    title = (
        f"Meu resumo do mes {selected_month}"
        if collaborator_id
        else f"Resumo geral do mes {selected_month}"
    )
    return _summary_lines(title, summary)


def _weekly_summary_message(
    collaborator_id: int | str = "",
    week: str = "",
) -> str:
    selected_week = week or calculate_week_reference(date.today())
    summary = rdv_service.weekly_report(
        week=selected_week,
        collaborator_id=collaborator_id,
    )

    title = (
        f"Meu resumo da semana {selected_week}"
        if collaborator_id
        else f"Resumo geral da semana {selected_week}"
    )
    return _summary_lines(title, summary)


def _summary_lines(title: str, summary: dict) -> str:
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


def _format_date_br(value: object) -> str:
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return text


def _format_datetime_br(value: object) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).strftime("%d/%m/%Y %H:%M")
    text = str(value or "").strip()
    if not text:
        return "-"
    for date_format in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, date_format).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(
            tzinfo=None
        ).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


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
