import os
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
DEFAULT_VISITA_DESCRICAO_MAX_CHARS = 5000
DEFAULT_VISITA_OBSERVACAO_MAX_CHARS = 20000
DEFAULT_VISITA_OBSERVACAO_TOTAL_MAX_CHARS = 80000
DEFAULT_FOTO_COMENTARIO_MAX_CHARS = 2000


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    value: str = ""
    error: str = ""


def validate_visit_field(field: str, value: str) -> ValidationResult:
    text = normalize_spaces(value)
    normalized = _normalize(text)

    if field in {
        "proprietario",
        "telefone_proprietario",
        "gerente",
        "telefone_gerente",
        "area",
        "localizacao_texto",
    }:
        if normalized in SKIP_ALIASES:
            return ValidationResult(
                True,
                "" if field in {"area", "localizacao_texto"} else SKIPPED_VALUE,
            )

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
            label="tamanho total da fazenda/propriedade",
            error='Não consegui entender essa informação. Informe o tamanho total da fazenda/propriedade ou envie "pular".',
        )
    if field == "localizacao_texto":
        return _validate_text(
            text,
            min_len=3,
            max_len=500,
            label="localização da fazenda/propriedade",
            error='Não consegui entender essa localização. Envie um link, endereço, referência ou "pular".',
            check_random=False,
        )
    if field == "descricao_visita":
        return _validate_text(
            text,
            min_len=10,
            max_len=visita_descricao_max_chars(),
            label="descrição da visita",
            error="A descrição ficou muito curta. Envie um resumo com pelo menos 10 caracteres.",
            too_long_error=(
                "A descrição ficou muito longa. "
                "Envie um resumo menor ou divida em partes."
            ),
            check_random=False,
        )
    if field == "observacoes_gerais":
        max_chars = visita_observacao_max_chars()
        if len(text) > max_chars:
            return ValidationResult(
                False,
                error=(
                    "A observação ficou muito longa. "
                    f"Envie no máximo {max_chars} caracteres por mensagem."
                ),
            )
        return ValidationResult(True, text)
    if field == "comentario_foto":
        max_chars = foto_comentario_max_chars()
        if len(text) > max_chars:
            return ValidationResult(
                False,
                error=(
                    "O comentário da foto ficou muito longo. "
                    f"Envie no máximo {max_chars} caracteres."
                ),
            )
        return ValidationResult(True, text)
    return ValidationResult(True, text)


def visita_descricao_max_chars() -> int:
    return _positive_int_from_env(
        "VISITA_DESCRICAO_MAX_CHARS", DEFAULT_VISITA_DESCRICAO_MAX_CHARS
    )


def visita_observacao_max_chars() -> int:
    return _positive_int_from_env(
        "VISITA_OBSERVACAO_MAX_CHARS", DEFAULT_VISITA_OBSERVACAO_MAX_CHARS
    )


def visita_observacao_total_max_chars() -> int:
    configured = _positive_int_from_env(
        "VISITA_OBSERVACAO_TOTAL_MAX_CHARS",
        DEFAULT_VISITA_OBSERVACAO_TOTAL_MAX_CHARS,
    )
    return max(configured, visita_observacao_max_chars())


def foto_comentario_max_chars() -> int:
    return _positive_int_from_env(
        "FOTO_COMENTARIO_MAX_CHARS", DEFAULT_FOTO_COMENTARIO_MAX_CHARS
    )


def split_visit_observation(value: str, max_chars: int | None = None) -> list[str]:
    text = normalize_spaces(value)
    limit = max_chars or visita_observacao_max_chars()
    if not text:
        return []

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _validate_text(
    text: str,
    min_len: int,
    max_len: int,
    label: str,
    error: str,
    too_long_error: str = "",
    reject_only_numbers: bool = False,
    check_random: bool = True,
) -> ValidationResult:
    if len(text) < min_len:
        return ValidationResult(False, error=error)
    if len(text) > max_len:
        return ValidationResult(
            False,
            error=too_long_error
            or f"Essa informação ficou muito longa. Envie {label} com no máximo {max_len} caracteres.",
        )
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


def _positive_int_from_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
