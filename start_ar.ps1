param([switch]$CheckOnly, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$url = 'http://127.0.0.1:38479/'
Set-Location -LiteralPath $project
. (Join-Path $project 'python_runtime.ps1')
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

if (-not (Test-Path -LiteralPath (Join-Path $project 'web\data.js') -PathType Leaf)) {
    Write-Host 'Local data is missing. Run python ar.py pull --all-tables in your Python PowerShell first.'
    exit 1
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
