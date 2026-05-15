from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Query, UploadFile
from pydantic import BaseModel

from core.nucleus import Nucleus


app = FastAPI()
UPLOAD_DIR = Path("data/documentos/uploads")


class ProcessDocumentRequest(BaseModel):
    tipo_documento: str
    caminho_imagem: str


def build_whatsapp_message(
    success: bool,
    tipo_documento: str,
    message: str,
) -> str:
    if not success:
        return f"Não consegui processar o documento. Motivo: {message}"

    if tipo_documento == "1":
        return "Nota fiscal recebida e processada com sucesso. QR Code lido corretamente."

    if tipo_documento == "2":
        return "Recibo/comprovante recebido e registrado com sucesso."

    return message


@app.post("/processar-documento")
def processar_documento(request: ProcessDocumentRequest) -> dict[str, str | bool]:
    nucleus = Nucleus()
    result = nucleus.process_document(
        document_type=request.tipo_documento,
        image_path=request.caminho_imagem,
    )
    whatsapp_message = build_whatsapp_message(
        success=result.success,
        tipo_documento=request.tipo_documento,
        message=result.message,
    )

    return {
        "success": result.success,
        "message": result.message,
        "data": result.data,
        "whatsapp_message": whatsapp_message,
    }


@app.post("/processar-upload")
async def processar_upload(
    tipo_documento_form: str | None = Form(None, alias="tipo_documento"),
    tipo_documento_query: str | None = Query(None, alias="tipo_documento"),
    arquivo: UploadFile = File(...),
) -> dict[str, str | bool]:
    tipo_documento = tipo_documento_form or tipo_documento_query
    if not tipo_documento:
        message = "O tipo do documento não foi informado."
        whatsapp_message = build_whatsapp_message(
            success=False,
            tipo_documento="",
            message=message,
        )
        return {
            "success": False,
            "message": message,
            "data": "",
            "saved_path": "",
            "whatsapp_message": whatsapp_message,
        }

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    suffix = Path(arquivo.filename or "").suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_path = UPLOAD_DIR / f"{timestamp}_{uuid4().hex}{suffix}"

    content = await arquivo.read()
    with open(saved_path, "wb") as output_file:
        output_file.write(content)

    nucleus = Nucleus()
    result = nucleus.process_document(
        document_type=tipo_documento,
        image_path=str(saved_path),
    )
    whatsapp_message = build_whatsapp_message(
        success=result.success,
        tipo_documento=tipo_documento,
        message=result.message,
    )

    return {
        "success": result.success,
        "message": result.message,
        "data": result.data,
        "saved_path": str(saved_path),
        "whatsapp_message": whatsapp_message,
    }
