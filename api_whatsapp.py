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
    parse_receipt_date,
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
from services.audio_transcription_service import (
    AUDIO_TOO_LONG_MESSAGE,
    TRANSCRIPTION_FAILED_MESSAGE,
    AudioLimitExceededError,
    AudioTranscriptionService,
    whisper_enabled_from_env,
)
from services.assistente_inteligente_service import (
    AssistenteInteligenteService,
    AssistenteRequest,
)
from services.audio_transcription_review_service import (
    AudioTranscriptionReviewService,
    ReviewedTranscription,
)
from services.audio_transcription_intelligence_service import (
    AudioTranscriptionIntelligenceService,
    IntelligentTranscriptionResult,
    transcription_review_default_mode,
)
from services.visita_summary_service import (
    VisitaSummary,
    VisitaSummaryResult,
    VisitaSummaryService,
)
from services.visita_summary_llm_adapter import VisitaSummaryLlmAdapter
from services.report_catalog import (
    interactive_report_commands,
    parse_rdv_report_command,
    report_aliases,
    report_menu_sections,
)
from services.visitas_excel_service import build_visitas_workbook
from services.visitas_pdf_service import build_visita_pdf
from services.visita_media_service import (
    VideoLimitReachedError,
    VideoTooLargeError,
    VideoUploadError,
    VisitaMediaService,
    video_max_mb,
    video_max_per_visita,
    video_max_seconds,
)
from services.object_storage_service import ObjectStorageError, delete_file as delete_storage_file
from services.visita_report_commands import parse_visit_report_command
from services.visita_validation import (
    split_visit_observation,
    validate_visit_field,
    visita_observacao_total_max_chars,
)
from services.visitas_service import VisitasTecnicasService, normalize_phone, _now
from services.visita_summary_service import _env_flag
from services.whatsapp_meta_client import send_payload as send_meta_whatsapp_payload
from services.whatsapp_meta_error_service import WhatsAppSendError


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
VISITA_START_COMMANDS = {"visita", "iniciar visita"}
VISITA_NEW_COMMANDS = {"nova visita", "iniciar nova visita", "outra visita"}
VISITA_EDITABLE_FIELDS = {
    "fazenda": "Fazenda",
    "proprietario": "Proprietário",
    "gerente": "Gerente/responsável",
    "localizacao_texto": "Localização da fazenda/propriedade",
    "area": "Tamanho total da fazenda/propriedade",
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
    "aguardando_gerente": ("gerente", "Qual a localização da fazenda/propriedade?"),
    "aguardando_localizacao": ("localizacao_texto", "Qual o tamanho total da fazenda/propriedade?"),
    "aguardando_area": ("area", "Qual a safra?"),
    "aguardando_safra": ("safra", "Qual o tipo de visita?"),
    "aguardando_tipo_visita": ("tipo_visita", ""),
}
VISITA_FLOW_STEPS = {
    "aguardando_fazenda": ("fazenda", "Qual o nome do proprietario da fazenda/propriedade?"),
    "aguardando_proprietario": ("proprietario", "Qual o telefone do proprietario?"),
    "aguardando_telefone_proprietario": ("telefone_proprietario", "Qual o nome do gerente ou responsavel local pela propriedade?"),
    "aguardando_gerente": ("gerente", "Qual o telefone do gerente ou responsavel local?"),
    "aguardando_telefone_gerente": ("telefone_gerente", "Envie a localizacao da fazenda/propriedade."),
    "aguardando_localizacao": ("localizacao_texto", "Qual e o tamanho total da fazenda/propriedade?\n\nExemplos:\n500 hectares\n120 alqueires\n35 hectares\nNao sei\nPular"),
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
    "aguardando_telefone_gerente": ("telefone_gerente", "📍 Envie a localização da fazenda/propriedade.\n\nVocê pode:\n- Compartilhar a localização pelo WhatsApp\n- Enviar um link do Google Maps\n- Digitar o endereço ou referência\n- Digitar \"pular\" se não tiver essa informação agora"),
    "aguardando_localizacao": ("localizacao_texto", "📏 Qual a área total da fazenda?\n\nExemplos:\n500 hectares\n120 alqueires\n35 hectares\nPular"),
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
        "Você pode responder digitando o texto ou enviando um áudio.",
        "Se enviar áudio, o sistema fará a transcrição automaticamente.",
        "",
        "Digite agora a descrição da visita:",
    ]
)
VISITA_OBSERVACOES_MESSAGE = "\n".join(
    [
        "📝 Observações adicionais",
        "",
        "Use este campo para registrar detalhes importantes que não entraram nas perguntas anteriores, por exemplo:",
        "",
        "- tamanho de plantações específicas;",
        "- se a plantação é pequena ou apenas para consumo dos animais;",
        "- tamanho da área onde fica o combustível;",
        "- detalhes sobre barracões, irrigação, pasto, máquinas ou estrutura;",
        "- qualquer ponto relevante para o relatório.",
        "",
        "Você pode responder por texto ou áudio.",
        "Se não houver observações, digite \"pular\".",
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
    "pular",
    "nao sei",
    "sem informacao",
}
VISITA_FOTO_COMENTAR_COMMANDS = {"1", "sim", "s", "comentar"}
VISITA_FOTO_PULAR_COMMANDS = {"2", "nao", "pular", "sem comentario"}
VISITA_CLOSE_COMMANDS = {"fechar visita", "finalizar visita", "encerrar visita"}
VISITA_REVIEW_FINALIZE_COMMANDS = {
    "1",
    "finalizar",
    "finalizar visita",
    "confirmar finalizacao",
    "concluir visita",
}
VISITA_REVIEW_PREVIEW_COMMANDS = {
    "5",
    "previa",
    "previa relatorio",
    "gerar previa",
    "relatorio",
    "gerar relatorio",
    "relatorio visita",
    "relatorio da visita",
}
VISITA_REVIEW_MEDIA_OPTION_COMMANDS = {
    "midia",
    "midias",
    "enviar midia",
    "enviar midias",
    "enviar foto",
    "enviar video",
    "localizacao",
}
VISITA_REVIEW_DELETE_PHOTO_COMMANDS = {"6", "apagar foto", "excluir foto", "remover foto"}
VISITA_REVIEW_DELETE_VIDEO_COMMANDS = {"7", "apagar video", "apagar vídeo", "excluir video", "excluir vídeo", "remover video", "remover vídeo"}
VISITA_REVIEW_BACK_COMMANDS = {"8", "voltar", "voltar sem finalizar"}
VISITA_REVIEW_CANCEL_COMMANDS = {"cancelar", "voltar"}
VISITA_REVIEW_CONFIRM_DELETE_COMMANDS = {"1", "sim", "s", "confirmar"}
VISITA_REVIEW_DENY_DELETE_COMMANDS = {"2", "nao", "não", "n", "cancelar"}
VISITA_REVIEW_MEDIA_GUIDANCE_MESSAGE = "\n".join(
    [
        "Envie a foto, o vídeo ou a localização agora.",
        "",
        "Depois de anexar, a prévia anterior pode ficar desatualizada.",
        "Digite \"prévia\" para gerar o relatório atualizado antes de finalizar.",
    ]
)
VISITA_CLOSED_MEDIA_MESSAGE = "\n".join(
    [
        "⚠️ Esta visita já foi finalizada.",
        "",
        "Para anexar novas fotos ou vídeos, inicie uma nova visita técnica ou registre uma nova visita complementar.",
    ]
)
MENU_OPEN_COMMANDS = {"menu", "iniciar", "inicio", "ajuda", "oi", "ola", "voltar"}
STANDALONE_TRANSCRIPTION_COMMANDS = {
    "transcrever audio",
    "transcricao de audio",
    "transcricao audio",
}
STANDALONE_TRANSCRIPTION_EXIT_COMMANDS = {
    "cancelar",
    "sair",
    "menu",
    "inicio",
    "voltar",
}
STANDALONE_TRANSCRIPTION_STATE = "audio_transcription_waiting"
STANDALONE_TRANSCRIPTION_MODE_STATE = "audio_transcription_select_mode"
VISITA_AUDIO_REVIEW_CONTEXT_BY_STATE = {
    "aguardando_descricao_visita": "visita_descricao",
    "aguardando_edicao_descricao": "visita_descricao",
    "aguardando_observacoes_gerais": "visita_observacao",
    "aguardando_adicao_observacao": "visita_observacao",
    "aguardando_reescrita_observacoes": "visita_observacao",
}
STANDALONE_TRANSCRIPTION_PROMPT = "\n".join(
    [
        "Como você quer receber a transcrição?",
        "",
        "1. Literal",
        "2. Revisada",
        "",
        "Digite o número da opção.",
    ]
)
STANDALONE_TRANSCRIPTION_INVALID_MODE_PROMPT = "\n".join(
    [
        "Escolha uma opção válida:",
        "",
        "1. Literal",
        "",
        "2. Revisada",
    ]
)
STANDALONE_TRANSCRIPTION_AUDIO_PROMPT = (
    "Envie um áudio do WhatsApp que eu vou transcrever para texto.\n\n"
    "Para cancelar, digite cancelar."
)
STANDALONE_TRANSCRIPTION_TEXT_PROMPT = (
    "Envie um áudio para transcrever ou digite menu para voltar."
)
INTERACTIVE_COMMAND_IDS = {
    "menu_rdv_receipt": "rdv",
    "menu_km": "km",
    "menu_visit_start": "visita",
    "menu_audio_transcription": "transcrever audio",
    "menu_reports": "relatorios",
    "menu_help": "menu",
    "confirm_clear_km": "confirmar limpar km",
    "cancel_action": "menu",
    "confirm_visit_close": "confirmar",
    "cancel_visit_review": "cancelar",
    "visita_revisao_finalizar": "1",
    "visita_revisao_corrigir_dados": "2",
    "visita_revisao_corrigir_descricao": "3",
    "visita_revisao_corrigir_observacoes": "4",
    "visita_revisao_previa": "5",
    "visita_revisao_apagar_foto": "6",
    "visita_revisao_apagar_video": "7",
    "visita_revisao_voltar": "8",
    "visita_apagar_foto_cancelar": "cancelar",
    "visita_apagar_video_cancelar": "cancelar",
    "visita_confirmar_apagar_midia_sim": "sim",
    "visita_confirmar_apagar_midia_nao": "nao",
    "rdv_review_confirm": "1",
    "rdv_review_edit_value": "2",
    "rdv_review_edit_date": "3",
    "rdv_review_edit_category": "4",
    "rdv_review_edit_comment": "5",
    "rdv_review_cancel": "6",
    "menu_assistente_inteligente": "assistente",
}
INTERACTIVE_COMMAND_IDS.update(interactive_report_commands())
# Assistente Inteligente Ciclus (Módulo 1): estado exclusivo, simulado, desligado.
ASSISTENTE_INTELIGENTE_COMMANDS = {"assistente", "assistente inteligente"}
ASSISTENTE_INTELIGENTE_EXIT_COMMANDS = {"sair", "menu", "cancelar", "voltar"}
ASSISTENTE_INTELIGENTE_ENTRY_BLOCKED_MESSAGE = (
    "⚠️ Você possui uma operação em andamento.\n\n"
    "Conclua a operação atual ou envie *cancelar* para encerrá-la antes de abrir o Assistente Inteligente."
)
ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE = (
    "🤖 *Assistente Inteligente Ciclus*\n\n"
    "Modo de teste ativado.\n\n"
    "Envie uma pergunta em texto para validar o novo canal.\n"
    "Para voltar ao sistema, envie *sair* ou *menu*."
)
ASSISTENTE_INTELIGENTE_SIMULATED_REPLY = (
    "🤖 Recebi sua pergunta.\n\n"
    "O canal do Assistente Inteligente está funcionando. A integração com as consultas da Ciclus será adicionada na próxima etapa.\n\n"
    "Para voltar ao menu, envie *sair*."
)
ASSISTENTE_INTELIGENTE_MEDIA_REPLY = (
    "🤖 Nesta primeira versão, o Assistente Inteligente aceita apenas mensagens de texto.\n\n"
    "Envie sua pergunta em texto ou envie *sair* para voltar ao menu."
)
ASSISTENTE_INTELIGENTE_EXIT_MESSAGE = (
    "✅ Assistente Inteligente encerrado.\n"
    "Você voltou ao menu principal."
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

# Product navigation intentionally exposes only visits and standalone audio.
# RDV/KM/document implementations remain available internally, but are not
# advertised in the normal flow.
MAIN_MENU_MESSAGE = "\n".join(
    [
        "🌱 Ciclus Agro",
        "",
        "Escolha uma opção para continuar:",
        "",
        "1. Nova visita técnica",
        "2. Transcrever áudio",
    ]
)
REPORTS_MENU_MESSAGE = "\n".join(
    [
        "Relatórios de visitas disponíveis:",
        "",
        "* planilha visitas — planilha com todas as visitas/fazendas registradas",
        "* fazendas visitadas — atalho para a planilha de visitas",
        "* visitas — lista visitas/fazendas registradas",
        "* visitas abertas — lista visitas abertas da equipe",
        "* ver visita 12 — mostra dados da visita",
        "* editar visita 12 — corrige dados da visita",
        "* relatório visita 12 — gera PDF pelo ID da visita",
        "* relatório fazenda Nome da Fazenda — busca relatório pelo nome",
        "* localização visita 12 — mostra GPS de uma visita pelo ID",
    ]
)
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
RDV_REVIEW_CONFIRM_STATE = "rdv_review_confirm"
RDV_REVIEW_EDIT_VALUE_STATE = "rdv_review_edit_value"
RDV_REVIEW_EDIT_DATE_STATE = "rdv_review_edit_date"
RDV_REVIEW_EDIT_CATEGORY_STATE = "rdv_review_edit_category"
RDV_REVIEW_EDIT_COMMENT_STATE = "rdv_review_edit_comment"
INVALID_RDV_RECEIPT_MESSAGE = (
    "Não consegui identificar esse arquivo como comprovante.\n\n"
    "Envie uma foto ou PDF legível de nota, cupom, recibo ou comprovante.\n"
    "Se preferir cancelar, digite cancelar."
)
RDV_RECEIPT_CANCEL_MESSAGE = "Lançamento de comprovante cancelado."
VISITA_VIDEO_NO_OPEN_MESSAGE = (
    "\U0001f3a5 Recebi um v\u00eddeo, mas ainda n\u00e3o h\u00e1 uma visita t\u00e9cnica em andamento.\n"
    "Para anexar v\u00eddeos a um relat\u00f3rio, primeiro inicie uma visita t\u00e9cnica."
)
VISITA_VIDEO_UPLOAD_ERROR_MESSAGE = (
    "N\u00e3o consegui anexar esse v\u00eddeo \u00e0 visita agora. Tente novamente em instantes."
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
visita_media_service = VisitaMediaService()
whatsapp_menu_states: dict[str, str] = {}
visita_edit_states: dict[str, int] = {}
visita_active_states: dict[str, int] = {}
visita_new_visit_states: set[str] = set()
visita_recently_finalized_states: dict[str, int] = {}
rdv_comment_states: dict[str, dict] = {}
rdv_receipt_review_states: dict[str, dict] = {}
# Estado temporario (em memoria, sem persistencia) da confirmacao do resumo de
# visita gerado por IA a partir de um audio. Indexado pelo telefone normalizado.
visita_summary_confirmation_states: dict[str, dict] = {}
# Servico isolado de resumo de visita (flag VISITA_SUMMARY_ENABLED desligada por padrao).
_visita_summary_service = VisitaSummaryService(VisitaSummaryLlmAdapter())
_audio_transcription_service: AudioTranscriptionService | None = None
_audio_transcription_review_service = AudioTranscriptionReviewService()
_audio_transcription_intelligence_service = AudioTranscriptionIntelligenceService(
    local_reviewer=_audio_transcription_review_service
)
standalone_transcription_modes: dict[str, str] = {}

# Estado exclusivo do Assistente Inteligente Ciclus (Módulo 1).
# Chaveado pelo telefone normalizado. Em memoria, sem persistencia.
# A sessão pode ser perdida apos o restart do servico (aceitavel no MVP).
assistente_inteligente_states: dict[str, dict] = {}

# Serviço isolado de conversa do Assistente Inteligente (Módulo 2A).
# O handler NÃO conhece o provider; só chama generate(request). Provider
# mock por padrão; nenhuma chamada externa ocorre nesta etapa.
_assistente_inteligente_service = AssistenteInteligenteService()


def _is_assistente_inteligente_enabled() -> bool:
    # Segue o padrao de _env_flag: ausencia da variavel => False.
    return _env_flag("ASSISTENTE_INTELIGENTE_ENABLED", False)


def _assistente_active(sender_phone: str) -> bool:
    phone = normalize_phone(sender_phone)
    if not phone:
        return False
    return bool((assistente_inteligente_states.get(phone) or {}).get("active"))


def _assistente_enter(sender_phone: str, collaborator: dict) -> None:
    phone = normalize_phone(sender_phone)
    if not phone:
        return
    assistente_inteligente_states[phone] = {
        "active": True,
        "collaborator_id": int((collaborator or {}).get("id") or 0),
    }


def _assistente_exit(sender_phone: str) -> None:
    phone = normalize_phone(sender_phone)
    if phone:
        assistente_inteligente_states.pop(phone, None)


def _has_operational_flow(sender_phone: str) -> bool:
    # Nao altera nenhum estado existente; apenas detecta conflito.
    phone = normalize_phone(sender_phone)
    if not phone:
        return False
    return (
        phone in visita_edit_states
        or phone in visita_active_states
        or phone in visita_new_visit_states
        or phone in rdv_comment_states
        or phone in rdv_receipt_review_states
        or phone in visita_summary_confirmation_states
        or phone in standalone_transcription_modes
        or whatsapp_menu_states.get(phone)
        in {STANDALONE_TRANSCRIPTION_MODE_STATE, STANDALONE_TRANSCRIPTION_STATE}
        or rdv_service.get_open_launch_by_phone(phone) is not None
        or rdv_service.get_open_km_launch_by_phone(phone) is not None
        or visitas_service.obter_visita_aberta(phone) is not None
    )


def _assistente_exit(sender_phone: str) -> None:
    phone = normalize_phone(sender_phone)
    if phone:
        assistente_inteligente_states.pop(phone, None)
        # Limpa o historico daquele usuario ao sair (nao afeta outros).
        try:
            _assistente_inteligente_service.clear_history(phone)
        except Exception:
            pass


def _handle_assistente_inteligente_message(sender_phone: str, text: str, normalized: str) -> str | None:
    # Chamado APENAS quando o Assistente ja esta ativo.
    # Intercepta antes dos fluxos de RDV/KM/visitas. Nunca chama API externa,
    # nao consulta banco alem da autorizacao e nao altera dados.
    if normalized in ASSISTENTE_INTELIGENTE_EXIT_COMMANDS:
        _assistente_exit(sender_phone)
        send_main_menu_interactive(sender_phone)
        return ASSISTENTE_INTELIGENTE_EXIT_MESSAGE
    # Encaminha o texto para o servico isolado de conversa (Modulo 2A).
    # O handler nao conhece o provider; em falha o servico devolve fallback.
    phone = normalize_phone(sender_phone) or sender_phone
    response = _assistente_inteligente_service.generate(
        AssistenteRequest(sender_key=phone, message=text)
    )
    if response is None or not str(getattr(response, "text", "") or "").strip():
        # Fallback seguro se o servico nao devolver texto.
        return ASSISTENTE_INTELIGENTE_SIMULATED_REPLY
    return str(response.text)


def _try_enter_assistente_inteligente(sender_phone: str, collaborator: dict) -> str | None:
    # Tenta ativar o Assistente (comando textual ou item de menu).
    # Nao entra se houver fluxo operacional em andamento.
    if not _is_assistente_inteligente_enabled():
        return None
    if _assistente_active(sender_phone):
        return None
    if _has_operational_flow(sender_phone):
        return ASSISTENTE_INTELIGENTE_ENTRY_BLOCKED_MESSAGE
    _assistente_enter(sender_phone, collaborator)
    return ASSISTENTE_INTELIGENTE_ENTRY_MESSAGE


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
    message_type = "text"
    recipient = str(to or "").strip()
    recipient_strategy = "destinatario via from/wa_id do webhook"
    if not recipient:
        raise RuntimeError("Destinatario WhatsApp nao informado.")

    _post_whatsapp_message_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": message_type,
            "text": {"body": message},
        },
        recipient,
        message_type,
    )
    logger.info(
        "Mensagem WhatsApp enviada com sucesso: to=%s type=%s estrategia=%s",
        _mask_phone(recipient),
        message_type,
        recipient_strategy,
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
    except WhatsAppSendError as exc:
        if not exc.fallback_allowed:
            raise
        logger.warning(
            "Falha permanente ao enviar lista interativa; usando fallback texto: to=%s category=%s",
            _mask_phone(to),
            exc.category,
        )
        send_whatsapp_text(to, fallback_text)


def send_rdv_review_menu_interactive(to: str, pending: dict) -> None:
    message = _rdv_review_message(pending)
    send_whatsapp_list_message(
        to=to,
        header="RDV",
        body=f"{message}\n\nToque no menu abaixo para confirmar ou editar.",
        button_text="Revisar RDV",
        sections=[
            {
                "title": "Revisao obrigatoria",
                "rows": [
                    {"id": "rdv_review_confirm", "title": "Confirmar e salvar"},
                    {"id": "rdv_review_edit_value", "title": "Editar valor"},
                    {"id": "rdv_review_edit_date", "title": "Editar data"},
                    {"id": "rdv_review_edit_category", "title": "Editar categoria"},
                    {"id": "rdv_review_edit_comment", "title": "Editar comentario"},
                    {"id": "rdv_review_cancel", "title": "Cancelar lancamento"},
                ],
            }
        ],
        fallback_text=_rdv_review_fallback_message(pending),
    )


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
    sections = [
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
                    "id": "menu_audio_transcription",
                    "title": "🎙️ Transcrever áudio",
                    "description": "Receber a transcrição em texto",
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
    ]
    sections[0]["rows"] = [
        {
            "id": "menu_visit_start",
            "title": "🌱 Nova visita técnica",
            "description": "Registrar fazenda visitada",
        },
        {
            "id": "menu_audio_transcription",
            "title": "🎙️ Transcrever áudio",
            "description": "Receber a transcrição em texto",
        },
    ]
    if _is_assistente_inteligente_enabled():
        sections[0]["rows"].append(
            {
                "id": "menu_assistente_inteligente",
                "title": "🤖 Assistente Inteligente",
                "description": "Conversar com a Ciclus",
            }
        )
    send_whatsapp_list_message(
        to=to,
        header="🌱 Ciclus Agro",
        body="Escolha uma opção para continuar:",
        button_text="Abrir menu",
        sections=sections,
        fallback_text=MAIN_MENU_MESSAGE,
    )


def send_reports_menu_interactive(to: str) -> None:
    sections = [
        section
        for section in report_menu_sections()
        if section.get("title") == "Visitas técnicas"
    ]
    send_whatsapp_list_message(
        to=to,
        header="Relatorios",
        body="Escolha qual relatorio deseja receber.",
        button_text="Ver relatorios",
        sections=sections,
        fallback_text=REPORTS_MENU_MESSAGE,
    )


def send_visita_review_menu_interactive(to: str, fallback_text: str | None = None) -> None:
    send_whatsapp_list_message(
        to=to,
        header="Revisar visita",
        body="\n".join(
            [
                "Prévia do relatório enviada.",
                "",
                "Revise os dados antes de finalizar a visita.",
                "Você ainda pode corrigir informações ou enviar mais fotos, vídeos e localização antes de finalizar.",
                "",
                "O que deseja fazer agora?",
            ]
        ),
        button_text="Revisar visita",
        sections=[
            {
                "title": "Revisão final",
                "rows": [
                    {"id": "visita_revisao_finalizar", "title": "Finalizar visita"},
                    {"id": "visita_revisao_corrigir_dados", "title": "Corrigir dados"},
                    {"id": "visita_revisao_corrigir_descricao", "title": "Corrigir descrição"},
                    {"id": "visita_revisao_corrigir_observacoes", "title": "Corrigir observações"},
                    {"id": "visita_revisao_previa", "title": "Gerar nova prévia"},
                    {"id": "visita_revisao_apagar_foto", "title": "Apagar foto"},
                    {"id": "visita_revisao_apagar_video", "title": "Apagar vídeo"},
                    {"id": "visita_revisao_voltar", "title": "Voltar sem finalizar"},
                ],
            },
        ],
        fallback_text=fallback_text or _visita_revisao_final_message(),
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
    send_meta_whatsapp_payload(
        payload,
        token=token,
        phone_number_id=phone_number_id,
        api_version=api_version,
        timeout=20,
        requests_module=requests,
        message_kind=message_type,
    )
    logger.info(
        "Mensagem WhatsApp enviada via cliente Meta: to=%s type=%s",
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
    _post_whatsapp_message_payload(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {
                "id": media_id,
                "caption": caption,
                "filename": filename,
            },
        },
        recipient,
        "document",
    )

    logger.info(
        "Excel RDV enviado pelo WhatsApp: to=%s",
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
    media = (
        message.get(message_type)
        if message_type in ("image", "document", "audio", "voice", "video")
        else {}
    )
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

    # Contatos (contacts) - não processados em nenhum fluxo operacional.
    # Resposta explícita sem acessar dados do contato, sem baixar mídia,
    # sem chamar provider de IA, sem alterar estado.
    if message_type == "contacts":
        _safe_send_text(
            sender_phone,
            "📇 Recebi um contato, mas ainda não consigo processar esse tipo de mensagem. "
            "Envie sua pergunta em texto ou digite *sair* para voltar ao menu."
        )
        return

    # Assistente Inteligente ativo: intercepta TODA midia nao textual antes
    # dos handlers normais. Nao baixa a midia e nao toca visita/RDV/comprovante.
    if _assistente_active(sender_phone):
        _safe_send_text(sender_phone, ASSISTENTE_INTELIGENTE_MEDIA_REPLY)
        return

    if message_type == "location":
        reply = handle_visitas_location_message(sender_phone, message.get("location") or {})
        if reply:
            _safe_send_text(sender_phone, reply)
            return

    if message_type in {"audio", "voice"}:
        standalone_mode = _is_standalone_transcription_session(sender_phone)
        reply = handle_whatsapp_audio_message(
            sender_phone=sender_phone,
            media_id=media_id,
            mime_type=mime_type,
        )
        if reply:
            if standalone_mode:
                _safe_send_text_chunks(sender_phone, reply)
            else:
                _safe_send_text(sender_phone, reply)
        return

    if message_type == "video":
        reply = handle_visitas_video_message(
            sender_phone=sender_phone,
            media_id=media_id,
            mime_type=mime_type,
        )
        _safe_send_text(sender_phone, reply)
        return

    open_visit = visitas_service.obter_visita_aberta(sender_phone)
    if (
        open_visit is not None
        and _visita_state_accepts_media(open_visit)
        and message_type in ("image", "document")
        and not media_id
    ):
        _safe_send_text(sender_phone, "Nao consegui salvar essa midia da visita. Tente enviar novamente.")
        return

    if message_type not in ("image", "document") or not media_id:
        _safe_send_text(
            sender_phone,
            "Recebi sua mensagem, mas por enquanto consigo processar apenas imagem ou documento.",
        )
        return

    if open_visit is not None and _visita_state_accepts_media(open_visit):
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
    except AudioLimitExceededError as exc:
        logger.warning(
            "Audio RDV acima do limite: media_id=%s erro=%s",
            _mask_media_id(media_id),
            _safe_exception_summary(exc),
        )
        state["state"] = "awaiting_correction"
        return AUDIO_TOO_LONG_MESSAGE
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
        pending_review = _start_rdv_receipt_review(
            sender_phone=sender_phone,
            caminho_arquivo=str(downloaded_path),
            whatsapp_message_id=message_id,
            message_type=message_type,
            received_at=data_hora_recebimento,
            analysis=analysis,
        )
    except Exception:
        logger.exception(
            "Erro ao iniciar revisao do RDV recebido pelo WhatsApp: message_id=%s",
            _mask_message_id(message_id),
        )
        _safe_send_text(
            sender_phone,
            "Recebi o arquivo, mas nao consegui iniciar a revisao. Tente novamente.",
        )
        return
    logger.info(
        "Comprovante RDV aguardando revisao: from=%s message_id=%s fonte=%s",
        _mask_phone(sender_phone),
        _mask_message_id(message_id),
        pending_review.get("source"),
    )
    try:
        send_rdv_review_menu_interactive(sender_phone, pending_review)
    except WhatsAppSendError as exc:
        if not exc.fallback_allowed:
            raise
        logger.warning(
            "Falha permanente ao enviar menu de revisao RDV; usando texto: to=%s category=%s",
            _mask_phone(sender_phone),
            exc.category,
        )
        _safe_send_text(sender_phone, _rdv_review_fallback_message(pending_review))


def handle_rdv_text_message(
    sender_phone: str,
    text: str,
    *,
    is_audio_transcription: bool = False,
) -> str | None:
    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        return (
            "Seu telefone ainda nao esta cadastrado no RDV da Ciclus Agro. "
            "Procure o responsavel pelo cadastro."
        )

    normalized = _normalize_caption(text)

    # Intercepta a escolha do resumo de IA de visita (se houver confirmacao
    # pendente). Nao afeta RDV/comprovantes/avulso: o estado de confirmacao so
    # existe para audio de descricao/observacao de visita. Se nao houver estado
    # pendente, devolve None e o fluxo normal continua.
    summary_reply = _handle_visita_summary_confirmation(sender_phone, text)
    if summary_reply is not None:
        return summary_reply

    menu_state = whatsapp_menu_states.get(sender_phone)
    if menu_state in {
        STANDALONE_TRANSCRIPTION_MODE_STATE,
        STANDALONE_TRANSCRIPTION_STATE,
    }:
        if normalized in STANDALONE_TRANSCRIPTION_EXIT_COMMANDS:
            whatsapp_menu_states.pop(sender_phone, None)
            standalone_transcription_modes.pop(sender_phone, None)
            send_main_menu_interactive(sender_phone)
            return None
        if menu_state == STANDALONE_TRANSCRIPTION_MODE_STATE:
            selected_mode = {
                "1": "literal",
                "literal": "literal",
                "2": "revisada",
                "revisada": "revisada",
            }.get(normalized)
            if selected_mode is None:
                return STANDALONE_TRANSCRIPTION_INVALID_MODE_PROMPT
            standalone_transcription_modes[sender_phone] = selected_mode
            whatsapp_menu_states[sender_phone] = STANDALONE_TRANSCRIPTION_STATE
            return STANDALONE_TRANSCRIPTION_AUDIO_PROMPT
        return STANDALONE_TRANSCRIPTION_TEXT_PROMPT

    if normalized in STANDALONE_TRANSCRIPTION_COMMANDS:
        whatsapp_menu_states[sender_phone] = STANDALONE_TRANSCRIPTION_MODE_STATE
        standalone_transcription_modes.pop(sender_phone, None)
        return STANDALONE_TRANSCRIPTION_PROMPT

    if (
        menu_state == RDV_WAITING_RECEIPT_STATE
        and normalized in {"cancelar", "sair"}
    ):
        whatsapp_menu_states.pop(sender_phone, None)
        return RDV_RECEIPT_CANCEL_MESSAGE

    review_handled, review_reply = _handle_rdv_receipt_review_message(
        sender_phone,
        text,
        normalized,
        is_audio_transcription=is_audio_transcription,
    )
    if review_handled:
        return review_reply

    rdv_service.cancel_legacy_km_launches_by_phone(sender_phone)
    global_command_handled, global_reply = _handle_global_rdv_command(
        sender_phone,
        collaborator,
        normalized,
    )
    if global_command_handled:
        return global_reply

    if normalized in ASSISTENTE_INTELIGENTE_COMMANDS:
        assistant_reply = _try_enter_assistente_inteligente(sender_phone, collaborator)
        if assistant_reply is not None:
            return assistant_reply

    if _assistente_active(sender_phone):
        return _handle_assistente_inteligente_message(sender_phone, text, normalized)

    if normalized in MENU_OPEN_COMMANDS:
        active_visit = _get_active_visita_for_phone(sender_phone)
        if active_visit is not None:
            return _active_visita_menu_message(active_visit)
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
        is_audio_transcription=is_audio_transcription,
    )
    if visita_handled:
        return visita_reply

    comment_handled, comment_reply = handle_rdv_comment_text_message(
        sender_phone,
        text,
        normalized,
    )
    if comment_handled:
        return comment_reply

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
        return MAIN_MENU_MESSAGE

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
        lines = _rdv_completed_lines(completed)
        if _audio_transcription_enabled():
            _start_rdv_comment_state(sender_phone, completed["id"])
            lines.extend(
                [
                    "",
                    "Deseja adicionar comentario ao RDV?",
                    "Digite o comentario ou envie um audio.",
                    "Para deixar sem comentario, envie: 3",
                ]
            )
        else:
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


def _rdv_completed_lines(completed: dict) -> list[str]:
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
    return lines


def handle_rdv_comment_text_message(
    sender_phone: str,
    text: str,
    normalized: str | None = None,
) -> tuple[bool, str | None]:
    state = _get_rdv_comment_state(sender_phone)
    if state is None:
        return False, None

    normalized_text = normalized if normalized is not None else _normalize_caption(text)
    expense_id = int(state["expense_id"])
    current_state = str(state.get("state") or "")

    if current_state == "awaiting_audio_confirmation":
        if normalized_text == "1":
            saved = rdv_service.save_launch_observation(
                expense_id,
                str(state.get("text") or ""),
            )
            _clear_rdv_comment_state(sender_phone)
            return True, _rdv_comment_saved_message(saved)
        if normalized_text == "2":
            state["state"] = "awaiting_correction"
            return True, "Digite o comentario corrigido para salvar no RDV."
        if normalized_text == "3":
            _clear_rdv_comment_state(sender_phone)
            return True, "Comentario removido. O RDV ficou sem comentario adicional."
        return True, _rdv_transcription_confirmation_message(str(state.get("text") or ""))

    if current_state in {"awaiting_comment", "awaiting_correction"}:
        if normalized_text in {"3", "nao", "sem comentario", "remover"}:
            _clear_rdv_comment_state(sender_phone)
            return True, "Comentario removido. O RDV ficou sem comentario adicional."
        comment = str(text or "").strip()
        if not comment:
            return True, "Digite o comentario ou envie 3 para deixar sem comentario."
        saved = rdv_service.save_launch_observation(expense_id, comment)
        _clear_rdv_comment_state(sender_phone)
        return True, _rdv_comment_saved_message(saved)

    return False, None


def handle_rdv_audio_comment_message(
    sender_phone: str,
    media_id: str,
    mime_type: str = "",
) -> str:
    state = _get_rdv_comment_state(sender_phone)
    if state is None:
        if not _audio_transcription_enabled():
            return (
                "Recebi um audio, mas comentarios por audio ainda estao desativados. "
                "Digite o comentario em texto."
            )
        return (
            "Recebi um audio, mas nao ha RDV aguardando comentario agora. "
            "Finalize um comprovante antes de enviar audio de comentario."
        )

    if not _audio_transcription_enabled():
        state["state"] = "awaiting_correction"
        return (
            "Recebi um audio, mas a transcricao esta desativada. "
            "Voce pode digitar o comentario?"
        )

    if not media_id:
        state["state"] = "awaiting_correction"
        return "Nao consegui ler o audio recebido. Voce pode digitar o comentario?"

    destination = _build_audio_transcription_destination(
        sender_phone=sender_phone,
        media_id=media_id,
        mime_type=mime_type,
    )
    try:
        downloaded_path = download_media(media_id, destination)
        result = _transcribe_audio_with_result(downloaded_path)
    except Exception as exc:
        logger.exception(
            "Falha ao transcrever audio RDV: media_id=%s erro=%s",
            _mask_media_id(media_id),
            _safe_exception_summary(exc),
        )
        state["state"] = "awaiting_correction"
        return TRANSCRIPTION_FAILED_MESSAGE
    finally:
        if not _keep_audio_after_transcription():
            _safe_unlink(destination)

    if not result.ok:
        state["state"] = "awaiting_correction"
        return TRANSCRIPTION_FAILED_MESSAGE

    # Avisos ao usuário
    warnings = list(result.warnings) if result.warnings else []
    user_warning = ""
    if warnings:
        has_suspicious = any(w.startswith("suspicious_") for w in warnings)
        if has_suspicious:
            user_warning = "\n\n⚠️ Identifiquei números, datas ou medidas que precisam de conferência. Revise o texto antes de confirmar."

    raw_text = result.raw_text
    reviewed_text = result.reviewed_text or raw_text
    is_safe = not any(w.startswith("suspicious_") for w in warnings)

    # Armazena ambos os textos e metadados no estado
    state["state"] = "awaiting_audio_confirmation"
    state["raw_text"] = raw_text
    state["text"] = reviewed_text  # texto que será usado se confirmar
    state["reviewed_text"] = reviewed_text
    state["raw_text_full"] = raw_text
    state["warnings"] = list(warnings) if warnings else []
    state["used_fallback"] = result.used_fallback
    state["request_id"] = result.metadata.request_id
    state["is_safe"] = is_safe
    state["user_warning"] = user_warning

    # Se não for seguro, usa o raw_text como opção padrão na mensagem
    display_text = reviewed_text if is_safe else raw_text
    message = _rdv_transcription_confirmation_message(display_text)
    if user_warning:
        message += user_warning
    return message


def handle_whatsapp_audio_message(
    sender_phone: str,
    media_id: str,
    mime_type: str = "",
) -> str:
    menu_state = whatsapp_menu_states.get(sender_phone)
    standalone_mode = menu_state == STANDALONE_TRANSCRIPTION_STATE
    if menu_state == STANDALONE_TRANSCRIPTION_MODE_STATE:
        return STANDALONE_TRANSCRIPTION_PROMPT
    if not standalone_mode and _get_rdv_comment_state(sender_phone) is not None:
        return handle_rdv_audio_comment_message(sender_phone, media_id, mime_type)

    if not _audio_transcription_enabled():
        return "Recebi seu audio, mas a transcricao esta desativada. Pode digitar a informacao?"

    if not media_id:
        return "Nao consegui entender esse audio. Pode enviar novamente ou digitar a informacao?"

    destination = _build_audio_transcription_destination(
        sender_phone=sender_phone,
        media_id=media_id,
        mime_type=mime_type,
    )
    downloaded_path = destination
    try:
        downloaded_path = download_media(media_id, destination)
        result = _transcribe_audio_with_result(downloaded_path)
    except AudioLimitExceededError as exc:
        logger.warning(
            "Audio WhatsApp acima do limite: media_id=%s erro=%s",
            _mask_media_id(media_id),
            _safe_exception_summary(exc),
        )
        return AUDIO_TOO_LONG_MESSAGE
    except Exception as exc:
        logger.exception(
            "Falha ao transcrever audio WhatsApp: media_id=%s status_code=%s erro=%s",
            _mask_media_id(media_id),
            _http_status_from_exception(exc) or "-",
            _safe_exception_summary(exc),
        )
        return TRANSCRIPTION_FAILED_MESSAGE
    finally:
        if not _keep_audio_after_transcription():
            _safe_unlink(downloaded_path)

    if not result.ok:
        return TRANSCRIPTION_FAILED_MESSAGE

    # Avisos ao usuário
    warnings = list(result.warnings) if result.warnings else []
    user_warning = ""
    if warnings:
        # Verifica se há warnings de alteração suspeita de números/datas/medidas
        has_suspicious = any(w.startswith("suspicious_") for w in warnings)
        if has_suspicious:
            user_warning = "\n\n⚠️ Identifiquei números, datas ou medidas que precisam de conferência. Revise o texto antes de confirmar."

    transcription = result.raw_text
    reviewed_text = result.reviewed_text or transcription

    if standalone_mode:
        mode = standalone_transcription_modes.get(
            sender_phone, transcription_review_default_mode()
        )
        intelligent = _audio_transcription_intelligence_service.process(
            transcription,
            mode=mode,
        )
        message = _standalone_transcription_message(intelligent)
        if user_warning:
            message += user_warning
        return message

    # Revisão local adicional (já feita no service, mas mantemos para compatibilidade)
    reviewed = _review_audio_transcription_for_sender(sender_phone, transcription)
    final_text = reviewed.reviewed_text or transcription
    if user_warning:
        # Adiciona aviso ao final da mensagem de confirmação
        pass  # O aviso será adicionado na mensagem de confirmação

    # Resumo de IA controlado por flag: so para audio de descricao/observacao
    # de visita. Se o resumo for preparado, mostra a previsualizacao e pausa
    # o fluxo de salvamento até o usuario escolher. Caso contrario (flag off,
    # falha ou estado invalido), mantem o fluxo anterior inalterado.
    visit = _get_active_visita_for_phone(sender_phone)
    visit_state = str((visit or {}).get("estado_fluxo") or "")
    summary_preview = _maybe_prepare_visita_audio_summary(
        sender_phone,
        visit,
        visit_state,
        final_text,
        media_id,
    )
    if summary_preview is not None:
        if user_warning:
            summary_preview += user_warning
        return summary_preview

    reply = handle_rdv_text_message(
        sender_phone,
        final_text,
        is_audio_transcription=True,
    )
    return reply or "Audio transcrito e registrado."


def _start_rdv_comment_state(sender_phone: str, expense_id: int) -> None:
    phone = normalize_phone(sender_phone)
    if not phone:
        return
    rdv_comment_states[phone] = {
        "expense_id": int(expense_id),
        "state": "awaiting_comment",
        "text": "",
    }


def _get_rdv_comment_state(sender_phone: str) -> dict | None:
    phone = normalize_phone(sender_phone)
    if not phone:
        return None
    state = rdv_comment_states.get(phone)
    if state is None:
        return None
    try:
        expense_id = int(state.get("expense_id") or 0)
    except (TypeError, ValueError):
        expense_id = 0
    if expense_id <= 0 or rdv_service.get_expense(expense_id) is None:
        rdv_comment_states.pop(phone, None)
        return None
    return state


def _clear_rdv_comment_state(sender_phone: str) -> None:
    phone = normalize_phone(sender_phone)
    if phone:
        rdv_comment_states.pop(phone, None)


def _rdv_comment_saved_message(expense: dict) -> str:
    month = calculate_month_reference(expense["data_despesa"])
    return "\n".join(
        [
            "Comentario salvo no RDV.",
            f"Lancamento #{expense['id']}.",
            "",
            "Para receber a planilha do mes, envie:",
            f"planilha {month}",
        ]
    )


def _rdv_transcription_confirmation_message(text: str) -> str:
    return "\n".join(
        [
            "Transcrevi seu audio assim:",
            "",
            f'"{_safe_text_for_message(text)}"',
            "",
            "1 - Confirmar comentario",
            "2 - Corrigir digitando",
            "3 - Remover comentario",
        ]
    )


def _safe_text_for_message(text: str, limit: int = 1200) -> str:
    safe_text = str(text or "").strip()
    safe_text = safe_text.replace("\r", " ").strip()
    if len(safe_text) <= limit:
        return safe_text
    return safe_text[: limit - 3].rstrip() + "..."


def _audio_transcription_enabled() -> bool:
    return whisper_enabled_from_env()


def _review_transcription_in_revisada_mode(
    raw_text: str,
    *,
    context: str,
) -> ReviewedTranscription:
    try:
        result = _audio_transcription_intelligence_service.process(
            raw_text,
            mode="revisada",
            context=context,
        )
        raw = str(raw_text or "").strip()
        output = result.output_text or raw
        warnings = ["llm_fallback"] if result.used_fallback else []
        return ReviewedTranscription(raw, output, output != raw, warnings)
    except Exception as exc:
        logger.exception(
            "Falha ao revisar transcricao; usando texto bruto: contexto=%s erro=%s",
            context,
            _safe_exception_summary(exc),
        )
        raw = str(raw_text or "").strip()
        return ReviewedTranscription(raw, raw, False, ["review_failed"])


def _review_audio_transcription_for_sender(
    sender_phone: str,
    raw_text: str,
) -> ReviewedTranscription:
    """Aplica sempre o modo revisado aos áudios fora do transcritor avulso."""
    return _review_transcription_in_revisada_mode(
        raw_text,
        context=_transcription_context_for_sender(sender_phone),
    )


def _transcription_context_for_sender(sender_phone: str) -> str:
    visit = _get_active_visita_for_phone(sender_phone)
    state = str((visit or {}).get("estado_fluxo") or "")
    return VISITA_AUDIO_REVIEW_CONTEXT_BY_STATE.get(state, "relatorio_campo")


# Estados de visita que aceitam resumo de IA a partir de audio.
_VISITA_SUMMARY_AUDIO_STATES = {
    "aguardando_descricao_visita",
    "aguardando_edicao_descricao",
    "aguardando_observacoes_gerais",
    "aguardando_adicao_observacao",
    "aguardando_reescrita_observacoes",
}
_VISITA_SUMMARY_DESTINATION_BY_STATE = {
    "aguardando_descricao_visita": "descricao",
    "aguardando_edicao_descricao": "descricao",
    "aguardando_observacoes_gerais": "observacoes",
    "aguardando_adicao_observacao": "observacoes",
    "aguardando_reescrita_observacoes": "observacoes",
}


def _visita_summary_destination_for_state(state: str) -> str | None:
    return _VISITA_SUMMARY_DESTINATION_BY_STATE.get(state)


def _summary_to_text(summary: VisitaSummary) -> str:
    """Formata o resumo estruturado como texto unico para confirmacao/salvar."""
    parts = [
        f"Assunto principal: {summary.assunto_principal}",
        f"Necessidades: {summary.necessidades}",
        f"Decisoes: {summary.decisoes}",
        f"Pendencias: {summary.pendencias}",
        f"Proximos passos: {summary.proximos_passos}",
    ]
    return "\n".join(p for p in parts if p)


def _maybe_prepare_visita_audio_summary(
    sender_phone: str,
    visit: dict | None,
    state: str,
    reviewed_text: str,
    media_id: str,
) -> str | None:
    """Prepara (opcionalmente) o resumo de IA a partir de um audio de visita.

    Retorna a mensagem de previsualizacao do resumo se:
    - houver visita ativa;
    - o estado for de audio de descricao/observacao de visita;
    - VISITA_SUMMARY_ENABLED estiver ativo;
    - o resumo for gerado e validado com sucesso.

    Em qualquer outra situacao (flag desligada, falha, resposta invalida,
    ausencia de visita/estado invalido), retorna None para que o fluxo
    anterior (salvar a transcricao revisada) continue intacto.
    """
    if visit is None:
        return None
    if state not in _VISITA_SUMMARY_AUDIO_STATES:
        return None
    destination = _visita_summary_destination_for_state(state)
    if destination is None:
        return None

    # O servico ja respeita VISITA_SUMMARY_ENABLED internamente; a chamada a
    # generate() simplesmente retorna fallback (sem chamar provider) se off.
    result: VisitaSummaryResult = _visita_summary_service.generate(reviewed_text)
    if not result.ok or result.summary is None:
        return None

    phone = normalize_phone(sender_phone)
    if not phone:
        return None
    visita_summary_confirmation_states[phone] = {
        "visita_id": int(visit.get("id")),
        "destination": destination,
        "original_state": state,
        "reviewed_text": reviewed_text,
        "summary_text": _summary_to_text(result.summary),
        "media_id": media_id or "",
    }
    return _visita_summary_preview_message(result.summary, destination)


def _visita_summary_preview_message(summary: VisitaSummary, destination: str) -> str:
    label = "descricao da visita" if destination == "descricao" else "observacoes da visita"
    return "\n".join(
        [
            "📋 Resumo sugerido para " + label + ":",
            "",
            f"Assunto principal: {summary.assunto_principal}",
            f"Necessidades: {summary.necessidades}",
            f"Decisoes: {summary.decisoes}",
            f"Pendencias: {summary.pendencias}",
            f"Proximos passos: {summary.proximos_passos}",
            "",
            "Responda com uma opcao:",
            "1 - Usar o resumo sugerido",
            "2 - Usar a transcricao revisada",
            "3 - Reenviar o audio ou digitar o conteudo",
        ]
    )


def _handle_visita_summary_confirmation(
    sender_phone: str,
    text: str,
) -> str | None:
    """Intercepta a escolha do usuario enquanto ha resumo pendente.

    Retorna a resposta (ja salva no campo existente) ou None se nao houver
    confirmacao pendente. Nunca interrompe o fluxo: se o estado nao existir,
    devolve None e o fluxo normal de texto continua.
    """
    phone = normalize_phone(sender_phone)
    if not phone or phone not in visita_summary_confirmation_states:
        return None

    pending = visita_summary_confirmation_states.pop(phone)
    normalized = _normalize_caption(text)
    choice = normalized.replace(" ", "").replace("-", "")

    if choice in {"1", "usaresumo", "usarresumo"}:
        chosen_text = pending.get("summary_text") or ""
    elif choice in {"2", "usartranscricao", "usartranscricao", "usararevisada"}:
        chosen_text = pending.get("reviewed_text") or ""
    elif choice in {"3", "reenviar", "reenviaraudio", "cancelar"}:
        return (
            "Ok. Voce pode reenviar o audio ou digitar o conteudo diretamente "
            "para a " + (
                "descricao da visita." if pending.get("destination") == "descricao"
                else "observacao da visita."
            )
        )
    else:
        # Escolha invalida: mantem o estado para o usuario tentar de novo.
        visita_summary_confirmation_states[phone] = pending
        return (
            "Opcao invalida. Responda:\n"
            "1 - Usar o resumo sugerido\n"
            "2 - Usar a transcricao revisada\n"
            "3 - Reenviar o audio ou digitar o conteudo"
        )

    if not chosen_text.strip():
        return "Nao foi possivel recuperar o conteudo escolhido. Envie novamente."
    # Reutiliza o fluxo existente de salvamento, como texto digitado normal.
    handled, reply = handle_visitas_text_message(
        sender_phone, chosen_text, is_audio_transcription=False
    )
    if handled:
        return reply
    return "Conteudo registrado."


def _is_standalone_transcription_session(sender_phone: str) -> bool:
    return whatsapp_menu_states.get(sender_phone) in {
        STANDALONE_TRANSCRIPTION_MODE_STATE,
        STANDALONE_TRANSCRIPTION_STATE,
    }


def _standalone_transcription_message(
    result: IntelligentTranscriptionResult,
) -> str:
    headings = {
        "literal": "🎙️ Transcrição literal:",
        "revisada": "📝 Transcrição revisada:",
        "relatorio": "📄 Texto organizado para relatório:",
    }
    heading = headings.get(result.mode, headings["revisada"])
    parts = [heading, "", result.output_text or result.raw_text]
    if result.used_fallback:
        parts.extend(["", "Revisão local aplicada como fallback."])
    parts.extend(["", "Você pode enviar outro áudio ou digitar menu para voltar."])
    return "\n".join(parts)


def _keep_audio_after_transcription() -> bool:
    return _env_flag_enabled("WHISPER_KEEP_AUDIO")


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def _transcribe_audio_file(audio_path: Path) -> str:
    global _audio_transcription_service
    provider = os.getenv("AUDIO_TRANSCRIPTION_PROVIDER", "whisper_local").strip()
    if provider != "whisper_local":
        raise RuntimeError(f"Provider de transcricao nao suportado: {provider}")
    if _audio_transcription_service is None:
        _audio_transcription_service = AudioTranscriptionService.from_env()
    # Usa novo método com resultado completo, mas retorna apenas o texto para compatibilidade
    result = _audio_transcription_service.transcrever_com_resultado(str(audio_path))
    return result.reviewed_text if result.ok else result.raw_text


def _transcribe_audio_with_result(audio_path: Path) -> "TranscriptionResult":
    """Nova função que retorna o TranscriptionResult completo para os fluxos A2.2."""
    global _audio_transcription_service
    provider = os.getenv("AUDIO_TRANSCRIPTION_PROVIDER", "whisper_local").strip()
    if provider != "whisper_local":
        raise RuntimeError(f"Provider de transcricao nao suportado: {provider}")
    if _audio_transcription_service is None:
        _audio_transcription_service = AudioTranscriptionService.from_env()
    return _audio_transcription_service.transcrever_com_resultado(str(audio_path))


def _build_audio_transcription_destination(
    sender_phone: str,
    media_id: str,
    mime_type: str,
) -> Path:
    tmp_dir = Path(os.getenv("WHISPER_TMP_DIR", "tmp/audio_transcriptions"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_phone = _safe_filename_part(sender_phone) or "sem_telefone"
    safe_media_id = _safe_filename_part(media_id)[-12:] or "audio"
    extension = _extension_from_mime_type(mime_type)
    if extension == ".bin":
        extension = ".ogg"
    return tmp_dir / f"{timestamp}_{safe_phone}_{safe_media_id}{extension}"


def _safe_unlink(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        logger.warning("Nao foi possivel remover arquivo temporario: %s", Path(path).name)


def _open_main_menu(sender_phone: str) -> str:
    return MAIN_MENU_MESSAGE


def _save_visita_observacoes(
    visita_id: int,
    text: str,
    *,
    is_audio_transcription: bool,
) -> tuple[int, str]:
    if not is_audio_transcription:
        validation = validate_visit_field("observacoes_gerais", text)
        if not validation.ok:
            return 0, validation.error
        visitas_service.adicionar_observacao_geral(visita_id, validation.value)
        return 1, ""

    normalized_text = " ".join(str(text or "").split())
    total_limit = visita_observacao_total_max_chars()
    if len(normalized_text) > total_limit:
        return (
            0,
            "A transcrição ficou muito longa para as observações do relatório. "
            "Envie o áudio dividido em partes menores.",
        )

    parts = split_visit_observation(normalized_text)
    for part in parts:
        validation = validate_visit_field("observacoes_gerais", part)
        if not validation.ok:
            return 0, validation.error
    for part in parts:
        visitas_service.adicionar_observacao_geral(visita_id, part)
    return len(parts), ""


def handle_visitas_text_message(
    sender_phone: str,
    text: str,
    collaborator: dict | None = None,
    normalized: str | None = None,
    *,
    is_audio_transcription: bool = False,
) -> tuple[bool, str | None]:
    normalized_text = normalized if normalized is not None else _normalize_caption(text)
    collaborator = collaborator or rdv_service.get_collaborator_by_phone(sender_phone)
    open_visit = _get_active_visita_for_phone(sender_phone)
    phone = normalize_phone(sender_phone)

    if (
        open_visit is None
        and normalized_text in VISITA_REVIEW_FINALIZE_COMMANDS
        and phone in visita_recently_finalized_states
    ):
        return True, "Esta visita já foi finalizada."

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
        visita_recently_finalized_states.pop(phone, None)
        visita_active_states[phone] = int(visit["id"])
        return True, "\n".join(
            [
                "Vamos iniciar uma visita técnica.",
                "Qual o nome da fazenda ou propriedade visitada?",
            ]
        )

    if _is_planilha_visitas_command(normalized_text):
        try:
            _send_visitas_excel(sender_phone, normalized_text)
        except WhatsAppSendError:
            raise
        except Exception as exc:
            logger.exception(
                "Falha ao enviar Excel de visitas pelo WhatsApp: to=%s erro=%s",
                _mask_phone(sender_phone),
                _safe_exception_summary(exc),
            )
            return True, "Não consegui enviar a planilha de visitas agora. Tente novamente mais tarde."
        return True, None

    if _is_listar_visitas_command(normalized_text):
        messages = _listar_visitas_messages(normalized_text)
        if messages == [NO_VALID_VISITA_MESSAGE]:
            return True, NO_VALID_VISITA_MESSAGE
        for message in messages:
            send_whatsapp_text(sender_phone, message)
        return True, None

    if (
        open_visit is not None
        and str(open_visit.get("estado_fluxo") or "") == "aguardando_revisao_final"
        and normalized_text in VISITA_REVIEW_PREVIEW_COMMANDS
    ):
        return True, _start_visita_review(sender_phone, open_visit["id"])

    if _is_relatorio_visita_command(normalized_text):
        try:
            reply = _handle_relatorio_visita(sender_phone, text, normalized_text)
        except ValueError as exc:
            if str(exc) == "visita_cancelada":
                return True, CANCELED_VISITA_REPORT_MESSAGE
            raise
        except WhatsAppSendError:
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

    if normalized_text in VISITA_CLOSE_COMMANDS:
        if open_visit is None:
            return True, NO_OPEN_VISITA_MESSAGE
        if (
            str(open_visit.get("estado_fluxo") or "") == "aguardando_revisao_final"
            and normalized_text in VISITA_REVIEW_FINALIZE_COMMANDS
        ):
            return True, _finalize_visita(sender_phone, open_visit)
        if _is_legacy_quick_visit(open_visit):
            return True, _start_visita_review(sender_phone, open_visit["id"])
        if visitas_service.existem_fotos_pendentes(open_visit["id"]):
            return True, VISITA_FOTO_PENDENTE_MESSAGE
        return True, _start_visita_review(sender_phone, open_visit["id"])

    if normalized_text == "cancelar visita":
        if open_visit is None:
            return True, NO_OPEN_VISITA_MESSAGE
        visitas_service.cancelar_visita(open_visit["id"])
        _clear_active_visita(sender_phone, open_visit["id"])
        return True, "Visita cancelada com sucesso."

    if normalized_text in VISITA_REVIEW_DELETE_PHOTO_COMMANDS or normalized_text in VISITA_REVIEW_DELETE_VIDEO_COMMANDS:
        closed_message = _visita_finalizada_delete_media_message_if_applicable(sender_phone)
        if closed_message:
            return True, closed_message

    if open_visit is None:
        return False, None

    state = str(open_visit.get("estado_fluxo") or "")
    if state in {"aguardando_exclusao_foto", "aguardando_exclusao_video"} and normalized_text in VISITA_REVIEW_CANCEL_COMMANDS:
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_revisao_final_message()
    if (
        (
            state.startswith("aguardando_confirmacao_exclusao_foto:")
            or state.startswith("aguardando_confirmacao_exclusao_video:")
        )
        and normalized_text in VISITA_REVIEW_DENY_DELETE_COMMANDS
    ):
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_revisao_final_message()

    if normalized_text in {"cancelar", "sair"}:
        visitas_service.cancelar_visita(open_visit["id"])
        _clear_active_visita(sender_phone, open_visit["id"])
        return True, "Visita cancelada com sucesso."

    if state.startswith("aguardando_legenda_video:") or state.startswith("aguardando_legenda_video_revisao:"):
        review_mode = state.startswith("aguardando_legenda_video_revisao:")
        pending = visitas_service.proximo_video_pendente(open_visit["id"])
        if pending is None:
            return True, _visita_proxima_midia_ou_finaliza(open_visit["id"], review_mode=review_mode)
        if normalized_text in VISITA_FOTO_PULAR_COMMANDS:
            visitas_service.salvar_comentario_midia(pending["id"], "Sem comentario informado.")
            return True, _visita_proxima_midia_ou_finaliza(
                open_visit["id"],
                review_mode=review_mode,
                resolved_message="✅ Legenda salva para o vídeo.",
            )
        validation = validate_visit_field("comentario_foto", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.salvar_comentario_midia(pending["id"], validation.value)
        return True, _visita_proxima_midia_ou_finaliza(
            open_visit["id"],
            review_mode=review_mode,
            resolved_message="✅ Legenda salva para o vídeo.",
        )

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
        saved_count, error = _save_visita_observacoes(
            open_visit["id"],
            text,
            is_audio_transcription=is_audio_transcription,
        )
        if error:
            return True, error
        if is_audio_transcription and saved_count > 1:
            return (
                True,
                f"Áudio transcrito e salvo em {saved_count} observações do relatório.",
            )
        return True, "Observação salva. Envie outra observação ou finalize com: finalizar observações"

    if state in {"aguardando_decisao_comentario_foto", "aguardando_decisao_comentario_foto_revisao"}:
        review_mode = state.endswith("_revisao")
        pending = visitas_service.proxima_foto_pendente(open_visit["id"])
        if pending is None:
            visitas_service.atualizar_campo(
                open_visit["id"],
                "estado_fluxo",
                "aguardando_revisao_final" if review_mode else "visita_aberta",
            )
            return True, _visita_midia_atualizada_message("Fotos salvas no relatório.") if review_mode else "Fotos salvas no relatorio."
        if normalized_text in VISITA_FOTO_COMENTAR_COMMANDS:
            visitas_service.atualizar_campo(
                open_visit["id"],
                "estado_fluxo",
                "aguardando_texto_comentario_foto_revisao" if review_mode else "aguardando_texto_comentario_foto",
            )
            return True, f"Digite o comentario da Foto {pending.get('indice') or 1}:"
        if normalized_text in VISITA_FOTO_PULAR_COMMANDS:
            visitas_service.salvar_comentario_foto(pending["id"], "Sem comentario informado.")
            return True, _visita_proxima_midia_ou_finaliza(open_visit["id"], review_mode=review_mode)
        validation = validate_visit_field("comentario_foto", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.salvar_comentario_foto(pending["id"], validation.value)
        return True, _visita_proxima_midia_ou_finaliza(
            open_visit["id"],
            review_mode=review_mode,
            resolved_message="✅ Comentário salvo.",
        )

    if state in {"aguardando_texto_comentario_foto", "aguardando_texto_comentario_foto_revisao"}:
        review_mode = state.endswith("_revisao")
        pending = visitas_service.proxima_foto_pendente(open_visit["id"])
        if pending is None:
            visitas_service.atualizar_campo(
                open_visit["id"],
                "estado_fluxo",
                "aguardando_revisao_final" if review_mode else "visita_aberta",
            )
            return True, _visita_midia_atualizada_message("Fotos salvas no relatório.") if review_mode else "Fotos salvas no relatorio."
        if normalized_text in VISITA_FOTO_PULAR_COMMANDS:
            visitas_service.salvar_comentario_foto(pending["id"], "Sem comentario informado.")
            return True, _visita_proxima_midia_ou_finaliza(open_visit["id"], review_mode=review_mode)
        validation = validate_visit_field("comentario_foto", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.salvar_comentario_foto(pending["id"], validation.value)
        return True, _visita_proxima_midia_ou_finaliza(
            open_visit["id"],
            review_mode=review_mode,
            resolved_message="✅ Comentário salvo.",
        )

    if state == "aguardando_revisao_final":
        if normalized_text in VISITA_REVIEW_FINALIZE_COMMANDS:
            return True, _finalize_visita(sender_phone, open_visit)
        if _is_maps_location_text(text):
            visitas_service.salvar_localizacao_textual(open_visit["id"], text)
            return True, _visita_midia_atualizada_message("✅ Localização atualizada.")
        if normalized_text == "2":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "corrigindo_dados_propriedade")
            return True, _visita_corrigir_dados_message()
        if normalized_text == "3":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_edicao_descricao")
            return True, "Digite a nova descricao da visita:"
        if normalized_text == "4":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "corrigindo_observacoes")
            return True, _visita_corrigir_observacoes_message()
        if normalized_text in VISITA_REVIEW_DELETE_PHOTO_COMMANDS:
            return True, _start_visita_media_delete(open_visit, "foto")
        if normalized_text in VISITA_REVIEW_DELETE_VIDEO_COMMANDS:
            return True, _start_visita_media_delete(open_visit, "video")
        if normalized_text in VISITA_REVIEW_MEDIA_OPTION_COMMANDS:
            return True, VISITA_REVIEW_MEDIA_GUIDANCE_MESSAGE
        if normalized_text in VISITA_REVIEW_PREVIEW_COMMANDS:
            return True, _start_visita_review(sender_phone, open_visit["id"])
        if normalized_text in VISITA_REVIEW_BACK_COMMANDS:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "visita_aberta")
            return True, "Visita continua aberta. Envie ajustes, fotos, vídeos, observações ou \"fechar visita\" para revisar novamente."
        return True, _visita_revisao_final_message()

    if state in {"aguardando_exclusao_foto", "aguardando_exclusao_video"}:
        media_type = "foto" if state.endswith("foto") else "video"
        if normalized_text in VISITA_REVIEW_CANCEL_COMMANDS:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_revisao_final_message()
        media = _visita_media_by_current_number(open_visit["id"], media_type, normalized_text)
        if media is None:
            return True, _visita_delete_media_list_message(open_visit["id"], media_type, invalid=True)
        index = int(media.get("numero_relatorio") or 1)
        visitas_service.atualizar_campo(
            open_visit["id"],
            "estado_fluxo",
            f"aguardando_confirmacao_exclusao_{media_type}:{media['id']}:{index}",
        )
        label = "Foto" if media_type == "foto" else "Vídeo"
        return True, "\n".join([f"Deseja apagar a {label} {index} da visita?", "", "1. Sim", "2. Não"])

    if state.startswith("aguardando_confirmacao_exclusao_foto:") or state.startswith("aguardando_confirmacao_exclusao_video:"):
        media_type = "foto" if state.startswith("aguardando_confirmacao_exclusao_foto:") else "video"
        if normalized_text in VISITA_REVIEW_DENY_DELETE_COMMANDS:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_revisao_final_message()
        if normalized_text not in VISITA_REVIEW_CONFIRM_DELETE_COMMANDS:
            parts = state.rsplit(":", 2)
            index = parts[-1] if len(parts) >= 3 else "1"
            label = "Foto" if media_type == "foto" else "Vídeo"
            return True, "\n".join([f"Deseja apagar a {label} {index} da visita?", "", "1. Sim", "2. Não"])
        try:
            _, media_id_text, index_text = state.rsplit(":", 2)
            media_id = int(media_id_text)
            index = int(index_text)
        except ValueError:
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_revisao_final_message()
        removed = _delete_visita_media(open_visit, media_id)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        if removed is None:
            return True, _visita_delete_media_list_message(open_visit["id"], media_type, invalid=True)
        label = "Foto" if media_type == "foto" else "Vídeo"
        title = (
            f"âœ… {label} {index} removida da visita."
            if media_type == "foto"
            else f"âœ… {label} {index} removido da visita."
        )
        return True, "\n".join(
            [
                title,
                "",
                "A prévia anterior pode estar desatualizada.",
                "Digite \"prévia\" ou escolha \"Gerar nova prévia\" para ver o relatório atualizado.",
            ]
        )

    if state == "corrigindo_dados_propriedade":
        fields = {
            "1": ("fazenda", "Digite a nova fazenda/propriedade:"),
            "2": ("proprietario", "Digite o novo proprietario:"),
            "3": ("telefone_proprietario", "Digite o novo telefone do proprietario:"),
            "4": ("gerente", "Digite o novo gerente/responsavel local:"),
            "5": ("telefone_gerente", "Digite o novo telefone do gerente:"),
            "6": ("localizacao_texto", "Digite a nova localização da fazenda/propriedade:"),
            "7": ("area", "Digite o novo tamanho total da fazenda/propriedade:"),
        }
        if normalized_text == "8":
            visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
            return True, _visita_revisao_final_message()
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
        if field == "localizacao_texto":
            visitas_service.salvar_localizacao_textual(open_visit["id"], validation.value)
        else:
            visitas_service.atualizar_campo(open_visit["id"], field, validation.value)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_revisao_texto_atualizado_message()

    if state == "aguardando_edicao_descricao":
        validation = validate_visit_field("descricao_visita", text)
        if not validation.ok:
            return True, validation.error
        visitas_service.atualizar_campo(open_visit["id"], "descricao_visita", validation.value)
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_revisao_texto_atualizado_message()

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
            return True, _visita_revisao_final_message()
        return True, _visita_corrigir_observacoes_message()

    if state == "aguardando_adicao_observacao":
        saved_count, error = _save_visita_observacoes(
            open_visit["id"],
            text,
            is_audio_transcription=is_audio_transcription,
        )
        if error:
            return True, error
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        if is_audio_transcription and saved_count > 1:
            return (
                True,
                f"Áudio transcrito e salvo em {saved_count} observações do relatório.",
            )
        return True, _visita_revisao_texto_atualizado_message()

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
            return True, _visita_revisao_texto_atualizado_message()
        return True, _visita_listar_observacoes_para_remover(open_visit)

    if state == "aguardando_reescrita_observacoes":
        visitas_service.substituir_observacoes_gerais(open_visit["id"], text.splitlines())
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_revisao_final")
        return True, _visita_revisao_texto_atualizado_message()

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
        next_state = _next_visita_state(state)
        if field == "localizacao_texto":
            if validation.value:
                saved = visitas_service.salvar_localizacao_textual(open_visit["id"], validation.value)
            else:
                saved = open_visit
            saved = visitas_service.atualizar_campo(saved["id"], "estado_fluxo", next_state)
        else:
            updates = {field: validation.value, "estado_fluxo": next_state}
            saved = open_visit
            for update_field, update_value in updates.items():
                saved = visitas_service.atualizar_campo(saved["id"], update_field, update_value)
        visita_active_states[phone] = int(saved["id"])
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

    return True, _active_visita_menu_message(open_visit)


def handle_visitas_location_message(sender_phone: str, location: dict) -> str | None:
    open_visit = _get_active_visita_for_phone(sender_phone)
    if open_visit is None:
        return _visita_closed_media_message_if_applicable(sender_phone)
    state = str(open_visit.get("estado_fluxo") or "")
    if state not in {"visita_aberta", "aguardando_localizacao", "aguardando_revisao_final"}:
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
    if state == "aguardando_localizacao":
        visitas_service.atualizar_campo(open_visit["id"], "estado_fluxo", "aguardando_area")
        return "\n".join(
            [
                "📍 Localização salva.",
                "Abrir no GPS:",
                saved["maps_url"],
                "",
                VISITA_FLOW_STEPS["aguardando_localizacao"][1],
            ]
        )
    if state == "aguardando_revisao_final":
        return _visita_midia_atualizada_message("✅ Localização atualizada.")
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
        return _visita_closed_media_message_if_applicable(sender_phone) or "Nenhuma visita em andamento encontrada."
    media = visitas_service.adicionar_midia(
        open_visit["id"],
        tipo="foto" if message_type == "image" else message_type,
        media_id_whatsapp=media_id,
        caminho_arquivo=file_path,
        legenda=caption,
    )
    if message_type == "image":
        review_mode = _visita_state_is_review_media_queue(open_visit)
        pending = visitas_service.proxima_midia_pendente(open_visit["id"]) or media
        _set_visita_pending_media_state(open_visit["id"], pending, review_mode=review_mode)
        fazenda = open_visit.get("fazenda") or "visita em andamento"
        saved_message = (
            f"✅ Foto anexada à visita. Foto {media.get('indice') or 1} recebida."
            if review_mode
            else f"✅ Foto {media.get('indice') or 1} recebida. Foto salva na visita {fazenda}."
        )
        return "\n\n".join(
            [
                saved_message,
                _visita_pending_media_message(pending),
                _visita_preview_outdated_hint() if review_mode else "",
            ]
        ).strip()
    fazenda = open_visit.get("fazenda") or "visita em andamento"
    return "\n".join(
        [
            f"Foto salva na visita {fazenda}.",
            "Envie outra foto, observação, localização ou \"fechar visita\".",
        ]
    )


def handle_visitas_video_message(
    sender_phone: str,
    media_id: str,
    mime_type: str = "",
) -> str:
    open_visit = _get_active_visita_for_phone(sender_phone)
    if open_visit is None:
        return _visita_closed_media_message_if_applicable(sender_phone) or VISITA_VIDEO_NO_OPEN_MESSAGE
    if not _visita_state_accepts_media(open_visit):
        return "Continue preenchendo a visita técnica atual antes de anexar vídeos."
    review_mode = _visita_state_is_review_media_queue(open_visit)

    destination = _build_media_destination(
        sender_phone=sender_phone,
        media_id=media_id,
        mime_type=mime_type or "video/mp4",
    )
    downloaded_path = destination
    try:
        downloaded_path = download_media(media_id, destination)
        visita_media_service.validate_video_file(downloaded_path)
        video_hash = visita_media_service.calculate_video_sha256(downloaded_path)
        if visitas_service.existe_video_hash(open_visit["id"], video_hash):
            return _visita_video_duplicate_message()

        limit = visita_media_service.video_limit_per_visit()
        current_count = visitas_service.contar_midias_por_tipo(open_visit["id"], "video")
        if current_count >= limit:
            return _visita_video_limit_message(limit)

        upload = visita_media_service.upload_visit_video(
            visita_id=open_visit["id"],
            local_path=downloaded_path,
            video_id=media_id,
            mime_type=mime_type or "video/mp4",
        )
        media = visitas_service.adicionar_midia(
            open_visit["id"],
            tipo="video",
            media_id_whatsapp=media_id,
            caminho_arquivo="",
            legenda="",
            storage_key=upload.get("storage_key"),
            public_url=upload.get("public_url"),
            tamanho_bytes=upload.get("size_bytes"),
            mime_type=upload.get("content_type") or mime_type,
            video_hash=video_hash,
        )
        pending = visitas_service.proxima_midia_pendente(open_visit["id"]) or media
        _set_visita_pending_media_state(open_visit["id"], pending, review_mode=review_mode)
    except VideoTooLargeError:
        return _visita_video_too_large_message()
    except (VideoUploadError, OSError, RuntimeError) as exc:
        logger.exception(
            "Falha ao anexar video da visita: media_id=%s erro=%s",
            _mask_media_id(media_id),
            _safe_exception_summary(exc),
        )
        return VISITA_VIDEO_UPLOAD_ERROR_MESSAGE
    finally:
        _safe_unlink(downloaded_path)

    return "\n".join(
        [
            f"✅ Vídeo recebido e anexado à visita. Vídeo {_visita_media_display_index(media)}.",
            _visita_pending_media_message(pending),
            "Depois da legenda, a prévia anterior ficará desatualizada." if review_mode else "",
            "Digite \"prévia\" para gerar o relatório atualizado antes de finalizar." if review_mode else "",
        ]
    ).strip()


def _visita_state_accepts_media(visita: dict) -> bool:
    state = str(visita.get("estado_fluxo") or "")
    return (
        state in {
        "visita_aberta",
        "aguardando_revisao_final",
        "corrigindo_dados_propriedade",
        "corrigindo_observacoes",
        "corrigindo_comentario_foto",
        "aguardando_decisao_comentario_foto",
        "aguardando_decisao_comentario_foto_revisao",
        "aguardando_texto_comentario_foto",
        "aguardando_texto_comentario_foto_revisao",
        }
        or state.startswith("aguardando_legenda_video:")
        or state.startswith("aguardando_legenda_video_revisao:")
    )


def _visita_state_is_review_media_queue(visita: dict) -> bool:
    state = str(visita.get("estado_fluxo") or "")
    return state == "aguardando_revisao_final" or state.endswith("_revisao") or state.startswith(
        "aguardando_legenda_video_revisao:"
    )


def _visita_video_too_large_message() -> str:
    return "\n".join(
        [
            "⚠️ Esse vídeo ficou muito grande.",
            f"Envie um vídeo menor, de até {int(video_max_mb())} MB.",
            f"Dica: grave um trecho curto, de preferência até {int(video_max_seconds())} segundos.",
        ]
    )


def _visita_video_limit_message(limit: int | None = None) -> str:
    max_videos = int(limit or video_max_per_visita())
    return "\n".join(
        [
            "⚠️ Esta visita já atingiu o limite de vídeos permitido.",
            "",
            f"Limite atual: {max_videos} vídeos por visita.",
            "",
            "Se precisar adicionar mais vídeos, fale com o administrador para aumentar o limite.",
        ]
    )


def _visita_video_duplicate_message() -> str:
    return "\n".join(
        [
            "⚠️ Este vídeo parece já ter sido enviado nesta visita.",
            "",
            "Para evitar duplicidade, ele não foi anexado novamente.",
            "",
            "Você pode enviar outro vídeo ou continuar o preenchimento da visita.",
        ]
    )


def _is_legacy_quick_visit(visita: dict) -> bool:
    if not str(visita.get("fazenda") or "").strip():
        return False
    return not any(
        str(visita.get(field) or "").strip()
        for field in (
            "descricao_visita",
            "objetivo",
            "observacoes",
            "observacoes_gerais",
        )
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
        ("area", "area"),
        ("localizacao_texto", "localizacao"),
    )
    for field, prefix in direct_patterns:
        if normalized_text == prefix or normalized_text.startswith(prefix + " "):
            value = text[len(text.split(maxsplit=1)[0]):].strip()
            if not value:
                return "Informe o valor junto com o comando."
            if field in {"area_hectares", "area_alqueires"}:
                value = _parse_visita_area(value)
            if field == "localizacao_texto":
                visitas_service.salvar_localizacao_textual(open_visit["id"], value)
            else:
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
        "aguardando_localizacao",
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
    index = _visita_media_display_index(media)
    return "\n".join(
        [
            f"Foto {index} adicionada ao relatorio.",
            "",
            f"Envie o comentario da Foto {index} ou digite \"pular\".",
            "",
            "1 - Sim, quero comentar",
            "2 - Nao, continuar sem comentario",
        ]
    )


def _visita_video_legenda_message(media: dict) -> str:
    index = _visita_media_display_index(media)
    return "\n".join(
        [
            f"Agora envie uma legenda rápida para o Vídeo {index} ou digite \"pular\".",
            "Exemplo: Área com falha perto da entrada da fazenda.",
        ]
    )


def _visita_pending_media_message(media: dict) -> str:
    if str(media.get("tipo") or "") == "video":
        return _visita_video_legenda_message(media)
    return _visita_foto_comentario_message(media)


def _visita_media_display_index(media: dict) -> int:
    if str(media.get("tipo") or "") != "video":
        return int(media.get("indice") or 1)
    visita_id = media.get("visita_id")
    media_id = int(media.get("id") or 0)
    if not visita_id or not media_id:
        return int(media.get("indice") or 1)
    resumo = visitas_service.obter_visita_completa(int(visita_id)) or {}
    videos = [
        item
        for item in resumo.get("midias") or []
        if str(item.get("tipo") or "") == "video"
    ]
    videos.sort(key=lambda item: (str(item.get("enviado_em") or ""), int(item.get("id") or 0)))
    for index, item in enumerate(videos, start=1):
        if int(item.get("id") or 0) == media_id:
            return index
    return int(media.get("indice") or 1)


def _set_visita_pending_media_state(visita_id: int, media: dict, review_mode: bool = False) -> None:
    if str(media.get("tipo") or "") == "video":
        state = (
            f"aguardando_legenda_video_revisao:{media['id']}"
            if review_mode
            else f"aguardando_legenda_video:{media['id']}"
        )
    else:
        state = (
            "aguardando_decisao_comentario_foto_revisao"
            if review_mode
            else "aguardando_decisao_comentario_foto"
        )
    visitas_service.atualizar_campo(visita_id, "estado_fluxo", state)


def _visita_proxima_midia_ou_finaliza(
    visita_id: int,
    review_mode: bool = False,
    resolved_message: str | None = None,
) -> str:
    pending = visitas_service.proxima_midia_pendente(visita_id)
    if pending is not None:
        _set_visita_pending_media_state(visita_id, pending, review_mode=review_mode)
        parts = []
        if resolved_message:
            parts.append(resolved_message)
        parts.append(_visita_pending_media_message(pending))
        return "\n\n".join(parts)
    if review_mode:
        visitas_service.atualizar_campo(visita_id, "estado_fluxo", "aguardando_revisao_final")
        return _visita_midia_atualizada_message(resolved_message or "✅ Mídias atualizadas.")
    visitas_service.atualizar_campo(visita_id, "estado_fluxo", "visita_aberta")
    lines = []
    if resolved_message:
        lines.extend([resolved_message, ""])
    lines.extend(
        [
            "Fotos salvas no relatorio.",
            "",
            "Voce pode continuar enviando fotos, videos, adicionar mais informacoes ou finalizar a visita.",
            "",
            "Para finalizar, envie: fechar visita",
        ]
    )
    return "\n".join(lines)


def _visita_proxima_foto_ou_finaliza(visita_id: int, review_mode: bool = False) -> str:
    return _visita_proxima_midia_ou_finaliza(visita_id, review_mode=review_mode)


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
    visita_edit_states.pop(phone, None)
    visita_summary_confirmation_states.pop(phone, None)


def _existing_open_visita_choice_message(visita: dict) -> str:
    return _active_visita_menu_message(visita)


def _active_visita_menu_message(visita: dict) -> str:
    reviewing = str(visita.get("estado_fluxo") or "") == "aguardando_revisao_final"
    return "\n".join(
        [
            "🌱 Visita em andamento",
            "",
            f"Visita #{visita.get('id')}",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Etapa: {'revisão antes da finalização' if reviewing else 'coleta de informações'}",
            "",
            f"Continuar visita: continuar visita {visita.get('id')}",
            "Revisar e finalizar: fechar visita",
            "Cancelar visita: cancelar visita",
        ]
    )


def _start_new_visita_flow(sender_phone: str) -> str:
    phone = normalize_phone(sender_phone)
    existing = visitas_service.obter_visita_aberta(phone)
    if existing is not None:
        visita_active_states[phone] = int(existing["id"])
        visita_new_visit_states.discard(phone)
        return _active_visita_menu_message(existing)
    visita_new_visit_states.add(phone)
    visita_recently_finalized_states.pop(phone, None)
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
    existing = visitas_service.obter_visita_aberta(sender_phone)
    if existing is not None:
        visita_new_visit_states.discard(phone)
        visita_active_states[phone] = int(existing["id"])
        return _active_visita_menu_message(existing)
    visita = visitas_service.iniciar_visita(
        sender_phone,
        tecnico_nome=(collaborator or {}).get("nome"),
        fazenda=farm,
        estado_fluxo="visita_aberta",
    )
    if not visita.pop("_created", True):
        visita_new_visit_states.discard(phone)
        visita_active_states[phone] = int(visita["id"])
        return _active_visita_menu_message(visita)
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
            "* tamanho",
            "* safra",
            "* tipo",
            "* observações",
            "* data",
            "",
            "Exemplos:",
            "gerente = Marcos Silva",
            "tamanho = 250 hectares",
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
            "Campos aceitos: fazenda, proprietário, gerente, tamanho, safra, tipo, observações, data.",
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
        "area": "area",
        "tamanho": "area",
        "tamanho total": "area",
        "tamanho propriedade": "area",
        "tamanho da propriedade": "area",
        "tamanho fazenda": "area",
        "tamanho da fazenda": "area",
        "localizacao": "localizacao_texto",
        "localizacao fazenda": "localizacao_texto",
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


def _visita_status_message(visita: dict) -> str:
    return "\n".join(
        [
            "Visita em andamento.",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Proprietário: {visita.get('proprietario') or '-'}",
            f"Gerente: {visita.get('gerente') or '-'}",
            f"Tamanho total: {visita.get('area') or '-'}",
            f"Descrição da visita: {visitas_service.descricao_da_visita(visita) or '-'}",
        ]
    )


def _start_visita_review(sender_phone: str, visita_id: int) -> str:
    visitas_service.atualizar_campo(visita_id, "estado_fluxo", "aguardando_revisao_final")
    visita = visitas_service.obter_visita_completa(visita_id)
    if visita is not None:
        visita = dict(visita)
        visita["report_kind"] = "preview"
        _send_visita_pdf_data(sender_phone, visita)
    return _visita_revisao_final_message()


def _finalize_visita(sender_phone: str, visita: dict) -> str:
    visita_id = int(visita["id"])
    current = visitas_service.obter_visita(visita_id)
    if current is None:
        return NO_OPEN_VISITA_MESSAGE
    if current.get("status") == "fechada":
        _clear_active_visita(sender_phone, visita_id)
        return "Esta visita já foi finalizada."
    visita_completa = visitas_service.obter_visita_completa(visita_id) or current
    snapshot = dict(visita_completa)
    snapshot.update(status="fechada", estado_fluxo="fechada", fechado_em=_now())
    try:
        build_visita_pdf(snapshot)
    except Exception:
        logger.exception("Falha ao gerar PDF ao fechar visita %s", visita_id)
        return "❌ Não foi possível gerar o PDF final. A visita permanece aberta."
    closed = visitas_service.fechar_visita(visita_id)
    _clear_active_visita(sender_phone, visita_id)
    visita_recently_finalized_states[normalize_phone(sender_phone)] = visita_id
    final_data = visitas_service.obter_visita_completa(visita_id) or closed
    _send_visita_pdf_data(sender_phone, final_data)
    return _visita_finalizada_message(closed)


def _visita_revisao_final_message() -> str:
    menu_lines = [
        "1. Finalizar visita",
        "2. Corrigir dados da propriedade",
        "3. Corrigir descrição da visita",
        "4. Corrigir observações",
        "5. Gerar nova prévia",
        "6. Apagar foto",
        "7. Apagar vídeo",
        "8. Voltar sem finalizar",
    ]
    return "\n".join(
        [
            "📄 Prévia do relatório enviada.",
            "",
            "Revise os dados antes de finalizar a visita.",
            "",
            "Você ainda pode corrigir informações ou enviar mais fotos, vídeos e localização antes de finalizar.",
            "",
            "O que deseja fazer agora?",
            "",
            *menu_lines,
            "",
            "A visita ainda não foi finalizada.",
        ]
    )
    return "\n".join(
        [
            "📄 Prévia do relatório enviada.",
            "",
            "Revise os dados antes de finalizar a visita.",
            "",
            "Você ainda pode corrigir informações ou enviar mais fotos, vídeos e localização antes de finalizar.",
            "",
            "O que deseja fazer agora?",
            "",
            "1. Finalizar visita",
            "2. Corrigir dados da propriedade",
            "3. Corrigir descrição da visita",
            "4. Corrigir observações",
            "5. Enviar mais foto, vídeo ou localização",
            "6. Gerar nova prévia",
            "7. Voltar sem finalizar",
            "",
            "A visita ainda não foi finalizada.",
        ]
    )


def _visita_revisao_texto_atualizado_message() -> str:
    return "\n".join(
        [
            "✅ Informação atualizada.",
            "",
            "A prévia anterior pode estar desatualizada.",
            "Digite \"prévia\" para gerar o relatório atualizado ou \"finalizar\" para encerrar a visita.",
        ]
    )


def _visita_preview_outdated_hint() -> str:
    return "\n".join(
        [
            "A prévia anterior pode estar desatualizada.",
            "Digite \"prévia\" para gerar o relatório atualizado ou envie mais informações antes de finalizar.",
        ]
    )


def _visita_midia_atualizada_message(title: str) -> str:
    return "\n\n".join([title, _visita_preview_outdated_hint()])


def _start_visita_media_delete(visita: dict, media_type: str) -> str:
    if str(visita.get("status") or "") == "fechada":
        return "Esta visita já foi finalizada. Não é possível apagar mídias."
    visita_id = int(visita["id"])
    medias = _visita_numbered_media(visita_id, media_type)
    if not medias:
        noun = "fotos" if media_type == "foto" else "vídeos"
        return f"Esta visita ainda não possui {noun} para apagar."
    visitas_service.atualizar_campo(visita_id, "estado_fluxo", f"aguardando_exclusao_{media_type}")
    return _visita_delete_media_list_message(visita_id, media_type)


def _visita_delete_media_list_message(visita_id: int, media_type: str, invalid: bool = False) -> str:
    medias = _visita_numbered_media(visita_id, media_type)
    if not medias:
        noun = "fotos" if media_type == "foto" else "vídeos"
        return f"Esta visita ainda não possui {noun} para apagar."
    title = "Fotos da visita:" if media_type == "foto" else "Vídeos da visita:"
    label = "foto" if media_type == "foto" else "vídeo"
    lines = []
    if invalid:
        lines.extend(["Número inválido. Responda com um número válido.", ""])
    lines.extend([title])
    for media in medias:
        number = int(media.get("numero_relatorio") or 1)
        comment = media.get("comentario") or media.get("legenda") or "Sem comentário informado."
        prefix = f"{number}. {'Foto' if media_type == 'foto' else 'Vídeo'} {number}"
        if comment == "Sem comentário informado.":
            detail = comment
        else:
            detail_name = "comentário" if media_type == "foto" else "legenda"
            detail = f"{detail_name}: {comment}"
        file_name = Path(str(media.get("caminho_arquivo") or "")).name
        if file_name:
            detail = f"{detail} ({file_name})"
        elif media_type == "video" and media.get("tamanho_bytes") not in (None, ""):
            detail = f"{detail} ({_format_visita_media_size(media.get('tamanho_bytes'))})"
        lines.append(f"{prefix} â€” {detail}")
    lines.extend(["", f"Responda com o número da {label} que deseja apagar.", "Digite \"cancelar\" para voltar à revisão."])
    return "\n".join(lines)


def _send_visita_delete_media_choice_interactive(
    to: str,
    visita_id: int,
    media_type: str,
    fallback_text: str,
) -> None:
    medias = _visita_numbered_media(visita_id, media_type)
    if not medias:
        _safe_send_text(to, fallback_text)
        return

    body = _visita_delete_media_choice_body(visita_id, media_type)
    if len(medias) <= 2:
        buttons = [
            {
                "id": f"visita_apagar_{media_type}_{int(media.get('numero_relatorio') or 1)}",
                "title": f"{'Foto' if media_type == 'foto' else 'Vídeo'} {int(media.get('numero_relatorio') or 1)}",
            }
            for media in medias
        ]
        buttons.append({"id": f"visita_apagar_{media_type}_cancelar", "title": "Cancelar"})
        send_whatsapp_button_message(to=to, body=body, buttons=buttons)
        return

    rows = [
        {
            "id": f"visita_apagar_{media_type}_{int(media.get('numero_relatorio') or 1)}",
            "title": f"{'Foto' if media_type == 'foto' else 'Vídeo'} {int(media.get('numero_relatorio') or 1)}",
            "description": _visita_media_short_description(media),
        }
        for media in medias
    ]
    rows.append(
        {
            "id": f"visita_apagar_{media_type}_cancelar",
            "title": "Cancelar",
            "description": "Voltar para a revisão",
        }
    )
    send_whatsapp_list_message(
        to=to,
        header="Apagar foto" if media_type == "foto" else "Apagar vídeo",
        body=body,
        button_text="Escolher",
        sections=[{"title": "Mídias da visita", "rows": rows}],
        fallback_text=fallback_text,
    )


def _visita_delete_media_choice_body(visita_id: int, media_type: str) -> str:
    text = _visita_delete_media_list_message(visita_id, media_type)
    marker = "Responda com o n"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
    return "\n".join(
        [
            text,
            "",
            f"Escolha qual {'foto' if media_type == 'foto' else 'vídeo'} deseja apagar.",
        ]
    )


def _visita_media_short_description(media: dict) -> str:
    comment = str(media.get("comentario") or media.get("legenda") or "Sem comentário informado.").strip()
    if len(comment) > 68:
        return comment[:65].rstrip() + "..."
    return comment


def _send_visita_delete_confirmation_buttons(to: str, fallback_text: str) -> None:
    send_whatsapp_button_message(
        to=to,
        body=fallback_text,
        buttons=[
            {"id": "visita_confirmar_apagar_midia_sim", "title": "Sim"},
            {"id": "visita_confirmar_apagar_midia_nao", "title": "Não"},
        ],
    )


def _visita_numbered_media(visita_id: int, media_type: str) -> list[dict]:
    medias = visitas_service.listar_midias_por_tipo(visita_id, media_type)
    numbered = []
    for index, media in enumerate(medias, start=1):
        item = dict(media)
        item["numero_relatorio"] = index
        numbered.append(item)
    return numbered


def _visita_media_by_current_number(visita_id: int, media_type: str, value: str) -> dict | None:
    try:
        selected = int(str(value or "").strip())
    except ValueError:
        return None
    if selected < 1:
        return None
    for media in _visita_numbered_media(visita_id, media_type):
        if int(media.get("numero_relatorio") or 0) == selected:
            return media
    return None


def _delete_visita_media(visita: dict, media_id: int) -> dict | None:
    if str(visita.get("status") or "") == "fechada":
        return None
    visita_id = int(visita["id"])
    media = visitas_service.obter_midia(media_id)
    if media is None or int(media.get("visita_id") or 0) != visita_id:
        return None
    removed = visitas_service.remover_midia(visita_id, media_id)
    if removed is None:
        return None
    _cleanup_removed_visita_media(removed)
    return removed


def _cleanup_removed_visita_media(media: dict) -> None:
    local_path = Path(str(media.get("caminho_arquivo") or "").strip())
    if str(local_path) not in {"", "."} and local_path.is_file():
        try:
            local_path.unlink()
        except OSError as exc:
            logger.warning("Nao foi possivel remover arquivo local da visita: arquivo=%s erro=%s", local_path, exc)
    storage_key = str(media.get("storage_key") or "").strip().lstrip("/")
    if str(media.get("tipo") or "") == "video" and storage_key.startswith("visitas/"):
        try:
            delete_storage_file(storage_key)
        except (ObjectStorageError, Exception) as exc:
            logger.warning("Nao foi possivel remover video da visita no storage: storage_key=%s erro=%s", storage_key, exc)


def _format_visita_media_size(value: object) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _visita_closed_media_message_if_applicable(sender_phone: str) -> str | None:
    visita = visitas_service.obter_ultima_visita(sender_phone)
    if visita is not None and visita.get("status") == "fechada":
        return VISITA_CLOSED_MEDIA_MESSAGE
    return None


def _visita_finalizada_delete_media_message_if_applicable(sender_phone: str) -> str | None:
    visita = visitas_service.obter_ultima_visita(sender_phone)
    if visita is not None and visita.get("status") == "fechada":
        return "Esta visita já foi finalizada. Não é possível apagar mídias."
    return None


def _is_maps_location_text(value: str) -> bool:
    normalized = _normalize_caption(value)
    return (
        "maps.google" in normalized
        or "google.com/maps" in normalized
        or "maps.app.goo.gl" in normalized
        or "goo.gl/maps" in normalized
    )


def _visita_finalizada_message(visita: dict) -> str:
    return "\n".join(
        [
            "✅ Visita finalizada com sucesso.",
            "",
            "O relatório foi marcado como finalizado.",
            "",
            f"Fazenda: {visita.get('fazenda') or '-'}",
            f"Gerente: {visita.get('gerente') or '-'}",
        ]
    )


def _visita_state_is_text_review(visita: dict) -> bool:
    state = str(visita.get("estado_fluxo") or "")
    return state == "aguardando_revisao_final" or state in {
        "corrigindo_dados_propriedade",
        "aguardando_edicao_descricao",
        "corrigindo_observacoes",
        "aguardando_adicao_observacao",
        "aguardando_remocao_observacao",
        "aguardando_reescrita_observacoes",
    } or state.startswith("aguardando_edicao_campo:")


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
        f"Tamanho total da fazenda/propriedade: {resumo.get('area') or '-'}",
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
            "6 - Localização da fazenda/propriedade",
            "7 - Tamanho total da fazenda/propriedade",
            "8 - Voltar",
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
            f"Tamanho total: {visita.get('area') or '-'}",
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


VISITA_LIST_MESSAGE_MAX_CHARS = 3500


def _listar_visitas_message(normalized_text: str) -> str:
    """Compatibilidade: junta as partes geradas pela listagem paginada."""
    return "\n\n".join(_listar_visitas_messages(normalized_text))



def _listar_visitas_messages(normalized_text: str) -> list[str]:
    filters = {}
    if normalized_text == "visitas hoje":
        filters["periodo"] = "hoje"
    if normalized_text == "visitas abertas":
        filters["status"] = "aberta"
    data = visitas_service.listar_visitas_validas(**filters)
    visitas = data.get("visitas") or []
    if not visitas:
        return [NO_VALID_VISITA_MESSAGE]

    title = _visita_list_title(normalized_text, len(visitas))
    visit_blocks = [
        "\n".join(_format_visita_list_item(visita, detailed=True))
        for visita in visitas
    ]
    instructions = "\n".join(
        [
            "Para gerar PDF individual de uma visita, envie:",
            f"relatÃ³rio visita {visitas[0]['id']}",
            "",
            "Para buscar por fazenda, envie:",
            f"relatÃ³rio fazenda {visitas[0].get('fazenda') or 'Nome da Fazenda'}",
        ]
    )
    return _chunk_visita_list_messages(title, visit_blocks, instructions)


def _visita_list_title(normalized_text: str, total: int) -> str:
    if normalized_text == "visitas abertas":
        return f"Visitas abertas encontradas: {total}"
    if normalized_text == "visitas hoje":
        return f"Visitas tÃ©cnicas encontradas hoje: {total}"
    return f"Visitas tÃ©cnicas encontradas: {total}"


def _chunk_visita_list_messages(
    title: str,
    visit_blocks: list[str],
    instructions: str,
    max_chars: int = VISITA_LIST_MESSAGE_MAX_CHARS,
) -> list[str]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for block in visit_blocks:
        candidate = current + [block]
        if current and len("\n\n".join([title, *candidate, instructions])) > max_chars:
            chunks.append(current)
            current = [block]
            continue
        current = candidate
    if current:
        chunks.append(current)

    total_parts = len(chunks)
    messages: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        header = title
        if total_parts > 1:
            header = f"{title}\nParte {index} de {total_parts}"
        parts = [header, *chunk]
        if index == total_parts:
            parts.append(instructions)
        messages.append("\n\n".join(parts).strip())
    return messages


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
    try:
        _send_visita_pdf_data(sender_phone, visita)
    except Exception:
        _safe_send_text(
            sender_phone,
            "❌ Não foi possível gerar o PDF do relatório. O conteúdo pode ser muito extenso. "
            "Tente reduzir as descrições ou observações e tente novamente.",
        )
        return True  # Return True to indicate we handled the command, even though it failed
    return True


def _send_visita_pdf_data(sender_phone: str, visita: dict) -> None:
    try:
        content = build_visita_pdf(visita)
    except Exception as exc:
        logger.exception(
            "Falha ao gerar PDF da visita %s: %s",
            visita.get("id"),
            exc,
        )
        # Re-raise to let caller handle the failure
        raise
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
    rdv_receipt_review_states.clear()
    rdv_comment_states.clear()
    standalone_transcription_modes.clear()
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
        except WhatsAppSendError:
            raise
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
        except WhatsAppSendError:
            raise
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


def _start_rdv_receipt_review(
    sender_phone: str,
    caminho_arquivo: str,
    whatsapp_message_id: str,
    message_type: str,
    received_at: str | datetime | None,
    analysis: dict,
) -> dict:
    collaborator = rdv_service.get_collaborator_by_phone(sender_phone)
    if collaborator is None:
        raise ValueError("Remetente nao cadastrado como colaborador RDV.")
    input_type = message_type if message_type in {"image", "document"} else "document"
    pending = {
        "collaborator_id": collaborator["id"],
        "collaborator": collaborator["nome"],
        "phone": sender_phone,
        "input_type": {"image": "imagem", "document": "documento"}[input_type],
        "file_path": caminho_arquivo,
        "whatsapp_message_id": whatsapp_message_id,
        "received_at": received_at,
        "analysis": dict(analysis or {}),
        "valor": analysis.get("valor_detectado"),
        "data": analysis.get("data_detectada") or "",
        "categoria": "outro",
        "comentario": _receipt_default_observation(),
        "source": _analysis_source_label(analysis),
        "status": RDV_REVIEW_CONFIRM_STATE,
    }
    rdv_receipt_review_states[sender_phone] = pending
    whatsapp_menu_states[sender_phone] = RDV_REVIEW_CONFIRM_STATE
    logger.info(
        "RDV pendente de revisao criado: from=%s message_id=%s fonte=%s reasons=%s",
        _mask_phone(sender_phone),
        _mask_message_id(whatsapp_message_id),
        pending["source"],
        (analysis or {}).get("reasons"),
    )
    return pending


def _get_rdv_receipt_review(sender_phone: str) -> dict | None:
    pending = rdv_receipt_review_states.get(sender_phone)
    if not pending:
        if whatsapp_menu_states.get(sender_phone) in {
            RDV_REVIEW_CONFIRM_STATE,
            RDV_REVIEW_EDIT_VALUE_STATE,
            RDV_REVIEW_EDIT_DATE_STATE,
            RDV_REVIEW_EDIT_CATEGORY_STATE,
            RDV_REVIEW_EDIT_COMMENT_STATE,
        }:
            whatsapp_menu_states.pop(sender_phone, None)
        return None
    return pending


def _clear_rdv_receipt_review(sender_phone: str) -> None:
    rdv_receipt_review_states.pop(sender_phone, None)
    if whatsapp_menu_states.get(sender_phone) in {
        RDV_REVIEW_CONFIRM_STATE,
        RDV_REVIEW_EDIT_VALUE_STATE,
        RDV_REVIEW_EDIT_DATE_STATE,
        RDV_REVIEW_EDIT_CATEGORY_STATE,
        RDV_REVIEW_EDIT_COMMENT_STATE,
    }:
        whatsapp_menu_states.pop(sender_phone, None)


def _rdv_review_message(pending: dict) -> str:
    return "\n".join(
        [
            "Revise o RDV antes de salvar",
            "",
            f"Data: {_format_date_br(pending.get('data')) or '-'}",
            f"Valor: {_format_brl_text(pending.get('valor'))}",
            f"Categoria: {_category_label(pending.get('categoria') or 'outro')}",
            f"Comentario: {pending.get('comentario') or '-'}",
            f"Fonte da leitura: {pending.get('source') or '-'}",
        ]
    )


def _rdv_review_fallback_message(pending: dict) -> str:
    return "\n".join(
        [
            _rdv_review_message(pending),
            "",
            "Toque no menu abaixo para confirmar ou editar.",
            "",
            "1. Confirmar e salvar",
            "2. Editar valor",
            "3. Editar data",
            "4. Editar categoria",
            "5. Editar comentario",
            "6. Cancelar lancamento",
        ]
    )


def _analysis_source_label(analysis: dict | None) -> str:
    source = str((analysis or {}).get("origem_valor") or "").strip().lower()
    if source == "qr_code":
        return "QR Code"
    if source == "ocr":
        return "OCR"
    reasons = {str(reason or "") for reason in (analysis or {}).get("reasons") or []}
    if "qr_code_detectado" in reasons:
        return "QR Code"
    if any(reason.startswith("valor_encontrado_ocr") for reason in reasons):
        return "OCR"
    return "Manual"


def _source_to_origin_value(source: str) -> str:
    normalized = _normalize_caption(source)
    if normalized == "qr code":
        return "qr_code"
    if normalized == "ocr":
        return "ocr"
    return "manual"


def _receipt_default_observation() -> str:
    return "comprovante recebido pelo WhatsApp"


def _handle_rdv_receipt_review_message(
    sender_phone: str,
    text: str,
    normalized: str,
    *,
    is_audio_transcription: bool = False,
) -> tuple[bool, str | None]:
    pending = _get_rdv_receipt_review(sender_phone)
    if pending is None:
        return False, None

    state = whatsapp_menu_states.get(sender_phone) or RDV_REVIEW_CONFIRM_STATE
    if normalized in {"cancelar", "sair"}:
        _clear_rdv_receipt_review(sender_phone)
        return True, RDV_RECEIPT_CANCEL_MESSAGE

    if state == RDV_REVIEW_EDIT_VALUE_STATE:
        value = _parse_rdv_value(text)
        if value is None:
            return True, "Valor invalido. Informe somente o valor, por exemplo: 125,50"
        pending["valor"] = value
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_CONFIRM_STATE
        return True, _rdv_review_fallback_message(pending)

    if state == RDV_REVIEW_EDIT_DATE_STATE:
        try:
            receipt_date = parse_receipt_date(text)
        except ValueError:
            return True, "Data invalida. Informe a data do comprovante no formato 11/06/2026."
        pending["data"] = receipt_date.isoformat()
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_CONFIRM_STATE
        return True, _rdv_review_fallback_message(pending)

    if state == RDV_REVIEW_EDIT_CATEGORY_STATE:
        category = _match_numbered_choice(text, RDV_CATEGORIES)
        if category is None:
            return True, _category_prompt("Categoria invalida.")
        pending["categoria"] = category
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_CONFIRM_STATE
        return True, _rdv_review_fallback_message(pending)

    if state == RDV_REVIEW_EDIT_COMMENT_STATE:
        comment = str(text or "").strip()
        if not is_audio_transcription and normalized in {"3", "sem comentario", "pular"}:
            comment = ""
        pending["comentario"] = comment
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_CONFIRM_STATE
        return True, _rdv_review_fallback_message(pending)

    selected = {
        "1": "confirm",
        "confirmar": "confirm",
        "confirmar e salvar": "confirm",
        "2": "edit_value",
        "editar valor": "edit_value",
        "3": "edit_date",
        "editar data": "edit_date",
        "4": "edit_category",
        "editar categoria": "edit_category",
        "5": "edit_comment",
        "editar comentario": "edit_comment",
        "6": "cancel",
        "cancelar lancamento": "cancel",
    }.get(normalized)
    if selected == "confirm":
        return True, _confirm_rdv_receipt_review(sender_phone, pending)
    if selected == "edit_value":
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_EDIT_VALUE_STATE
        return True, "Informe o valor correto. Exemplo: 150,00"
    if selected == "edit_date":
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_EDIT_DATE_STATE
        return True, "Informe a data correta do comprovante. Exemplo: 06/07/2026"
    if selected == "edit_category":
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_EDIT_CATEGORY_STATE
        return True, _category_prompt("Escolha a categoria correta.")
    if selected == "edit_comment":
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_EDIT_COMMENT_STATE
        return True, "Digite o comentario correto ou envie um audio."
    if selected == "cancel":
        _clear_rdv_receipt_review(sender_phone)
        return True, RDV_RECEIPT_CANCEL_MESSAGE
    return True, _rdv_review_fallback_message(pending)


def _confirm_rdv_receipt_review(sender_phone: str, pending: dict) -> str:
    value = _parse_rdv_value(str(pending.get("valor") or ""))
    if value is None:
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_EDIT_VALUE_STATE
        return "Valor invalido ou ausente. Informe o valor correto. Exemplo: 150,00"
    try:
        receipt_date = parse_receipt_date(pending.get("data") or "")
    except ValueError:
        whatsapp_menu_states[sender_phone] = RDV_REVIEW_EDIT_DATE_STATE
        return "Data invalida ou ausente. Informe a data do comprovante no formato 11/06/2026."

    analysis = dict(pending.get("analysis") or {})
    analysis.update(
        {
            "valor_detectado": value,
            "data_detectada": receipt_date.isoformat(),
            "origem_valor": _source_to_origin_value(pending.get("source") or ""),
        }
    )
    expense = rdv_service.create_whatsapp_receipt(
        collaborator_id=pending["collaborator_id"],
        phone=sender_phone,
        input_type=pending["input_type"],
        file_path=pending["file_path"],
        whatsapp_message_id=pending["whatsapp_message_id"],
        received_at=pending.get("received_at"),
        observation=pending.get("comentario") or "",
        analysis=analysis,
    )
    expense = rdv_service.complete_launch_category(expense["id"], pending["categoria"])
    if pending.get("comentario") != expense.get("observacao"):
        expense = rdv_service.save_launch_observation(
            expense["id"],
            pending.get("comentario") or "",
        )
    _clear_rdv_receipt_review(sender_phone)
    logger.info(
        "RDV revisado confirmado: from=%s message_id=%s rdv_id=%s fonte=%s",
        _mask_phone(sender_phone),
        _mask_message_id(pending.get("whatsapp_message_id") or ""),
        expense.get("id"),
        pending.get("source"),
    )
    return "\n".join(_rdv_completed_lines(expense))


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
    dynamic_command = _interactive_visit_command(reply_id)
    if dynamic_command:
        return dynamic_command

    interactive = message.get("interactive") or {}
    if not isinstance(interactive, dict):
        return ""
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    if not isinstance(reply, dict):
        return ""
    title = str(reply.get("title") or "").strip()
    return title


def _interactive_visit_command(reply_id: str) -> str:
    match = re.fullmatch(r"visita_apagar_(foto|video)_(\d+)", str(reply_id or "").strip())
    if match:
        return match.group(2)
    return ""


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


def _safe_send_text_chunks(to: str, message: str, max_chars: int = 4000) -> None:
    remaining = str(message or "").strip()
    while remaining:
        if len(remaining) <= max_chars:
            _safe_send_text(to, remaining)
            return
        split_at = remaining.rfind("\n", 0, max_chars + 1)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        _safe_send_text(to, remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()


def _send_rdv_reply(to: str, command_text: str, reply: str) -> None:
    normalized = _normalize_caption(command_text)
    try:
        if normalized in MENU_OPEN_COMMANDS and reply == MAIN_MENU_MESSAGE:
            send_main_menu_interactive(to)
            return
        if normalized == "relatorios" and reply == REPORTS_MENU_MESSAGE:
            send_reports_menu_interactive(to)
            return
        if reply == _visita_revisao_final_message():
            send_visita_review_menu_interactive(to, fallback_text=reply)
            return
        open_visit = visitas_service.obter_visita_aberta(to)
        if open_visit is not None:
            state = str(open_visit.get("estado_fluxo") or "")
            if state == "aguardando_exclusao_foto":
                _send_visita_delete_media_choice_interactive(
                    to,
                    int(open_visit["id"]),
                    "foto",
                    fallback_text=reply,
                )
                return
            if state == "aguardando_exclusao_video":
                _send_visita_delete_media_choice_interactive(
                    to,
                    int(open_visit["id"]),
                    "video",
                    fallback_text=reply,
                )
                return
            if (
                state.startswith("aguardando_confirmacao_exclusao_foto:")
                or state.startswith("aguardando_confirmacao_exclusao_video:")
            ):
                _send_visita_delete_confirmation_buttons(to, fallback_text=reply)
                return
        if normalized in KM_CLEAR_REQUEST_COMMANDS and reply == KM_CLEAR_WARNING:
            send_confirmation_buttons(
                to,
                KM_CLEAR_WARNING,
                confirm_id="confirm_clear_km",
                confirm_title="Limpar KM",
            )
            return
    except WhatsAppSendError as exc:
        if not exc.fallback_allowed:
            raise
        logger.warning(
            "Falha permanente ao enviar mensagem interativa; usando fallback texto: to=%s category=%s",
            _mask_phone(to),
            exc.category,
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
