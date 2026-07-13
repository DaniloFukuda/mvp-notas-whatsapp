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


def test_visita_salvar_localizacao_textual_reaproveita_url_principal():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001")

        saved = service.salvar_localizacao_textual(
            visita["id"],
            "https://maps.google.com/?q=-15,-50",
        )

        assert saved["localizacao_texto"] == "https://maps.google.com/?q=-15,-50"
        assert saved["maps_url_principal"] == "https://maps.google.com/?q=-15,-50"


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


def test_listar_visitas_validas_global():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        primeira = service.iniciar_visita("5500000000001", tecnico_nome="Danilo")
        service.atualizar_campo(primeira["id"], "fazenda", "Fazenda Imperial")
        service.fechar_visita(primeira["id"])
        segunda = service.iniciar_visita("5500000000002", tecnico_nome="Marcelo")
        service.atualizar_campo(segunda["id"], "fazenda", "Fazenda Boi Dourado 3J")
        cancelada = service.iniciar_visita("5500000000003", tecnico_nome="Henrique Saraiva")
        service.atualizar_campo(cancelada["id"], "fazenda", "Fazenda Cancelada")
        service.cancelar_visita(cancelada["id"])

        data = service.listar_visitas_validas()

        ids = {item["id"] for item in data["visitas"]}
        assert ids == {primeira["id"], segunda["id"]}
        assert all(item["status"] in {"aberta", "fechada"} for item in data["visitas"])


def test_historico_edicao_registra_alteracao():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001", tecnico_nome="Danilo")
        service.atualizar_campo(visita["id"], "gerente", "Marcos")

        result = service.editar_campo(
            visita["id"],
            "gerente",
            "Marcos Silva",
            telefone_editor="5500000000002",
        )
        edicoes = service.listar_edicoes(visita["id"])

        assert result["valor_anterior"] == "Marcos"
        assert result["valor_novo"] == "Marcos Silva"
        assert len(edicoes) == 1
        assert edicoes[0]["campo"] == "gerente"
        assert edicoes[0]["valor_anterior"] == "Marcos"
        assert edicoes[0]["valor_novo"] == "Marcos Silva"
        assert edicoes[0]["telefone_editor"] == "5500000000002"


def test_remover_midia_remove_apenas_da_visita_e_retorna_metadados():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001")
        outra = service.iniciar_visita("5500000000002")
        foto = service.adicionar_midia(
            visita["id"],
            "foto",
            caminho_arquivo=str(Path(temp_dir) / "foto-1.jpg"),
        )
        service.adicionar_midia(outra["id"], "foto", caminho_arquivo="outra.jpg")

        removed = service.remover_midia(visita["id"], foto["id"])

        assert removed["id"] == foto["id"]
        assert service.listar_midias_por_tipo(visita["id"], "foto") == []
        assert len(service.listar_midias_por_tipo(outra["id"], "foto")) == 1


def test_video_hash_detecta_duplicidade_apenas_na_mesma_visita():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = VisitasTecnicasService(Path(temp_dir) / "visitas.db")
        visita = service.iniciar_visita("5500000000001")
        outra = service.iniciar_visita("5500000000002")

        video = service.adicionar_midia(
            visita["id"],
            "video",
            storage_key="visitas/video-1.mp4",
            video_hash="sha256-video",
        )

        assert video["video_hash"] == "sha256-video"
        assert service.existe_video_hash(visita["id"], "sha256-video")
        assert not service.existe_video_hash(outra["id"], "sha256-video")
        assert not service.existe_video_hash(visita["id"], "")
