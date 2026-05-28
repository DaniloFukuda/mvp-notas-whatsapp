import html
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from api_whatsapp import router as whatsapp_router
from core.database import (
    delete_processed_document,
    get_processed_document_by_id,
    list_invalid_documents,
    list_processed_documents,
    save_processed_document,
    update_processed_document,
)
from core.nucleus import Nucleus


app = FastAPI(title="Envio de Documentos")
app.include_router(whatsapp_router)
UPLOAD_DIR = Path("data/documentos/uploads")
DOCUMENT_TABLE_COLUMNS = [
    "Data do Documento",
    "Recebido Em",
    "Tipo",
    "Fornecedor",
    "Valor",
    "Categoria",
    "Responsavel",
    "Acoes",
]
ERROR_TABLE_COLUMNS = [
    "ID",
    "Tipo",
    "Mensagem",
    "Valor",
    "Data do Documento",
    "Recebido Em",
    "Origem",
    "Acoes",
]


def html_page(content: str, title: str = "Envio de Documentos") -> str:
    return f"""
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Arial, Helvetica, sans-serif;
      background: #f4f6f8;
      color: #1f2933;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}

    main {{
      width: 100%;
      max-width: 1040px;
      background: #ffffff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}

    h1 {{
      margin: 0 0 20px;
      font-size: 24px;
    }}

    form {{
      display: grid;
      gap: 16px;
    }}

    .filters-form {{
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      align-items: end;
      margin-bottom: 24px;
      padding: 16px;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      background: #f8fafc;
    }}

    label {{
      display: grid;
      gap: 6px;
      font-weight: 700;
    }}

    select,
    input,
    button {{
      font: inherit;
    }}

    select,
    input[type="date"],
    input[type="month"],
    input[type="time"],
    input[type="file"],
    input[type="number"],
    input[type="text"],
    textarea {{
      border: 1px solid #bcccdc;
      border-radius: 6px;
      padding: 10px;
      background: #ffffff;
    }}

    textarea {{
      min-height: 80px;
      resize: vertical;
    }}

    button,
    .button-link {{
      display: inline-block;
      border: 0;
      border-radius: 6px;
      padding: 12px 16px;
      background: #2563eb;
      color: #ffffff;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }}

    .actions {{
      display: grid;
      gap: 12px;
    }}

    .result {{
      display: grid;
      gap: 12px;
    }}

    .status {{
      margin: 0;
      padding: 12px;
      border-radius: 6px;
      font-weight: 700;
    }}

    .success {{
      background: #dcfce7;
      color: #166534;
    }}

    .error {{
      background: #fee2e2;
      color: #991b1b;
    }}

    dl {{
      display: grid;
      gap: 8px;
      margin: 0;
    }}

    dt {{
      font-weight: 700;
    }}

    dd {{
      margin: 0 0 8px;
      overflow-wrap: anywhere;
    }}

    .nav-link {{
      display: inline-block;
      margin-top: 16px;
      color: #1d4ed8;
      font-weight: 700;
    }}

    .table-wrap {{
      overflow-x: auto;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}

    .summary-card {{
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      background: #f8fafc;
      padding: 14px;
    }}

    .summary-card strong {{
      display: block;
      margin-bottom: 8px;
      font-size: 13px;
      color: #52616b;
    }}

    .summary-card span {{
      display: block;
      font-size: 22px;
      font-weight: 700;
      color: #102a43;
    }}

    .category-summary {{
      margin-bottom: 24px;
    }}

    .category-summary h2 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}

    .category-list {{
      display: grid;
      gap: 8px;
      margin: 0;
    }}

    .category-row {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 10px 12px;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      background: #ffffff;
    }}

    .category-row strong {{
      overflow-wrap: anywhere;
    }}

    .notice {{
      margin: 0 0 18px;
      padding: 12px;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      background: #f8fafc;
      color: #52616b;
    }}

    table {{
      width: 100%;
      min-width: 860px;
      border-collapse: collapse;
      font-size: 14px;
    }}

    th,
    td {{
      border-bottom: 1px solid #d9e2ec;
      padding: 12px 10px;
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}

    th {{
      background: #f8fafc;
      font-weight: 700;
    }}

    td {{
      overflow-wrap: normal;
    }}

    td.message-cell {{
      max-width: 360px;
      white-space: normal;
      overflow-wrap: break-word;
    }}

    td.actions-cell,
    th.actions-cell {{
      position: sticky;
      right: 0;
      background: #ffffff;
      box-shadow: -8px 0 12px rgba(15, 23, 42, 0.04);
      white-space: nowrap;
    }}

    th.actions-cell {{
      background: #f8fafc;
    }}

    .table-action {{
      display: inline-block;
      border-radius: 6px;
      padding: 8px 10px;
      background: #2563eb;
      color: #ffffff;
      font-weight: 700;
      text-decoration: none;
    }}

    .delete-form {{
      display: inline-block;
      margin-left: 8px;
    }}

    .delete-action {{
      border: 0;
      border-radius: 6px;
      padding: 8px 10px;
      background: #dc2626;
      color: #ffffff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <main>
    {content}
  </main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home_page() -> str:
    return html_page(
        """
    <h1>Documentos</h1>

    <nav class="actions" aria-label="Acoes principais">
      <a class="button-link" href="/upload">Enviar arquivo</a>
      <a class="button-link" href="/lancamento-manual">Fazer lan&ccedil;amento manual</a>
      <a class="button-link" href="/documentos">Ver documentos processados</a>
      <a class="button-link" href="/documentos/erros">Ver documentos com erro</a>
    </nav>
""",
        title="Documentos",
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_page() -> str:
    return html_page(
        """
    <h1>Envio de Documentos</h1>

    <form action="/processar-upload" method="post" enctype="multipart/form-data">
      <label>
        Tipo do documento
        <select name="tipo_documento" required>
          <option value="1">nota fiscal</option>
          <option value="2">recibo/comprovante</option>
        </select>
      </label>

      <label>
        Arquivo
        <input name="arquivo" type="file" accept="image/*,.pdf,application/pdf" required>
      </label>

      <label>
        Valor total
        <input name="valor_total" type="text" inputmode="decimal" placeholder="Ex.: 32,50">
      </label>

      <label>
        Fornecedor
        <input name="fornecedor" type="text" placeholder="Ex.: Teste Mercado">
      </label>

      <label>
        Categoria
        <input name="categoria" type="text" placeholder="Ex.: alimentação">
      </label>

      <label>
        Responsável
        <input name="responsavel" type="text" placeholder="Ex.: Danilo">
      </label>

      <label>
        Data do documento
        <input name="data_documento" type="date">
      </label>

      <label>
        Observação
        <textarea name="observacao" placeholder="Ex.: teste manual"></textarea>
      </label>

      <button type="submit">Enviar documento</button>
    </form>

    <a class="nav-link" href="/">Voltar ao inicio</a>
    <a class="nav-link" href="/documentos">Ver documentos processados</a>
"""
    )


# Para usar Form/File, mantenha python-multipart instalado.
@app.post("/processar-upload", response_class=HTMLResponse)
@app.post("/enviar", response_class=HTMLResponse)
def enviar_documento(
    tipo_documento: str = Form(...),
    valor_total: str = Form(""),
    fornecedor: str = Form(""),
    categoria: str = Form(""),
    responsavel: str = Form(""),
    observacao: str = Form(""),
    data_documento: str = Form(""),
    arquivo: UploadFile = File(...),
) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    suffix = Path(arquivo.filename or "").suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_path = UPLOAD_DIR / f"{timestamp}_{uuid4().hex}{suffix}"

    try:
        with saved_path.open("wb") as output_file:
            shutil.copyfileobj(arquivo.file, output_file)

        result = Nucleus().process_document(
            document_type=tipo_documento,
            image_path=str(saved_path),
            metadata={
                "valor_total": valor_total.strip(),
                "fornecedor": fornecedor.strip(),
                "categoria": categoria.strip(),
                "responsavel": responsavel.strip(),
                "observacao": observacao.strip(),
                "data_documento": data_documento.strip(),
            },
        )
        success = result.success
        message = result.message
    except Exception as exc:
        success = False
        message = f"Não foi possível processar o documento: {exc}"
    finally:
        arquivo.file.close()

    status_class = "success" if success else "error"
    status_text = "Processamento concluído com sucesso." if success else "O processamento não deu certo."
    final_message = (
        "Documento recebido. Você já pode enviar outro arquivo."
        if success
        else "Confira o arquivo enviado e tente novamente."
    )

    return html_page(
        f"""
    <h1>Resultado do envio</h1>

    <section class="result">
      <p class="status {status_class}">{html.escape(status_text)}</p>

      <dl>
        <dt>Mensagem do sistema</dt>
        <dd>{html.escape(message)}</dd>

        <dt>Caminho do arquivo salvo</dt>
        <dd>{html.escape(str(saved_path))}</dd>
      </dl>

      <p>{html.escape(final_message)}</p>

      <a class="button-link" href="/upload">Voltar e enviar outro documento</a>
    </section>
""",
        title="Resultado do envio",
    )


@app.get("/lancamento-manual", response_class=HTMLResponse)
def lancamento_manual_page() -> str:
    return html_page(
        """
    <h1>Lan&ccedil;amento Manual</h1>

    <form action="/lancamento-manual" method="post">
      <label>
        Tipo do documento
        <select name="tipo_documento" required>
          <option value="1">nota fiscal</option>
          <option value="2">recibo/comprovante</option>
        </select>
      </label>

      <label>
        Fornecedor
        <input name="fornecedor" type="text" placeholder="Ex.: Teste Mercado">
      </label>

      <label>
        Valor total
        <input name="valor_total" type="text" inputmode="decimal" placeholder="Ex.: 32,50" required>
      </label>

      <label>
        Data do documento
        <input name="data_documento" type="date">
      </label>

      <label>
        Categoria
        <input name="categoria" type="text" placeholder="Ex.: alimenta&ccedil;&atilde;o">
      </label>

      <label>
        Responsavel
        <input name="responsavel" type="text" placeholder="Ex.: Danilo">
      </label>

      <label>
        Observacao
        <textarea name="observacao" placeholder="Ex.: teste manual"></textarea>
      </label>

      <button type="submit">Registrar lan&ccedil;amento</button>
    </form>

    <a class="nav-link" href="/">Voltar ao inicio</a>
""",
        title="Lancamento Manual",
    )


@app.post("/lancamento-manual", response_class=HTMLResponse)
def salvar_lancamento_manual(
    tipo_documento: str = Form(...),
    fornecedor: str = Form(""),
    valor_total: str = Form(""),
    data_documento: str = Form(""),
    categoria: str = Form(""),
    responsavel: str = Form(""),
    observacao: str = Form(""),
) -> str:
    tipo_documento_text = _normalize_tipo_documento(tipo_documento)
    valor_total_text = valor_total.strip()
    success = bool(tipo_documento_text and valor_total_text)
    message = (
        "Lancamento manual registrado com sucesso."
        if success
        else f"Informe pelo menos {humanizar_texto('tipo_documento')} e {humanizar_texto('valor_total')}."
    )

    if success:
        save_processed_document(
            {
                "data_processamento": datetime.now().isoformat(timespec="seconds"),
                "tipo_documento": tipo_documento_text,
                "caminho_imagem": "",
                "caminho_arquivo": "",
                "sucesso": True,
                "mensagem": message,
                "dados_extraidos": "",
                "valor_total": valor_total_text,
                "data_documento": data_documento.strip(),
                "fornecedor": fornecedor.strip(),
                "categoria": categoria.strip(),
                "responsavel": responsavel.strip(),
                "observacao": observacao.strip(),
                "status_conferencia": "pendente",
            }
        )

    status_class = "success" if success else "error"
    status_text = "Registro salvo." if success else "Registro incompleto."

    return html_page(
        f"""
    <h1>Resultado do lan&ccedil;amento</h1>

    <section class="result">
      <p class="status {status_class}">{html.escape(status_text)}</p>

      <dl>
        <dt>Mensagem do sistema</dt>
        <dd>{html.escape(message)}</dd>
      </dl>

      <a class="button-link" href="/lancamento-manual">Fazer outro lan&ccedil;amento</a>
      <a class="nav-link" href="/documentos">Ver documentos processados</a>
    </section>
""",
        title="Resultado do lancamento",
    )


@app.get("/documentos", response_class=HTMLResponse)
def listar_documentos(
    atualizado: str = Query(""),
    mes_ano: str = Query(""),
    tipo_documento: str = Query(""),
    categoria: str = Query(""),
    responsavel_origem: str = Query(""),
    data_recebimento: str = Query(""),
    hora_inicio: str = Query(""),
    hora_fim: str = Query(""),
) -> str:
    filters = {
        "mes_ano": mes_ano.strip(),
        "tipo_documento": tipo_documento.strip(),
        "categoria": categoria.strip(),
        "responsavel_origem": responsavel_origem.strip(),
        "data_recebimento": data_recebimento.strip(),
        "hora_inicio": hora_inicio.strip(),
        "hora_fim": hora_fim.strip(),
    }
    documentos = _filter_documents(list_processed_documents(limit=5000), filters)
    summary = _build_documents_summary(documentos)
    category_totals = _build_category_totals(documentos)
    update_notice = (
        '<p class="status success">Documento atualizado com sucesso.</p>'
        if atualizado == "1"
        else ""
    )

    if documentos:
        rows = "\n".join(_document_row(documento) for documento in documentos)
    else:
        rows = f"""
        <tr>
          <td colspan="{len(DOCUMENT_TABLE_COLUMNS)}">Nenhum documento processado ainda.</td>
        </tr>
"""

    return html_page(
        f"""
    <h1>Documentos Processados</h1>

    {update_notice}

    {_filters_form(filters)}

    {_summary_cards(summary)}

    {_category_totals_section(category_totals)}

    <p class="notice">Registros incompletos ou com erro não aparecem nesta lista principal. <a href="/documentos/erros">Ver registros ocultos</a>.</p>

    <div class="table-wrap">
      <table>
        <thead>
          {_document_table_header(DOCUMENT_TABLE_COLUMNS)}
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>

    <a class="nav-link" href="/">Voltar ao inicio</a>
""",
        title="Documentos Processados",
    )


@app.get("/documentos/erros", response_class=HTMLResponse)
def listar_documentos_invalidos() -> str:
    documentos = list_invalid_documents(limit=50)

    if documentos:
        rows = "\n".join(_error_document_row(documento) for documento in documentos)
    else:
        rows = f"""
        <tr>
          <td colspan="{len(ERROR_TABLE_COLUMNS)}">Nenhum registro incompleto ou com erro encontrado.</td>
        </tr>
"""

    return html_page(
        f"""
    <h1>Registros Ocultos</h1>

    <p class="notice">Esta página é apenas para conferência técnica. Os registros continuam salvos no banco.</p>

    <div class="table-wrap">
      <table>
        <thead>
          {_document_table_header(ERROR_TABLE_COLUMNS)}
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>

    <a class="nav-link" href="/documentos">Voltar aos documentos</a>
""",
        title="Registros Ocultos",
    )


@app.get("/documentos/{documento_id}/editar", response_class=HTMLResponse)
def editar_documento_page(documento_id: int) -> str:
    documento = get_processed_document_by_id(documento_id)
    if documento is None:
        return _documento_nao_encontrado_page()

    return html_page(
        f"""
    <h1>Editar / Conferir Documento</h1>

    <form action="/documentos/{html.escape(str(documento_id))}/editar" method="post">
      <label>
        Tipo do documento
        <input name="tipo_documento" type="text" value="{_form_value(documento.get("tipo_documento"))}">
      </label>

      <label>
        Fornecedor
        <input name="fornecedor" type="text" value="{_form_value(documento.get("fornecedor"))}">
      </label>

      <label>
        Valor total
        <input name="valor_total" type="text" inputmode="decimal" value="{_form_value(_format_optional_decimal(documento.get("valor_total")))}">
      </label>

      <label>
        Data do documento
        <input name="data_documento" type="date" value="{_form_value(documento.get("data_documento"))}">
      </label>

      <label>
        Categoria
        <input name="categoria" type="text" value="{_form_value(documento.get("categoria"))}">
      </label>

      <label>
        Responsavel
        <input name="responsavel" type="text" value="{_form_value(documento.get("responsavel"))}">
      </label>

      <label>
        Observacao
        <textarea name="observacao">{html.escape(str(documento.get("observacao") or ""))}</textarea>
      </label>

      <label>
        Status da conferencia
        {_status_conferencia_select(documento.get("status_conferencia"))}
      </label>

      <button type="submit">Salvar conferencia</button>
    </form>

    <a class="nav-link" href="/documentos">Voltar aos documentos</a>
""",
        title="Editar Documento",
    )


@app.post("/documentos/{documento_id}/editar", response_class=HTMLResponse)
def salvar_edicao_documento(
    documento_id: int,
    tipo_documento: str = Form(""),
    fornecedor: str = Form(""),
    valor_total: str = Form(""),
    data_documento: str = Form(""),
    categoria: str = Form(""),
    responsavel: str = Form(""),
    observacao: str = Form(""),
    status_conferencia: str = Form(""),
):
    documento = get_processed_document_by_id(documento_id)
    if documento is None:
        return HTMLResponse(_documento_nao_encontrado_page(), status_code=404)

    valor_normalizado, erro_valor = _normalizar_valor_total(valor_total)
    if erro_valor:
        return html_page(
            f"""
    <h1>Editar / Conferir Documento</h1>

    <p class="status error">{html.escape(erro_valor)}</p>
    <a class="button-link" href="/documentos/{html.escape(str(documento_id))}/editar">Voltar para edicao</a>
""",
            title="Valor invalido",
        )

    update_processed_document(
        documento_id,
        {
            "tipo_documento": tipo_documento.strip(),
            "fornecedor": fornecedor.strip(),
            "valor_total": valor_normalizado,
            "data_documento": data_documento.strip(),
            "categoria": categoria.strip(),
            "responsavel": responsavel.strip(),
            "observacao": observacao.strip(),
            "status_conferencia": status_conferencia.strip(),
        },
    )

    return RedirectResponse("/documentos?atualizado=1", status_code=303)


@app.post("/documentos/{documento_id}/apagar", response_class=HTMLResponse)
def apagar_documento(documento_id: int, origem: str = Form("/documentos")):
    delete_processed_document(documento_id)
    redirect_to = "/documentos/erros" if origem == "/documentos/erros" else "/documentos"
    return RedirectResponse(redirect_to, status_code=303)


def _filter_documents(documents: list[dict], filters: dict) -> list[dict]:
    return [
        document
        for document in documents
        if _matches_month(document, filters.get("mes_ano"))
        and _matches_text(document.get("tipo_documento"), filters.get("tipo_documento"))
        and _matches_text(document.get("categoria"), filters.get("categoria"))
        and _matches_responsavel_origem(document, filters.get("responsavel_origem"))
        and _matches_received_filters(
            document,
            filters.get("data_recebimento"),
            filters.get("hora_inicio"),
            filters.get("hora_fim"),
        )
    ]


def _build_documents_summary(documents: list[dict]) -> dict:
    summary = {
        "total_geral": 0.0,
        "total_notas_fiscais": 0.0,
        "total_recibos_comprovantes": 0.0,
        "quantidade_total_documentos": 0,
        "quantidade_notas_fiscais": 0,
        "quantidade_recibos_comprovantes": 0,
        "quantidade_pendentes_revisao": 0,
    }

    for document in documents:
        tipo_documento = str(document.get("tipo_documento") or "").lower()
        valor_total = _document_value(document)

        summary["quantidade_total_documentos"] += 1
        summary["total_geral"] += valor_total

        if "nota" in tipo_documento:
            summary["quantidade_notas_fiscais"] += 1
            summary["total_notas_fiscais"] += valor_total

        if "recibo" in tipo_documento or "comprovante" in tipo_documento:
            summary["quantidade_recibos_comprovantes"] += 1
            summary["total_recibos_comprovantes"] += valor_total

        if _is_pending_review(document.get("status_conferencia")):
            summary["quantidade_pendentes_revisao"] += 1

    return summary


def _build_category_totals(documents: list[dict]) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for document in documents:
        category = str(document.get("categoria") or "").strip() or "Sem categoria"
        totals[category] = totals.get(category, 0.0) + _document_value(document)

    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _summary_cards(summary: dict) -> str:
    return f"""
    <section class="summary-grid" aria-label="Resumo financeiro">
      <div class="summary-card">
        <strong>Total geral</strong>
        <span>{html.escape(format_brl(summary["total_geral"]))}</span>
      </div>
      <div class="summary-card">
        <strong>Notas fiscais</strong>
        <span>{html.escape(format_brl(summary["total_notas_fiscais"]))}</span>
      </div>
      <div class="summary-card">
        <strong>Recibos/comprovantes</strong>
        <span>{html.escape(format_brl(summary["total_recibos_comprovantes"]))}</span>
      </div>
      <div class="summary-card">
        <strong>Documentos cadastrados</strong>
        <span>{html.escape(str(summary["quantidade_total_documentos"]))}</span>
      </div>
      <div class="summary-card">
        <strong>Pendentes de revisão</strong>
        <span>{html.escape(str(summary["quantidade_pendentes_revisao"]))}</span>
      </div>
    </section>
"""


def _filters_form(filters: dict) -> str:
    tipo_documento = str(filters.get("tipo_documento") or "")
    return f"""
    <form class="filters-form" action="/documentos" method="get">
      <label>
        Data de recebimento
        <input name="data_recebimento" type="date" value="{_form_value(filters.get("data_recebimento"))}">
      </label>

      <label>
        M&ecirc;s/Ano
        <input name="mes_ano" type="month" value="{_form_value(filters.get("mes_ano"))}">
      </label>

      <label>
        Hora inicial
        <input name="hora_inicio" type="time" value="{_form_value(filters.get("hora_inicio"))}">
      </label>

      <label>
        Hora final
        <input name="hora_fim" type="time" value="{_form_value(filters.get("hora_fim"))}">
      </label>

      <label>
        Tipo do documento
        <select name="tipo_documento">
          <option value="">Todos</option>
          {_select_option("nota_fiscal", tipo_documento, "nota_fiscal")}
          {_select_option("recibo_comprovante", tipo_documento, "recibo_comprovante")}
        </select>
      </label>

      <label>
        Categoria
        <input name="categoria" type="text" value="{_form_value(filters.get("categoria"))}" placeholder="Ex.: alimenta&ccedil;&atilde;o">
      </label>

      <label>
        Responsavel/Origem
        <input name="responsavel_origem" type="text" value="{_form_value(filters.get("responsavel_origem"))}" placeholder="Ex.: whatsapp">
      </label>

      <button type="submit">Filtrar</button>
      <a class="button-link" href="/documentos">Limpar filtros</a>
    </form>
"""


def _category_totals_section(category_totals: list[tuple[str, float]]) -> str:
    if category_totals:
        rows = "\n".join(
            f"""
      <div class="category-row">
        <strong>{html.escape(category)}</strong>
        <span>{html.escape(format_brl(total))}</span>
      </div>
"""
            for category, total in category_totals
        )
    else:
        rows = """
      <div class="category-row">
        <strong>Nenhuma categoria encontrada</strong>
        <span>R$ 0,00</span>
      </div>
"""

    return f"""
    <section class="category-summary" aria-label="Total por categoria">
      <h2>Total por categoria</h2>
      <div class="category-list">
        {rows}
      </div>
    </section>
"""


def _document_table_header(columns: list[str]) -> str:
    headers = "\n".join(
        f'            <th class="{_column_class(column)}">{html.escape(humanizar_texto(column))}</th>'
        for column in columns
    )
    return f"""
          <tr>
{headers}
          </tr>
"""


def _document_row(documento: dict) -> str:
    valor_total = documento.get("valor_total")
    valor_total_text = "" if valor_total is None else f"{valor_total:.2f}"
    documento_id = str(documento.get("id") or "")

    return f"""
        <tr>
          <td>{html.escape(str(documento.get("data_documento") or ""))}</td>
          <td>{html.escape(format_datetime_display(documento.get("data_hora_recebimento")))}</td>
          <td>{html.escape(humanizar_texto(documento.get("tipo_documento")))}</td>
          <td>{html.escape(str(documento.get("fornecedor") or ""))}</td>
          <td>{html.escape(valor_total_text)}</td>
          <td>{html.escape(str(documento.get("categoria") or ""))}</td>
          <td>{html.escape(str(documento.get("responsavel") or ""))}</td>
          <td class="actions-cell">{_action_buttons(documento_id, "/documentos")}</td>
        </tr>
"""


def _error_document_row(documento: dict) -> str:
    valor_total = documento.get("valor_total")
    valor_total_text = "" if valor_total is None else f"{valor_total:.2f}"
    documento_id = str(documento.get("id") or "")

    return f"""
        <tr>
          <td>{html.escape(documento_id)}</td>
          <td>{html.escape(humanizar_texto(documento.get("tipo_documento")))}</td>
          <td class="message-cell">{html.escape(str(documento.get("mensagem") or ""))}</td>
          <td>{html.escape(valor_total_text)}</td>
          <td>{html.escape(str(documento.get("data_documento") or ""))}</td>
          <td>{html.escape(format_datetime_display(documento.get("data_hora_recebimento")))}</td>
          <td>{html.escape(str(documento.get("responsavel") or ""))}</td>
          <td class="actions-cell">{_action_buttons(documento_id, "/documentos/erros")}</td>
        </tr>
"""


def _action_buttons(documento_id: str, origem: str) -> str:
    return f'{_edit_link(documento_id)}{_delete_form(documento_id, origem)}'


def _edit_link(documento_id: str) -> str:
    safe_id = html.escape(documento_id)
    return f'<a class="table-action" href="/documentos/{safe_id}/editar">Editar / Conferir</a>'


def _delete_form(documento_id: str, origem: str) -> str:
    safe_id = html.escape(documento_id)
    safe_origin = html.escape(origem, quote=True)
    return f"""
            <form class="delete-form" action="/documentos/{safe_id}/apagar" method="post" onsubmit="return confirm('Tem certeza que deseja apagar este documento?');">
              <input type="hidden" name="origem" value="{safe_origin}">
              <button class="delete-action" type="submit">Apagar</button>
            </form>
"""


def _column_class(column: str) -> str:
    return "actions-cell" if column == "Acoes" else ""


def _documento_nao_encontrado_page() -> str:
    return html_page(
        """
    <h1>Documento n&atilde;o encontrado</h1>

    <p class="notice">Documento n&atilde;o encontrado.</p>
    <a class="button-link" href="/documentos">Voltar aos documentos</a>
""",
        title="Documento nao encontrado",
    )


def _status_conferencia_select(current_status: object) -> str:
    current_status_text = str(current_status or "").strip()
    options = ["pendente_revisao", "revisado", "erro"]
    option_tags = []
    if current_status_text and current_status_text not in options:
        option_tags.append(
            _select_option(current_status_text, current_status_text, current_status_text)
        )

    for option in options:
        option_tags.append(_select_option(option, current_status_text, option))

    return f"""
        <select name="status_conferencia">
          {"".join(option_tags)}
        </select>
"""


def _select_option(value: str, current_value: str, label: str) -> str:
    selected = " selected" if value == current_value else ""
    return (
        f'<option value="{html.escape(value, quote=True)}"{selected}>'
        f"{html.escape(humanizar_texto(label))}</option>"
    )


def _form_value(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _format_optional_decimal(value: object) -> str:
    if value in (None, ""):
        return ""

    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _normalizar_valor_total(value: str) -> tuple[float | None, str | None]:
    value = str(value or "").strip()
    if not value:
        return None, None

    try:
        return float(value.replace(",", ".")), None
    except ValueError:
        return None, "Valor Total deve ficar vazio ou conter um numero."


def _matches_month(document: dict, month_filter: object) -> bool:
    expected_month = str(month_filter or "").strip()
    if not expected_month:
        return True

    document_date = _parse_document_date(document.get("data_documento"))
    if document_date is None:
        return False

    return document_date.strftime("%Y-%m") == expected_month


def _matches_text(value: object, expected: object) -> bool:
    expected_text = str(expected or "").strip().lower()
    if not expected_text:
        return True

    return expected_text in str(value or "").strip().lower()


def _matches_responsavel_origem(document: dict, expected: object) -> bool:
    expected_text = str(expected or "").strip().lower()
    if not expected_text:
        return True

    searchable_values = (
        document.get("responsavel"),
        document.get("observacao"),
        document.get("conta_origem"),
    )
    return any(expected_text in str(value or "").lower() for value in searchable_values)


def _matches_received_filters(
    document: dict,
    date_filter: object,
    start_filter: object,
    end_filter: object,
) -> bool:
    expected_date = str(date_filter or "").strip()
    start_time = _parse_time_filter(start_filter)
    end_time = _parse_time_filter(end_filter)
    has_received_filter = bool(expected_date or start_time is not None or end_time is not None)
    if not has_received_filter:
        return True

    received_at = _parse_received_datetime(document.get("data_hora_recebimento"))
    if received_at is None:
        return False

    if expected_date and received_at.strftime("%Y-%m-%d") != expected_date:
        return False

    received_time = received_at.time().replace(second=0, microsecond=0)
    if start_time is not None and received_time < start_time:
        return False

    if end_time is not None and received_time > end_time:
        return False

    return True


def _document_value(document: dict) -> float:
    value = document.get("valor_total")
    if value in (None, ""):
        return 0.0

    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _parse_document_date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue

    return None


def _parse_received_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    for date_format in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_time_filter(value: object):
    text = str(value or "").strip()
    if not text:
        return None

    for time_format in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, time_format).time().replace(
                second=0,
                microsecond=0,
            )
        except ValueError:
            continue

    return None


def _is_pending_review(value: object) -> bool:
    return str(value or "").strip().lower() != "revisado"


def humanizar_texto(valor: object) -> str:
    if valor is None:
        return ""

    return str(valor).replace("_", " ").title()


def _normalize_tipo_documento(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "1":
        return "nota_fiscal"

    if normalized == "2":
        return "recibo_comprovante"

    return normalized


def format_brl(value: float) -> str:
    formatted = f"{float(value or 0):,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def format_datetime_display(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        parsed_display = datetime.strptime(text, "%d/%m/%Y %H:%M")
    except ValueError:
        parsed_display = None

    if parsed_display is not None:
        return parsed_display.strftime("%d/%m/%Y %H:%M")

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text

    return parsed.strftime("%d/%m/%Y %H:%M")
