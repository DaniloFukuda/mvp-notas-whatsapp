param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$url = "http://127.0.0.1:$Port/webhook/whatsapp"

Write-Host "Testando webhook local:"
Write-Host $url
Write-Host ""

try {
    $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 10 -UseBasicParsing
    Write-Host "Servidor respondeu."
    Write-Host "Status HTTP: $($response.StatusCode)"
    Write-Host "Observacao: para validacao real da Meta, a rota GET exige parametros hub.*."
    exit 0
} catch {
    $response = $_.Exception.Response
    if ($null -ne $response) {
        $statusCode = [int]$response.StatusCode
        Write-Host "Servidor respondeu."
        Write-Host "Status HTTP: $statusCode"
        if ($statusCode -in @(400, 403, 405)) {
            Write-Host "Isso e esperado se faltam parametros de verificacao da Meta."
            Write-Host "A rota /webhook/whatsapp esta acessivel localmente."
            exit 0
        }

        Write-Warning "A rota respondeu, mas com status inesperado."
        exit 1
    }

    Write-Error "Servidor local nao respondeu em $url. Suba o FastAPI antes de testar: python -m uvicorn web_upload:app --reload --host 127.0.0.1 --port $Port"
    exit 1
}
