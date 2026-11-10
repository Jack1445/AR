# Copy this file to setup-feishu-credentials.ps1, then fill in the two values below.
# The local copy is ignored by Git. Keep it private and delete it after setup if desired.
$appId = 'PASTE_APP_ID_HERE'
$appSecret = 'PASTE_APP_SECRET_HERE'

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$appId = $appId.Trim()
$appSecret = $appSecret.Trim()
if ($appId -eq 'PASTE_APP_ID_HERE' -or $appSecret -eq 'PASTE_APP_SECRET_HERE' -or
    -not $appId -or -not $appSecret) {
    Write-Host '请先在脚本开头填写当前飞书应用的 App ID 和 App Secret。'
    exit 1
}

try {
    $env:FEISHU_APP_ID = $appId
    $env:FEISHU_APP_SECRET = $appSecret

    Write-Host '正在验证飞书应用凭据和多维表格访问权限...'
    python ar.py check
    if ($LASTEXITCODE -ne 0) {
        Write-Host '验证失败，凭据尚未保存。请核对 App ID 和 App Secret 是否来自同一个飞书应用。'
        exit 1
    }

    python ar.py save-credentials
    if ($LASTEXITCODE -ne 0) {
        Write-Host '验证成功，但保存到 Windows 凭据管理器失败。'
        exit 1
    }
    Write-Host '设置完成。若当前 PowerShell 曾设置旧凭据，请先在原窗口运行：'
    Write-Host 'Remove-Item Env:\FEISHU_APP_ID, Env:\FEISHU_APP_SECRET -ErrorAction SilentlyContinue'
    Write-Host '然后运行 python ar.py pull --all-tables。'
}
finally {
    Remove-Item Env:\FEISHU_APP_ID, Env:\FEISHU_APP_SECRET -ErrorAction SilentlyContinue
}
