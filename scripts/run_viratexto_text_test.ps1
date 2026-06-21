param(
    [string]$Message = "Ola, teste de integracao",
    [switch]$SendReal
)

$ErrorActionPreference = "Stop"

function Import-DotEnvIfPresent {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Mask-Phone {
    param([string]$Phone)

    if (-not $Phone -or $Phone.Length -le 4) {
        return "***"
    }
    return "***$($Phone.Substring($Phone.Length - 4))"
}

function Test-Truthy {
    param([string]$Value)

    return @("1", "true", "yes", "sim", "on") -contains $Value.Trim().ToLowerInvariant()
}

function Test-InvalidViraTextoPhone {
    param([string]$Phone)

    $clean = $Phone.Trim()
    if (-not $clean) {
        return $true
    }
    if ($clean -in @("55DDDNUMERO", "55DDDNÚMERO", "55XXXXXXXXXXX")) {
        return $true
    }
    if ($clean -match "[A-Za-zXx]") {
        return $true
    }
    if ($clean -notmatch "^\d+$") {
        return $true
    }
    if ($clean.Length -lt 12) {
        return $true
    }
    return $false
}

function Ensure-ViraTextoLogFile {
    $logDir = "logs"
    $logFile = Join-Path $logDir "viratexto_test_log.jsonl"

    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }

    if (-not (Test-Path -LiteralPath $logFile)) {
        New-Item -ItemType File -Force -Path $logFile | Out-Null
    }

    return $logFile
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
Import-DotEnvIfPresent -Path (Join-Path $repoRoot ".env")

$tokenPresent = -not [string]::IsNullOrWhiteSpace($env:WHATSAPP_TOKEN) -or -not [string]::IsNullOrWhiteSpace($env:WHATSAPP_ACCESS_TOKEN)
$phoneNumberIdPresent = -not [string]::IsNullOrWhiteSpace($env:WHATSAPP_PHONE_NUMBER_ID)
$viratextoPhone = [string]$env:VIRATEXTO_PHONE
$apiVersion = if (-not [string]::IsNullOrWhiteSpace($env:WHATSAPP_API_VERSION)) {
    $env:WHATSAPP_API_VERSION
} elseif (-not [string]::IsNullOrWhiteSpace($env:WHATSAPP_GRAPH_API_VERSION)) {
    $env:WHATSAPP_GRAPH_API_VERSION
} else {
    "v21.0"
}
$testModeActive = Test-Truthy -Value ([string]$env:VIRATEXTO_TEST_MODE)
$modeLabel = if ($SendReal) { "envio real" } else { "dry-run" }

Write-Host "Modo: $modeLabel"
Write-Host "Destino: $(Mask-Phone -Phone $viratextoPhone)"
Write-Host "API version: $apiVersion"
Write-Host "VIRATEXTO_TEST_MODE ativo: $testModeActive"

if (-not $phoneNumberIdPresent) {
    Write-Error "Variavel obrigatoria ausente: WHATSAPP_PHONE_NUMBER_ID."
    exit 1
}

if (-not $tokenPresent) {
    Write-Error "Token ausente. Configure WHATSAPP_TOKEN ou WHATSAPP_ACCESS_TOKEN. O token nao sera impresso."
    exit 1
}

if (Test-InvalidViraTextoPhone -Phone $viratextoPhone) {
    Write-Error "VIRATEXTO_PHONE invalido. Configure um numero real no formato 55DDDNUMERO, sem placeholders."
    exit 1
}

if (-not $testModeActive) {
    Write-Warning "ATENCAO: VIRATEXTO_TEST_MODE nao esta true. O webhook pode nao interceptar a resposta como teste."
}

if ([string]::IsNullOrWhiteSpace($env:WHATSAPP_API_VERSION) -and [string]::IsNullOrWhiteSpace($env:WHATSAPP_GRAPH_API_VERSION)) {
    Write-Warning "WHATSAPP_API_VERSION ou WHATSAPP_GRAPH_API_VERSION nao configurada; o script Python usara o default."
}

if ($SendReal) {
    Write-Warning "Voce solicitou ENVIO REAL para $(Mask-Phone -Phone $viratextoPhone)."
    $confirmation = Read-Host "Digite ENVIAR para confirmar o envio real"
    if ($confirmation -ne "ENVIAR") {
        Write-Host "Envio real cancelado."
        exit 0
    }
}

$pythonArgs = @(
    "scripts/test_viratexto_whatsapp.py",
    "--to",
    $viratextoPhone,
    "--text",
    $Message
)

if (-not $SendReal) {
    $pythonArgs += "--dry-run"
}

Write-Host "Executando script Python..."
python @pythonArgs
$exitCode = $LASTEXITCODE

$logFile = Ensure-ViraTextoLogFile
Write-Host ""
Write-Host "Para acompanhar respostas do webhook, use:"
Write-Host "powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_viratexto_log.ps1"
Write-Host "Arquivo de log preparado em: $logFile"

exit $exitCode
