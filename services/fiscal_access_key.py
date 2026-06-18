from __future__ import annotations

import re
from dataclasses import dataclass


SUPPORTED_NFE_MODELS = ("55", "65")
VALID_UF_CODES = {
    "11",  # RO
    "12",  # AC
    "13",  # AM
    "14",  # RR
    "15",  # PA
    "16",  # AP
    "17",  # TO
    "21",  # MA
    "22",  # PI
    "23",  # CE
    "24",  # RN
    "25",  # PB
    "26",  # PE
    "27",  # AL
    "28",  # SE
    "29",  # BA
    "31",  # MG
    "32",  # ES
    "33",  # RJ
    "35",  # SP
    "41",  # PR
    "42",  # SC
    "43",  # RS
    "50",  # MS
    "51",  # MT
    "52",  # GO
    "53",  # DF
}


@dataclass(frozen=True)
class FiscalAccessKey:
    """Chave de acesso fiscal validada localmente, sem chamada a SEFAZ."""

    chave_acesso: str
    uf_codigo: str
    ano_mes: str
    cnpj_emitente: str
    modelo: str
    serie: str
    numero: str
    tipo_emissao: str
    codigo_numerico: str
    digito_verificador: str


def only_digits(value: object) -> str:
    """Retorna apenas digitos de uma entrada textual."""

    return re.sub(r"\D+", "", str(value or ""))


def calculate_access_key_check_digit(first_43_digits: str) -> str:
    """Calcula o digito verificador Modulo 11 da chave de acesso NF-e/NFC-e."""

    base = only_digits(first_43_digits)
    if len(base) != 43:
        raise ValueError("A base da chave de acesso deve conter 43 digitos.")

    total = 0
    weight = 2
    for digit in reversed(base):
        total += int(digit) * weight
        weight += 1
        if weight > 9:
            weight = 2

    result = 11 - (total % 11)
    return "0" if result in (10, 11) else str(result)


def is_valid_cnpj(value: object) -> bool:
    """Valida CNPJ para reduzir falso positivo em OCR/QR Code."""

    cnpj = only_digits(value)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    first_weights = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    first_sum = sum(int(digit) * weight for digit, weight in zip(cnpj[:12], first_weights))
    first_digit = 0 if first_sum % 11 < 2 else 11 - (first_sum % 11)

    second_weights = (6, *first_weights)
    second_sum = sum(int(digit) * weight for digit, weight in zip(cnpj[:13], second_weights))
    second_digit = 0 if second_sum % 11 < 2 else 11 - (second_sum % 11)

    return cnpj[-2:] == f"{first_digit}{second_digit}"


def parse_access_key(
    value: object,
    allowed_models: tuple[str, ...] | None = SUPPORTED_NFE_MODELS,
) -> FiscalAccessKey | None:
    """Valida e quebra uma chave de acesso fiscal de 44 digitos.

    Por padrao aceita os modelos 55 (NF-e) e 65 (NFC-e), que sao os mais uteis
    para comprovantes de despesa do RDV. Passe ``allowed_models=None`` para
    aceitar outros modelos com a mesma estrutura de chave.
    """

    key = only_digits(value)
    if len(key) != 44 or len(set(key)) == 1:
        return None

    uf_code = key[:2]
    year_month = key[2:6]
    cnpj = key[6:20]
    model = key[20:22]
    month = int(year_month[2:4])

    if uf_code not in VALID_UF_CODES:
        return None
    if month < 1 or month > 12:
        return None
    if allowed_models is not None and model not in allowed_models:
        return None
    if not is_valid_cnpj(cnpj):
        return None
    if calculate_access_key_check_digit(key[:43]) != key[43]:
        return None

    return FiscalAccessKey(
        chave_acesso=key,
        uf_codigo=uf_code,
        ano_mes=year_month,
        cnpj_emitente=cnpj,
        modelo=model,
        serie=key[22:25],
        numero=key[25:34],
        tipo_emissao=key[34],
        codigo_numerico=key[35:43],
        digito_verificador=key[43],
    )


def normalize_access_key(value: object) -> str:
    """Retorna chave validada com 44 digitos ou string vazia."""

    parsed = parse_access_key(value)
    return parsed.chave_acesso if parsed else ""


def validate_access_key(value: object) -> bool:
    """Retorna True quando a entrada contem uma chave fiscal valida."""

    return parse_access_key(value) is not None


def extract_access_keys(
    text: object,
    allowed_models: tuple[str, ...] | None = SUPPORTED_NFE_MODELS,
) -> list[str]:
    """Extrai chaves fiscais validas de texto, QR Code, URL ou OCR.

    Aceita tanto chaves continuas quanto chaves com separadores comuns
    gerados por OCR, como espacos, pontos, barras, hifens e pipes.
    """

    raw_text = str(text or "")
    candidates: list[str] = []

    candidates.extend(match.group(0) for match in re.finditer(r"\d{44}", raw_text))
    candidates.extend(
        match.group(0)
        for match in re.finditer(r"(?:\d[\s.\-\/|]*){44}", raw_text)
    )

    valid_keys: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        parsed = parse_access_key(candidate, allowed_models=allowed_models)
        if parsed is None or parsed.chave_acesso in seen:
            continue
        valid_keys.append(parsed.chave_acesso)
        seen.add(parsed.chave_acesso)

    return valid_keys
