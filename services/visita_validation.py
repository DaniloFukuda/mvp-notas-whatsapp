import re
import unicodedata
from dataclasses import dataclass


SKIP_ALIASES = {
    "pular",
    "nao sei",
    "não sei",
    "sem informacao",
    "sem informação",
    "nao informado",
    "não informado",
    "sem telefone",
    "nao tem",
    "não tem",
}
SKIPPED_VALUE = "Não informado"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    value: str = ""
    error: str = ""


def validate_visit_field(field: str, value: str) -> ValidationResult:
    text = normalize_spaces(value)
    normalized = _normalize(text)

    if field in {"proprietario", "telefone_proprietario", "gerente", "telefone_gerente"}:
        if normalized in SKIP_ALIASES:
            return ValidationResult(True, SKIPPED_VALUE)

    if field == "fazenda":
        return _validate_text(
            text,
            min_len=3,
            max_len=120,
            label="nome da fazenda",
            error="Não consegui entender essa informação. Informe o nome da fazenda com pelo menos 3 caracteres.",
            reject_only_numbers=True,
        )
    if field == "proprietario":
        return _validate_text(
            text,
            min_len=3,
            max_len=100,
            label="nome do proprietário",
            error="Não consegui entender essa informação. Informe o nome do proprietário com pelo menos 3 caracteres. Você também pode enviar \"pular\" caso não tenha essa informação agora.",
        )
    if field == "telefone_proprietario":
        return _validate_phone(text)
    if field == "gerente":
        return _validate_text(
            text,
            min_len=3,
            max_len=100,
            label="nome do gerente ou responsável",
            error="Não consegui entender essa informação. Informe o nome do gerente ou responsável com pelo menos 3 caracteres. Você também pode enviar \"pular\" caso não tenha essa informação agora.",
        )
    if field == "telefone_gerente":
        return _validate_phone(text)
    if field == "area":
        return _validate_text(
            text,
            min_len=3,
            max_len=120,
            label="área, talhão ou local visitado",
            error="Não consegui entender essa informação. Informe a área, talhão ou local visitado com pelo menos 3 caracteres.",
        )
    if field == "descricao_visita":
        return _validate_text(
            text,
            min_len=10,
            max_len=1000,
            label="descrição da visita",
            error="A descrição ficou muito curta. Envie um resumo com pelo menos 10 caracteres.",
            check_random=False,
        )
    if field in {"observacoes_gerais", "comentario_foto"}:
        if len(text) > 1000:
            return ValidationResult(False, error="O texto ficou muito longo. Envie no máximo 1000 caracteres.")
        return ValidationResult(True, text)
    return ValidationResult(True, text)


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _validate_text(
    text: str,
    min_len: int,
    max_len: int,
    label: str,
    error: str,
    reject_only_numbers: bool = False,
    check_random: bool = True,
) -> ValidationResult:
    if len(text) < min_len:
        return ValidationResult(False, error=error)
    if len(text) > max_len:
        return ValidationResult(False, error=f"Essa informação ficou muito longa. Envie {label} com no máximo {max_len} caracteres.")
    if reject_only_numbers and re.fullmatch(r"\d+", text):
        return ValidationResult(False, error=error)
    if check_random and _looks_random(text):
        return ValidationResult(False, error=error)
    return ValidationResult(True, text)


def _validate_phone(text: str) -> ValidationResult:
    digits = re.sub(r"\D+", "", text)
    if not 10 <= len(digits) <= 13:
        return ValidationResult(
            False,
            error='Telefone inválido. Envie apenas números, com DDD. Exemplo: 62999998888. Você também pode enviar "pular" caso não tenha essa informação agora.',
        )
    return ValidationResult(True, digits)


def _looks_random(text: str) -> bool:
    compact = re.sub(r"[^a-z]", "", _normalize(text))
    if len(compact) < 8 or " " in text:
        return False
    rare_pairs = ("jk", "jf", "fd", "dl", "lj", "js", "sd", "kj", "hh", "jh", "zx", "xq")
    rare_count = sum(1 for pair in rare_pairs if pair in compact)
    if rare_count >= 2:
        return True
    consonant_clusters = re.findall(r"[bcdfghjklmnpqrstvwxyz]{5,}", compact)
    return bool(consonant_clusters)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in text if not unicodedata.combining(char))
