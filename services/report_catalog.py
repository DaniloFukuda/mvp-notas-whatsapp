import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from services.rdv_service import calculate_month_reference, calculate_week_reference


ReportFormat = Literal["text", "excel", "pdf"]
ReportPeriod = Literal["mensal", "semanal", "visitas"]


@dataclass(frozen=True)
class ReportDefinition:
    report_id: str
    menu_title: str
    menu_description: str
    aliases: tuple[str, ...]
    format: ReportFormat
    period: ReportPeriod
    handler: str
    menu_section: str


REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        report_id="menu_rdv_summary",
        menu_title="Resumo RDV",
        menu_description="Resumo mensal de despesas",
        aliases=("resumo", "resumo mensal", "resumo mes"),
        format="text",
        period="mensal",
        handler="rdv_summary",
        menu_section="RDV",
    ),
    ReportDefinition(
        report_id="menu_rdv_excel",
        menu_title="Planilha RDV",
        menu_description="Excel mensal de despesas",
        aliases=("planilha", "planilha mensal", "excel", "excel mensal", "relatorio", "relatorio mensal"),
        format="excel",
        period="mensal",
        handler="rdv_excel",
        menu_section="RDV",
    ),
    ReportDefinition(
        report_id="menu_rdv_pdf",
        menu_title="PDF RDV",
        menu_description="Relatório mensal em PDF",
        aliases=("pdf", "pdf rdv", "pdf mensal", "relatorio pdf", "relatorio mensal pdf"),
        format="pdf",
        period="mensal",
        handler="rdv_pdf",
        menu_section="RDV",
    ),
    ReportDefinition(
        report_id="menu_weekly_summary",
        menu_title="Resumo semanal",
        menu_description="Resumo semanal de despesas",
        aliases=("resumo semanal", "resumo semana"),
        format="text",
        period="semanal",
        handler="rdv_summary",
        menu_section="RDV",
    ),
    ReportDefinition(
        report_id="menu_weekly_excel",
        menu_title="Planilha semanal",
        menu_description="Excel semanal de despesas",
        aliases=("planilha semanal", "planilha semana", "excel semanal", "excel semana", "relatorio semanal"),
        format="excel",
        period="semanal",
        handler="rdv_excel",
        menu_section="RDV",
    ),
    ReportDefinition(
        report_id="menu_weekly_pdf",
        menu_title="PDF semanal",
        menu_description="Relatório semanal em PDF",
        aliases=("pdf semanal", "pdf semana", "relatorio semanal pdf", "relatorio pdf semanal"),
        format="pdf",
        period="semanal",
        handler="rdv_pdf",
        menu_section="RDV",
    ),
    ReportDefinition(
        report_id="menu_visit_list",
        menu_title="Listar visitas",
        menu_description="Ver visitas/fazendas",
        aliases=("visitas", "listar visitas", "visitas hoje", "visitas abertas", "fazendas"),
        format="text",
        period="visitas",
        handler="visit_list",
        menu_section="Visitas técnicas",
    ),
    ReportDefinition(
        report_id="menu_visit_excel",
        menu_title="Planilha visitas",
        menu_description="Excel de visitas técnicas",
        aliases=("planilha visitas", "fazendas visitadas"),
        format="excel",
        period="visitas",
        handler="visit_excel",
        menu_section="Visitas técnicas",
    ),
)


REPORTS_BY_ID = {report.report_id: report for report in REPORT_DEFINITIONS}


def report_menu_sections() -> list[dict]:
    sections: list[dict] = []
    for section_title in ("RDV", "Visitas técnicas"):
        rows = [
            {
                "id": report.report_id,
                "title": report.menu_title,
                "description": report.menu_description,
            }
            for report in REPORT_DEFINITIONS
            if report.menu_section == section_title
        ]
        sections.append({"title": section_title, "rows": rows})
    return sections


def interactive_report_commands() -> dict[str, str]:
    return {
        report.report_id: report.aliases[0]
        for report in REPORT_DEFINITIONS
        if report.aliases
    }


def report_aliases(handler: str | None = None, report_id: str | None = None) -> set[str]:
    aliases: set[str] = set()
    for report in REPORT_DEFINITIONS:
        if handler is not None and report.handler != handler:
            continue
        if report_id is not None and report.report_id != report_id:
            continue
        aliases.update(report.aliases)
    return aliases


def parse_rdv_report_command(normalized_text: str, today: date | None = None) -> dict | None:
    text = str(normalized_text or "").strip()
    if not text:
        return None

    selected_today = today or date.today()
    reference = _extract_report_reference(text)
    definition = _match_exact_alias(text) or _match_parameterized_alias(text)
    if definition is None:
        return None

    if reference is not None:
        period = "week" if _is_week_reference(reference) else "month"
        return _request(definition, period, _normalize_reference(reference), "all")

    if _is_previous_month_request(text):
        return _request(
            definition,
            "month",
            _previous_month_reference(selected_today),
            "all",
        )

    if definition.period == "semanal":
        return _request(
            definition,
            "week",
            calculate_week_reference(selected_today),
            "all",
        )

    return _request(
        definition,
        "month",
        calculate_month_reference(selected_today),
        "all",
    )


def _match_exact_alias(text: str) -> ReportDefinition | None:
    for report in REPORT_DEFINITIONS:
        if report.period == "visitas":
            continue
        if text in report.aliases:
            return report
    return None


def _match_parameterized_alias(text: str) -> ReportDefinition | None:
    if re.fullmatch(r"(?:pdf visita|visita pdf)\s+\d+", text):
        return None

    if re.search(r"(?:^|\s)pdf(?:\s|$)", text):
        if re.search(r"(?:^|\s)(semanal|semana)(?:\s|$)", text) or _is_week_reference(text):
            return _definition("pdf", "semanal")
        return _definition("pdf", "mensal")

    match = re.fullmatch(r"(resumo|planilha|relatorio|excel)(?:\s+(.+))?", text)
    if match is not None:
        command = match.group(1)
        argument = str(match.group(2) or "").strip()
        if command == "resumo":
            if argument in {"", "mensal", "mes", "anterior", "mes anterior"} or _extract_report_reference(argument):
                return _definition("text", "semanal" if argument in {"semanal", "semana"} or _is_week_reference(argument) else "mensal")
            if argument in {"semanal", "semana"}:
                return _definition("text", "semanal")
            return None
        if argument in {"semanal", "semana"} or _is_week_reference(argument):
            return _definition("excel", "semanal")
        if argument in {"", "mensal", "mes", "anterior", "mes anterior"} or _extract_report_reference(argument):
            return _definition("excel", "mensal")
        return None

    return None


def _definition(format: ReportFormat, period: ReportPeriod) -> ReportDefinition | None:
    for report in REPORT_DEFINITIONS:
        if report.format == format and report.period == period:
            return report
    return None


def _request(
    definition: ReportDefinition,
    period: Literal["month", "week"],
    reference: str,
    scope: str,
) -> dict:
    return {
        "id": definition.report_id,
        "kind": "summary" if definition.format == "text" else definition.format,
        "format": definition.format,
        "period": period,
        "reference": reference,
        "scope": scope,
        "handler": definition.handler,
    }


def _extract_report_reference(text: str) -> str | None:
    week_match = re.search(r"\b\d{4}-W\d{2}\b", text, flags=re.IGNORECASE)
    if week_match is not None:
        return week_match.group(0)
    month_match = re.search(r"\b\d{4}-\d{2}\b", text)
    if month_match is not None:
        return month_match.group(0)
    return None


def _is_week_reference(text: str) -> bool:
    return re.search(r"\b\d{4}-W\d{2}\b", str(text or ""), flags=re.IGNORECASE) is not None


def _is_previous_month_request(text: str) -> bool:
    return (
        re.fullmatch(r"(resumo|planilha|relatorio|excel)\s+(anterior|mes anterior)", text)
        is not None
    )


def _normalize_reference(reference: str) -> str:
    return reference.upper() if _is_week_reference(reference) else reference


def _previous_month_reference(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"
