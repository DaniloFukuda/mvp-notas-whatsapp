import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.visitas_service import VisitasTecnicasService


def test_visita_service_cria_schema_e_fluxo_basico():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")

        visita = service.iniciar_visita("55 (00) 0000-0001", tecnico_nome="Danilo")

        assert visita["telefone_origem"] == "550000000001"
        assert visita["tecnico_nome"] == "Danilo"
        assert visita["status"] == "aberta"
        assert visita["estado_fluxo"] == "aguardando_fazenda"
        assert service.obter_visita_aberta("550000000001")["id"] == visita["id"]


def test_visita_salvar_localizacao_preenche_ponto_principal():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001")

        location = service.adicionar_localizacao(
            visita["id"],
            -15.0019124,
            -50.7714295,
            descricao="Tanque",
        )
        saved = service.obter_visita(visita["id"])

        assert location["maps_url"] == "https://maps.google.com/?q=-15.0019124,-50.7714295"
        assert saved["latitude_principal"] == -15.0019124
        assert saved["longitude_principal"] == -50.7714295
        assert saved["maps_url_principal"] == location["maps_url"]


def test_visita_fechar_marca_status_e_data():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001")

        closed = service.fechar_visita(visita["id"])

        assert closed["status"] == "fechada"
        assert closed["estado_fluxo"] == "fechada"
        assert closed["fechado_em"]
        assert service.obter_visita_aberta("5500000000001") is None


def test_obter_ultima_visita_ignora_cancelada():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001")

        service.cancelar_visita(visita["id"])

        assert service.obter_ultima_visita("5500000000001") is None


def test_obter_ultima_visita_prefere_aberta_ou_fechada():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        cancelada = service.iniciar_visita("5500000000001")
        service.cancelar_visita(cancelada["id"])
        fechada = service.iniciar_visita("5500000000001")
        service.atualizar_campo(fechada["id"], "fazenda", "Fazenda Valida")
        service.fechar_visita(fechada["id"])

        selected = service.obter_ultima_visita("5500000000001")

        assert selected["id"] == fechada["id"]
        assert selected["status"] == "fechada"
