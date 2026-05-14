import html
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse

from core.database import get_documents_summary, list_invalid_documents, list_processed_documents
from core.nucleus import Nucleus


app = FastAPI(title="Envio de Documentos")
UPLOAD_DIR = Path("data/documentos/uploads")


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
      max-width: 640px;
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
    input[type="file"],
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
      border-collapse: collapse;
      font-size: 14px;
    }}

    th,
    td {{
      border-bottom: 1px solid #d9e2ec;
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}

    th {{
      background: #f8fafc;
      font-weight: 700;
    }}

    td {{
      overflow-wrap: anywhere;
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
def upload_page() -> str:
    return html_page(
        """
    <h1>Envio de Documentos</h1>

    <form action="/enviar" method="post" enctype="multipart/form-data">
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

    <a class="nav-link" href="/documentos">Ver documentos processados</a>
"""
    )


# Para usar Form/File, mantenha python-multipart instalado.
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

      <a class="button-link" href="/">Voltar e enviar outro documento</a>
    </section>
""",
        title="Resultado do envio",
    )


@app.get("/documentos", response_class=HTMLResponse)
def listar_documentos() -> str:
    summary = get_documents_summary()
    documentos = list_processed_documents(limit=50)

    if documentos:
        rows = "\n".join(_document_row(documento) for documento in documentos)
    else:
        rows = """
        <tr>
          <td colspan="14">Nenhum documento processado ainda.</td>
        </tr>
"""

    return html_page(
        f"""
    <h1>Documentos Processados</h1>

    {_summary_cards(summary)}

    <p class="notice">Registros incompletos ou com erro não aparecem nesta lista principal. <a href="/documentos/erros">Ver registros ocultos</a>.</p>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>id</th>
            <th>data_processamento</th>
            <th>tipo_documento</th>
            <th>document_kind</th>
            <th>valor_total</th>
            <th>data_documento</th>
            <th>hora_documento</th>
            <th>favorecido</th>
            <th>id_transacao</th>
            <th>comentario</th>
            <th>conta_origem</th>
            <th>needs_review</th>
            <th>mensagem</th>
            <th>chave_acesso</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>

    <a class="nav-link" href="/">Voltar ao envio</a>
""",
        title="Documentos Processados",
    )


@app.get("/documentos/erros", response_class=HTMLResponse)
def listar_documentos_invalidos() -> str:
    documentos = list_invalid_documents(limit=50)

    if documentos:
        rows = "\n".join(_document_row(documento) for documento in documentos)
    else:
        rows = """
        <tr>
          <td colspan="14">Nenhum registro incompleto ou com erro encontrado.</td>
        </tr>
"""

    return html_page(
        f"""
    <h1>Registros Ocultos</h1>

    <p class="notice">Esta página é apenas para conferência técnica. Os registros continuam salvos no banco.</p>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>id</th>
            <th>data_processamento</th>
            <th>tipo_documento</th>
            <th>document_kind</th>
            <th>valor_total</th>
            <th>data_documento</th>
            <th>hora_documento</th>
            <th>favorecido</th>
            <th>id_transacao</th>
            <th>comentario</th>
            <th>conta_origem</th>
            <th>needs_review</th>
            <th>mensagem</th>
            <th>chave_acesso</th>
          </tr>
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


def _document_row(documento: dict) -> str:
    valor_total = documento.get("valor_total")
    valor_total_text = "" if valor_total is None else f"{valor_total:.2f}"

    return f"""
        <tr>
          <td>{html.escape(str(documento.get("id") or ""))}</td>
          <td>{html.escape(str(documento.get("data_processamento") or ""))}</td>
          <td>{html.escape(str(documento.get("tipo_documento") or ""))}</td>
          <td>{html.escape(str(documento.get("document_kind") or ""))}</td>
          <td>{html.escape(valor_total_text)}</td>
          <td>{html.escape(str(documento.get("data_documento") or ""))}</td>
          <td>{html.escape(str(documento.get("hora_documento") or ""))}</td>
          <td>{html.escape(str(documento.get("favorecido") or ""))}</td>
          <td>{html.escape(str(documento.get("id_transacao") or ""))}</td>
          <td>{html.escape(str(documento.get("comentario") or ""))}</td>
          <td>{html.escape(str(documento.get("conta_origem") or ""))}</td>
          <td>{html.escape("sim" if documento.get("needs_review") else "não")}</td>
          <td>{html.escape(str(documento.get("mensagem") or ""))}</td>
          <td>{html.escape(str(documento.get("chave_acesso") or ""))}</td>
        </tr>
"""


def format_brl(value: float) -> str:
    formatted = f"{float(value or 0):,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"
