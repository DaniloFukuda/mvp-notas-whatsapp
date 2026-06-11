param(
    [int]$Port = 8001,
    [int]$RecentBackupHours = 48
)

$ErrorActionPreference = "Continue"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DatabasePath = Join-Path $ProjectRoot "data\app.db"
$UploadsPath = Join-Path $ProjectRoot "data\documentos\uploads"
$BackupDir = Join-Path $ProjectRoot "backups"
$EnvPath = Join-Path $ProjectRoot ".env"

Push-Location $ProjectRoot
try {
    Write-Output "Projeto: Ciclus/RDV"
    Write-Output "Branch: $(git branch --show-current)"
    Write-Output "Commit: $(git log -1 --oneline)"

    $Upstream = git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $Divergence = git rev-list --left-right --count "HEAD...@{u}"
        Write-Output "Upstream: $Upstream"
        Write-Output "Divergencia HEAD/upstream: $Divergence"
    }
    else {
        Write-Warning "Branch sem upstream configurado."
    }

    Write-Output ".env existe: $(Test-Path -LiteralPath $EnvPath -PathType Leaf)"
    Write-Output "Banco existe: $(Test-Path -LiteralPath $DatabasePath -PathType Leaf)"

    if (Test-Path -LiteralPath $DatabasePath -PathType Leaf) {
        $Integrity = @'
import sqlite3
import sys
connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    print(connection.execute("PRAGMA integrity_check").fetchone()[0])
finally:
    connection.close()
'@ | python - $DatabasePath
        Write-Output "Integridade SQLite: $Integrity"
    }

    $UploadFiles = @()
    if (Test-Path -LiteralPath $UploadsPath -PathType Container) {
        $UploadFiles = @(Get-ChildItem -LiteralPath $UploadsPath -File -Recurse -Force)
    }
    Write-Output "Quantidade de uploads: $($UploadFiles.Count)"

    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        Write-Output "Health local: $($Health | ConvertTo-Json -Compress)"
    }
    catch {
        Write-Output "Health local: servidor nao respondeu na porta $Port"
    }

    $Cutoff = (Get-Date).AddHours(-$RecentBackupHours)
    $RecentBackups = @()
    if (Test-Path -LiteralPath $BackupDir -PathType Container) {
        $RecentBackups = @(
            Get-ChildItem -LiteralPath $BackupDir -File -Force |
                Where-Object { $_.LastWriteTime -ge $Cutoff }
        )
    }
    Write-Output "Backups nas ultimas ${RecentBackupHours}h: $($RecentBackups.Count)"

    $SensitiveTracked = @(
        git ls-files |
            Where-Object {
                $_ -match '(^|/)\.env$' -or
                $_ -match '(^|/)data/app\.db$' -or
                $_ -match '(^|/)uploads/' -or
                $_ -match '(^|/)backups/' -or
                $_ -match '\.(db|sqlite)$'
            }
    )
    Write-Output "Caminhos sensiveis rastreados: $($SensitiveTracked.Count)"
    if ($SensitiveTracked.Count -gt 0) {
        $SensitiveTracked | ForEach-Object { Write-Warning "Rastreado: $_" }
    }
}
finally {
    Pop-Location
}
