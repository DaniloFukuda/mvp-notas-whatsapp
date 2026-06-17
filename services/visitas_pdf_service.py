from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def build_visita_pdf(visita_data: dict) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Relatorio de Visita Tecnica",
    )
    styles = _styles()
    story = [
        Paragraph("Relatorio de Visita Tecnica", styles["Title"]),
        Paragraph("Ciclus Agro", styles["Subtitle"]),
        Spacer(1, 0.35 * cm),
    ]

    story.append(_info_table(visita_data, styles))
    story.append(Spacer(1, 0.35 * cm))

    maps_url = _text(visita_data.get("maps_url_principal"))
    if maps_url:
        gps_lines = [
            ["Localizacao principal", maps_url],
            ["Latitude", _number(visita_data.get("latitude_principal"))],
            ["Longitude", _number(visita_data.get("longitude_principal"))],
        ]
        story.extend(_section("Localizacao principal", styles))
        story.append(_key_value_table(gps_lines, styles))
        story.append(Spacer(1, 0.25 * cm))

    observations = _text(visita_data.get("observacoes"))
    if observations:
        story.extend(_section("Observacoes", styles))
        story.append(Paragraph(_escape_lines(observations), styles["Body"]))
        story.append(Spacer(1, 0.25 * cm))

    dados = visita_data.get("dados_coletados") or []
    if dados:
        story.extend(_section("Dados coletados", styles))
        rows = [["Chave", "Valor", "Observacao"]]
        rows.extend(
            [
                _paragraph(row.get("chave"), styles),
                _paragraph(row.get("valor"), styles),
                _paragraph(row.get("observacao"), styles),
            ]
            for row in dados
        )
        story.append(_data_table(rows, [4 * cm, 7 * cm, 5 * cm]))
        story.append(Spacer(1, 0.25 * cm))

    localizacoes = visita_data.get("localizacoes") or []
    if localizacoes:
        story.extend(_section("Localizacoes", styles))
        rows = [["Descricao", "Latitude", "Longitude", "Link GPS"]]
        rows.extend(
            [
                _paragraph(row.get("descricao") or "Ponto", styles),
                _paragraph(_number(row.get("latitude")), styles),
                _paragraph(_number(row.get("longitude")), styles),
                _paragraph(row.get("maps_url"), styles),
            ]
            for row in localizacoes
        )
        story.append(_data_table(rows, [3.5 * cm, 3 * cm, 3 * cm, 6.5 * cm]))
        story.append(Spacer(1, 0.25 * cm))

    midias = visita_data.get("midias") or []
    if midias:
        story.extend(_section("Fotos e anexos", styles))
        for media in midias:
            story.append(_media_block(media, styles))

    document.build(story)
    return output.getvalue()


def _info_table(visita: dict, styles: dict) -> Table:
    rows = [
        ["Data da visita", _format_date(visita.get("data_visita"))],
        ["Tecnico", _text(visita.get("tecnico_nome"))],
        ["Telefone", _text(visita.get("telefone_origem"))],
        ["Fazenda", _text(visita.get("fazenda"))],
        ["Proprietario", _text(visita.get("proprietario"))],
        ["Gerente/responsavel", _text(visita.get("gerente"))],
        ["Safra", _text(visita.get("safra"))],
        ["Tipo de visita", _text(visita.get("tipo_visita"))],
        ["Area em hectares", _number(visita.get("area_hectares"))],
        ["Area em alqueires", _number(visita.get("area_alqueires"))],
        ["Status", _text(visita.get("status"))],
    ]
    return _key_value_table(rows, styles)


def _key_value_table(rows: list[list[str]], styles: dict) -> Table:
    table_rows = [
        [Paragraph(str(label), styles["Label"]), Paragraph(_escape(str(value or "-")), styles["Body"])]
        for label, value in rows
    ]
    table = Table(table_rows, colWidths=[4.5 * cm, 11.5 * cm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F7")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1F4E78")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _data_table(rows: list[list], col_widths: list[float]) -> Table:
    table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _media_block(media: dict, styles: dict) -> KeepTogether:
    lines = [
        ["Legenda", _text(media.get("legenda"))],
        ["Arquivo", Path(_text(media.get("caminho_arquivo"))).name if media.get("caminho_arquivo") else "-"],
        ["Latitude", _number(media.get("latitude"))],
        ["Longitude", _number(media.get("longitude"))],
        ["Link GPS", _text(media.get("maps_url"))],
    ]
    elements = [_key_value_table(lines, styles), Spacer(1, 0.15 * cm)]
    image_path = Path(_text(media.get("caminho_arquivo")))
    if image_path.exists() and image_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        try:
            elements.extend([Image(str(image_path), width=8 * cm, height=6 * cm, kind="proportional"), Spacer(1, 0.2 * cm)])
        except Exception:
            pass
    return KeepTogether(elements)


def _section(title: str, styles: dict) -> list:
    return [Paragraph(title, styles["Heading"]), Spacer(1, 0.12 * cm)]


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "VisitaTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#16324F"),
            spaceAfter=4,
        ),
        "Subtitle": ParagraphStyle(
            "VisitaSubtitle",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#52616B"),
        ),
        "Heading": ParagraphStyle(
            "VisitaHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#1F4E78"),
            spaceBefore=6,
            spaceAfter=2,
        ),
        "Label": ParagraphStyle(
            "VisitaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
        ),
        "Body": ParagraphStyle(
            "VisitaBody",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            wordWrap="CJK",
        ),
    }


def _paragraph(value: object, styles: dict) -> Paragraph:
    return Paragraph(_escape(_text(value) or "-"), styles["Body"])


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
    parsed = float(value)
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
