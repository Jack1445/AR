# Find an installed Python 3.10+ without relying on one computer's install path.
function Find-ARPython {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:AR_PYTHON) { $candidates.Add($env:AR_PYTHON) }
    if ($env:CONDA_PREFIX) { $candidates.Add((Join-Path $env:CONDA_PREFIX 'python.exe')) }

    foreach ($command in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($command.Source -and $command.Source -notmatch '\\WindowsApps\\') {
            $candidates.Add($command.Source)
        }
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $found = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { $candidates.Add(([string]$found).Trim()) }
        } catch { }
    }

    foreach ($root in @(
        (Join-Path $env:USERPROFILE 'miniconda3'),
        (Join-Path $env:USERPROFILE 'anaconda3'),
        (Join-Path $env:LOCALAPPDATA 'miniconda3'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        'C:\Miniconda3', 'D:\Miniconda3', 'C:\ProgramData\Miniconda3'
    )) {
        $candidates.Add((Join-Path $root 'python.exe'))
        if (Test-Path -LiteralPath $root -PathType Container) {
            foreach ($directory in @(Get-ChildItem -LiteralPath $root -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
                $candidates.Add((Join-Path $directory.FullName 'python.exe'))
            }
        }
    }

    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $supported = & $candidate -c 'import sys; print(int(sys.version_info >= (3, 10)))' 2>$null
            if ($LASTEXITCODE -eq 0 -and ([string]$supported).Trim() -eq '1') {
                return (Resolve-Path -LiteralPath $candidate).Path
            }
        } catch { }
    }
    return $null
}
