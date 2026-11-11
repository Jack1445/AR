param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
Set-Location -LiteralPath $project
. (Join-Path $project 'python_runtime.ps1')

function Read-LocalCredentials([string]$file) {
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw '凭据文件有语法错误，请检查引号。' }
    $values = @{}
    foreach ($assignment in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true)) {
        if ($assignment.Left -isnot [System.Management.Automation.Language.VariableExpressionAst] -or
            $assignment.Right -isnot [System.Management.Automation.Language.CommandExpressionAst] -or
            $assignment.Right.Expression -isnot [System.Management.Automation.Language.StringConstantExpressionAst]) { continue }
        $name = $assignment.Left.VariablePath.UserPath
        if ($name -in @('appId', 'appSecret')) { $values[$name] = $assignment.Right.Expression.Value.Trim() }
    }
    return $values
}

function Run-Python([string]$python, [string[]]$arguments) {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "上一步失败（退出代码 $LASTEXITCODE），安装已停止；修复后重新运行即可。" }
}

try {
    $python = Find-ARPython
    if (-not $python) {
        throw '未找到 Python 3.10 或更新版本。请先安装 Python，并勾选 Add Python to PATH，然后重新运行首次配置AR.cmd。'
    }
    Write-Host "找到 Python：$python"
    if ($CheckOnly) { exit 0 }

    $credentialsFile = Join-Path $project 'setup-feishu-credentials.ps1'
    if (-not (Test-Path -LiteralPath $credentialsFile -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $project 'setup-feishu-credentials.example.ps1') -Destination $credentialsFile
    }
    $values = Read-LocalCredentials $credentialsFile
    if (-not $values.appId -or -not $values.appSecret -or
        $values.appId -eq 'PASTE_APP_ID_HERE' -or $values.appSecret -eq 'PASTE_APP_SECRET_HERE') {
        Write-Host '请在打开的文件顶部填写 App ID 和 App Secret，保存并关闭记事本；安装会继续。'
        Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $credentialsFile + '"') -Wait
        $values = Read-LocalCredentials $credentialsFile
    }
    if (-not $values.appId -or -not $values.appSecret -or
        $values.appId -eq 'PASTE_APP_ID_HERE' -or $values.appSecret -eq 'PASTE_APP_SECRET_HERE') {
        throw 'App ID 或 App Secret 尚未填写。'
    }

    $venvPython = Join-Path $project '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host '正在创建项目独立的 Python 环境...'
        Run-Python $python @('-m', 'venv', '--without-pip', (Join-Path $project '.venv'))
    }
    Write-Host '正在安装项目依赖（包括 PDF 读取组件）...'
    Run-Python $python @('-m', 'pip', 'install', '--ignore-installed', '--upgrade', '--target', (Join-Path $project '.venv\Lib\site-packages'), '-r', (Join-Path $project 'requirements.txt'))
    Run-Python $venvPython @('-c', 'import keyring, pypdf')

    $env:FEISHU_APP_ID = $values.appId
    $env:FEISHU_APP_SECRET = $values.appSecret
    $baseUrl = ''
    if (-not (Test-Path -LiteralPath (Join-Path $project 'ar.json') -PathType Leaf)) {
        $baseUrl = (Read-Host '首次使用：请粘贴目标飞书多维表格链接').Trim()
        if (-not $baseUrl) { throw '没有提供飞书多维表格链接。' }
    }
    Write-Host '正在识别并验证三张飞书数据表...'
    $configArgs = @((Join-Path $project 'setup_config.py'))
    if ($baseUrl) { $configArgs += @('--base-url', $baseUrl) }
    Run-Python $venvPython $configArgs

    Write-Host '正在检查飞书访问权限...'
    Run-Python $venvPython @((Join-Path $project 'ar.py'), 'check')
    Write-Host '正在保存凭据到当前 Windows 用户的凭据管理器...'
    Run-Python $venvPython @((Join-Path $project 'ar.py'), 'save-credentials')
    Write-Host '正在下载全部表格、简历附件并生成网页数据...'
    Run-Python $venvPython @((Join-Path $project 'ar.py'), 'pull', '--all-tables')
    if (-not (Test-Path -LiteralPath (Join-Path $project 'web\data.js') -PathType Leaf)) {
        throw '下载完成后仍未找到网页数据，请检查下载输出。'
    }
    Write-Host '首次配置完成！现在双击“打开AR网页.cmd”即可打开网页。'
    exit 0
} catch {
    Write-Host "配置失败：$($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item Env:\FEISHU_APP_ID, Env:\FEISHU_APP_SECRET -ErrorAction SilentlyContinue
}
