import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.fiscal_access_key import (
    calculate_access_key_check_digit,
    extract_access_keys,
    normalize_access_key,
    parse_access_key,
    validate_access_key,
)


VALID_NFCE_KEY = "52260612345678000195650010000001231876543210"


def test_calculates_access_key_check_digit():
    assert calculate_access_key_check_digit(VALID_NFCE_KEY[:43]) == VALID_NFCE_KEY[-1]


def test_parse_valid_nfce_key_returns_structured_fields():
    parsed = parse_access_key(VALID_NFCE_KEY)

    assert parsed is not None
    assert parsed.chave_acesso == VALID_NFCE_KEY
    assert parsed.uf_codigo == "52"
    assert parsed.ano_mes == "2606"
    assert parsed.cnpj_emitente == "12345678000195"
    assert parsed.modelo == "65"
    assert parsed.serie == "001"
    assert parsed.numero == "000000123"
    assert parsed.tipo_emissao == "1"
    assert parsed.codigo_numerico == "87654321"
    assert parsed.digito_verificador == "0"


def test_invalid_check_digit_is_rejected():
    invalid_key = f"{VALID_NFCE_KEY[:43]}9"

    assert parse_access_key(invalid_key) is None
    assert normalize_access_key(invalid_key) == ""


def test_rejects_unsupported_model_by_default():
    cte_like_base = (
        "52"
        "2606"
        "12345678000195"
        "57"
        "001"
        "000000123"
        "1"
        "87654321"
    )
    cte_like_key = cte_like_base + calculate_access_key_check_digit(cte_like_base)

    assert parse_access_key(cte_like_key) is None
    assert parse_access_key(cte_like_key, allowed_models=None) is not None


def test_extracts_key_from_qr_code_url_and_ocr_text():
    spaced_key = " ".join(
        VALID_NFCE_KEY[index : index + 4]
        for index in range(0, len(VALID_NFCE_KEY), 4)
    )
    text = (
        "Consulta NFC-e: https://www.sefaz.go.gov.br/nfce/qrcode?p="
        f"{VALID_NFCE_KEY}|2|1|1|ABC "
        f"Texto OCR com chave quebrada: {spaced_key}"
    )

    assert extract_access_keys(text) == [VALID_NFCE_KEY]


def test_ignores_random_44_digit_sequence():
    assert extract_access_keys("00000000000000000000000000000000000000000000") == []

def test_validate_access_key_accepts_valid_synthetic_key():
    assert validate_access_key(VALID_NFCE_KEY)


def test_parse_access_key_normalizes_spaces_and_separators():
    formatted = (
        "5226 0612.3456 7800 0195-6500 1000 0001 2318 7654 3210"
    )

    parsed = parse_access_key(formatted)

    assert parsed is not None
    assert parsed.chave_acesso == VALID_NFCE_KEY


def test_parse_access_key_rejects_wrong_check_digit():
    assert parse_access_key("12345678901234567890123456789012345678901234") is None
