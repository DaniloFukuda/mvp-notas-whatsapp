import base64
import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services import visitas_pdf_service


def test_build_visita_pdf_basico():
    content = visitas_pdf_service.build_visita_pdf(_visita_completa())

    assert content.startswith(b"%PDF")
    assert len(content) > 1000
    text = _extract_pdf_text(content)
    assert "Relatório de Visita Técnica" in text
    assert "Gestão de Campo" in text
    assert "Ciclus Agro" in text
    assert "FAZENDA IMPERIAL" in text
    assert "Técnico" in text
    assert "Proprietário" in text
    assert "Gerente/responsável" in text
    assert "Área em hectares" in text
    assert "Resumo da visita" in text
    assert "Objetivo comercial" in text
    assert "Oportunidades e próximos passos" in text
    assert "Localizações e pontos de referência" in text
    assert "Abrir no Google Maps" in text


def test_build_visita_pdf_com_logo_nao_quebra():
    assert visitas_pdf_service.LOGO_PATH.exists()

    content = visitas_pdf_service.build_visita_pdf(_visita_completa())

    assert content.startswith(b"%PDF")


def test_build_visita_pdf_sem_logo_usa_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(visitas_pdf_service, "LOGO_PATH", tmp_path / "logo-ausente.jpeg")

    content = visitas_pdf_service.build_visita_pdf(_visita_completa())

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Ciclus Agro" in text


def test_build_visita_pdf_sem_foto_sem_localizacao():
    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 2,
            "fazenda": "Fazenda sem anexos",
            "midias": [],
            "localizacoes": [],
            "dados_coletados": [],
        }
    )

    assert content.startswith(b"%PDF")


def test_build_visita_pdf_com_foto(tmp_path):
    image_path = tmp_path / "talhao.png"
    image_path.write_bytes(base64.b64decode(_ONE_PIXEL_PNG))

    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 3,
            "fazenda": "Fazenda Imperial",
            "midias": [
                {
                    "legenda": "Talhão norte",
                    "caminho_arquivo": str(image_path),
                    "latitude": -15.0019124,
                    "longitude": -50.7714295,
                    "maps_url": "https://maps.google.com/?q=-15.0019124,-50.7714295",
                }
            ],
        }
    )

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Registros fotográficos" in text
    assert "Talhão norte" in text


def test_build_visita_pdf_com_localizacao():
    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 4,
            "fazenda": "Fazenda Imperial",
            "latitude_principal": -15.0019124,
            "longitude_principal": -50.7714295,
            "maps_url_principal": "https://maps.google.com/?q=-15.0019124,-50.7714295",
            "localizacoes": [
                {
                    "descricao": "Tanque",
                    "latitude": -15.0019124,
                    "longitude": -50.7714295,
                    "maps_url": "https://maps.google.com/?q=-15.0019124,-50.7714295",
                }
            ],
        }
    )

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Localizações e pontos de referência" in text
    assert "Abrir no Google Maps" in text


def test_build_visita_pdf_com_dados_coletados():
    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 5,
            "fazenda": "Fazenda Imperial",
            "dados_coletados": [
                {
                    "chave": "tanque",
                    "valor": "capacidade 10000 L",
                    "observacao": "tanque vazio",
                }
            ],
        }
    )

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Dados coletados" in text
    assert "tanque" in text


def test_build_visita_pdf_destaca_oportunidade_por_orcamento():
    visita = _visita_completa()
    visita["observacoes"] = "Cliente pediu orçamento para a próxima compra."

    content = visitas_pdf_service.build_visita_pdf(visita)

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Oportunidade identificada" in text
    assert "Observações mencionam orçamento" in text


def test_build_visita_pdf_tolera_campos_vazios():
    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 6,
            "fazenda": "",
            "tecnico_nome": "",
            "observacoes": "",
            "dados_coletados": [{"chave": "", "valor": "", "observacao": ""}],
            "midias": [{"caminho_arquivo": "", "legenda": ""}],
            "localizacoes": [{"descricao": "", "latitude": "", "longitude": "", "maps_url": ""}],
        }
    )

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Fazenda não informada" in text
    assert "Resumo da visita" in text
    assert "Registros fotográficos" in text


def _visita_completa() -> dict:
    return {
        "id": 1,
        "data_visita": "2026-06-17",
        "tecnico_nome": "Danilo",
        "telefone_origem": "5500000000001",
        "fazenda": "Fazenda Imperial",
        "proprietario": "Alexander Duarte Paniago",
        "gerente": "Paulo Silva",
        "safra": "2025/2026",
        "tipo_visita": "Comercial",
        "area_hectares": 2299,
        "area_alqueires": 950,
        "latitude_principal": -15.0019124,
        "longitude_principal": -50.7714295,
        "maps_url_principal": "https://maps.google.com/?q=-15.0019124,-50.7714295",
        "observacoes": "Pedido de 300T para 100ha.\nRetornar em julho.",
        "status": "fechada",
        "localizacoes": [
            {
                "descricao": "Tanque",
                "latitude": -15.0019124,
                "longitude": -50.7714295,
                "maps_url": "https://maps.google.com/?q=-15.0019124,-50.7714295",
            }
        ],
        "dados_coletados": [
            {
                "chave": "solo",
                "valor": "corrigir acidez",
                "observacao": "avaliar próxima visita",
            }
        ],
    }


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


_ONE_PIXEL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
