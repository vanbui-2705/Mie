param(
    [Parameter(Mandatory = $true)]
    [string]$MachineId,

    [Parameter(Mandatory = $true)]
    [string]$Expires,

    [string]$PrivateKeyPath = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    $PrivateKeyPath = Join-Path $PSScriptRoot '..\license-private.key'
}

function ConvertTo-Base64Url {
    param([byte[]]$Bytes)

    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function New-PrivateKeyFile {
    param([string]$Path)

    $rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider 2048
    try {
        [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($Path)) | Out-Null
        [System.IO.File]::WriteAllText($Path, $rsa.ToXmlString($true), [System.Text.Encoding]::UTF8)
        Write-Host "Created private key: $Path"
        Write-Host "IMPORTANT: app public key must match this private key. If you regenerate this file, rebuild the app with the new public key."
        Write-Host "Public key:"
        Write-Host $rsa.ToXmlString($false)
    }
    finally {
        $rsa.PersistKeyInCsp = $false
        $rsa.Clear()
    }
}

if (-not (Test-Path -LiteralPath $PrivateKeyPath)) {
    New-PrivateKeyFile -Path $PrivateKeyPath
}

$machineIdValue = $MachineId.Trim().ToUpperInvariant()
$expiresText = $Expires.Trim()
$expiresLocal = [datetime]::Parse($expiresText)
if ($expiresLocal.TimeOfDay -eq [TimeSpan]::Zero -and $expiresText -notmatch '\d{1,2}:\d{2}') {
    $expiresLocal = $expiresLocal.Date.AddDays(1).AddSeconds(-1)
}

$expiresUtc = ([DateTimeOffset]$expiresLocal).ToUniversalTime()
$issuedUtc = [DateTimeOffset]::UtcNow
$payload = [ordered]@{
    Product = 'FlowMeta'
    MachineId = $machineIdValue
    IssuedAtUtc = $issuedUtc.ToString('O')
    ExpiresAtUtc = $expiresUtc.ToString('O')
    LicenseId = [Guid]::NewGuid().ToString('N')
}

$json = $payload | ConvertTo-Json -Compress
$payloadBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
$privateXml = [System.IO.File]::ReadAllText($PrivateKeyPath, [System.Text.Encoding]::UTF8)
$rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider
try {
    $rsa.FromXmlString($privateXml)
    $signatureBytes = $rsa.SignData($payloadBytes, 'SHA256')
}
finally {
    $rsa.PersistKeyInCsp = $false
    $rsa.Clear()
}

$licenseKey = 'FM1-' + (ConvertTo-Base64Url $payloadBytes) + '.' + (ConvertTo-Base64Url $signatureBytes)

Write-Host ''
Write-Host 'MachineID:' $machineIdValue
Write-Host 'Expires local:' $expiresLocal.ToString('yyyy-MM-dd HH:mm:ss')
Write-Host 'Expires UTC:' $expiresUtc.ToString('O')
Write-Host ''
Write-Host 'License key:'
Write-Host $licenseKey
