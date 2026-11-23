param([ValidateSet('candidate', 'alumni')][string]$Role = 'candidate', [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$url = 'http://127.0.0.1:38480/'
Set-Location -LiteralPath $project
. (Join-Path $project 'python_runtime.ps1')
. (Join-Path $project 'local_postgres.ps1')
Initialize-ARLocalPostgres
$projectPython = Join-Path $project '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $projectPython -PathType Leaf) { $python = $projectPython }
else { $python = Find-ARPython }
if (-not $python) { Write-Host 'Python 3.10+ was not found. Run the AR first-time setup script.'; exit 1 }

function Test-Portal {
    try {
        $request = [System.Net.HttpWebRequest]::Create("${url}health")
        $request.Proxy = $null
        $request.Timeout = 1000
        $response = $request.GetResponse()
        try { return ([int]$response.StatusCode -eq 200) }
        finally { $response.Close() }
    } catch { return $false }
}

function Test-CurrentPortal {
    try {
        $request = [System.Net.HttpWebRequest]::Create("${url}health")
        $request.Proxy = $null
        $request.Timeout = 1000
        $response = $request.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            try {
                $health = $reader.ReadToEnd() | ConvertFrom-Json
                return ([int]$health.candidate_chat -eq 12 -and $health.local_recommendations -eq $true -and [int]$health.alumni_company_fields -eq 1 -and [int]$health.portal_revision -eq 15)
            }
            finally { $reader.Close() }
        } finally { $response.Close() }
    } catch { return $false }
}

function Stop-OutdatedPortal {
    $serverScript = [System.IO.Path]::GetFullPath((Join-Path $project 'portal_server.py'))
    $venvPython = [System.IO.Path]::GetFullPath((Join-Path $project '.venv\Scripts\python.exe'))
    try {
        $listeners = @(Get-NetTCPConnection -LocalPort 38480 -State Listen -ErrorAction Stop)
        foreach ($listener in $listeners) {
            $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction Stop
            $command = [string]$processInfo.CommandLine
            $absoluteLaunch = $command.IndexOf($serverScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
            $venvRelativeLaunch = $command.IndexOf($venvPython, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $command -match '(?i)(?:^|\s)["'']?portal_server\.py["'']?(?:\s|$)'
            if ($processInfo -and ($absoluteLaunch -or $venvRelativeLaunch)) {
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
                return $true
            }
        }
    } catch {
        Write-Host "Could not restart the old AR portal: $($_.Exception.Message)"
    }
    return $false
}

if ((Test-Portal) -and -not (Test-CurrentPortal)) {
    if (-not (Stop-OutdatedPortal)) {
        Write-Host 'Port 38480 is in use by another or unverified process. Close it, then open AR again.'
        exit 1
    }
    for ($attempt = 0; $attempt -lt 12 -and (Test-Portal); $attempt++) { Start-Sleep -Milliseconds 250 }
}

if (-not (Test-Portal)) {
    Remove-Item Env:\FEISHU_APP_ID, Env:\FEISHU_APP_SECRET -ErrorAction SilentlyContinue
    Start-Process -FilePath $python -ArgumentList ('"' + (Join-Path $project 'portal_server.py') + '"') -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Portal) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Host 'AR portal did not start. Run python portal_server.py in PowerShell to see the error.'
        exit 1
    }
}
if (-not $NoBrowser) { Start-Process "${url}${Role}/" }
