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
from services.rdv_pdf_service import (
    build_monthly_rdv_pdf,
    build_weekly_rdv_pdf,
)
from services.rdv_receipt_analysis_service import RDVReceiptAnalysisService
from services.report_catalog import (
    interactive_report_commands,
    parse_rdv_report_command,
    report_aliases,
    report_menu_sections,
)
from services.visitas_excel_service import build_visitas_workbook
from services.visitas_pdf_service import build_visita_pdf
from services.visita_report_commands import parse_visit_report_command
from services.visita_validation import validate_visit_field
from services.visitas_service import VisitasTecnicasService


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
RDV_MONTHLY_PDF_FILENAME = "rdv_ciclus_relatorio_mensal.pdf"
RDV_WEEKLY_PDF_FILENAME = "rdv_ciclus_relatorio_semanal.pdf"
RDV_EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
RDV_PDF_MIME_TYPE = "application/pdf"
RDV_MONTHLY_EXCEL_CAPTION = "Segue a planilha mensal do RDV da Ciclus Agro."
RDV_WEEKLY_EXCEL_CAPTION = "Segue a planilha semanal do RDV da Ciclus Agro."
RDV_MONTHLY_PDF_CAPTION = "Segue o relatorio mensal em PDF do RDV da Ciclus Agro."
RDV_WEEKLY_PDF_CAPTION = "Segue o relatorio semanal em PDF do RDV da Ciclus Agro."
VISITAS_EXCEL_FILENAME = "visitas_tecnicas_ciclus.xlsx"
VISITAS_EXCEL_CAPTION = "Segue a planilha de visitas técnicas da Ciclus Agro."
VISITA_PDF_CAPTION = "Segue o relatório da visita técnica da Ciclus Agro."
VISITA_PDF_MIME_TYPE = "application/pdf"
VISITA_START_COMMANDS = {"visita", "nova visita", "iniciar visita"}
VISITA_FLOW_STEPS = {
    "aguardando_fazenda": ("fazenda", "Qual o nome do proprietário?"),
    "aguardando_proprietario": ("proprietario", "Qual o gerente/responsável?"),
    "aguardando_gerente": ("gerente", "Qual a área da fazenda?"),
    "aguardando_area": ("area_hectares", "Qual a safra?"),
    "aguardando_safra": ("safra", "Qual o tipo de visita?"),
    "aguardando_tipo_visita": ("tipo_visita", ""),
}
VISITA_FLOW_STEPS = {
    "aguardando_fazenda": ("fazenda", "Qual o nome do proprietario da fazenda/propriedade?"),
    "aguardando_proprietario": ("proprietario", "Qual o telefone do proprietario?"),
    "aguardando_telefone_proprietario": ("telefone_proprietario", "Qual o nome do gerente ou responsavel local pela propriedade?"),
    "aguardando_gerente": ("gerente", "Qual o telefone do gerente ou responsavel local?"),
    "aguardando_telefone_gerente": ("telefone_gerente", "Qual area, talhao ou local da propriedade foi visitado?\n\nExemplos:\nSede, Talhao 3, Area de irrigacao, Pasto proximo ao curral, Barracao de maquinas."),
    "aguardando_area": ("area", ""),
}
VISITA_DESCRICAO_MESSAGE = "\n".join(
    [
        "Descricao da visita",
        "",
        "Faca um breve resumo do motivo desta visita.",
        "",
        "Aqui voce deve informar, de forma curta e objetiva, por que a visita esta sendo realizada.",
        "",
        "Exemplos:",
        "",
        "* Vistoria tecnica da area de plantio",
        "* Avaliacao de irrigacao",
        "* Levantamento para orcamento",
        "* Verificacao de problema informado pelo gerente",
        "* Acompanhamento da lavoura",
        "* Coleta de informacoes para aplicacao",
        "",
        "Digite agora a descricao da visita:",
    ]
)
VISITA_OBSERVACOES_MESSAGE = "\n".join(
    [
        "Observacoes gerais da visita",
        "",
        "Agora voce pode enviar as observacoes gerais do relatorio.",
        "",
        "Aqui voce pode colocar tudo que percebeu durante a visita, como problemas encontrados, informacoes passadas pelo proprietario ou gerente, pontos de atencao, recomendacoes e qualquer detalhe importante.",
        "",
        "Voce pode mandar quantas mensagens quiser.",
        "Cada mensagem sera salva como uma observacao separada no relatorio.",
        "",
        "Quando terminar todas as observacoes, envie o comando:",
        "",
        "finalizar observacoes",
    ]
)
VISITA_OBSERVACOES_FINALIZADAS_MESSAGE = "\n".join(
    [
        "Observacoes salvas.",
        "",
        "Agora voce pode enviar fotos da visita.",
        "Cada foto podera receber um comentario proprio no relatorio.",
        "",
        "Quando terminar a visita, envie: fechar visita",
    ]
)
VISITA_FLOW_STEPS = {
    "aguardando_fazenda": ("fazenda", "Qual o nome do proprietário da fazenda/propriedade?"),
    "aguardando_proprietario": ("proprietario", "Qual o telefone do proprietário?"),
    "aguardando_telefone_proprietario": ("telefone_proprietario", "Qual o nome do gerente ou responsável local pela propriedade?"),
    "aguardando_gerente": ("gerente", "Qual o telefone do gerente ou responsável local?"),
    "aguardando_telefone_gerente": ("telefone_gerente", "Qual área, talhão ou local da propriedade foi visitado?\n\nExemplos:\nSede, Talhão 3, Área de irrigação, Pasto próximo ao curral, Barracão de máquinas."),
    "aguardando_area": ("area", ""),
}
VISITA_DESCRICAO_MESSAGE = "\n".join(
    [
        "Descrição da visita",
        "",
        "Faça um breve resumo do motivo desta visita.",
        "",
        "Aqui você deve informar, de forma curta e objetiva, por que a visita está sendo realizada.",
        "",
        "Exemplos:",
        "",
        "* Vistoria técnica da área de plantio",
        "* Avaliação de irrigação",
        "* Levantamento para orçamento",
        "* Verificação de problema informado pelo gerente",
        "* Acompanhamento da lavoura",
        "* Coleta de informações para aplicação",
        "",
        "Digite agora a descrição da visita:",
    ]
)
VISITA_OBSERVACOES_MESSAGE = "\n".join(
    [
        "Observações gerais da visita",
        "",
        "Agora você pode enviar as observações gerais do relatório.",
        "",
        "Aqui você pode colocar tudo que percebeu durante a visita, como problemas encontrados, informações passadas pelo proprietário ou gerente, pontos de atenção, recomendações e qualquer detalhe importante.",
        "",
        "Você pode mandar quantas mensagens quiser.",
        "Cada mensagem será salva como uma observação separada no relatório.",
        "",
        "Quando terminar todas as observações, envie o comando:",
        "",
        "finalizar observações",
    ]
)
VISITA_OBSERVACOES_FINALIZADAS_MESSAGE = "\n".join(
    [
        "Observações salvas.",
        "",
        "Agora você pode enviar fotos da visita.",
        "Cada foto poderá receber um comentário próprio no relatório.",
        "",
        "Quando terminar a visita, envie: fechar visita",
    ]
)
VISITA_FOTO_PENDENTE_MESSAGE = "\n".join(
    [
        "Antes de fechar a visita, preciso concluir os comentarios das fotos adicionadas.",
        "",
        "Ainda existem fotos aguardando confirmacao de comentario.",
        "",
        "Responda 1 para comentar ou 2 para seguir sem comentario na foto atual.",
    ]
)
VISITA_FINALIZAR_OBSERVACOES_COMMANDS = {
    "finalizar observacoes",
    "finalizar observacao",
    "finalizar observacoes gerais",
    "fim observacoes",
    "fim observacao",
    "concluir observacoes",
    "concluir observacao",
    "pronto",
    "terminei",
}
VISITA_FOTO_COMENTAR_COMMANDS = {"1", "sim", "s", "comentar"}
VISITA_FOTO_PULAR_COMMANDS = {"2", "nao", "pular", "sem comentario"}
MENU_OPEN_COMMANDS = {"menu", "iniciar", "inicio", "ajuda", "oi", "ola"}
INTERACTIVE_COMMAND_IDS = {
    "menu_rdv_receipt": "rdv",
    "menu_km": "km",
    "menu_visit_start": "visita",
    "menu_reports": "relatorios",
    "menu_help": "menu",
    "confirm_clear_km": "confirmar limpar km",
    "cancel_action": "menu",
    "confirm_visit_close": "confirmar",
    "cancel_visit_review": "cancelar",
}
INTERACTIVE_COMMAND_IDS.update(interactive_report_commands())
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
        "* pdf — envia o relatorio mensal do RDV em PDF",
        "* resumo semanal — mostra o resumo da semana",
        "* planilha semanal — envia a planilha da semana",
        "* pdf semanal — envia o relatorio semanal do RDV em PDF",
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
        "* pdf — relatorio mensal em PDF",
        "* resumo semanal — resumo semanal de despesas",
        "* planilha semanal — planilha semanal de despesas",
        "* pdf semanal — relatorio semanal em PDF",
        "",
        "🌱 Visitas técnicas",
        "",
        "* planilha visitas — planilha com todas as visitas/fazendas registradas",
        "* fazendas visitadas — atalho para a planilha de visitas",
        "* visitas — lista visitas/fazendas registradas",
        "* visitas abertas — lista visitas abertas da equipe",
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
KM_MENU_MESSAGE = "\n".join(
    [
        "Registro de KM",
        "",
        "Voce quer iniciar ou finalizar uma viagem?",
        "",
        "1 - Iniciar viagem",
        "2 - Finalizar viagem",
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
RDV_WAITING_RECEIPT_STATE = "rdv_waiting_receipt"
INVALID_RDV_RECEIPT_MESSAGE = (
    "Não consegui identificar esse arquivo como comprovante.\n\n"
    "Envie uma foto ou PDF legível de nota, cupom, recibo ou comprovante.\n"
    "Se preferir cancelar, digite cancelar."
)
RDV_RECEIPT_CANCEL_MESSAGE = "Lançamento de comprovante cancelado."
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


def send_whatsapp_list_message(
    to: str,
    header: str,
    body: str,
    button_text: str,
    sections: list[dict],
    fallback_text: str,
) -> None:
    payload = _build_whatsapp_list_payload(
        to=to,
        header=header,
        body=body,
        button_text=button_text,
        sections=sections,
    )
    try:
        _post_whatsapp_message_payload(payload, to, "interactive.list")
    except Exception:
        logger.exception(
            "Falha ao enviar lista interativa; usando fallback texto para %s",
            _mask_phone(to),
        )
        send_whatsapp_text(to, fallback_text)


def send_whatsapp_button_message(
    to: str,
    body: str,
    buttons: list[dict],
    header: str = "",
    footer: str = "",
) -> None:
    payload = _build_whatsapp_button_payload(
        to=to,
        body=body,
        buttons=buttons,
        header=header,
        footer=footer,
    )
    _post_whatsapp_message_payload(payload, to, "interactive.button")


def send_main_menu_interactive(to: str) -> None:
    send_whatsapp_list_message(
        to=to,
        header="🌱 Ciclus Agro",
        body="Escolha uma opção para continuar:",
        button_text="Abrir menu",
        sections=[
            {
                "title": "Menu principal",
                "rows": [
                    {
                        "id": "menu_rdv_receipt",
                        "title": "🧾 Lançar comprovante",
                        "description": "Enviar foto ou PDF",
                    },
                    {
                        "id": "menu_km",
                        "title": "🚗 Registrar KM",
                        "description": "Iniciar ou finalizar viagem",
                    },
                    {
                        "id": "menu_visit_start",
                        "title": "🌱 Nova visita técnica",
                        "description": "Registrar fazenda visitada",
                    },
                    {
                        "id": "menu_rdv_summary",
                        "title": "📊 Resumo RDV",
                        "description": "Ver resumo mensal",
                    },
                    {
                        "id": "menu_rdv_excel",
                        "title": "📎 Planilha RDV",
                        "description": "Receber Excel mensal",
                    },
                    {
                        "id": "menu_reports",
                        "title": "📋 Relatórios",
                        "description": "Ver relatórios disponíveis",
                    },
                    {
                        "id": "menu_help",
                        "title": "❓ Ajuda",
                        "description": "Ver comandos e orientações",
                    },
                ],
            },
        ],
        fallback_text=MAIN_MENU_MESSAGE,
    )


def send_reports_menu_interactive(to: str) -> None:
    send_whatsapp_list_message(
        to=to,
        header="Relatorios",
        body="Escolha qual relatorio deseja receber.",
        button_text="Ver relatorios",
        sections=report_menu_sections(),
        fallback_text=REPORTS_MENU_MESSAGE,
    )


def send_confirmation_buttons(
    to: str,
    body: str,
    confirm_id: str,
    confirm_title: str = "Confirmar",
    cancel_id: str = "cancel_action",
    cancel_title: str = "Cancelar",
) -> None:
    send_whatsapp_button_message(
        to=to,
        body=body,
        buttons=[
            {"id": confirm_id, "title": confirm_title},
            {"id": cancel_id, "title": cancel_title},
        ],
    )


def _build_whatsapp_list_payload(
    to: str,
    body: str,
    button_text: str,
    sections: list[dict],
    header: str = "",
    footer: str = "",
) -> dict:
    recipient = str(to or "").strip()
    if not recipient:
        raise RuntimeError("Destinatario WhatsApp nao informado.")

    interactive: dict = {
        "type": "list",
        "body": {"text": str(body or "").strip()},
        "action": {
            "button": str(button_text or "Ver opcoes").strip()[:20],
            "sections": sections,
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": str(header).strip()[:60]}
    if footer:
        interactive["footer"] = {"text": str(footer).strip()}
    return {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": interactive,
    }


def _build_whatsapp_button_payload(
    to: str,
    body: str,
    buttons: list[dict],
    header: str = "",
    footer: str = "",
) -> dict:
    recipient = str(to or "").strip()
    if not recipient:
        raise RuntimeError("Destinatario WhatsApp nao informado.")

    action_buttons = [
        {
            "type": "reply",
            "reply": {
                "id": str(button.get("id") or "").strip(),
                "title": str(button.get("title") or "").strip()[:20],
            },
        }
        for button in buttons[:3]
    ]
    interactive: dict = {
        "type": "button",
        "body": {"text": str(body or "").strip()},
        "action": {"buttons": action_buttons},
    }
    if header:
        interactive["header"] = {"type": "text", "text": str(header).strip()[:60]}
    if footer:
        interactive["footer"] = {"text": str(footer).strip()}
    return {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": interactive,
    }


def _post_whatsapp_message_payload(payload: dict, recipient: str, message_type: str) -> None:
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
        json=payload,
        timeout=20,
    )
    if response.status_code >= 400:
        logger.error(
            "Erro da Meta ao enviar mensagem interativa: status_code=%s to=%s type=%s body=%s",
            response.status_code,
            _mask_phone(recipient),
            message_type,
            _safe_response_body(response),
        )
        response.raise_for_status()

    logger.info(
        "Mensagem interativa WhatsApp enviada: status_code=%s to=%s type=%s",
        response.status_code,
        _mask_phone(recipient),
        message_type,
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

    if message_type in {"text", "interactive"}:
        reply = handle_rdv_text_message(sender_phone, text)
        if reply:
            _send_rdv_reply(sender_phone, text, reply)
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

    open_visit = visitas_service.obter_visita_aberta(sender_phone)
    if open_visit is not None and open_visit.get("estado_fluxo") in {
        "visita_aberta",
        "aguardando_revisao_final",
        "corrigindo_dados_propriedade",
        "corrigindo_observacoes",
        "corrigindo_comentario_foto",
        "aguardando_decisao_comentario_foto",
        "aguardando_texto_comentario_foto",
    }:
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
        analysis = _analyze_rdv_receipt_file(str(downloaded_path), message_id)
        if not _analysis_has_receipt_evidence(analysis):
            whatsapp_menu_states[sender_phone] = RDV_WAITING_RECEIPT_STATE
            logger.info(
                "Midia RDV rejeitada por falta de evidencias de comprovante: from=%s message_id=%s reasons=%s",
                _mask_phone(sender_phone),
                _mask_message_id(message_id),
                analysis.get("reasons"),
            )
            _safe_send_text(sender_phone, INVALID_RDV_RECEIPT_MESSAGE)
            return
        rdv_expense = _register_received_media_as_rdv(
            sender_phone=sender_phone,
            caminho_arquivo=str(downloaded_path),
            whatsapp_message_id=message_id,
            message_type=message_type,
            received_at=data_hora_recebimento,
            analysis=analysis,
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
    whatsapp_menu_states.pop(sender_phone, None)
    _safe_send_text(sender_phone, _rdv_received_message(rdv_expense))


def handle_rdv_text_message(sender_phone: str, text: str) -> str | None:
    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        return (
            "Seu telefone ainda nao esta cadastrado no RDV da Ciclus Agro. "
            "Procure o responsavel pelo cadastro."
        )

    normalized = _normalize_caption(text)
    if (
        whatsapp_menu_states.get(sender_phone) == RDV_WAITING_RECEIPT_STATE
        and normalized in {"cancelar", "sair"}
    ):
        whatsapp_menu_states.pop(sender_phone, None)
        return RDV_RECEIPT_CANCEL_MESSAGE

    rdv_service.cancel_legacy_km_launches_by_phone(sender_phone)
    global_command_handled, global_reply = _handle_global_rdv_command(
        sender_phone,
        collaborator,
        normalized,
    )
    if global_command_handled:
        return global_reply

    if normalized in MENU_OPEN_COMMANDS:
        send_main_menu_interactive(sender_phone)
        return None

    if normalized == "relatorios":
        send_reports_menu_interactive(sender_phone)
        return None

    open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)
    pending = rdv_service.get_open_launch_by_phone(sender_phone)

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

    km_flow_reply = _route_km_message(sender_phone, collaborator, text, normalized, open_km)
    if km_flow_reply is not None:
        return km_flow_reply

    open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)

    visita_handled, visita_reply = handle_visitas_text_message(
        sender_phone,
        text,
        collaborator,
        normalized,
    )
    if visita_handled:
        return visita_reply

    if pending is None:
        if normalized in {"meu resumo", "meuresumo", "individual"}:
            return _monthly_summary_message(collaborator["id"])
        if normalized in {"rdv", "despesa"}:
            whatsapp_menu_states[sender_phone] = RDV_WAITING_RECEIPT_STATE
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
    open_visit = visitas_service.obter_visita_aberta(sender_phone)

    if normalized_text in VISITA_START_COMMANDS:
        visit = visitas_service.iniciar_visita(
            sender_phone,
            tecnico_nome=(collaborator or {}).get("nome"),
        )
        return True, "\n".join(
            [
                "Vamos iniciar uma visita técnica.",
                "Qual o nome da fazenda ou propriedade visitada?",
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

    if open_visit is None:
        return False, None

    if normalized_text == "fechar visita":
        if visitas_service.existem_fotos_pendentes(open_visit["id"]):
            return True, VISITA_FOTO_PENDENTE_MESSAGE
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_resumo_final_message(open_visit["id"])

    if normalized_text == "cancelar visita":
        visitas_service.cancelar_visita(open_visit["id"])
        return True, "Visita cancelada com sucesso."

    if normalized_text in {"cancelar", "sair"}:
        visitas_service.cancelar_visita(open_visit["id"])
        return True, "Visita cancelada com sucesso."

    state = str(open_visit.get("estado_fluxo") or "")
    if state == "aguardando_descricao_visita":
        validation = validate_visit_field("descricao_visita", text)
        if not validation.ok:
            return True, validation.error
        saved = visitas_service.atualizar_campo(open_visit["id"], "descricao_visita", validation.value)
        visitas_service.atualizar_campo(saved["id"], "estado_fluxo", "aguardando_observacoes_gerais")
        return True, VISITA_OBSERVACOES_MESSAGE

    if state == "aguardando_observacoes_gerais":
        if normalized_text in VISITA_FINALIZAR_OBSERVACOES_COMMANDS:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "visita_aberta")
            return True, VISITA_OBSERVACOES_FINALIZADAS_MESSAGE
        validation = validate_visit_field("observacoes_gerais", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.adicionar_observacao_geral(open_visit["id"], validation.value)
        return True, "Observação salva. Envie outra observação ou finalize com: finalizar observações"

    if state == "aguardando_decisao_comentario_foto":
        pending = visitas_service.proxima_foto_pendente(open_visit["id"])
        if pending is None:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "visita_aberta")
            return True, "Fotos salvas no relatorio."
        if normalized_text in VISITA_FOTO_COMENTAR_COMMANDS:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_texto_comentario_foto")
            return True, f"Digite o comentario da Foto {pending.get('indice') or 1}:"
        if normalized_text in VISITA_FOTO_PULAR_COMMANDS:
            visitas_service.salvar_comentario_foto(pending["id"], "Sem comentario informado.")
            return True, _visita_proxima_foto_ou_finaliza(open_visit["id"])
        return True, "Responda 1 para comentar ou 2 para continuar sem comentario nesta foto."

    if state == "aguardando_texto_comentario_foto":
        pending = visitas_service.proxima_foto_pendente(open_visit["id"])
        if pending is None:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "visita_aberta")
            return True, "Fotos salvas no relatorio."
        validation = validate_visit_field("comentario_foto", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.salvar_comentario_foto(pending["id"], validation.value)
        return True, _visita_proxima_foto_ou_finaliza(open_visit["id"])

    if state == "aguardando_revisao_final":
        if normalized_text == "1":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "corrigindo_dados_propriedade")
            return True, _visita_corrigir_dados_message()
        if normalized_text == "2":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_edicao_descricao")
            return True, "Digite a nova descricao da visita:"
        if normalized_text == "3":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "corrigindo_observacoes")
            return True, _visita_corrigir_observacoes_message()
        if normalized_text == "4":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "corrigindo_comentario_foto")
            return True, _visita_corrigir_fotos_message(open_visit["id"])
        if normalized_text == "5":
            closed = visitas_service.fechar_visita(open_visit["id"])
            return True, _visita_fechada_message(closed)
        return True, _visita_resumo_final_message(open_visit["id"])

    if state == "corrigindo_dados_propriedade":
        fields = {
            "1": ("fazenda", "Digite a nova fazenda/propriedade:"),
            "2": ("proprietario", "Digite o novo proprietario:"),
            "3": ("telefone_proprietario", "Digite o novo telefone do proprietario:"),
            "4": ("gerente", "Digite o novo gerente/responsavel local:"),
            "5": ("telefone_gerente", "Digite o novo telefone do gerente:"),
            "6": ("area", "Digite a nova area/local visitado:"),
        }
        if normalized_text == "7":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_resumo_final_message(open_visit["id"])
        if normalized_text in fields:
            field, question = fields[normalized_text]
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", f"aguardando_edicao_campo:{field}")
            return True, question
        return True, _visita_corrigir_dados_message()

    if state.startswith("aguardando_edicao_campo:"):
        field = state.split(":", 1)[1]
        validation = validate_visit_field(field, text)
        if not validation.ok:
            return True, validation.error
        visitas_service.atualizar_campo(open_visit["id"], field, validation.value)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_resumo_final_message(open_visit["id"])

    if state == "aguardando_edicao_descricao":
        validation = validate_visit_field("descricao_visita", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.atualizar_campo(open_visit["id"], "descricao_visita", validation.value)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_resumo_final_message(open_visit["id"])

    if state == "corrigindo_observacoes":
        if normalized_text == "1":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_adicao_observacao")
            return True, "Digite a nova observacao geral:"
        if normalized_text == "2":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_remocao_observacao")
            return True, _visita_listar_observacoes_para_remover(open_visit)
        if normalized_text == "3":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_reescrita_observacoes")
            return True, "Digite todas as observacoes gerais. Cada linha sera salva como uma observacao separada:"
        if normalized_text == "4":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_resumo_final_message(open_visit["id"])
        return True, _visita_corrigir_observacoes_message()

    if state == "aguardando_adicao_observacao":
        validation = validate_visit_field("observacoes_gerais", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.adicionar_observacao_geral(open_visit["id"], validation.value)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_resumo_final_message(open_visit["id"])

    if state == "aguardando_remocao_observacao":
        observacoes = visitas_service.observacoes_gerais_lista(open_visit)
        try:
            index = int(normalized_text) - 1
        except ValueError:
            index = -1
        if 0 <= index < len(observacoes):
            observacoes.pop(index)
            visitas_service.substituir_observacoes_gerais(open_visit["id"], observacoes)
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_resumo_final_message(open_visit["id"])
        return True, _visita_listar_observacoes_para_remover(open_visit)

    if state == "aguardando_reescrita_observacoes":
        visitas_service.substituir_observacoes_gerais(open_visit["id"], text.splitlines())
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_resumo_final_message(open_visit["id"])

    if state == "corrigindo_comentario_foto":
        if normalized_text == "0":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_resumo_final_message(open_visit["id"])
        media = _visita_media_por_indice(open_visit["id"], normalized_text)
        if media is None:
            return True, _visita_corrigir_fotos_message(open_visit["id"])
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", f"aguardando_edicao_comentario_foto:{media['id']}")
        return True, f"Digite o novo comentario da Foto {media.get('indice') or 1}:"

    if state.startswith("aguardando_edicao_comentario_foto:"):
        media_id = int(state.split(":", 1)[1])
        validation = validate_visit_field("comentario_foto", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.salvar_comentario_foto(media_id, validation.value)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_resumo_final_message(open_visit["id"])
    if state in VISITA_FLOW_STEPS:
        field, next_question = VISITA_FLOW_STEPS[state]
        validation = validate_visit_field(field, text)
        if not validation.ok:
            return True, validation.error
        updates = {field: validation.value}
        next_state = _next_visita_state(state)
        updates["estado_fluxo"] = next_state
        saved = open_visit
        for update_field, update_value in updates.items():
            saved = visitas_service.atualizar_campo(saved["id"], update_field, update_value)
        if next_state == "aguardando_descricao_visita":
            return True, VISITA_DESCRICAO_MESSAGE
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
    open_visit = visitas_service.obter_visita_aberta(sender_phone)
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
    open_visit = visitas_service.obter_visita_aberta(sender_phone)
    if open_visit is None:
        return "Nenhuma visita em andamento encontrada."
    media = visitas_service.adicionar_midia(
        open_visit["id"],
        tipo="foto" if message_type == "image" else message_type,
        media_id_whatsapp=media_id,
        caminho_arquivo=file_path,
        legenda=caption,
    )
    if message_type == "image":
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_decisao_comentario_foto")
        pending = visitas_service.proxima_foto_pendente(open_visit["id"]) or media
        return _visita_foto_comentario_message(pending)
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
        "aguardando_telefone_proprietario",
        "aguardando_gerente",
        "aguardando_telefone_gerente",
        "aguardando_area",
        "aguardando_descricao_visita",
    )
    try:
        index = order.index(state)
    except ValueError:
        return "visita_aberta"
    if index + 1 >= len(order):
        return "visita_aberta"
    return order[index + 1]


def _normalize_optional_visit_value(value: str) -> str:
    normalized = _normalize_caption(value)
    if normalized in {"nao informado", "nao sei", "sem telefone", "nao tem"}:
        return "Nao informado"
    return str(value or "").strip()


def _visita_foto_comentario_message(media: dict) -> str:
    index = media.get("indice") or 1
    return "\n".join(
        [
            f"Foto {index} adicionada ao relatorio.",
            "",
            "Deseja adicionar um comentario para esta foto?",
            "",
            "1 - Sim, quero comentar",
            "2 - Nao, continuar sem comentario",
        ]
    )


def _visita_proxima_foto_ou_finaliza(visita_id: int) -> str:
    pending = visitas_service.proxima_foto_pendente(visita_id)
    if pending is not None:
        visitas_service.atualizar_campo(visita_id, "estado_fluxo", "aguardando_decisao_comentario_foto")
        return _visita_foto_comentario_message(pending)
    visitas_service.atualizar_campo(visita_id, "estado_fluxo", "visita_aberta")
    return "\n".join(
        [
            "Fotos salvas no relatorio.",
            "",
            "Voce pode continuar enviando fotos, adicionar mais informacoes ou finalizar a visita.",
            "",
            "Para finalizar, envie: fechar visita",
        ]
    )


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


def _visita_status_message(visita: dict) -> str:
    return "\n".join(
        [
            "Visita em andamento.",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Proprietário: {visita.get('proprietario') or '-'}",
            f"Gerente: {visita.get('gerente') or '-'}",
            f"Área/local: {visita.get('area') or '-'}",
            f"Descrição da visita: {visitas_service.descricao_da_visita(visita) or '-'}",
        ]
    )


def _visita_resumo_final_message(visita_id: int) -> str:
    resumo = visitas_service.obter_visita_completa(visita_id) or visitas_service.obter_visita(visita_id) or {}
    observacoes = visitas_service.observacoes_gerais_lista(resumo)
    midias = resumo.get("midias") or []
    lines = [
        "Resumo da visita técnica",
        "",
        "Dados da propriedade",
        f"Fazenda/propriedade: {resumo.get('fazenda') or '-'}",
        f"Proprietário: {resumo.get('proprietario') or '-'}",
        f"Telefone do proprietário: {resumo.get('telefone_proprietario') or '-'}",
        f"Gerente/responsável local: {resumo.get('gerente') or '-'}",
        f"Telefone do gerente: {resumo.get('telefone_gerente') or '-'}",
        f"Área/local visitado: {resumo.get('area') or '-'}",
        "",
        "Descrição da visita",
        visitas_service.descricao_da_visita(resumo) or "-",
        "",
        "Observações gerais",
    ]
    if observacoes:
        lines.extend(f"{index}. {item}" for index, item in enumerate(observacoes, start=1))
    else:
        lines.append("-")
    lines.extend(["", "Fotos da visita"])
    fotos = [media for media in midias if media.get("tipo") == "foto"]
    if fotos:
        for media in fotos:
            index = media.get("indice") or 1
            lines.extend(
                [
                    f"Foto {index}",
                    f"Comentário: {media.get('comentario') or 'Sem comentário informado.'}",
                    "",
                ]
            )
    else:
        lines.append("-")
    lines.extend(
        [
            "",
            "Deseja corrigir alguma informação antes de finalizar?",
            "",
            "1 - Corrigir dados da propriedade",
            "2 - Corrigir descrição da visita",
            "3 - Corrigir observações gerais",
            "4 - Corrigir comentários das fotos",
            "5 - Finalizar relatório",
        ]
    )
    return "\n".join(lines)


def _visita_corrigir_dados_message() -> str:
    return "\n".join(
        [
            "Qual informação deseja corrigir?",
            "",
            "1 - Fazenda/propriedade",
            "2 - Proprietário",
            "3 - Telefone do proprietário",
            "4 - Gerente/responsável local",
            "5 - Telefone do gerente",
            "6 - Área/local visitado",
            "7 - Voltar",
        ]
    )


def _visita_corrigir_observacoes_message() -> str:
    return "\n".join(
        [
            "Como deseja corrigir as observações?",
            "",
            "1 - Adicionar nova observação",
            "2 - Remover uma observação",
            "3 - Reescrever todas as observações",
            "4 - Voltar",
        ]
    )


def _visita_listar_observacoes_para_remover(visita: dict) -> str:
    observacoes = visitas_service.observacoes_gerais_lista(visita)
    lines = ["Qual observação deseja remover?", ""]
    if observacoes:
        lines.extend(f"{index} - {item}" for index, item in enumerate(observacoes, start=1))
    else:
        lines.append("Nenhuma observação geral registrada.")
    return "\n".join(lines)


def _visita_corrigir_fotos_message(visita_id: int) -> str:
    resumo = visitas_service.obter_visita_completa(visita_id) or {}
    fotos = [media for media in resumo.get("midias") or [] if media.get("tipo") == "foto"]
    lines = ["Qual comentário de foto deseja corrigir?", ""]
    if fotos:
        for media in fotos:
            comment = media.get("comentario") or "Sem comentário informado."
            lines.append(f"{media.get('indice') or 1} - Foto {media.get('indice') or 1} - {comment}")
    else:
        lines.append("Nenhuma foto registrada.")
    lines.append("0 - Voltar")
    return "\n".join(lines)


def _visita_media_por_indice(visita_id: int, indice_texto: str) -> dict | None:
    if indice_texto == "0":
        visitas_service.atualizar_campo(visita_id, "estado_fluxo", "aguardando_revisao_final")
        return None
    try:
        indice = int(indice_texto)
    except ValueError:
        return None
    resumo = visitas_service.obter_visita_completa(visita_id) or {}
    for media in resumo.get("midias") or []:
        if media.get("tipo") == "foto" and int(media.get("indice") or 0) == indice:
            return media
    return None


def _visita_fechada_message(visita: dict) -> str:
    resumo = visitas_service.visita_resumo(visita["id"])
    fotos = len(resumo.get("midias") or [])
    localizacoes = len(resumo.get("localizacoes") or [])
    return "\n".join(
        [
            "Visita fechada com sucesso.",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Proprietario: {visita.get('proprietario') or '-'}",
            f"Gerente: {visita.get('gerente') or '-'}",
            f"Area/local: {visita.get('area') or '-'}",
            f"Fotos: {fotos}",
            f"Localizacoes: {localizacoes}",
            "",
            "Comandos disponiveis:",
            "relatorio visita",
            "planilha visitas",
            "localizacao visita",
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
    return normalized_text in report_aliases(handler="visit_list")


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
            "Para gerar PDF individual de uma visita, envie:",
            f"relatório visita {visitas[0]['id']}",
            "",
        ]
    )
    lines.extend(
        [
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
    if normalized_text in report_aliases(report_id="menu_visit_excel"):
        return True
    return re.fullmatch(r"planilha visitas(?:\s+.+)?", normalized_text) is not None


def _is_relatorio_visita_command(normalized_text: str) -> bool:
    return parse_visit_report_command(normalized_text) is not None


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
    command = parse_visit_report_command(normalized_text)
    if command is None or command.kind != "by_id" or command.visita_id is None:
        return False
    visita = _select_visita_for_pdf(command.visita_id)
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
    command = parse_visit_report_command(normalized_text, text)
    if command is None:
        return None

    if command.kind == "by_fazenda":
        query = command.fazenda_query
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

    if command.kind == "by_id" and command.visita_id is not None:
        visita = _select_visita_for_pdf(command.visita_id)
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
    return _multiple_visitas_report_message(visitas)


def _select_visita_for_pdf(visita_id: int) -> dict | None:
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


def _multiple_fazenda_visitas_message(query: str, visitas: list[dict]) -> str:
    lines = [f'Encontrei mais de uma visita para "{query}":', ""]
    for visita in visitas[:10]:
        lines.extend(_format_visita_list_item(visita, detailed=True))
        lines.append("")
    lines.extend(["Escolha uma pelo ID:", f"relatório visita {visitas[0]['id']}"])
    return "\n".join(lines)


def _multiple_visitas_report_message(visitas: list[dict]) -> str:
    lines = [
        "Existem várias visitas técnicas registradas.",
        "Escolha uma pelo ID:",
        "",
    ]
    for visita in visitas[:10]:
        lines.extend(_format_visita_list_item(visita, detailed=True))
        lines.append("")
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


def _route_km_message(
    sender_phone: str,
    collaborator: dict,
    text: str,
    normalized_text: str,
    open_km: dict | None,
) -> str | None:
    menu_state = whatsapp_menu_states.get(sender_phone)
    if menu_state == "km_menu":
        if normalized_text in {"1", "iniciar", "iniciar viagem", "inicio", "km inicio"}:
            whatsapp_menu_states[sender_phone] = "km_waiting_start"
            return "Informe o KM inicial do veiculo:"
        if normalized_text in {"2", "finalizar", "finalizar viagem", "fim", "termino", "km termino"}:
            whatsapp_menu_states[sender_phone] = "km_waiting_end"
            return "Informe o KM final do veiculo:"
        return KM_MENU_MESSAGE

    if menu_state == "km_waiting_start":
        km_value = _parse_km_value(text)
        if km_value is None:
            return "Quilometragem invalida. Informe somente o KM inicial."
        whatsapp_menu_states.pop(sender_phone, None)
        return _start_km_trip(sender_phone, collaborator, km_value)

    if menu_state == "km_waiting_end":
        km_value = _parse_km_value(text)
        if km_value is None:
            return "Quilometragem invalida. Informe somente o KM final."
        whatsapp_menu_states.pop(sender_phone, None)
        return _finish_km_trip(sender_phone, km_value)

    if open_km is None:
        return None

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
    return None


def _start_km_trip(sender_phone: str, collaborator: dict, km_value: float) -> str:
    open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)
    if open_km is not None:
        return _open_trip_message(open_km)
    started = rdv_service.create_whatsapp_km_launch(
        collaborator_id=collaborator["id"],
        phone=sender_phone,
        km_start=km_value,
    )
    return "\n".join(
        [
            f"KM inicial: {_format_km_text(started['km_inicio'])}",
            "Qual a cidade/local de origem?",
        ]
    )


def _finish_km_trip(sender_phone: str, km_value: float) -> str:
    open_km = rdv_service.get_open_km_launch_by_phone(sender_phone)
    if open_km is None:
        return _no_open_trip_message()
    if open_km.get("status_fluxo") == "aguardando_km_origem":
        return "Antes de finalizar, informe a cidade/local de origem da viagem."
    if open_km.get("status_fluxo") == "aguardando_km_destino":
        return "Antes de finalizar, informe a cidade/local de destino da viagem."
    km_start = float(open_km.get("km_inicio") or 0)
    if km_value <= km_start:
        return (
            "A quilometragem final deve ser maior que a inicial. "
            "A viagem continua em andamento."
        )
    completed = rdv_service.complete_km_end(open_km["id"], km_value)
    return "\n".join(
        [
            "Viagem finalizada com sucesso.",
            f"Origem: {completed.get('cidade_origem') or '-'}",
            f"Destino: {completed.get('cidade_destino') or '-'}",
            f"KM inicial: {_format_km_text(completed['km_inicio'])}",
            f"KM final: {_format_km_text(completed['km_fim'])}",
            f"KM rodado: {_format_km_text(completed['km_rodado'])} km",
        ]
    )


def _is_rdv_excel_command(text: str) -> bool:
    request = _parse_rdv_report_command(_normalize_caption(text))
    return request is not None and request["kind"] == "excel"


def _is_rdv_pdf_command(text: str) -> bool:
    request = _parse_rdv_report_command(_normalize_caption(text))
    return request is not None and request["kind"] == "pdf"


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

    if report_request is not None and report_request["kind"] == "pdf":
        try:
            if report_request["period"] == "week":
                _send_weekly_rdv_pdf(sender_phone, week=report_request["reference"])
            else:
                _send_monthly_rdv_pdf(sender_phone, month=report_request["reference"])
        except Exception as exc:
            logger.exception(
                "Falha ao enviar PDF RDV pelo WhatsApp: to=%s erro=%s",
                _mask_phone(sender_phone),
                _safe_exception_summary(exc),
            )
            return True, _rdv_document_fallback_message()
        return True, None

    km_command = _parse_km_command(normalized_text)
    if km_command is not None:
        action, raw_value = km_command
        if action == "menu":
            whatsapp_menu_states[sender_phone] = "km_menu"
            return True, KM_MENU_MESSAGE
        if action == "start_prompt":
            whatsapp_menu_states[sender_phone] = "km_waiting_start"
            return True, "Informe o KM inicial do veiculo:"
        if action == "end_prompt":
            whatsapp_menu_states[sender_phone] = "km_waiting_end"
            return True, "Informe o KM final do veiculo:"
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
        whatsapp_menu_states.pop(sender_phone, None)
        if action == "start":
            return True, _start_km_trip(sender_phone, collaborator, km_value)
        return True, _finish_km_trip(sender_phone, km_value)

    return False, None


def _parse_km_command(normalized_text: str) -> tuple[str, str] | None:
    if normalized_text in {"km", "registrar km", "odometro"}:
        return "menu", ""
    if normalized_text in {"iniciar viagem"}:
        return "start_prompt", ""
    if normalized_text in {"finalizar viagem"}:
        return "end_prompt", ""

    patterns = (
        ("start", r"^(?:km inicio|km inicial|inicio km|iniciar km|iniciar viagem|odometro)(?:\s+(.*))?$"),
        ("end", r"^(?:km termino|km fim|km final|fim km|finalizar km|finalizar viagem)(?:\s+(.*))?$"),
    )
    for action, pattern in patterns:
        match = re.fullmatch(pattern, normalized_text)
        if match:
            return action, str(match.group(1) or "").strip()
    return None


def _is_standalone_number(text: str) -> bool:
    return re.fullmatch(r"\d+(?:[.,]\d+)?", str(text or "").strip()) is not None


def _parse_rdv_report_command(normalized_text: str) -> dict | None:
    return parse_rdv_report_command(normalized_text, today=date.today())


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


def _send_monthly_rdv_pdf(sender_phone: str, month: str = "") -> None:
    selected_month = month or calculate_month_reference(date.today())
    report_data = rdv_service.monthly_report_data(month=selected_month)
    content = build_monthly_rdv_pdf(report_data)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=RDV_MONTHLY_PDF_FILENAME,
        caption=RDV_MONTHLY_PDF_CAPTION,
        mime_type=RDV_PDF_MIME_TYPE,
    )


def _send_weekly_rdv_pdf(sender_phone: str, week: str = "") -> None:
    selected_week = week or calculate_week_reference(date.today())
    report_data = rdv_service.weekly_report_data(week=selected_week)
    content = build_weekly_rdv_pdf(report_data)
    send_whatsapp_document(
        sender_phone,
        content,
        filename=RDV_WEEKLY_PDF_FILENAME,
        caption=RDV_WEEKLY_PDF_CAPTION,
        mime_type=RDV_PDF_MIME_TYPE,
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


def _rdv_document_fallback_message() -> str:
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
    analysis: dict | None = None,
) -> dict:
    existing = rdv_service.get_by_whatsapp_message_id(whatsapp_message_id)
    if existing is not None:
        return existing

    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        raise ValueError("Remetente nao cadastrado como colaborador RDV.")

    input_type = message_type if message_type in {"image", "document"} else "document"
    input_type = {"image": "imagem", "document": "documento"}[input_type]
    analysis = analysis or _analyze_rdv_receipt_file(caminho_arquivo, whatsapp_message_id)
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


def _analyze_rdv_receipt_file(caminho_arquivo: str, whatsapp_message_id: str = "") -> dict:
    try:
        return rdv_receipt_analysis_service.analyze_file(caminho_arquivo).to_dict()
    except Exception:
        logger.exception(
            "Falha controlada ao analisar comprovante RDV: message_id=%s",
            _mask_message_id(whatsapp_message_id),
        )
        return {}


def _analysis_has_receipt_evidence(analysis: dict | None) -> bool:
    analysis = analysis or {}
    if any(
        str(analysis.get(field) or "").strip()
        for field in ("qr_code_text", "qr_code_url", "chave_acesso")
    ):
        return True
    if analysis.get("valor_detectado") not in (None, ""):
        return True
    if any(
        str(analysis.get(field) or "").strip()
        for field in ("data_detectada", "fornecedor_detectado")
    ):
        return True
    reasons = {str(reason or "").strip() for reason in analysis.get("reasons") or []}
    return bool(
        reasons
        & {
            "qr_code_detectado",
            "url_fiscal_encontrada",
            "chave_acesso_encontrada",
            "marcador_comprovante_encontrado",
        }
    )


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
    if str(message.get("type") or "") == "interactive":
        return _extract_interactive_command(message)
    text = message.get("text") or {}
    return str(text.get("body") or "").strip()


def _extract_interactive_command(message: dict) -> str:
    reply_id = _extract_interactive_reply_id(message)
    if reply_id in INTERACTIVE_COMMAND_IDS:
        return INTERACTIVE_COMMAND_IDS[reply_id]

    interactive = message.get("interactive") or {}
    if not isinstance(interactive, dict):
        return ""
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    if not isinstance(reply, dict):
        return ""
    title = str(reply.get("title") or "").strip()
    return title


def _extract_interactive_reply_id(message: dict) -> str:
    interactive = message.get("interactive") or {}
    if not isinstance(interactive, dict):
        return ""

    button_reply = interactive.get("button_reply") or {}
    if isinstance(button_reply, dict):
        reply_id = str(button_reply.get("id") or "").strip()
        if reply_id:
            return reply_id

    list_reply = interactive.get("list_reply") or {}
    if isinstance(list_reply, dict):
        return str(list_reply.get("id") or "").strip()

    return ""


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


def _send_rdv_reply(to: str, command_text: str, reply: str) -> None:
    normalized = _normalize_caption(command_text)
    try:
        if normalized in MENU_OPEN_COMMANDS and reply == MAIN_MENU_MESSAGE:
            send_main_menu_interactive(to)
            return
        if normalized == "relatorios" and reply == REPORTS_MENU_MESSAGE:
            send_reports_menu_interactive(to)
            return
        if normalized in KM_CLEAR_REQUEST_COMMANDS and reply == KM_CLEAR_WARNING:
            send_confirmation_buttons(
                to,
                KM_CLEAR_WARNING,
                confirm_id="confirm_clear_km",
                confirm_title="Limpar KM",
            )
            return
    except Exception:
        logger.exception(
            "Falha ao enviar mensagem interativa; usando fallback texto para %s",
            _mask_phone(to),
        )

    _safe_send_text(to, reply)


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
