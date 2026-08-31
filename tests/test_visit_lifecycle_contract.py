import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import api_whatsapp
from services.rdv_service import RDVService
from services.visitas_service import VisitasTecnicasService


PHONE = "5500000000001"


def _install(temp_dir, monkeypatch):
    rdv = RDVService(Path(temp_dir) / "rdv.db")
    visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
    monkeypatch.setattr(api_whatsapp, "rdv_service", rdv)
    monkeypatch.setattr(api_whatsapp, "visitas_service", visitas)
    monkeypatch.setattr(api_whatsapp, "_send_visita_pdf_data", lambda *args: None)
    monkeypatch.setattr(api_whatsapp, "build_visita_pdf", lambda data: b"%PDF-fake")
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    api_whatsapp.visita_edit_states.clear()
    api_whatsapp.visita_recently_finalized_states.clear()
    return visitas, rdv.get_collaborator_by_phone(PHONE)


def test_bug_real_review_menu_bloqueia_nova_e_finalizacao_libera(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas, collaborator = _install(temp_dir, monkeypatch)
        first = visitas.iniciar_visita(
            PHONE,
            tecnico_nome=collaborator["nome"],
            fazenda="Fazenda Um",
            estado_fluxo="visita_aberta",
        )

        review = api_whatsapp.handle_rdv_text_message(PHONE, "fechar visita")
        during_menu = api_whatsapp.handle_rdv_text_message(PHONE, "menu")
        blocked = api_whatsapp.handle_rdv_text_message(PHONE, "nova visita")

        assert "ainda não foi finalizada" in review
        assert "Visita em andamento" in during_menu
        assert "revisão" in during_menu
        assert "Visita em andamento" in blocked
        assert visitas.obter_visita_aberta(PHONE)["id"] == first["id"]

        finalized = api_whatsapp.handle_rdv_text_message(PHONE, "1")
        closed = visitas.obter_visita(first["id"])
        assert "finalizada com sucesso" in finalized
        assert closed["status"] == "fechada"
        assert closed["fechado_em"]
        assert visitas.obter_visita_aberta(PHONE) is None
        assert PHONE not in api_whatsapp.visita_active_states

        repeated = api_whatsapp.handle_rdv_text_message(PHONE, "1")
        closed_again = visitas.obter_visita(first["id"])
        assert repeated == "Esta visita já foi finalizada."
        assert closed_again["fechado_em"] == closed["fechado_em"]

        prompt = api_whatsapp.handle_rdv_text_message(PHONE, "nova visita")
        created = api_whatsapp.handle_rdv_text_message(PHONE, "Fazenda Dois")
        second = visitas.obter_visita_aberta(PHONE)
        assert "Qual o nome da fazenda" in prompt
        assert "Visita criada" in created
        assert second["id"] != first["id"]


def test_restart_recovery_usa_sqlite_e_bloqueia_segunda_visita(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas, collaborator = _install(temp_dir, monkeypatch)
        first = visitas.iniciar_visita(PHONE, tecnico_nome=collaborator["nome"])
        api_whatsapp.visita_active_states.clear()
        api_whatsapp.visita_new_visit_states.clear()

        menu = api_whatsapp.handle_rdv_text_message(PHONE, "menu")
        blocked = api_whatsapp.handle_rdv_text_message(PHONE, "nova visita")

        assert f"Visita #{first['id']}" in menu
        assert "Visita em andamento" in blocked
        assert visitas.obter_visita_aberta(PHONE)["id"] == first["id"]


def test_fechar_visita_service_e_idempotente(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas, collaborator = _install(temp_dir, monkeypatch)
        visita = visitas.iniciar_visita(PHONE, tecnico_nome=collaborator["nome"])
        first = visitas.fechar_visita(visita["id"])
        second = visitas.fechar_visita(visita["id"])

        assert first["status"] == second["status"] == "fechada"
        assert first["fechado_em"] == second["fechado_em"]


def test_cancelar_review_limpa_e_libera_nova_visita(monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas, collaborator = _install(temp_dir, monkeypatch)
        visita = visitas.iniciar_visita(
            PHONE, tecnico_nome=collaborator["nome"], estado_fluxo="visita_aberta"
        )
        api_whatsapp.handle_rdv_text_message(PHONE, "fechar visita")

        reply = api_whatsapp.handle_rdv_text_message(PHONE, "cancelar visita")
        canceled = visitas.obter_visita(visita["id"])

        assert "cancelada" in reply
        assert canceled["status"] == "cancelada"
        assert visitas.obter_visita_aberta(PHONE) is None
        assert "Qual o nome da fazenda" in api_whatsapp.handle_rdv_text_message(
            PHONE, "nova visita"
        )


def test_criacao_concorrente_mantem_uma_visita_ativa():
    with tempfile.TemporaryDirectory() as temp_dir:
        visitas = VisitasTecnicasService(Path(temp_dir) / "visitas.db")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: visitas.iniciar_visita(PHONE), range(2)))

        assert len({item["id"] for item in results}) == 1
        abertas = visitas.listar_visitas_validas(status="aberta")["visitas"]
        assert len(abertas) == 1
