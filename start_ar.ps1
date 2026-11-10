param([switch]$CheckOnly, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$url = 'http://127.0.0.1:38479/'
Set-Location -LiteralPath $project

function Find-Pythonw {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:AR_PYTHONW) { $candidates.Add($env:AR_PYTHONW) }

    foreach ($command in @(Get-Command pythonw.exe, python.exe -All -ErrorAction SilentlyContinue)) {
        if ($command.Source -and $command.Source -notmatch '\\WindowsApps\\') {
            $candidates.Add((Join-Path (Split-Path $command.Source) 'pythonw.exe'))
        }
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $python = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $python) {
                $candidates.Add((Join-Path (Split-Path ([string]$python).Trim()) 'pythonw.exe'))
            }
        } catch { }
    }

    foreach ($root in @(
        (Join-Path $env:USERPROFILE 'miniconda3'),
        (Join-Path $env:USERPROFILE 'anaconda3'),
        (Join-Path $env:LOCALAPPDATA 'miniconda3'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        'C:\Miniconda3', 'D:\Miniconda3', 'C:\ProgramData\Miniconda3'
    )) {
        $candidates.Add((Join-Path $root 'pythonw.exe'))
        if (Test-Path -LiteralPath $root -PathType Container) {
            foreach ($directory in @(Get-ChildItem -LiteralPath $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
                $candidates.Add((Join-Path $directory.FullName 'pythonw.exe'))
            }
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
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
    $pythonw = Find-Pythonw
    if ($CheckOnly) {
        if ($pythonw) { Write-Host "Python found: $pythonw"; exit 0 }
        Write-Host 'Python was not found. Run python web_server.py in the PowerShell where python ar.py works.'
        exit 1
    }
    if (-not $pythonw) {
        Write-Host 'Python was not found. Run python web_server.py in the PowerShell where python ar.py works.'
        exit 1
    }
    Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $project 'web_server.py') + '"') -WindowStyle Hidden
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
    $pythonw = Find-Pythonw
    if ($pythonw) { Write-Host "Python found: $pythonw"; exit 0 }
    Write-Host 'The server is running, but Python could not be found for a new launch.'
    exit 1
}

if (-not $NoBrowser) { Start-Process $url }
