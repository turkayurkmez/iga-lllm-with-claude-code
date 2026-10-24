# UserPromptSubmit hook'u: görev prompt'larına prompt-netlestir hatırlatması ekler.
# Slash komutlarını, boş prompt'ları ve onay/kısa yanıt kalıplarını atlar.
# Hiçbir koşulda prompt'u engellemez: her hata yutulur, çıkış kodu 0'dır.
# Not: Windows PowerShell 5.1 BOM'suz betiği ANSI okur; dosya UTF-8 BOM ile kaydedilmelidir.

# Tam eşleşme aranır; liste genişletilebilir.
$approvalPatterns = @(
    'evet', 'hayır', 'tamam', 'ok', 'devam', 'devam et', 'onay', 'onaylıyorum',
    'kabul', 'uygun', 'olur', 'iptal', 'dur'
)

$context = "Prompt netleştirme kontrolü: Bu mesaj yeni bir görev prompt'uysa, çalışmaya başlamadan önce prompt-netlestir skill'ini Skill aracıyla yükle ve uygula.`nMesaj senin sorduğun bir soruya ya da gösterdiğin özete yanıtsa bu kontrolü atla."

try {
    # Varsayılan kod sayfası Türkçe karakterleri bozduğu için stdin açıkça UTF-8 okunur.
    $reader = New-Object IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)
    $payload = $reader.ReadToEnd() | ConvertFrom-Json
    $prompt = [string]$payload.prompt
    $trimmed = $prompt.Trim()

    if ($trimmed -eq '' -or $trimmed.StartsWith('/')) { exit 0 }

    # "HAYIR" -> "hayır" doğru küçülsün diye tr-TR kültürü kullanılır.
    $normalized = ($trimmed -replace '^[\p{P}\s]+|[\p{P}\s]+$', '').ToLower(
        [Globalization.CultureInfo]::GetCultureInfo('tr-TR'))

    if ($approvalPatterns -contains $normalized -or $normalized -match '^[\p{L}\p{Nd}]$') { exit 0 }

    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    @{ hookSpecificOutput = @{ hookEventName = 'UserPromptSubmit'; additionalContext = $context } } |
        ConvertTo-Json -Compress -Depth 3
}
catch { }
exit 0
