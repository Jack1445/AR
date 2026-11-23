param([switch]$CheckOnly, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$url = 'http://127.0.0.1:38479/'
Set-Location -LiteralPath $project
. (Join-Path $project 'python_runtime.ps1')
. (Join-Path $project 'local_postgres.ps1')
Initialize-ARLocalPostgres
$env:AR_LOCAL_PRIMARY = '1'
$projectPython = Join-Path $project '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $projectPython -PathType Leaf) {
    $python = $projectPython
} else {
    $python = Find-ARPython
}

function Test-Server {
    try {
        $request = [System.Net.HttpWebRequest]::Create("${url}health")
        $request.Proxy = $null
        $request.Timeout = 1000
        $response = $request.GetResponse()
        try { return ([int]$response.StatusCode -eq 200) }
        finally { $response.Close() }
    } catch { return $false }
}

function Test-CurrentServer {
    try {
        $request = [System.Net.HttpWebRequest]::Create("${url}health")
        $request.Proxy = $null
        $request.Timeout = 1000
        $response = $request.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            try {
                $health = $reader.ReadToEnd() | ConvertFrom-Json
                return ([int]$health.candidate_ai_test -eq 10 -and $health.match_confirm -eq $true -and [int]$health.match_ai_test -eq 1 -and [int]$health.account_admin -eq 2)
            }
            finally { $reader.Close() }
        } finally { $response.Close() }
    } catch { return $false }
}

function Stop-OutdatedARServer {
    $serverScript = [System.IO.Path]::GetFullPath((Join-Path $project 'web_server.py'))
    $venvPython = [System.IO.Path]::GetFullPath((Join-Path $project '.venv\Scripts\python.exe'))
    try {
        $listeners = @(Get-NetTCPConnection -LocalPort 38479 -State Listen -ErrorAction Stop)
        foreach ($listener in $listeners) {
            $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction Stop
            $command = [string]$processInfo.CommandLine
            $absoluteLaunch = $command.IndexOf($serverScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
            $venvRelativeLaunch = $command.IndexOf($venvPython, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $command -match '(?i)(?:^|\s)["'']?web_server\.py["'']?(?:\s|$)'
            if ($processInfo -and ($absoluteLaunch -or $venvRelativeLaunch)) {
                Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
                return $true
            }
        }
    } catch {
        Write-Host "Could not restart the old AR server: $($_.Exception.Message)"
    }
    return $false
}

if (-not (Test-Path -LiteralPath (Join-Path $project 'web\data.js') -PathType Leaf)) {
    Write-Host 'Local data is missing. Run python ar.py pull --all-tables in your Python PowerShell first.'
    exit 1
}

if ((Test-Server) -and -not (Test-CurrentServer)) {
    if ($CheckOnly) {
        Write-Host 'An older AR server is running on port 38479. Restart it to load the new page.'
        exit 1
    }
    if (-not (Stop-OutdatedARServer)) {
        Write-Host 'Port 38479 is in use by another or unverified process. Close it, then open AR again.'
        exit 1
    }
    for ($attempt = 0; $attempt -lt 12 -and (Test-Server); $attempt++) { Start-Sleep -Milliseconds 250 }
}

if (-not (Test-Server)) {
    if ($CheckOnly) {
        if ($python) { Write-Host "Python found: $python"; exit 0 }
        Write-Host 'Python 3.10+ was not found. Install Python and run the first-time setup script.'
        exit 1
    }
    if (-not $python) {
        Write-Host 'Python 3.10+ was not found. Install Python and run the first-time setup script.'
        exit 1
    }
    # The browser service should use the verified Windows credential, not stale shell values.
    Remove-Item Env:\FEISHU_APP_ID, Env:\FEISHU_APP_SECRET -ErrorAction SilentlyContinue
    Start-Process -FilePath $python -ArgumentList ('"' + (Join-Path $project 'web_server.py') + '"') -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-Server) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Host 'AR local server did not start. Run python web_server.py in PowerShell to see the error.'
        exit 1
    }
} elseif ($CheckOnly) {
    if ($python) { Write-Host "Python found: $python"; exit 0 }
    Write-Host 'The server is running, but Python could not be found for a new launch.'
    exit 1
}

if (-not $NoBrowser) { Start-Process $url }
