import re
from dataclasses import dataclass
from typing import Literal


VisitReportCommandKind = Literal["by_id", "by_fazenda", "list"]


@dataclass(frozen=True)
class VisitReportCommand:
    kind: VisitReportCommandKind
    visita_id: int | None = None
    fazenda_query: str = ""


def parse_visit_report_command(normalized_text: str, original_text: str = "") -> VisitReportCommand | None:
    text = str(normalized_text or "").strip()
    if not text:
        return None

    id_match = re.fullmatch(
        r"(?:relatorio visitas?|pdf visita|visita pdf)\s+(\d+)",
        text,
    )
    if id_match is not None:
        return VisitReportCommand(kind="by_id", visita_id=int(id_match.group(1)))

    fazenda_match = re.fullmatch(r"relatorio fazenda\s+(.+)", text)
    if fazenda_match is not None:
        return VisitReportCommand(
            kind="by_fazenda",
            fazenda_query=_extract_fazenda_query(original_text),
        )

    if re.fullmatch(r"(?:relatorio visitas?|pdf visita|visita pdf)", text):
        return VisitReportCommand(kind="list")

    return None


def _extract_fazenda_query(text: str) -> str:
    match = re.match(r"(?is)\s*relat[oó]rio\s+fazenda\s+(.+?)\s*$", str(text or ""))
    if match is not None:
        return match.group(1).strip()
    return re.sub(r"(?i)^relatorio\s+fazenda\s+", "", str(text or "")).strip()
