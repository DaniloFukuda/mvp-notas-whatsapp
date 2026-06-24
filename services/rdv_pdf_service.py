from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


GREEN = colors.HexColor("#4CAF2F")
BLUE = colors.HexColor("#2B78C2")
DARK_BLUE = colors.HexColor("#16435C")
LIGHT_GREEN = colors.HexColor("#F4FAF1")
LIGHT_BLUE = colors.HexColor("#EEF6FC")
BORDER_GRAY = colors.HexColor("#DDE8DD")
TEXT = colors.HexColor("#263238")
MUTED = colors.HexColor("#5F6F73")
WHITE = colors.white

CONTENT_WIDTH = 26.7 * cm


def build_monthly_rdv_pdf(report_data: dict) -> bytes:
    period = str(report_data.get("mes") or "").strip()
    return _build_rdv_pdf(
        report_data=report_data,
        title="Relatorio mensal de RDV",
        period_label=f"Mes: {period or '-'}",
    )


def build_weekly_rdv_pdf(report_data: dict) -> bytes:
    period = str(report_data.get("semana") or "").strip()
    return _build_rdv_pdf(
        report_data=report_data,
        title="Relatorio semanal de RDV",
        period_label=f"Semana: {period or '-'}",
    )


def _build_rdv_pdf(report_data: dict, title: str, period_label: str) -> bytes:
    output = BytesIO()
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.5 * cm,
        title=title,
    )
    styles = _styles()
    story = [
        _header(title, period_label, generated_at, styles),
        Spacer(1, 0.35 * cm),
        _summary_table(report_data, styles),
        Spacer(1, 0.35 * cm),
        _section_title("Despesas", styles),
        _expenses_table(report_data.get("lancamentos") or [], styles),
    ]

    km_launches = report_data.get("quilometragens") or []
    if km_launches:
        story.extend(
            [
                Spacer(1, 0.35 * cm),
                _section_title("KM", styles),
                _km_table(km_launches, styles),
            ]
        )

    story.extend(
        [
            Spacer(1, 0.35 * cm),
            _section_title("Visitas tecnicas", styles),
            Paragraph(
                "Secao reservada para consolidacao futura de visitas tecnicas ou "
                "relatorio separado de visitas.",
                styles["Body"],
            ),
        ]
    )

    def draw_footer(canvas, doc):
        _footer(canvas, doc, generated_at)

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return output.getvalue()


def _header(title: str, period_label: str, generated_at: str, styles: dict) -> Table:
    brand = Paragraph("Ciclus Agro", styles["Brand"])
    report_title = Paragraph(title, styles["Title"])
    meta = Paragraph(
        f"{period_label}<br/>Gerado em: {generated_at}",
        styles["Meta"],
    )
    table = Table(
        [[brand, report_title, meta], ["", "", ""]],
        colWidths=[6.2 * cm, 12.5 * cm, 8 * cm],
        rowHeights=[1.7 * cm, 0.08 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ("ALIGN", (1, 0), (2, 0), "RIGHT"),
                ("BACKGROUND", (0, 1), (0, 1), GREEN),
                ("BACKGROUND", (1, 1), (2, 1), BLUE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _summary_table(report_data: dict, styles: dict) -> Table:
    rows = [
        [
            Paragraph("Total de despesas", styles["SummaryLabel"]),
            Paragraph("Lancamentos", styles["SummaryLabel"]),
            Paragraph("Comprovantes", styles["SummaryLabel"]),
            Paragraph("KM rodado", styles["SummaryLabel"]),
            Paragraph("Pendentes", styles["SummaryLabel"]),
        ],
        [
            Paragraph(_format_brl(report_data.get("total_geral")), styles["SummaryValue"]),
            Paragraph(str(report_data.get("quantidade_lancamentos") or 0), styles["SummaryValue"]),
            Paragraph(str(report_data.get("quantidade_comprovantes") or 0), styles["SummaryValue"]),
            Paragraph(_format_km(report_data.get("quilometragem_total")), styles["SummaryValue"]),
            Paragraph(str(report_data.get("pendentes_revisao") or 0), styles["SummaryValue"]),
        ],
    ]
    table = Table(rows, colWidths=[5.4 * cm] * 5)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_GRAY),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _section_title(text: str, styles: dict) -> Paragraph:
    return Paragraph(text, styles["Heading"])


def _expenses_table(rows: list[dict], styles: dict) -> Table:
    if not rows:
        return _empty_table("Nenhuma despesa encontrada para o periodo.", styles)
    table_rows = [[
        "Data",
        "Colaborador",
        "Categoria",
        "Valor",
        "Fornecedor",
        "Status",
        "Arquivo",
    ]]
    for row in rows:
        table_rows.append(
            [
                _paragraph(_format_date(row.get("data_despesa")), styles),
                _paragraph(row.get("colaborador"), styles),
                _paragraph(_humanize(row.get("categoria")), styles),
                _paragraph(_format_brl(row.get("valor")), styles),
                _paragraph(row.get("fornecedor_detectado") or row.get("fornecedor"), styles),
                _paragraph(_launch_status(row), styles),
                _paragraph(_filename(row.get("caminho_arquivo")), styles),
            ]
        )
    return _data_table(table_rows, [2.3 * cm, 4 * cm, 3.5 * cm, 2.6 * cm, 5 * cm, 4.2 * cm, 5.1 * cm])


def _km_table(rows: list[dict], styles: dict) -> Table:
    table_rows = [["Data", "Colaborador", "Origem", "Destino", "KM inicial", "KM final", "KM rodado", "Status"]]
    for row in rows:
        table_rows.append(
            [
                _paragraph(_format_date(row.get("data_despesa")), styles),
                _paragraph(row.get("colaborador"), styles),
                _paragraph(row.get("cidade_origem"), styles),
                _paragraph(row.get("cidade_destino"), styles),
                _paragraph(_number(row.get("km_inicio")), styles),
                _paragraph(_number(row.get("km_fim")), styles),
                _paragraph(_format_km(row.get("quilometragem") or row.get("km_rodado")), styles),
                _paragraph(_launch_status(row), styles),
            ]
        )
    return _data_table(table_rows, [2.2 * cm, 3.6 * cm, 4 * cm, 4 * cm, 2.7 * cm, 2.7 * cm, 2.7 * cm, 4.8 * cm])


def _empty_table(message: str, styles: dict) -> Table:
    table = Table([[Paragraph(message, styles["Body"])]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _data_table(rows: list, col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, BORDER_GRAY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BLUE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _footer(canvas, document, generated_at: str) -> None:
    canvas.saveState()
    width, _height = landscape(A4)
    y = 0.65 * cm
    canvas.setStrokeColor(BORDER_GRAY)
    canvas.line(document.leftMargin, y + 0.32 * cm, width - document.rightMargin, y + 0.32 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        document.leftMargin,
        y,
        f"Ciclus Agro - Relatorio gerado automaticamente pelo WhatsApp - {generated_at}",
    )
    canvas.drawRightString(width - document.rightMargin, y, f"Pagina {document.page}")
    canvas.restoreState()


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "Brand": ParagraphStyle(
            "RDVBrand",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=DARK_BLUE,
        ),
        "Title": ParagraphStyle(
            "RDVTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            alignment=2,
            textColor=DARK_BLUE,
        ),
        "Meta": ParagraphStyle(
            "RDVMeta",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            alignment=2,
            textColor=MUTED,
        ),
        "Heading": ParagraphStyle(
            "RDVHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=DARK_BLUE,
            spaceAfter=4,
        ),
        "SummaryLabel": ParagraphStyle(
            "RDVSummaryLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=MUTED,
        ),
        "SummaryValue": ParagraphStyle(
            "RDVSummaryValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=TEXT,
        ),
        "Body": ParagraphStyle(
            "RDVBody",
            parent=base["Normal"],
            fontSize=7.8,
            leading=10,
            textColor=TEXT,
            wordWrap="CJK",
        ),
    }


def _paragraph(value: object, styles: dict) -> Paragraph:
    return Paragraph(_escape(_text(value) or "-"), styles["Body"])


def _format_brl(value: object) -> str:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        parsed = 0.0
    text = f"{parsed:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def _format_km(value: object) -> str:
    number = _number(value)
    return f"{number} km" if number != "-" else "0 km"


def _number(value: object) -> str:
    if value in (None, ""):
        return "-"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return _text(value) or "-"
    if parsed.is_integer():
        return str(int(parsed))
    return f"{parsed:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _format_date(value: object) -> str:
    text = _text(value)
    if not text:
        return "-"
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return text


def _launch_status(row: dict) -> str:
    flow_status = _humanize(row.get("status_fluxo"))
    review_status = _humanize(row.get("status_revisao"))
    return f"{flow_status} / {review_status}" if review_status else flow_status


def _filename(value: object) -> str:
    text = _text(value)
    if not text:
        return ""
    return text.replace("\\", "/").split("/")[-1]


def _humanize(value: object) -> str:
    return _text(value).replace("_", " ").title()


def _text(value: object) -> str:
    return str(value or "").strip()


def _escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
