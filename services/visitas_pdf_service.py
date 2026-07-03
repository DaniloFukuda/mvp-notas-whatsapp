from datetime import datetime
from io import BytesIO
from pathlib import Path
import unicodedata

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
MUTED = colors.HexColor("#607D8B")
WHITE = colors.white
ROW_ALT = colors.HexColor("#FBFDFB")

CONTENT_WIDTH = 18 * cm


def build_visita_pdf(visita_data: dict) -> bytes:
    output = BytesIO()
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.6 * cm,
        title="Relatorio de Visita Tecnica",
    )
    styles = _styles()
    story = [
        _hero_header(visita_data, styles),
        Spacer(1, 0.35 * cm),
        _main_cards(visita_data, styles),
        Spacer(1, 0.35 * cm),
        *_section("Descrição da visita", styles),
        _note_box(
            _text(visita_data.get("descricao_visita")) or "Descrição não informada.",
            styles,
        ),
        Spacer(1, 0.28 * cm),
        *_section("Observações gerais", styles),
        _note_box(
            _text(visita_data.get("observacoes_gerais"))
            or _text(visita_data.get("observacoes"))
            or "Nenhuma observação geral informada.",
            styles,
        ),
        Spacer(1, 0.28 * cm),
        *_section("Resumo da visita", styles),
        _note_box(_executive_summary(visita_data), styles),
        Spacer(1, 0.28 * cm),
        *_section("Objetivo comercial", styles),
        _objective_box(visita_data, styles),
        Spacer(1, 0.28 * cm),
        *_section("Oportunidades e próximos passos", styles),
        _opportunities_box(visita_data, styles),
        Spacer(1, 0.28 * cm),
    ]

    dados = visita_data.get("dados_coletados") or []
    if dados:
        story.extend(_section("Dados coletados", styles))
        rows = [["Chave", "Valor", "Observação"]]
        rows.extend(
            [
                _paragraph(row.get("chave"), styles, "TableBody"),
                _paragraph(row.get("valor"), styles, "TableBody"),
                _paragraph(row.get("observacao"), styles, "TableBody"),
            ]
            for row in dados
        )
        story.append(_data_table(rows, [4.2 * cm, 6.8 * cm, 7 * cm]))
        story.append(Spacer(1, 0.3 * cm))

    location_cards = _location_cards(visita_data, styles)
    if location_cards:
        story.extend(_section("Localizações e pontos de referência", styles))
        story.extend(location_cards)
        story.append(Spacer(1, 0.1 * cm))

    midias = visita_data.get("midias") or []
    if midias:
        story.extend(_section("Registros fotográficos", styles))
        for media in midias:
            story.append(_media_card(media, styles))

    def draw_footer(canvas, doc):
        _footer(canvas, doc, generated_at)

    document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return output.getvalue()


def _hero_header(visita: dict, styles: dict) -> Table:
    logo_or_name = _logo_flowable(styles)
    title = Paragraph("Relatório de Visita Técnica", styles["Title"])
    subtitle = Paragraph("Gestão de Campo &bull; Ciclus Agro", styles["Subtitle"])
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
    farm_name = _text(visita.get("fazenda")) or "Fazenda não informada"
    visit_line = f"Visita técnica registrada em {_format_date(visita.get('data_visita'))}"
    technician = _text(visita.get("tecnico_nome")) or "-"
    status = _text(visita.get("status")).capitalize() or "-"
    highlight = Table(
        [
            [Paragraph(farm_name.upper(), styles["HeroFarm"])],
            [Paragraph(f"{visit_line}<br/>Técnico: {_escape(technician)}<br/>Status: {_escape(status)}", styles["HeroMeta"])],
        ],
        colWidths=[CONTENT_WIDTH],
    )
    highlight.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.55, BORDER_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    header = Table(
        [
            [logo_or_name, title_block],
            ["", ""],
            [highlight, ""],
        ],
        colWidths=[5.8 * cm, 12.2 * cm],
        rowHeights=[2.0 * cm, 0.09 * cm, None],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                ("BACKGROUND", (0, 1), (0, 1), GREEN),
                ("BACKGROUND", (1, 1), (1, 1), BLUE),
                ("SPAN", (0, 2), (1, 2)),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 2), (0, 2), 10),
            ]
        )
    )
    return header


def _logo_flowable(styles: dict):
    if LOGO_PATH.exists():
        try:
            width, height = _scaled_image_size(LOGO_PATH, max_width=4.8 * cm, max_height=1.65 * cm)
            return Image(str(LOGO_PATH), width=width, height=height)
        except Exception:
            pass
    return Paragraph("Ciclus Agro", styles["LogoFallback"])


def _main_cards(visita: dict, styles: dict) -> Table:
    midias = visita.get("midias") or []
    localizacoes = visita.get("localizacoes") or []
    cards = [
        _info_card(
            "Dados da propriedade",
            [
                ("Proprietário", visita.get("proprietario")),
                ("Telefone do proprietário", visita.get("telefone_proprietario")),
                ("Gerente/responsável", visita.get("gerente")),
                ("Telefone do gerente", visita.get("telefone_gerente")),
                ("Área/local visitado", visita.get("area")),
            ],
            styles,
        ),
        _info_card(
            "Área e Safra",
            [
                ("Área em hectares", _number(visita.get("area_hectares"))),
                ("Área em alqueires", _number(visita.get("area_alqueires"))),
                ("Safra", visita.get("safra")),
                ("Tipo de visita", visita.get("tipo_visita")),
            ],
            styles,
        ),
        _info_card(
            "Localização",
            [
                ("Latitude", _number(visita.get("latitude_principal"))),
                ("Longitude", _number(visita.get("longitude_principal"))),
                ("GPS", _maps_link(_text(visita.get("maps_url_principal")), styles, show_url=False)),
            ],
            styles,
        ),
        _info_card(
            "Registro",
            [
                ("ID da visita", visita.get("id")),
                ("Criado em", _format_datetime(visita.get("criado_em"))),
                ("Fechado em", _format_datetime(visita.get("fechado_em"))),
                ("Quantidade de fotos", len(midias)),
                ("Quantidade de localizações", len(localizacoes)),
            ],
            styles,
        ),
    ]
    table = Table(
        [[cards[0], cards[1]], [cards[2], cards[3]]],
        colWidths=[8.75 * cm, 8.75 * cm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (0, -1), 8),
            ]
        )
    )
    return table


def _info_card(title: str, items: list[tuple[str, object]], styles: dict) -> Table:
    body = [Paragraph(title, styles["CardTitle"])]
    for label, value in items:
        value_flowable = value if hasattr(value, "wrap") else _paragraph(value, styles)
        row = Table(
            [[Paragraph(_escape(label), styles["Label"]), value_flowable]],
            colWidths=[3.25 * cm, 4.85 * cm],
        )
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        body.append(row)
    card = Table([[body]], colWidths=[8.35 * cm], hAlign="LEFT")
    card.setStyle(_card_style())
    return card


def _objective_box(visita: dict, styles: dict) -> Table:
    description = _text(visita.get("descricao_visita"))
    objective = _text(visita.get("objetivo"))
    if not objective and description:
        objective = (
            "Objetivo identificado a partir da descrição da visita: "
            f"{_short_text(description)}"
        )

    rows = [
        ["Objetivo", objective or "Objetivo não informado."],
        [
            "Tipo de visita",
            _text(visita.get("tipo_visita"))
            or _infer_visit_type(description),
        ],
    ]
    return _key_value_table(rows, styles)


def _infer_visit_type(description: str) -> str:
    normalized = unicodedata.normalize("NFKD", _text(description))
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).lower()
    classifications = (
        (
            ("apresentacao", "produto", "produtos", "demonstracao", "tecnologia"),
            "Apresentação técnica / Comercial",
        ),
        (
            ("vistoria", "verificacao", "problema", "avaliar"),
            "Vistoria técnica",
        ),
        (
            ("orcamento", "levantamento"),
            "Levantamento para orçamento",
        ),
        (
            ("acompanhamento", "lavoura"),
            "Acompanhamento de lavoura",
        ),
    )
    for keywords, visit_type in classifications:
        if any(keyword in normalized for keyword in keywords):
            return visit_type
    return "Não classificado"


def _short_text(value: str, limit: int = 180) -> str:
    text = " ".join(_text(value).split())
    if len(text) <= limit:
        return text
    shortened = text[: limit - 1].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{shortened or text[: limit - 1]}…"


def _opportunities_box(visita: dict, styles: dict) -> Table:
    opportunity = _detect_opportunity(visita)
    next_step = "Registrar próximos passos comerciais após validação da equipe."
    if opportunity:
        next_step = "Validar oportunidade com a equipe comercial e registrar retorno ao cliente."
    rows = [
        ["Oportunidade identificada", opportunity or "Nenhuma oportunidade específica foi destacada nos dados atuais."],
        ["Próximo passo sugerido", next_step],
    ]
    return _key_value_table(rows, styles)


def _detect_opportunity(visita: dict) -> str:
    observations = _text(visita.get("observacoes"))
    if "orçamento" in observations.lower() or "orcamento" in observations.lower():
        return "Observações mencionam orçamento."
    keywords = ("pedido", "produto", "tanque", "combustível", "combustivel", "adubo", "hectares")
    for row in visita.get("dados_coletados") or []:
        key = _text(row.get("chave")).lower()
        if any(keyword in key for keyword in keywords):
            value = _text(row.get("valor"))
            return f"Dado coletado '{_text(row.get('chave'))}'" + (f": {value}" if value else ".")
    return ""


def _executive_summary(visita: dict) -> str:
    observations = _text(visita.get("observacoes"))
    if observations:
        return observations
    farm = _text(visita.get("fazenda")) or "não informada"
    contact = _text(visita.get("gerente")) or _text(visita.get("proprietario")) or "não informado"
    has_location = "possui localização georreferenciada" if _text(visita.get("maps_url_principal")) else "ainda não possui localização principal registrada"
    has_media = "e registros de campo anexados" if (visita.get("midias") or visita.get("dados_coletados")) else "para acompanhamento da equipe"
    return (
        f"Foi registrada uma visita técnica na Fazenda {farm}, com atendimento ao responsável {contact}. "
        f"A visita {has_location} {has_media}."
    )


def _location_cards(visita: dict, styles: dict) -> list:
    cards = []
    if _text(visita.get("maps_url_principal")) or visita.get("latitude_principal") not in (None, ""):
        cards.append(
            _location_card(
                {
                    "descricao": "Localização principal",
                    "latitude": visita.get("latitude_principal"),
                    "longitude": visita.get("longitude_principal"),
                    "maps_url": visita.get("maps_url_principal"),
                },
                styles,
            )
        )
    for location in visita.get("localizacoes") or []:
        cards.append(_location_card(location, styles))
    return cards


def _location_card(location: dict, styles: dict) -> KeepTogether:
    title = _text(location.get("descricao")) or "Ponto de referência"
    rows = [
        ["Descrição", title],
        ["Latitude / Longitude", f"{_number(location.get('latitude'))} / {_number(location.get('longitude'))}"],
        ["GPS", _maps_link(_text(location.get("maps_url")), styles, show_url=False)],
    ]
    return KeepTogether([_small_card(title, _key_value_table(rows, styles), styles), Spacer(1, 0.18 * cm)])


def _data_table(rows: list[list], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1, splitByRow=1)
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(rows), 2):
        table_style.append(("BACKGROUND", (0, row_index), (-1, row_index), ROW_ALT))
    table.setStyle(TableStyle(table_style))
    return table


def _key_value_table(rows: list[list], styles: dict) -> Table:
    table_rows = [
        [
            Paragraph(_escape(str(label)), styles["Label"]),
            value if hasattr(value, "wrap") else Paragraph(_escape(str(value or "-")), styles["Body"]),
        ]
        for label, value in rows
    ]
    table = Table(table_rows, colWidths=[4.5 * cm, 12.7 * cm], hAlign="LEFT")
    table_style = [
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GREEN),
        ("TEXTCOLOR", (0, 0), (0, -1), DARK_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(1, len(table_rows), 2):
        table_style.append(("BACKGROUND", (1, row_index), (1, row_index), ROW_ALT))
    table.setStyle(TableStyle(table_style))
    return table


def _note_box(text: str, styles: dict) -> Table:
    table = Table([[Paragraph(_escape_lines(text), styles["BodyLarge"])]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), ROW_ALT),
                ("BOX", (0, 0), (-1, -1), 0.35, BORDER_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _media_card(media: dict, styles: dict) -> KeepTogether:
    image_path = Path(_text(media.get("caminho_arquivo")))
    file_name = image_path.name if _text(media.get("caminho_arquivo")) else "-"
    caption = _text(media.get("legenda")) or file_name
    body = [Paragraph(_escape(caption), styles["MediaTitle"])]

    if image_path.exists() and image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        try:
            width, height = _scaled_image_size(image_path, max_width=15.8 * cm, max_height=10 * cm)
            image = Image(str(image_path), width=width, height=height)
            image.hAlign = "CENTER"
            body.extend([Spacer(1, 0.12 * cm), image, Spacer(1, 0.16 * cm)])
        except Exception:
            body.append(Paragraph(f"Imagem não pôde ser aberta: {_escape(file_name)}", styles["Body"]))
    else:
        body.append(Paragraph(f"Arquivo: {_escape(file_name)}", styles["Body"]))

    meta_rows = [
        ["Arquivo", file_name],
        ["Latitude / Longitude", f"{_number(media.get('latitude'))} / {_number(media.get('longitude'))}"],
        ["GPS", _maps_link(_text(media.get("maps_url")), styles, show_url=False)],
    ]
    body.append(_key_value_table(meta_rows, styles))
    card = Table([[body]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    card.setStyle(_card_style())
    return KeepTogether([card, Spacer(1, 0.28 * cm)])


def _small_card(title: str, content, styles: dict) -> Table:
    card = Table([[Paragraph(_escape(title), styles["CardTitle"])], [content]], colWidths=[CONTENT_WIDTH], hAlign="LEFT")
    card.setStyle(_card_style())
    return card


def _card_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, -1), WHITE),
            ("BOX", (0, 0), (-1, -1), 0.45, BORDER_GRAY),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]
    )


def _section(title: str, styles: dict) -> list:
    return [Paragraph(title, styles["Heading"]), Spacer(1, 0.1 * cm)]


def _footer(canvas, document, generated_at: str) -> None:
    canvas.saveState()
    width, _ = A4
    y = 0.95 * cm
    canvas.setStrokeColor(BORDER_GRAY)
    canvas.setLineWidth(0.4)
    canvas.line(document.leftMargin, y + 0.32 * cm, width - document.rightMargin, y + 0.32 * cm)
    canvas.setFont("Helvetica", 7.4)
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
            fontSize=10.8,
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
        "HeroFarm": ParagraphStyle(
            "HeroFarm",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=DARK_BLUE,
            wordWrap="CJK",
        ),
        "HeroMeta": ParagraphStyle(
            "HeroMeta",
            parent=base["Normal"],
            fontSize=9.3,
            leading=13,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "Heading": ParagraphStyle(
            "VisitaHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=DARK_BLUE,
            spaceBefore=5,
            spaceAfter=2,
        ),
        "CardTitle": ParagraphStyle(
            "CardTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.2,
            leading=13,
            textColor=DARK_BLUE,
            spaceAfter=4,
        ),
        "MediaTitle": ParagraphStyle(
            "MediaTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "Label": ParagraphStyle(
            "VisitaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.1,
            leading=10.5,
            textColor=DARK_BLUE,
        ),
        "Body": ParagraphStyle(
            "VisitaBody",
            parent=base["Normal"],
            fontSize=8.4,
            leading=11.2,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "BodyLarge": ParagraphStyle(
            "VisitaBodyLarge",
            parent=base["Normal"],
            fontSize=9.1,
            leading=12.5,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "TableBody": ParagraphStyle(
            "VisitaTableBody",
            parent=base["Normal"],
            fontSize=8.0,
            leading=10.7,
            textColor=TEXT,
            wordWrap="CJK",
        ),
        "Link": ParagraphStyle(
            "VisitaLink",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.4,
            leading=11.2,
            textColor=BLUE,
            wordWrap="CJK",
        ),
    }


def _paragraph(value: object, styles: dict, style_name: str = "Body") -> Paragraph:
    return Paragraph(_escape(_text(value) or "-"), styles[style_name])


def _maps_link(value: str, styles: dict, show_url: bool = True) -> Paragraph:
    url = _text(value)
    if not url:
        return Paragraph("-", styles["Body"])
    escaped_url = _escape(url)
    suffix = f"<br/>{escaped_url}" if show_url else ""
    return Paragraph(f'<a href="{escaped_url}" color="#2B78C2">Abrir no Google Maps</a>{suffix}', styles["Link"])


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
    parts = text[:10].split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return text


def _format_datetime(value: object) -> str:
    text = _text(value)
    if not text:
        return "-"
    normalized = text.replace("T", " ")
    date_part = _format_date(normalized[:10])
    time_part = normalized[11:16] if len(normalized) >= 16 else ""
    return f"{date_part} {time_part}".strip()
