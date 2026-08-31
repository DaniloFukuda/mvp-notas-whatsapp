import base64
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services import visitas_pdf_service


def _visita_completa() -> dict:
    return {
        "id": 1,
        "data_visita": "2026-06-17",
        "tecnico_nome": "Danilo",
        "telefone_origem": "5500000000001",
        "fazenda": "Fazenda Imperial",
        "proprietario": "Alexander Duarte Paniago",
        "telefone_proprietario": "(61) 99999-8888",
        "gerente": "Paulo Silva",
        "telefone_gerente": "(61) 98888-7777",
        "area": "500 hectares",
        "localizacao_texto": "Fazenda Imperial, entrada principal",
        "descricao_visita": "Inspeção do sistema de irrigação.\nLinha secundária revisada.",
        "observacoes_gerais": "Vazamento próximo ao reservatório.\nRetornar após o reparo.",
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


def _long_text_visit() -> dict:
    """Return a visit with very long description and observations that would exceed a single page."""
    long_desc = "\n".join(
        [
            f"Linha {i}: Descrição detalhada da atividade realizada no campo durante a visita técnica. Inclui observações sobre solo, cultura, irrigação e equipamentos."
            for i in range(1, 40)
        ]
    )
    long_obs = "\n".join(
        [
            f"Observação {i}: Ponto de atenção identificado que requer acompanhamento na próxima visita."
            for i in range(1, 30)
        ]
    )
    long_dados = [
        {
            "chave": f"campo_{i}",
            "valor": f"Valor muito longo para o campo {i} " + "x" * 200,
            "observacao": f"Observação detalhada para o campo {i} " + "y" * 150,
        }
        for i in range(1, 12)
    ]
    return {
        "id": 99,
        "data_visita": "2026-07-15",
        "tecnico_nome": "Teste Longo",
        "telefone_origem": "5500000000099",
        "fazenda": "Fazenda Teste Longo",
        "descricao_visita": long_desc,
        "observacoes_gerais": long_obs,
        "observacoes": long_obs,
        "dados_coletados": long_dados,
        "midias": [],
        "localizacoes": [],
    }


def test_build_visita_pdf_basico():
    content = visitas_pdf_service.build_visita_pdf(_visita_completa())

    assert content.startswith(b"%PDF")
    assert len(content) > 1000
    text = _extract_pdf_text(content)
    normalized_text = " ".join(text.split())
    assert "Relatório de Visita Técnica" in text
    assert "Gestão de Campo" in text
    assert "Ciclus Agro" in text
    assert "FAZENDA IMPERIAL" in text
    assert "Técnico" in text
    assert "Proprietário" in text
    assert "Telefone do proprietário" in normalized_text
    assert "(61) 99999-8888" in text
    assert "Gerente/responsável" in text
    assert "Telefone do gerente" in text
    assert "(61) 98888-7777" in text
    assert "Tamanho total da fazenda/propriedade" in normalized_text
    assert "500 hectares" in text
    assert "Área/local visitado" not in text
    assert "Descrição da visita" in text
    assert "Inspeção do sistema de irrigação." in text
    assert "Linha secundária revisada." in text
    assert "Observações gerais" in text
    assert "Vazamento próximo ao reservatório." in text
    assert "Retornar após o reparo." in text
    assert "Área em hectares" in text
    assert "Resumo da visita" in text
    assert "Objetivo comercial" not in text
    assert "Objetivo não informado" not in text
    assert "Tipo de visita" not in text
    assert "Tipo de visita não informado" not in text
    assert "Oportunidades e próximos passos" not in text
    assert "Localizações e pontos de referência" in text
    assert "Abrir no Google Maps" in text
    assert "Quantidade de vídeos" in text
    assert "Status: Finalizada" in text


def test_build_visita_pdf_preview_fica_inequivocamente_aberta():
    visita = _visita_completa()
    visita.update(status="aberta", fechado_em=None, report_kind="preview")

    text = _extract_pdf_text(visitas_pdf_service.build_visita_pdf(visita))

    assert "PRÉVIA — VISITA AINDA ABERTA" in text
    assert "Status: Aberta" in text
    assert "Fechado em" in text


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
    assert "Latitude / Longitude" not in text
    assert "https://maps.google.com/?q=-15.0019124,-50.7714295" not in text


def test_build_visita_pdf_foto_exibe_comentario_sem_gps_individual(tmp_path):
    image_path = tmp_path / "talhao.png"
    image_path.write_bytes(base64.b64decode(_ONE_PIXEL_PNG))

    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 9,
            "fazenda": "Fazenda Imperial",
            "midias": [
                {
                    "tipo": "foto",
                    "legenda": "Talhão norte",
                    "comentario": "Vazamento no registro",
                    "caminho_arquivo": str(image_path),
                    "latitude": -15.0019124,
                    "longitude": -50.7714295,
                    "maps_url": "https://maps.google.com/?q=-15.0019124,-50.7714295",
                }
            ],
            "latitude_principal": -15.0019124,
            "longitude_principal": -50.7714295,
            "maps_url_principal": "https://maps.google.com/?q=-15.0019124,-50.7714295",
        }
    )

    text = _extract_pdf_text(content)
    photo_section = text.split("Registros fotográficos", 1)[1]
    assert "Comentário" in photo_section
    assert "Vazamento no registro" in photo_section
    assert "Latitude / Longitude" not in photo_section
    assert "GPS" not in photo_section
    assert "Localizações e pontos de referência" in text
    assert "Abrir no Google Maps" in text


def test_build_visita_pdf_com_video_public_url_separado_de_fotos(tmp_path):
    image_path = tmp_path / "talhao.png"
    image_path.write_bytes(base64.b64decode(_ONE_PIXEL_PNG))

    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 8,
            "fazenda": "Fazenda Imperial",
            "midias": [
                {
                    "tipo": "foto",
                    "legenda": "Foto do talhão",
                    "caminho_arquivo": str(image_path),
                },
                {
                    "tipo": "video",
                    "comentario": "Falha perto da entrada",
                    "public_url": "https://cdn.example/visitas/video-1.mp4",
                    "mime_type": "video/mp4",
                    "tamanho_bytes": 2048,
                },
            ],
        }
    )

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Registros fotográficos" in text
    assert "Foto do talhão" in text
    assert "Registros em vídeo" in text
    assert "Vídeo 1" in text
    assert "Falha perto da entrada" in text
    assert "https://cdn.example/visitas/video-1.mp4" in text
    assert "Quantidade de vídeos" in text


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


def test_build_visita_pdf_converte_horarios_utc_para_brt(monkeypatch):
    monkeypatch.setattr(
        visitas_pdf_service,
        "_now_utc",
        lambda: datetime(2026, 7, 8, 1, 25, tzinfo=timezone.utc),
    )

    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 10,
            "fazenda": "Fazenda Imperial",
            "criado_em": "2026-07-08T01:25:00",
            "fechado_em": "2026-07-08T02:05:00+00:00",
            "midias": [],
            "localizacoes": [],
            "dados_coletados": [],
        }
    )

    text = _extract_pdf_text(content)
    assert "07/07/2026 22:25 BRT" in text
    assert "07/07/2026 23:05 BRT" in text
    assert "08/07/2026 01:25" not in text


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


def test_build_visita_pdf_nao_cria_oportunidade_artificial():
    visita = _visita_completa()
    visita["observacoes"] = "Cliente pediu orçamento para a próxima compra."

    content = visitas_pdf_service.build_visita_pdf(visita)

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Oportunidades e próximos passos" not in text
    assert "Oportunidade identificada" not in text
    assert "Próximo passo sugerido" not in text


def test_build_visita_pdf_mantem_descricao_e_observacoes_sem_objetivo():
    visita = _visita_completa()
    visita["objetivo"] = ""
    visita["tipo_visita"] = ""
    visita["descricao_visita"] = (
        "Apresentação dos produtos e demonstração da tecnologia disponível.\n"
        "Equipe esclareceu as dúvidas do responsável."
    )

    content = visitas_pdf_service.build_visita_pdf(visita)

    text = _extract_pdf_text(content)
    assert "Objetivo comercial" not in text
    assert "Objetivo não informado." not in text
    assert "Tipo de visita não informado." not in text
    assert "Descrição da visita" in text
    assert "Equipe esclareceu as dúvidas do responsável." in text
    assert "Observações gerais" in text
    assert "Vazamento próximo ao reservatório." in text


def test_build_visita_pdf_sem_descricao_mantem_compatibilidade():
    content = visitas_pdf_service.build_visita_pdf(
        {
            "id": 7,
            "fazenda": "Fazenda Legada",
            "objetivo": "",
            "tipo_visita": "",
            "descricao_visita": "",
            "observacoes_gerais": "",
            "midias": [],
            "localizacoes": [],
            "dados_coletados": [],
        }
    )

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Objetivo comercial" not in text
    assert "Objetivo não informado." not in text
    assert "Tipo de visita não informado." not in text


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


def test_build_visita_pdf_descricao_muito_longa():
    """Test that a visit with a very long description generates PDF without LayoutError."""
    content = visitas_pdf_service.build_visita_pdf(_long_text_visit())

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    # PDF text extraction may uppercase some content
    assert "FAZENDA TESTE LONGO" in text or "Fazenda Teste Longo" in text
    assert "Linha 1:" in text
    # Should generate multiple pages - verify we have at least some long content
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) > 1
    # Verify the content spans multiple pages by checking first and last pages have different content
    page1_text = reader.pages[0].extract_text() or ""
    last_page_text = reader.pages[-1].extract_text() or ""
    assert page1_text != last_page_text


def test_build_visita_pdf_observacoes_muito_longa():
    """Test that a visit with very long observations generates PDF without LayoutError."""
    visit = _visita_completa()
    visit["observacoes_gerais"] = "\n".join([f"Observação extensa linha {i}." for i in range(1, 80)])
    visit["observacoes"] = visit["observacoes_gerais"]

    content = visitas_pdf_service.build_visita_pdf(visit)

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "Observação extensa linha 1." in text
    assert "Observação extensa linha 79." in text
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) > 1


def test_build_visita_pdf_dados_coletados_longos():
    """Test that a visit with many long collected data rows generates PDF without LayoutError."""
    long_dados = [
        {
            "chave": f"parametro_{i}",
            "valor": "Valor muito longo " + "z" * 300,
            "observacao": "Obs detalhada " + "w" * 200,
        }
        for i in range(20)
    ]
    visit = _visita_completa()
    visit["dados_coletados"] = long_dados

    content = visitas_pdf_service.build_visita_pdf(visit)

    assert content.startswith(b"%PDF")
    text = _extract_pdf_text(content)
    assert "parametro_1" in text
    assert "parametro_19" in text
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) > 1


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


_ONE_PIXEL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
