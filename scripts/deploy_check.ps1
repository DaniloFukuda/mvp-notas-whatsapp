param(
    [int]$Port = 8001
)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvPath = Join-Path $ProjectRoot ".env"
$DatabasePath = Join-Path $ProjectRoot "data\app.db"
$UploadsPath = Join-Path $ProjectRoot "data\documentos\uploads"

Push-Location $ProjectRoot
try {
    Write-Output "Branch: $(git branch --show-current)"
    Write-Output "Commit: $(git log -1 --oneline)"
    Write-Output ".env existe: $(Test-Path -LiteralPath $EnvPath -PathType Leaf)"
    Write-Output "Banco existe: $(Test-Path -LiteralPath $DatabasePath -PathType Leaf)"
    Write-Output "Uploads existem: $(Test-Path -LiteralPath $UploadsPath -PathType Container)"

    python -m compileall services scripts api_whatsapp.py web_upload.py
    if ($LASTEXITCODE -ne 0) {
        Write-Error "compileall falhou."
    }

    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        Write-Output "Health: $($Health | ConvertTo-Json -Compress)"
    }
    catch {
        Write-Output "Health: servidor nao respondeu em http://127.0.0.1:$Port/health"
    }
}
finally {
    Pop-Location
}
