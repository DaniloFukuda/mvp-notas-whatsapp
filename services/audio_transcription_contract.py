"""Contrato padronizado e imutável para resultado de transcrição de áudio.

Este módulo define os dataclasses que representam o resultado completo
de uma transcrição, separando metadados de áudio do resultado textual.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class AudioMetadata:
    """Metadados técnicos do processamento de áudio.

    Imutável: garante que os metadados não sejam alterados após criação.
    """
    provider: str = "whisper_local"
    model_name: str = "base"
    language: str = "pt"
    duration_seconds: float = 0.0
    size_bytes: int = 0
    chunk_count: int = 1
    preprocessed: bool = False
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def size_mb(self) -> float:
        """Tamanho em megabytes."""
        return self.size_bytes / (1024 * 1024) if self.size_bytes else 0.0


@dataclass(frozen=True)
class TranscriptionResult:
    """Resultado completo e padronizado de transcrição.

    Regras imutáveis:
    - raw_text é a fonte de verdade e nunca é substituído pela revisão
    - reviewed_text pode ser igual a raw_text (se revisão desativada/falhar)
    - ok=True implica raw_text não vazio
    - warnings lista alertas conservadores
    """
    ok: bool
    raw_text: str
    reviewed_text: str
    metadata: AudioMetadata
    used_fallback: bool = False
    warnings: tuple[str, ...] = ()
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        # Validações de consistência
        if self.ok and not (self.raw_text or "").strip():
            raise ValueError("TranscriptionResult.ok=True requer raw_text não vazio")

        # reviewed_text nunca deve ser None
        object.__setattr__(self, "reviewed_text", self.reviewed_text or self.raw_text)

        # warnings deve ser tupla imutável
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings or ()))

    @classmethod
    def success(
        cls,
        raw_text: str,
        reviewed_text: str,
        metadata: AudioMetadata,
        *,
        used_fallback: bool = False,
        warnings: tuple[str, ...] = (),
    ) -> "TranscriptionResult":
        """Cria resultado de sucesso."""
        return cls(
            ok=True,
            raw_text=raw_text,
            reviewed_text=reviewed_text,
            metadata=metadata,
            used_fallback=used_fallback,
            warnings=warnings,
        )

    @classmethod
    def failure(
        cls,
        error_code: str,
        error_message: str,
        metadata: Optional[AudioMetadata] = None,
        *,
        raw_text: str = "",
        warnings: tuple[str, ...] = (),
    ) -> "TranscriptionResult":
        """Cria resultado de falha controlada."""
        meta = metadata or AudioMetadata()
        return cls(
            ok=False,
            raw_text=raw_text,
            reviewed_text=raw_text,
            metadata=meta,
            used_fallback=True,
            warnings=warnings,
            error_code=error_code,
            error_message=error_message,
        )

    @property
    def has_numeric_warning(self) -> bool:
        """Indica se há warning relacionado a alteração suspeita de números."""
        return any(w.startswith("suspicious_") for w in self.warnings)


# ---------------------------------------------------------------------------
# Validação de âncoras (números, datas, moeda, unidades) entre raw e reviewed
# ---------------------------------------------------------------------------

_ANCHOR_PATTERNS = {
    "number": r"\b\d+(?:[.,]\d+)?\b",
    "currency": r"R\$\s*\d+(?:[.,]\d+)?",
    "percentage": r"\b\d+(?:[.,]\d+)?\s*%",
    "unit_ha": r"\b\d+(?:[.,]\d+)?\s*ha\b",
    "unit_km": r"\b\d+(?:[.,]\d+)?\s*km\b",
    "unit_kg": r"\b\d+(?:[.,]\d+)?\s*kg\b",
    "unit_liters": r"\b\d+(?:[.,]\d+)?\s*(?:l|litros?)\b",
    "unit_m2": r"\b\d+(?:[.,]\d+)?\s*m2\b",
    "unit_m3": r"\b\d+(?:[.,]\d+)?\s*m3\b",
    "date_br": r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    "date_iso": r"\b\d{4}-\d{2}-\d{2}\b",
    "time": r"\b\d{1,2}:\d{2}\b",
}


def _extract_anchors(text: str) -> dict[str, set[str]]:
    """Extrai âncoras do texto por categoria, priorizando padrões específicos."""
    import re

    anchors: dict[str, set[str]] = {}
    used_spans: list[tuple[int, int]] = []  # (start, end) de matches já capturados

    # Ordem de prioridade: mais específico primeiro
    priority_order = [
        "currency", "percentage", "unit_ha", "unit_km", "unit_kg",
        "unit_liters", "unit_m2", "unit_m3", "date_br", "date_iso", "time",
        "number",  # genérico por último
    ]

    for category in priority_order:
        pattern = _ANCHOR_PATTERNS[category]
        matches = set()
        for m in re.finditer(pattern, text, re.IGNORECASE):
            span = (m.start(), m.end())
            # Verifica se este span já foi capturado por padrão mais específico
            overlaps = any(not (span[1] <= used[0] or span[0] >= used[1]) for used in used_spans)
            if not overlaps:
                matches.add(m.group(0).lower())
                used_spans.append(span)
        if matches:
            anchors[category] = matches

    return anchors


def validate_anchors(raw_text: str, reviewed_text: str) -> tuple[bool, list[str]]:
    """Valida se a revisão preservou todas as âncoras numéricas/temporais.

    Returns:
        tuple: (is_safe, warnings_list)
        - is_safe: False se houve perda ou adição suspeita de âncoras críticas
        - warnings_list: lista de warnings (ex: "suspicious_anchor_loss:currency")
    """
    import re

    raw_anchors = _extract_anchors(raw_text)
    reviewed_anchors = _extract_anchors(reviewed_text)

    warnings = []

    # Categorias críticas que invalidam a revisão se perdidas/adicionadas
    CRITICAL_CATEGORIES = {
        "currency", "date_br", "date_iso", "time",
        "unit_ha", "unit_km", "unit_kg", "unit_liters", "unit_m2", "unit_m3",
        "percentage",
    }

    is_safe = True

    # Verifica perda de âncoras (coletar TODAS as perdas antes de decidir)
    for category, raw_set in raw_anchors.items():
        reviewed_set = reviewed_anchors.get(category, set())
        lost = raw_set - reviewed_set
        if lost:
            warnings.append(f"suspicious_anchor_loss:{category}")
            if category in CRITICAL_CATEGORIES:
                is_safe = False

    # Verifica adição suspeita (coletar TODAS as adições antes de decidir)
    for category, reviewed_set in reviewed_anchors.items():
        raw_set = raw_anchors.get(category, set())
        added = reviewed_set - raw_set
        if added:
            warnings.append(f"suspicious_anchor_gain:{category}")
            if category in CRITICAL_CATEGORIES:
                is_safe = False

    return is_safe, warnings