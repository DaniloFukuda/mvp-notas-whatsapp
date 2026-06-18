import sys
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.rdv_receipt_analysis_service import RDVReceiptAnalysisService


VALID_NFCE_KEY = "52260612345678000195650010000001231876543210"


MERCADO_PAGO_PIX_TEXT = """
Comprovante de Pix
14/junho/2026 as 10:17:47.
R$ 80
De Danilo Yuji Fukuda
CPF: ***.862.791-**
Mercado Pago
Para Juan Patrick Barretos da Silva
CPF: ***.597.471-**
NU PAGAMENTOS S.A. - INSTITUICAO DE PAGAMENTO
N.o transacao do Mercado Pago
163261980821
ID de transacao Pix
E10573521202606141317QoWzciMLWDa
Atendimento ao cliente
0800 637 7246
"""


def test_mercado_pago_pix_ocr_text_detects_value_date_and_supplier():
    result = RDVReceiptAnalysisService().analyze_text(MERCADO_PAGO_PIX_TEXT)

    assert result.valor_detectado == 80.0
    assert result.data_detectada == "2026-06-14"
    assert result.origem_valor == "ocr"
    assert result.fornecedor_detectado == "Mercado Pago"
    assert "valor_encontrado_ocr" in result.reasons
    assert "data_encontrada" in result.reasons


def test_mercado_pago_pix_ocr_ignores_transaction_phone_and_cpf_numbers():
    service = RDVReceiptAnalysisService()

    result = service.analyze_text(MERCADO_PAGO_PIX_TEXT)

    assert result.valor_detectado == 80.0
    assert result.valor_detectado not in {163261980821.0, 8006377246.0}
    assert result.valor_detectado not in {862.0, 791.0, 597.0, 471.0}


def test_extracts_portuguese_textual_date():
    result = RDVReceiptAnalysisService().analyze_text(
        "14/junho/2026 as 10:17:47"
    )

    assert result.data_detectada == "2026-06-14"


def test_qr_value_wins_over_ocr_but_ocr_fills_missing_date():
    service = RDVReceiptAnalysisService()
    qr_result = service.analyze_text(
        "https://fiscal.exemplo.invalid/consulta?valor=64.00",
        source="qr_code",
    )
    ocr_result = service.analyze_text(
        "Comprovante de Pix\n14 de junho de 2026\nR$ 80\nMercado Pago",
        source="ocr",
    )

    merged = service._merge_results(qr_result, ocr_result)

    assert merged.valor_detectado == 64.0
    assert merged.origem_valor == "qr_code"
    assert merged.data_detectada == "2026-06-14"
    assert merged.fornecedor_detectado == "Mercado Pago"


def test_rejects_future_date_from_ocr_text():
    future_date = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
    result = RDVReceiptAnalysisService().analyze_text(
        f"Comprovante de Pix\n{future_date}\nR$ 80\nMercado Pago"
    )

    assert result.valor_detectado == 80.0
    assert result.data_detectada == ""


def test_extracts_only_valid_fiscal_access_key_from_nfce_qr_url():
    result = RDVReceiptAnalysisService().analyze_text(
        "https://www.sefaz.go.gov.br/nfce/qrcode?p="
        f"{VALID_NFCE_KEY}|2|1|1|ABC&valor=64.00",
        source="qr_code",
    )

    assert result.chave_acesso == VALID_NFCE_KEY
    assert "chave_acesso_encontrada" in result.reasons


def test_rejects_random_44_digit_sequence_as_fiscal_access_key():
    random_sequence = "12345678901234567890123456789012345678901234"

    result = RDVReceiptAnalysisService().analyze_text(
        f"Texto OCR com numero longo {random_sequence} e valor R$ 64,00"
    )

    assert result.valor_detectado == 64.0
    assert result.chave_acesso == ""
    assert "chave_acesso_encontrada" not in result.reasons
