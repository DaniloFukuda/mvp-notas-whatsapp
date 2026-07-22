import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


def _install_services_with_assistente(temp_dir):
    """Instala serviços e limpa estados do Assistente."""
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    api_whatsapp.rdv_service = rdv
    api_whatsapp.visitas_service = visitas
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    api_whatsapp.assistente_inteligente_states.clear()
    collaborator = rdv.get_collaborator_by_phone("5500000000001")
    return rdv, visitas, collaborator["telefone_whatsapp"]


def test_contacts_com_assistente_ativo():
    """Quando Assistente ativo, contacts recebe resposta padrão de mídia (não chama provider)."""
    import os
    os.environ["ASSISTENTE_INTELIGENTE_ENABLED"] = "true"
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_send_text = api_whatsapp.send_whatsapp_text
    original_download = api_whatsapp.download_media
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services_with_assistente(temp_dir)
            sent = []
            api_whatsapp.send_whatsapp_text = lambda to, msg: sent.append((to, msg))
            download_called = []
            api_whatsapp.download_media = lambda *a, **k: download_called.append(True)

            # Ativa Assistente
            api_whatsapp.handle_rdv_text_message(sender, "assistente")
            assert api_whatsapp._assistente_active(sender)

            # Envia contato
            message = {
                "from": sender,
                "id": "wamid.contacts",
                "type": "contacts",
                "contacts": [{"name": {"formatted_name": "João Silva"}, "phones": [{"phone": "5511999999999"}]}],
                "timestamp": "1700000000",
            }
            api_whatsapp._handle_whatsapp_message(message)

            # Verificações
            assert len(sent) == 1
            to, text = sent[0]
            assert to == sender
            # Resposta padrão de mídia do Assistente
            assert "apenas mensagens de texto" in text.lower() or "texto" in text.lower()
            # Não tentou baixar mídia
            assert not download_called
            # Assistente permanece ativo
            assert api_whatsapp._assistente_active(sender)
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_text = original_send_text
        api_whatsapp.download_media = original_download
        api_whatsapp.assistente_inteligente_states.clear()
        os.environ.pop("ASSISTENTE_INTELIGENTE_ENABLED", None)


def test_contacts_com_assistente_inativo():
    """Quando Assistente inativo, contacts recebe resposta explícita de não suportada."""
    import os
    os.environ["ASSISTENTE_INTELIGENTE_ENABLED"] = "false"
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_send_text = api_whatsapp.send_whatsapp_text
    original_download = api_whatsapp.download_media
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services_with_assistente(temp_dir)
            sent = []
            api_whatsapp.send_whatsapp_text = lambda to, msg: sent.append((to, msg))
            download_called = []
            api_whatsapp.download_media = lambda *a, **k: download_called.append(True)

            # Garante Assistente INATIVO
            assert not api_whatsapp._assistente_active(sender)

            # Envia contato
            message = {
                "from": sender,
                "id": "wamid.contacts2",
                "type": "contacts",
                "contacts": [{"name": {"formatted_name": "Maria"}, "phones": [{"phone": "5521888888888"}]}],
                "timestamp": "1700000000",
            }
            api_whatsapp._handle_whatsapp_message(message)

            # Verificações
            assert len(sent) == 1
            to, text = sent[0]
            assert to == sender
            # Resposta explícita para contacts
            assert "contato" in text.lower() or "📇" in text
            assert "não consigo processar" in text.lower() or "processar" in text.lower()
            # Não tentou baixar mídia
            assert not download_called
            # Assistente continua inativo
            assert not api_whatsapp._assistente_active(sender)
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_text = original_send_text
        api_whatsapp.download_media = original_download
        api_whatsapp.assistente_inteligente_states.clear()
        os.environ.pop("ASSISTENTE_INTELIGENTE_ENABLED", None)


def test_contacts_payload_vazio_ou_incompleto_nao_quebra():
    """Payload contacts vazio ou malformado não deve lançar exceção."""
    import os
    os.environ["ASSISTENTE_INTELIGENTE_ENABLED"] = "false"
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    original_send_text = api_whatsapp.send_whatsapp_text
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rdv, visitas, sender = _install_services_with_assistente(temp_dir)
            sent = []
            api_whatsapp.send_whatsapp_text = lambda to, msg: sent.append((to, msg))

            # Assistente inativo
            assert not api_whatsapp._assistente_active(sender)

            # Payload contacts vazio
            message = {
                "from": sender,
                "id": "wamid.contacts3",
                "type": "contacts",
                "contacts": [],
                "timestamp": "1700000000",
            }
            api_whatsapp._handle_whatsapp_message(message)

            assert len(sent) == 1
            # Resposta enviada sem erro
            assert sent[0][0] == sender
    finally:
        api_whatsapp.rdv_service = original_rdv
        api_whatsapp.visitas_service = original_visitas
        api_whatsapp.send_whatsapp_text = original_send_text
        api_whatsapp.assistente_inteligente_states.clear()
        os.environ.pop("ASSISTENTE_INTELIGENTE_ENABLED", None)