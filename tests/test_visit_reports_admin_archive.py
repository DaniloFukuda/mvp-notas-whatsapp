import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

import api_whatsapp
from scripts.mark_test_visits import mark_test_visits
from services.rdv_service import RDVService
from services.visit_reports_auth import is_reports_manager, reports_manager_phones
from services.visitas_migration import migrate_add_is_test
from services.visitas_service import VisitasTecnicasService


OWNER = "5500000000001"
OTHER = "5500000000002"


@pytest.fixture(autouse=True)
def _restore_api_services_and_state():
    original_rdv = api_whatsapp.rdv_service
    original_visitas = api_whatsapp.visitas_service
    yield
    api_whatsapp.rdv_service = original_rdv
    api_whatsapp.visitas_service = original_visitas
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_active_states.clear()
    api_whatsapp.visita_new_visit_states.clear()
    api_whatsapp.visita_edit_states.clear()


def _install(root: str):
    api_whatsapp.rdv_service = RDVService(Path(root) / "rdv.db")
    api_whatsapp.visitas_service = VisitasTecnicasService(Path(root) / "visitas.db")
    api_whatsapp.whatsapp_menu_states.clear()
    api_whatsapp.visita_active_states.clear()
    return api_whatsapp.visitas_service


def _closed(service, phone: str, farm: str):
    visit = service.iniciar_visita(phone, tecnico_nome=f"Técnico {phone[-1]}", fazenda=farm)
    return service.fechar_visita(visit["id"])


def _set_test(service, visit_id: int, value: int = 1):
    with closing(sqlite3.connect(service.db_path)) as connection:
        connection.execute(
            "UPDATE visitas_tecnicas SET is_test=? WHERE id=?", (value, visit_id)
        )
        connection.commit()


def _is_test(service, visit_id: int) -> int:
    with closing(sqlite3.connect(service.db_path)) as connection:
        return int(
            connection.execute(
                "SELECT is_test FROM visitas_tecnicas WHERE id=?", (visit_id,)
            ).fetchone()[0]
        )


def _legacy_db(path: Path):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE visitas_tecnicas ("
            "id INTEGER PRIMARY KEY, telefone_origem TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'aberta', criado_em TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO visitas_tecnicas VALUES (1, '5500000000001', 'fechada', '2026-01-01')"
        )
        connection.commit()


def test_adm01_banco_novo_tem_is_test_default_zero():
    with tempfile.TemporaryDirectory() as root:
        service = VisitasTecnicasService(Path(root) / "new.db")
        visit = service.iniciar_visita(OWNER, fazenda="Nova")
        assert _is_test(service, visit["id"]) == 0


def test_adm02_05_migration_legada_idempotente_preserva_dados():
    with tempfile.TemporaryDirectory() as root:
        path = Path(root) / "legacy.db"
        _legacy_db(path)
        assert migrate_add_is_test(path) is True
        assert migrate_add_is_test(path) is False
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute(
                "SELECT id, telefone_origem, status, criado_em, is_test FROM visitas_tecnicas"
            ).fetchone()
        assert row == (1, OWNER, "fechada", "2026-01-01", 0)


def test_adm06_10_usuario_comum_respeita_owner_test_e_id(monkeypatch):
    monkeypatch.delenv("REPORTS_MANAGER_PHONES", raising=False)
    with tempfile.TemporaryDirectory() as root:
        service = _install(root)
        own = _closed(service, OWNER, "Própria")
        foreign = _closed(service, OTHER, "Alheia")
        archived = _closed(service, OWNER, "Teste")
        _set_test(service, archived["id"])
        visible = service.listar_relatorios_finalizados(OWNER, limite=20)
        assert [row["id"] for row in visible] == [own["id"]]
        assert api_whatsapp._select_visita_for_pdf(foreign["id"], OWNER) is None
        assert api_whatsapp._select_visita_for_pdf(archived["id"], OWNER) is None


def test_adm11_12_manager_config_normaliza_e_default_false(monkeypatch):
    monkeypatch.delenv("REPORTS_MANAGER_PHONES", raising=False)
    assert reports_manager_phones() == set()
    assert is_reports_manager(OWNER) is False
    monkeypatch.setenv("REPORTS_MANAGER_PHONES", "+55 (00) 00000-0001; 5500000000002")
    assert is_reports_manager(OWNER) is True
    assert is_reports_manager(OTHER) is True
    assert is_reports_manager("5500000000003") is False


def test_adm13_14_gestor_ve_escolha_de_escopo(monkeypatch):
    monkeypatch.setenv("REPORTS_MANAGER_PHONES", OWNER)
    captured = []
    monkeypatch.setattr(api_whatsapp, "send_whatsapp_list_message", lambda **kw: captured.append(kw))
    api_whatsapp.send_reports_menu_interactive(OWNER)
    rows = captured[0]["sections"][0]["rows"]
    assert [row["id"] for row in rows] == [
        "visit_reports:own:page:1",
        "visit_reports:team:page:1",
    ]
    assert "Meus relatórios" in rows[0]["title"]
    assert "Relatórios da equipe" in rows[1]["title"]


def test_adm15_19_gestor_lista_e_abre_equipe_sem_testes_ou_canceladas(monkeypatch):
    monkeypatch.setenv("REPORTS_MANAGER_PHONES", OWNER)
    with tempfile.TemporaryDirectory() as root:
        service = _install(root)
        own = _closed(service, OWNER, "Própria")
        foreign = _closed(service, OTHER, "Alheia")
        archived = _closed(service, OTHER, "Teste")
        _set_test(service, archived["id"])
        cancelled = service.iniciar_visita(OTHER, fazenda="Cancelada")
        service.cancelar_visita(cancelled["id"])
        captured = []
        monkeypatch.setattr(api_whatsapp, "send_whatsapp_list_message", lambda **kw: captured.append(kw))
        assert api_whatsapp._send_visit_reports_page(OWNER, "team", 1) is None
        rows = [r for r in captured[0]["sections"][0]["rows"] if r["id"].startswith("visita_relatorio_")]
        assert {r["id"] for r in rows} == {
            f"visita_relatorio_{own['id']}", f"visita_relatorio_{foreign['id']}"
        }
        assert all("Técnico" in r["description"] for r in rows)
        assert api_whatsapp._select_visita_for_pdf(foreign["id"], OWNER)["id"] == foreign["id"]
        assert api_whatsapp._select_visita_for_pdf(archived["id"], OWNER) is None
        assert api_whatsapp._select_visita_for_pdf(cancelled["id"], OWNER) is None
        assert service.obter_visita_por_id(foreign["id"])["telefone_origem"] == OTHER


def test_adm20_29_paginacao_estavel_sem_duplicar_pular_ou_vazar_phone(monkeypatch):
    monkeypatch.setenv("REPORTS_MANAGER_PHONES", OWNER)
    with tempfile.TemporaryDirectory() as root:
        service = _install(root)
        expected = []
        for index in range(23):
            expected.append(_closed(service, OTHER, f"Fazenda {index}")["id"])
        expected.reverse()
        captured = []
        monkeypatch.setattr(api_whatsapp, "send_whatsapp_list_message", lambda **kw: captured.append(kw))
        for page in (1, 2, 3):
            assert api_whatsapp._send_visit_reports_page(OWNER, "team", page) is None
        pages = []
        for payload in captured:
            rows = payload["sections"][0]["rows"]
            assert len(rows) <= 10
            assert all(OWNER not in row["id"] and OTHER not in row["id"] for row in rows)
            pages.append([
                int(row["id"].rsplit("_", 1)[1])
                for row in rows if row["id"].startswith("visita_relatorio_")
            ])
        assert pages[0] + pages[1] + pages[2] == expected
        assert not any(row["title"].endswith("Anterior") for row in captured[0]["sections"][0]["rows"])
        assert not any(row["title"].endswith("Próxima") for row in captured[-1]["sections"][0]["rows"])
        assert api_whatsapp._send_visit_reports_page(OWNER, "team", 99).startswith("Página")


def test_team_page_id_nao_concede_acesso_a_nao_gestor(monkeypatch):
    monkeypatch.delenv("REPORTS_MANAGER_PHONES", raising=False)
    assert api_whatsapp._send_visit_reports_page(OWNER, "team", 1) == "Relatório não encontrado."


def test_adm30_39_mark_tool_dry_run_apply_idempotente_unmark_e_dependencias():
    with tempfile.TemporaryDirectory() as root:
        service = VisitasTecnicasService(Path(root) / "visitas.db")
        first = service.iniciar_visita(OWNER, fazenda="A")
        service.adicionar_midia(first["id"], "foto", caminho_arquivo="foto.jpg")
        service.adicionar_localizacao(first["id"], -1, -2)
        service.cancelar_visita(first["id"])
        second = service.iniciar_visita(OWNER, fazenda="B")
        before = service.obter_visita_por_id(first["id"])
        assert mark_test_visits(service.db_path, [first["id"]])["dry_run"] is True
        assert _is_test(service, first["id"]) == 0
        mark_test_visits(service.db_path, [first["id"]], apply=True)
        mark_test_visits(service.db_path, [first["id"]], apply=True)
        after = service.obter_visita_por_id(first["id"])
        assert _is_test(service, first["id"]) == 1
        assert after["status"] == before["status"]
        assert after["telefone_origem"] == before["telefone_origem"]
        assert _is_test(service, second["id"]) == 0
        complete = service.obter_visita_completa(first["id"])
        assert len(complete["midias"]) == 1
        assert len(complete["localizacoes"]) == 1
        mark_test_visits(service.db_path, [first["id"]], apply=True, unmark=True)
        assert _is_test(service, first["id"]) == 0


def test_adm39_id_inexistente_nao_altera_banco():
    with tempfile.TemporaryDirectory() as root:
        service = VisitasTecnicasService(Path(root) / "visitas.db")
        visit = service.iniciar_visita(OWNER, fazenda="A")
        with pytest.raises(ValueError, match="inexistentes"):
            mark_test_visits(service.db_path, [visit["id"], 999], apply=True)
        assert _is_test(service, visit["id"]) == 0


def test_adm40_erro_transacional_faz_rollback():
    with tempfile.TemporaryDirectory() as root:
        service = VisitasTecnicasService(Path(root) / "visitas.db")
        one = service.iniciar_visita(OWNER, fazenda="A")
        service.cancelar_visita(one["id"])
        two = service.iniciar_visita(OWNER, fazenda="B")
        with pytest.raises(RuntimeError, match="simulada"):
            mark_test_visits(
                service.db_path, [one["id"], two["id"]], apply=True, _fail_after=1
            )
        assert _is_test(service, one["id"]) == 0
        assert _is_test(service, two["id"]) == 0
