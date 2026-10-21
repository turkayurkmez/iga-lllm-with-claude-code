# PostToolUse (Write|Edit) hook'u: backend/tools/ altında bir dosya değişince tool testlerini koşar.
# Yeşilse ya da dosya tool dışıysa sessizce 0 ile çıkar. Kırmızıysa (ya da testler koşamadıysa)
# FAILED satırlarını ve son özet satırını stderr'e yazıp 2 ile çıkar; Claude Code bunu Claude'a iletir.
# Test hedefi TOOL_HOOK_TEST_TARGET ile değiştirilebilir (varsayılan tests/test_tools.py).
# Not: Windows PowerShell 5.1 BOM'suz betiği ANSI okur; dosya UTF-8 BOM ile kaydedilmelidir.

$ErrorActionPreference = 'Stop'

function Get-NormalizedPath([string]$path) {
    return [IO.Path]::GetFullPath($path).Replace('/', '\').TrimEnd('\').ToLowerInvariant()
}

try {
    $root = $env:CLAUDE_PROJECT_DIR
    if (-not $root) { $root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }

    # Varsayılan kod sayfası Türkçe karakterleri bozduğu için stdin açıkça UTF-8 okunur.
    $reader = New-Object IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)
    $payload = $reader.ReadToEnd() | ConvertFrom-Json
    $path = [string]$payload.tool_input.file_path
    if (-not $path) { $path = [string]$payload.tool_response.filePath }
    if (-not $path) { exit 0 }

    if (-not [IO.Path]::IsPathRooted($path)) { $path = Join-Path $root $path }
    $file = Get-NormalizedPath $path
    $toolsDir = Get-NormalizedPath (Join-Path $root 'backend\tools')
    # Ayraçla karşılaştırılır; backend\tools_eski gibi önek benzerleri tetiklemez.
    if (-not $file.StartsWith($toolsDir + '\')) { exit 0 }
}
catch { exit 0 }

$target = $env:TOOL_HOOK_TEST_TARGET
if (-not $target) { $target = 'tests\test_tools.py' }

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
# Yerel komutun stderr satırları 5.1'de ErrorRecord'a sarılır; Stop ile bunlar istisnaya dönerdi.
$ErrorActionPreference = 'Continue'

try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    Push-Location $root
    try {
        # rootdir hedefin klasörüdür (varsayılan hedefte pytest'in zaten seçtiği tests\).
        # Verilmezse repo dışındaki hedefte pytest ev dizinine çıkıp dakikalarca bekliyor.
        $targetPath = $target
        if (-not [IO.Path]::IsPathRooted($targetPath)) { $targetPath = Join-Path $root $targetPath }
        $rootdir = Split-Path $targetPath -Parent
        $output = & $python -m pytest $target -q -p no:cacheprovider --rootdir $rootdir 2>&1 |
            ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    }
    finally { Pop-Location }
}
catch {
    [Console]::Error.WriteLine("Tool testleri çalıştırılamadı ($target): $($_.Exception.Message)")
    exit 2
}

if ($code -eq 0) { exit 0 }

$failures = @($output | Where-Object { $_ -match '^(FAILED|ERROR)\b' })
$summary = @($output | Where-Object { $_.Trim() }) | Select-Object -Last 1
$lines = @("Tool testleri kırmızı (pytest çıkış kodu $code, hedef: $target). Değişen dosya: $path") +
    $failures + @($summary)
[Console]::Error.WriteLine(($lines | Select-Object -Unique) -join "`n")
exit 2
