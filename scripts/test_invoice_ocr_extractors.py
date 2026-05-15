import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agents.invoice_agent import (
    extract_date_time_from_text,
    extract_payment_method_from_text,
    extract_total_value_from_text,
)


def main() -> int:
    text = """
    NFC-e n 000034171 Serie 001 13/05/2026 14:55:44 Via Empresa
    Valor Total R$ 64,00
    Cartao de Debito
    """

    date_time = extract_date_time_from_text(text)
    assert date_time["data_documento"] == "2026-05-13"
    assert date_time["hora_documento"] == "14:55:44"
    assert extract_total_value_from_text(text) == 64.00
    assert extract_payment_method_from_text(text) == "Cartao de Debito"

    print("Invoice OCR extractor tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
