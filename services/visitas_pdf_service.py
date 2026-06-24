from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGO_PATH = PROJECT_ROOT / "assets" / "branding" / "ciclus_agro_logo.jpeg"

GREEN = colors.HexColor("#4CAF2F")
BLUE = colors.HexColor("#2B78C2")
DARK_BLUE = colors.HexColor("#16435C")
LIGHT_GREEN = colors.HexColor("#F4FAF1")
BORDER_GRAY = colors.HexColor("#DDE8DD")
TEXT = colors.HexColor("#263238")
MUTED = colors.HexColor("#5F6F73")
WHITE = colors.white

CONTENT_WIDTH = 18 * cm


def build_visita_pdf(visita_data: dict) -> bytes:
    output = BytesIO()
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.3 * cm,
        bottomMargin=1.6 * cm,
        title="Relatório de Visita Técnica",
    )
    styles = _styles()
    story = [
        _header(styles),
        Spacer(1, 0.35 * cm),
        _summary_card(visita_data, styles),
        Spacer(1, 0.35 * cm),
    ]

    story.extend(_section("Dados gerais", styles))
    story.append(_info_table(visita_data, styles))
    story.append(Spacer(1, 0.35 * cm))

    maps_url = _text(visita_data.get("maps_url_principal"))
    if maps_url:
        gps_lines = [
            ["Latitude", _number(visita_data.get("latitude_principal"))],
            ["Longitude", _number(visita_data.get("longitude_principal"))],
            ["Link GPS", _maps_link(maps_url, styles)],
        ]
        story.extend(_section("Localização principal", styles))
        story.append(_key_value_table(gps_lines, styles))
        story.append(Spacer(1, 0.3 * cm))

    observations = _text(visita_data.get("observacoes_gerais")) or _text(visita_data.get("observacoes"))
    if observations:
        story.extend(_section("Observações", styles))
        story.append(_note_box(observations, styles))
        story.append(Spacer(1, 0.3 * cm))

    dados = visita_data.get("dados_coletados") or []
    if dados:
        story.extend(_section("Dados coletados", styles))
        rows = [["Chave", "Valor", "Observação"]]
        rows.extend(
            [
                _paragraph(row.get("chave"), styles),
                _paragraph(row.get("valor"), styles),
                _paragraph(row.get("observacao"), styles),
            ]
            for row in dados
        )
        story.append(_data_table(rows, [4.2 * cm, 7.1 * cm, 6.7 * cm]))
        story.append(Spacer(1, 0.3 * cm))

    localizacoes = visita_data.get("localizacoes") or []
    if localizacoes:
        story.extend(_section("Localizações", styles))
        rows = [["Descrição", "Latitude", "Longitude", "Link GPS"]]
        rows.extend(
            [
                _paragraph(row.get("descricao") or "Ponto", styles),
                _paragraph(_number(row.get("latitude")), styles),
                _paragraph(_number(row.get("longitude")), styles),
                _maps_link(_text(row.get("maps_url")), styles),
            ]
            for row in localizacoes
        )
        story.append(_data_table(rows, [4.2 * cm, 3 * cm, 3 * cm, 7.8 * cm]))
        story.append(Spacer(1, 0.3 * cm))

    midias = visita_data.get("midias") or []
    if midias:
        story.extend(_section("Fotos e anexos", styles))
        for media in midias:
            story.append(_media_block(media, styles))

    def draw_footer(canvas, doc):
        _footer(canvas, doc, generated_at)

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return output.getvalue()


def _header(styles: dict) -> Table:
    logo_or_name = _logo_flowable(styles)
    title = Paragraph("Relatório de Visita Técnica", styles["Title"])
    subtitle = Paragraph("Ciclus Agro", styles["Subtitle"])
    title_block = Table([[title], [subtitle]], colWidths=[12.2 * cm], hAlign="RIGHT")
    title_block.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    header = Table(
        [
            [logo_or_name, title_block],
            ["", ""],
        ],
        colWidths=[5.8 * cm, 12.2 * cm],
        rowHeights=[2.1 * cm, 0.08 * cm],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ("SPAN", (0, 1), (0, 1)),
                ("BACKGROUND", (0, 1), (0, 1), GREEN),
                ("BACKGROUND", (1, 1), (1, 1), BLUE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return header


def _logo_flowable(styles: dict):
    if LOGO_PATH.exists():
        try:
            width, height = _scaled_image_size(LOGO_PATH, max_width=4.6 * cm, max_height=1.7 * cm)
            return Image(str(LOGO_PATH), width=width, height=height)
        except Exception:
            pass
    return Paragraph("Ciclus Agro", styles["LogoFallback"])


def _summary_card(visita: dict, styles: dict) -> Table:
    title = Paragraph("Resumo da visita", styles["CardTitle"])
    rows = [
        [
            Paragraph("Fazenda", styles["SummaryLabel"]),
            Paragraph("Data da visita", styles["SummaryLabel"]),
            Paragraph("Técnico", styles["SummaryLabel"]),
            Paragraph("Status", styles["SummaryLabel"]),
        ],
        [
            _paragraph(visita.get("fazenda"), styles, "SummaryValue"),
            _paragraph(_format_date(visita.get("data_visita")), styles, "SummaryValue"),
            _paragraph(visita.get("tecnico_nome"), styles, "SummaryValue"),
            _paragraph(visita.get("status"), styles, "SummaryValue"),
        ],
    ]
    table = Table([[title], [Table(rows, colWidths=[4.9 * cm, 4.1 * cm, 4.7 * cm, 3.7 * cm])]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _info_table(visita: dict, styles: dict) -> Table:
    rows = [
        ["Técnico", _text(visita.get("tecnico_nome"))],
        ["Telefone", _text(visita.get("telefone_origem"))],
        ["Fazenda", _text(visita.get("fazenda"))],
        ["Proprietário", _text(visita.get("proprietario"))],
        ["Gerente/responsável", _text(visita.get("gerente"))],
        ["Safra", _text(visita.get("safra"))],
        ["Tipo de visita", _text(visita.get("tipo_visita"))],
        ["Área em hectares", _number(visita.get("area_hectares"))],
        ["Área em alqueires", _number(visita.get("area_alqueires"))],
        ["Status", _text(visita.get("status"))],
    ]
    return _key_value_table(rows, styles)


def _info_table(visita: dict, styles: dict) -> Table:
    rows = [
        ["Técnico", _text(visita.get("tecnico_nome"))],
        ["Telefone", _text(visita.get("telefone_origem"))],
        ["Fazenda/propriedade", _text(visita.get("fazenda"))],
        ["Proprietário", _text(visita.get("proprietario"))],
        ["Telefone do proprietário", _text(visita.get("telefone_proprietario"))],
        ["Gerente/responsável local", _text(visita.get("gerente"))],
        ["Telefone do gerente", _text(visita.get("telefone_gerente"))],
        ["Área/local visitado", _text(visita.get("area"))],
        ["Área em hectares", _number(visita.get("area_hectares"))],
        ["Área em alqueires", _number(visita.get("area_alqueires"))],
        ["Descrição da visita", _text(visita.get("descricao_visita")) or _text(visita.get("tipo_visita"))],
        ["Status", _text(visita.get("status"))],
    ]
    return _key_value_table(rows, styles)


def _key_value_table(rows: list[list], styles: dict) -> Table:
    table_rows = [
        [
            Paragraph(_escape(str(label)), styles["Label"]),
            value if hasattr(value, "wrap") else Paragraph(_escape(str(value or "-")), styles["Body"]),
        ]
        for label, value in rows
    ]
    table = Table(table_rows, colWidths=[4.6 * cm, 13.4 * cm], hAlign="LEFT")
    table_style = [
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GREEN),
        ("TEXTCOLOR", (0, 0), (0, -1), DARK_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(table_rows), 2):
        table_style.append(("BACKGROUND", (1, row_index), (1, row_index), colors.HexColor("#FBFDFB")))
    table.setStyle(TableStyle(table_style))
    return table


def _data_table(rows: list[list], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(rows), 2):
        table_style.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#FBFDFB")))
    table.setStyle(TableStyle(table_style))
    return table


def _note_box(text: str, styles: dict) -> Table:
    table = Table([[Paragraph(_escape_lines(text), styles["Body"])]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFDFB")),
                ("BOX", (0, 0), (-1, -1), 0.35, BORDER_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _media_block(media: dict, styles: dict) -> KeepTogether:
    image_path = Path(_text(media.get("caminho_arquivo")))
    file_name = image_path.name if _text(media.get("caminho_arquivo")) else "-"
    rows = [
        ["Comentário", _text(media.get("comentario")) or _text(media.get("legenda"))],
        ["Arquivo", file_name],
        ["Latitude", _number(media.get("latitude"))],
        ["Longitude", _number(media.get("longitude"))],
        ["Link GPS", _maps_link(_text(media.get("maps_url")), styles)],
    ]
    elements = [_key_value_table(rows, styles), Spacer(1, 0.18 * cm)]
    if image_path.exists() and image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        try:
            width, height = _scaled_image_size(image_path, max_width=13.5 * cm, max_height=8.5 * cm)
            image = Image(str(image_path), width=width, height=height)
            image.hAlign = "CENTER"
            elements.extend([image, Spacer(1, 0.2 * cm)])
        except Exception:
            elements.append(Paragraph(f"Imagem não pôde ser aberta: {_escape(file_name)}", styles["Body"]))
    card = Table([[elements]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
                ("BOX", (0, 0), (-1, -1), 0.45, BORDER_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return KeepTogether([card, Spacer(1, 0.25 * cm)])


def _section(title: str, styles: dict) -> list:
    return [Paragraph(title, styles["Heading"]), Spacer(1, 0.12 * cm)]


def _footer(canvas, document, generated_at: str) -> None:
    canvas.saveState()
    width, _ = A4
    y = 0.95 * cm
    canvas.setStrokeColor(BORDER_GRAY)
    canvas.setLineWidth(0.4)
    canvas.line(document.leftMargin, y + 0.32 * cm, width - document.rightMargin, y + 0.32 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    left_text = f"Ciclus Agro • Relatório gerado automaticamente pelo WhatsApp • {generated_at}"
    page_text = f"Página {document.page}"
    canvas.drawString(document.leftMargin, y, left_text)
    canvas.drawRightString(width - document.rightMargin, y, page_text)
    canvas.restoreState()


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "VisitaTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            alignment=2,
            textColor=DARK_BLUE,
            spaceAfter=4,
        ),
        "Subtitle": ParagraphStyle(
            "VisitaSubtitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            alignment=2,
            textColor=GREEN,
        ),
        "LogoFallback": ParagraphStyle(
            "LogoFallback",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=DARK_BLUE,
        ),
        "Heading": ParagraphStyle(
            "VisitaHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=DARK_BLUE,
            spaceBefore=6,
            spaceAfter=2,
        ),
        "CardTitle": ParagraphStyle(
            "CardTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=DARK_BLUE,
            spaceAfter=6,
        ),
        "SummaryLabel": ParagraphStyle(
            "SummaryLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=10,
            textColor=MUTED,
        ),
        "SummaryValue": ParagraphStyle(
            "SummaryValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "Label": ParagraphStyle(
            "VisitaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.6,
            leading=11,
            textColor=DARK_BLUE,
        ),
        "Body": ParagraphStyle(
            "VisitaBody",
            parent=base["Normal"],
            fontSize=8.6,
            leading=11.5,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "Link": ParagraphStyle(
            "VisitaLink",
            parent=base["Normal"],
            fontSize=8.6,
            leading=11.5,
            textColor=BLUE,
            wordWrap="CJK",
        ),
    }


def _paragraph(value: object, styles: dict, style_name: str = "Body") -> Paragraph:
    return Paragraph(_escape(_text(value) or "-"), styles[style_name])


def _maps_link(value: str, styles: dict) -> Paragraph:
    url = _text(value)
    if not url:
        return Paragraph("-", styles["Body"])
    escaped_url = _escape(url)
    return Paragraph(f'<a href="{escaped_url}" color="#2B78C2">Abrir no Google Maps</a><br/>{escaped_url}', styles["Link"])


def _scaled_image_size(path: Path, max_width: float, max_height: float) -> tuple[float, float]:
    original_width, original_height = ImageReader(str(path)).getSize()
    if not original_width or not original_height:
        return max_width, max_height
    ratio = min(max_width / original_width, max_height / original_height)
    return original_width * ratio, original_height * ratio


def _escape_lines(value: str) -> str:
    return "<br/>".join(_escape(line) for line in str(value or "").splitlines())


def _escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def _number(value: object) -> str:
    if value in (None, ""):
        return "-"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return _text(value) or "-"
    if parsed.is_integer():
        return str(int(parsed))
    return f"{parsed:.6f}".rstrip("0").rstrip(".")


def _format_date(value: object) -> str:
    text = _text(value)
    if not text:
        return "-"
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return text
