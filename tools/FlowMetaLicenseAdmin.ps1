param(
    [string]$PrivateKeyPath = ''
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if ([string]::IsNullOrWhiteSpace($PrivateKeyPath)) {
    $PrivateKeyPath = Join-Path $PSScriptRoot '..\license-private.key'
}

function ConvertTo-Base64Url {
    param([byte[]]$Bytes)

    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function New-FlowMetaLicense {
    param(
        [Parameter(Mandatory = $true)]
        [string]$MachineId,

        [Parameter(Mandatory = $true)]
        [datetime]$ExpiresLocal,

        [Parameter(Mandatory = $true)]
        [string]$PrivateKeyPath
    )

    if (-not (Test-Path -LiteralPath $PrivateKeyPath)) {
        throw "Khong tim thay private key: $PrivateKeyPath`r`nKhong tao key moi tai day vi app khach chi nhan public key hien tai."
    }

    $machineIdValue = $MachineId.Trim().ToUpperInvariant()
    if ([string]::IsNullOrWhiteSpace($machineIdValue)) {
        throw 'Chua nhap MachineID.'
    }

    if ($machineIdValue -notmatch '^FM-[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}$') {
        throw 'MachineID sai dinh dang. Dinh dang dung: FM-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX'
    }

    $expiresUtc = ([DateTimeOffset]$ExpiresLocal).ToUniversalTime()
    if ($expiresUtc -le [DateTimeOffset]::UtcNow) {
        throw 'Ngay het han phai lon hon thoi gian hien tai.'
    }

    $payload = [ordered]@{
        Product = 'FlowMeta'
        MachineId = $machineIdValue
        IssuedAtUtc = ([DateTimeOffset]::UtcNow).ToString('O')
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

    return 'FM1-' + (ConvertTo-Base64Url $payloadBytes) + '.' + (ConvertTo-Base64Url $signatureBytes)
}

[System.Windows.Forms.Application]::EnableVisualStyles()

$primary = [System.Drawing.Color]::FromArgb(0, 174, 239)
$danger = [System.Drawing.Color]::FromArgb(220, 38, 38)
$back = [System.Drawing.Color]::FromArgb(225, 245, 249)
$text = [System.Drawing.Color]::FromArgb(17, 24, 39)

$form = New-Object System.Windows.Forms.Form
$form.Text = 'FlowMeta License Admin'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(820, 520)
$form.MinimumSize = New-Object System.Drawing.Size(760, 480)
$form.BackColor = $back
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Tao license FlowMeta'
$title.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 15)
$title.ForeColor = $text
$title.Location = New-Object System.Drawing.Point(18, 16)
$title.Size = New-Object System.Drawing.Size(760, 34)
$form.Controls.Add($title)

$machineLabel = New-Object System.Windows.Forms.Label
$machineLabel.Text = 'MachineID nguoi dung gui:'
$machineLabel.ForeColor = $text
$machineLabel.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9)
$machineLabel.Location = New-Object System.Drawing.Point(20, 68)
$machineLabel.Size = New-Object System.Drawing.Size(220, 24)
$form.Controls.Add($machineLabel)

$machineTextBox = New-Object System.Windows.Forms.TextBox
$machineTextBox.Location = New-Object System.Drawing.Point(20, 94)
$machineTextBox.Size = New-Object System.Drawing.Size(760, 26)
$machineTextBox.Anchor = 'Top,Left,Right'
$machineTextBox.BorderStyle = 'FixedSingle'
$form.Controls.Add($machineTextBox)

$expiryLabel = New-Object System.Windows.Forms.Label
$expiryLabel.Text = 'Han su dung:'
$expiryLabel.ForeColor = $text
$expiryLabel.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9)
$expiryLabel.Location = New-Object System.Drawing.Point(20, 138)
$expiryLabel.Size = New-Object System.Drawing.Size(160, 24)
$form.Controls.Add($expiryLabel)

$expiryPicker = New-Object System.Windows.Forms.DateTimePicker
$expiryPicker.Location = New-Object System.Drawing.Point(20, 164)
$expiryPicker.Size = New-Object System.Drawing.Size(220, 26)
$expiryPicker.Format = 'Custom'
$expiryPicker.CustomFormat = 'yyyy-MM-dd HH:mm:ss'
$expiryPicker.Value = (Get-Date).Date.AddMonths(1).AddDays(1).AddSeconds(-1)
$form.Controls.Add($expiryPicker)

$presetLabel = New-Object System.Windows.Forms.Label
$presetLabel.Text = 'Chon nhanh:'
$presetLabel.ForeColor = $text
$presetLabel.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9)
$presetLabel.Location = New-Object System.Drawing.Point(270, 138)
$presetLabel.Size = New-Object System.Drawing.Size(160, 24)
$form.Controls.Add($presetLabel)

$presetCombo = New-Object System.Windows.Forms.ComboBox
$presetCombo.Location = New-Object System.Drawing.Point(270, 164)
$presetCombo.Size = New-Object System.Drawing.Size(180, 26)
$presetCombo.DropDownStyle = 'DropDownList'
[void]$presetCombo.Items.Add('1 ngay')
[void]$presetCombo.Items.Add('7 ngay')
[void]$presetCombo.Items.Add('30 ngay')
[void]$presetCombo.Items.Add('90 ngay')
[void]$presetCombo.Items.Add('365 ngay')
$presetCombo.SelectedIndex = 2
$presetCombo.Add_SelectedIndexChanged({
    $days = switch ($presetCombo.SelectedItem) {
        '1 ngay' { 1 }
        '7 ngay' { 7 }
        '30 ngay' { 30 }
        '90 ngay' { 90 }
        '365 ngay' { 365 }
        default { 30 }
    }
    $expiryPicker.Value = (Get-Date).AddDays($days)
})
$form.Controls.Add($presetCombo)

$keyLabel = New-Object System.Windows.Forms.Label
$keyLabel.Text = 'License key:'
$keyLabel.ForeColor = $text
$keyLabel.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9)
$keyLabel.Location = New-Object System.Drawing.Point(20, 214)
$keyLabel.Size = New-Object System.Drawing.Size(160, 24)
$form.Controls.Add($keyLabel)

$keyTextBox = New-Object System.Windows.Forms.TextBox
$keyTextBox.Location = New-Object System.Drawing.Point(20, 240)
$keyTextBox.Size = New-Object System.Drawing.Size(760, 160)
$keyTextBox.Anchor = 'Top,Left,Right,Bottom'
$keyTextBox.Multiline = $true
$keyTextBox.ScrollBars = 'Both'
$keyTextBox.WordWrap = $false
$keyTextBox.BorderStyle = 'FixedSingle'
$form.Controls.Add($keyTextBox)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "Private key: $PrivateKeyPath"
$statusLabel.ForeColor = $text
$statusLabel.Location = New-Object System.Drawing.Point(20, 412)
$statusLabel.Size = New-Object System.Drawing.Size(760, 30)
$statusLabel.Anchor = 'Left,Right,Bottom'
$form.Controls.Add($statusLabel)

$generateButton = New-Object System.Windows.Forms.Button
$generateButton.Text = 'Tao key'
$generateButton.BackColor = $primary
$generateButton.ForeColor = [System.Drawing.Color]::White
$generateButton.FlatStyle = 'Flat'
$generateButton.Location = New-Object System.Drawing.Point(440, 458)
$generateButton.Size = New-Object System.Drawing.Size(110, 34)
$generateButton.Anchor = 'Right,Bottom'
$form.Controls.Add($generateButton)

$copyButton = New-Object System.Windows.Forms.Button
$copyButton.Text = 'Copy key'
$copyButton.BackColor = $primary
$copyButton.ForeColor = [System.Drawing.Color]::White
$copyButton.FlatStyle = 'Flat'
$copyButton.Location = New-Object System.Drawing.Point(560, 458)
$copyButton.Size = New-Object System.Drawing.Size(110, 34)
$copyButton.Anchor = 'Right,Bottom'
$form.Controls.Add($copyButton)

$clearButton = New-Object System.Windows.Forms.Button
$clearButton.Text = 'Xoa'
$clearButton.BackColor = $danger
$clearButton.ForeColor = [System.Drawing.Color]::White
$clearButton.FlatStyle = 'Flat'
$clearButton.Location = New-Object System.Drawing.Point(680, 458)
$clearButton.Size = New-Object System.Drawing.Size(100, 34)
$clearButton.Anchor = 'Right,Bottom'
$form.Controls.Add($clearButton)

$generateButton.Add_Click({
    try {
        $keyTextBox.Text = New-FlowMetaLicense `
            -MachineId $machineTextBox.Text `
            -ExpiresLocal $expiryPicker.Value `
            -PrivateKeyPath $PrivateKeyPath
        $statusLabel.ForeColor = $primary
        $statusLabel.Text = 'Da tao license key. Gui key nay cho nguoi dung.'
    }
    catch {
        $statusLabel.ForeColor = $danger
        $statusLabel.Text = $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'FlowMeta License Admin', 'OK', 'Error') | Out-Null
    }
})

$copyButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($keyTextBox.Text)) {
        $statusLabel.ForeColor = $danger
        $statusLabel.Text = 'Chua co license key de copy.'
        return
    }

    [System.Windows.Forms.Clipboard]::SetText($keyTextBox.Text)
    $statusLabel.ForeColor = $primary
    $statusLabel.Text = 'Da copy license key.'
})

$clearButton.Add_Click({
    $machineTextBox.Clear()
    $keyTextBox.Clear()
    $statusLabel.ForeColor = $text
    $statusLabel.Text = "Private key: $PrivateKeyPath"
})

[void]$form.ShowDialog()
