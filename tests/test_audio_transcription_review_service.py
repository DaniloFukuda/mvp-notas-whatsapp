import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.audio_transcription_review_service import (
    AudioTranscriptionReviewService,
    transcription_review_enabled,
)


def test_revisa_erros_conhecidos_do_whisper():
    result = AudioTranscriptionReviewService().review(
        "usar o cadax nos botes do whats app"
    )

    assert result.raw_text == "usar o cadax nos botes do whats app"
    assert "Codex" in result.reviewed_text
    assert "botões" in result.reviewed_text
    assert "WhatsApp" in result.reviewed_text
    assert result.changed is True


def test_revisa_contentor_com_contexto_de_campo():
    result = AudioTranscriptionReviewService().review(
        "o contitor está alugado",
        context="visita_observacao",
    )

    assert result.reviewed_text == "O contentor está alugado"


def test_melhora_pontuacao_e_remove_repeticao_obvia():
    raw = (
        "fizemos a visita visita na fazenda e depois verificamos a aplicação "
        "com o operador e então registramos a entrega dos contentores disponíveis"
    )

    result = AudioTranscriptionReviewService().review(raw)

    assert "visita visita" not in result.reviewed_text
    assert ". Depois" in result.reviewed_text
    assert result.reviewed_text.endswith(".")


def test_preserva_numeros_valores_datas_contentores_e_telefone():
    raw = (
        "contentores 1 2 3 e 99 valor R$ 50,00 em 26/06/2026 telefone "
        "22999998888"
    )

    reviewed = AudioTranscriptionReviewService().review(raw).reviewed_text

    for value in ("1", "2", "3", "99", "R$ 50,00", "26/06/2026", "22999998888"):
        assert value in reviewed


def test_preserva_comando_tecnico():
    result = AudioTranscriptionReviewService().review("visita")

    assert result.reviewed_text == "visita"


def test_revisao_desabilitada_retorna_texto_bruto(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_REVIEW_ENABLED", "false")
    raw = "usar cadax e botes"

    result = AudioTranscriptionReviewService().review(raw)

    assert transcription_review_enabled() is False
    assert result.reviewed_text == raw
    assert result.changed is False
