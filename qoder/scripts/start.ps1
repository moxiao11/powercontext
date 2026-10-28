[CmdletBinding()]
param(
    [switch]$RemoteSeekdb,
    [switch]$InitOnly,
    [ValidateRange(1, 65535)][int]$WebPort = 5173,
    [ValidateRange(1, 65535)][int]$ApiPort = 8100,
    [ValidateRange(1, 65535)][int]$PowerContextPort = 8010,
    [ValidateRange(1, 65535)][int]$SeekdbPort = 2881
)
$ErrorActionPreference = 'Stop'
$qoderRoot = Split-Path $PSScriptRoot -Parent
$configPath = Join-Path $qoderRoot '.env'
$utf8 = New-Object System.Text.UTF8Encoding($false)
if (-not (Test-Path -LiteralPath $configPath)) {
    [IO.File]::WriteAllText($configPath, [IO.File]::ReadAllText((Join-Path $qoderRoot '.env.example')), $utf8)
}
function Add-MissingSetting([string]$Name, [string]$Value) {
    $text = [IO.File]::ReadAllText($configPath)
    if ($text -notmatch "(?m)^\s*$Name\s*=\s*[^\r\n#\s]+") {
        $text = [regex]::Replace($text, "(?m)^\s*$Name\s*=\s*$", '')
        [IO.File]::WriteAllText($configPath, $text.TrimEnd() + "`n$Name=$Value`n", $utf8)
    }
}
function New-LocalSecret {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}
Add-MissingSetting 'POWERCONTEXT_AUTH_TOKEN' (New-LocalSecret)
Add-MissingSetting 'LABTRACE_WEB_PORT' "$WebPort"
Add-MissingSetting 'LABTRACE_API_PORT' "$ApiPort"
Add-MissingSetting 'POWERCONTEXT_PORT' "$PowerContextPort"
if ($RemoteSeekdb) {
    Add-MissingSetting 'SEEKDB_ROOT_PASSWORD' (New-LocalSecret)
    Add-MissingSetting 'SEEKDB_SERVER_PORT' "$SeekdbPort"
}
Write-Host 'Local .env is ready. Existing settings were preserved; credentials are not printed.'
if ($InitOnly) { return }
Get-Command docker -ErrorAction Stop | Out-Null
Push-Location $qoderRoot
try {
    $composeArgs = @('compose', '-f', 'docker-compose.yml')
    if ($RemoteSeekdb) { $composeArgs += @('-f', 'docker/docker-compose.seekdb-server.yml') }
    & docker @composeArgs up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose startup failed. Check Docker Desktop and image access.' }
    & docker @composeArgs ps
    Write-Host 'Use the frontend port saved in .env. First database startup may take a few minutes.'
} finally { Pop-Location }
