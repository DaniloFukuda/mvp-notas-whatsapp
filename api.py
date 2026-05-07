from fastapi import FastAPI
from pydantic import BaseModel

from core.nucleus import Nucleus


app = FastAPI()


class ProcessDocumentRequest(BaseModel):
    tipo_documento: str
    caminho_imagem: str


@app.post("/processar-documento")
def processar_documento(request: ProcessDocumentRequest) -> dict[str, str | bool]:
    nucleus = Nucleus()
    result = nucleus.process_document(
        document_type=request.tipo_documento,
        image_path=request.caminho_imagem,
    )

    return {
        "success": result.success,
        "message": result.message,
        "data": result.data,
    }
