import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.rdv_receipt_analysis_service import RDVReceiptAnalysisService


def main() -> None:
    service = RDVReceiptAnalysisService()
    key = "1" * 44
    text = f"""
    MERCADO FICTICIO LTDA
    NFC-e numero 123
    Data de emissao: 13/05/2026 14:55:44
    Valor Total R$ 64,00
    Chave de acesso: {key}
    """

    result = service.analyze_text(text)
    assert result.valor_detectado == 64.0
    assert result.data_detectada == "2026-05-13"
    assert result.fornecedor_detectado == "MERCADO FICTICIO LTDA"
    assert result.chave_acesso == key
    assert result.origem_valor == "ocr"
    assert result.confidence >= 0.8
    assert "valor_encontrado_ocr" in result.reasons

    examples = (
        "Valor Total R$ 64,00",
        "VALOR PAGO R$ 64,00",
        "VALOR INFORMADO: CARTAO DEBITO - 64,00",
        "Valor total 64,00",
    )
    for example in examples:
        parsed = service.analyze_text(example)
        assert parsed.valor_detectado == 64.0, example
        assert parsed.origem_valor == "ocr"

    degraded_ocr = service.analyze_text(
        "Valor Total Rs 4\nALOR INFORMADO: CARTAO DEBITO : 64"
    )
    assert degraded_ocr.valor_detectado == 64.0

    qr_result = service.analyze_text(
        f"https://fiscal.exemplo.invalid/consulta?chNFe={key}&valor=64.00",
        source="qr_code",
    )
    assert qr_result.valor_detectado == 64.0
    assert qr_result.qr_code_url.startswith("https://fiscal.exemplo.invalid/")
    assert qr_result.chave_acesso == key
    assert qr_result.origem_valor == "qr_code"

    print("OK: parser fiscal simulado do RDV validado.")


if __name__ == "__main__":
    main()
