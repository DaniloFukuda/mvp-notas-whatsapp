import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.visitas_pdf_service import build_visita_pdf


def test_build_visita_pdf_basico():
    content = build_visita_pdf(
        {
            "id": 1,
            "data_visita": "2026-06-17",
            "tecnico_nome": "Danilo",
            "telefone_origem": "5500000000001",
            "fazenda": "Fazenda Imperial",
            "proprietario": "Alexander Duarte Paniago",
            "gerente": "Paulo Silva",
            "area_hectares": 2299,
            "latitude_principal": -15.0019124,
            "longitude_principal": -50.7714295,
            "maps_url_principal": "https://maps.google.com/?q=-15.0019124,-50.7714295",
            "observacoes": "Pedido de 300T para 100ha.",
            "status": "fechada",
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
    assert len(content) > 1000
    text = _extract_pdf_text(content)
    assert "Relatório de Visita Técnica" in text
    assert "Técnico" in text
    assert "Proprietário" in text
    assert "Gerente/responsável" in text
    assert "Área em hectares" in text
    assert "Localização principal" in text
    assert "Localizações" in text


def test_build_visita_pdf_sem_foto_sem_localizacao():
    content = build_visita_pdf(
        {
            "id": 2,
            "fazenda": "Fazenda sem anexos",
            "midias": [],
            "localizacoes": [],
            "dados_coletados": [],
        }
    )

    assert content.startswith(b"%PDF")


def test_build_visita_pdf_com_localizacao():
    content = build_visita_pdf(
        {
            "id": 3,
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


def test_build_visita_pdf_com_dados_coletados():
    content = build_visita_pdf(
        {
            "id": 4,
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


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
