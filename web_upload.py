from fastapi.responses import HTMLResponse

from api import app


@app.get("/", response_class=HTMLResponse)
def upload_page() -> str:
    return """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Upload de documentos</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Arial, Helvetica, sans-serif;
      background: #f4f6f8;
      color: #1f2933;
    }

    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }

    main {
      width: 100%;
      max-width: 640px;
      background: #ffffff;
      border: 1px solid #d9e2ec;
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }

    h1 {
      margin: 0 0 20px;
      font-size: 24px;
    }

    form {
      display: grid;
      gap: 16px;
    }

    label {
      display: grid;
      gap: 6px;
      font-weight: 700;
    }

    select,
    input,
    button {
      font: inherit;
    }

    select,
    input[type="file"] {
      border: 1px solid #bcccdc;
      border-radius: 6px;
      padding: 10px;
      background: #ffffff;
    }

    button {
      border: 0;
      border-radius: 6px;
      padding: 12px 16px;
      background: #2563eb;
      color: #ffffff;
      font-weight: 700;
      cursor: pointer;
    }

    button:disabled {
      cursor: wait;
      opacity: 0.7;
    }

    pre {
      min-height: 120px;
      margin: 20px 0 0;
      padding: 16px;
      overflow: auto;
      border-radius: 6px;
      background: #111827;
      color: #e5e7eb;
      white-space: pre-wrap;
      word-break: break-word;
    }
  </style>
</head>
<body>
  <main>
    <h1>Upload de documentos</h1>

    <form id="upload-form">
      <label>
        Tipo de documento
        <select id="tipo-documento" name="tipo_documento" required>
          <option value="1">1 - Nota fiscal</option>
          <option value="2">2 - Recibo / comprovante</option>
        </select>
      </label>

      <label>
        Arquivo
        <input id="arquivo" name="arquivo" type="file" accept="image/*,.pdf,application/pdf" required>
      </label>

      <button id="submit-button" type="submit">Enviar</button>
    </form>

    <pre id="resultado">A resposta aparecerá aqui.</pre>
  </main>

  <script>
    const form = document.getElementById("upload-form");
    const button = document.getElementById("submit-button");
    const resultado = document.getElementById("resultado");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const tipoDocumento = document.getElementById("tipo-documento").value;
      const arquivo = document.getElementById("arquivo").files[0];
      const formData = new FormData();
      formData.append("arquivo", arquivo);

      button.disabled = true;
      resultado.textContent = "Enviando...";

      try {
        const response = await fetch(`/processar-upload?tipo_documento=${encodeURIComponent(tipoDocumento)}`, {
          method: "POST",
          body: formData,
        });

        const data = await response.json();
        resultado.textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        resultado.textContent = JSON.stringify({
          success: false,
          message: "Falha ao enviar o arquivo.",
          error: String(error),
        }, null, 2);
      } finally {
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
"""
