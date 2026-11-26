function Initialize-ARLocalPostgres {
    if ($env:DATABASE_URL) { return }

    $project = $PSScriptRoot
    $pgBin = Join-Path $project '.postgresql\Library\bin'
    $pgData = Join-Path $project '.postgresql-data'
    $pgLog = Join-Path $project 'postgres-local.log'
    $pgPort = 55432
    $pgUser = 'ar_local'
    $pgDatabase = 'alumni_talent'
    $pgCtl = Join-Path $pgBin 'pg_ctl.exe'
    $pgReady = Join-Path $pgBin 'pg_isready.exe'
    $psql = Join-Path $pgBin 'psql.exe'
    $createdb = Join-Path $pgBin 'createdb.exe'

    if (-not (Test-Path -LiteralPath $pgCtl -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION') -PathType Leaf)) {
        throw 'AR local PostgreSQL is not installed. Re-run the local database setup.'
    }

    & $pgReady -h 127.0.0.1 -p $pgPort -q
    if ($LASTEXITCODE -ne 0) {
        $pidFile = Join-Path $pgData 'postmaster.pid'
        if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
            $postmasterPid = 0
            [void][int]::TryParse(([string](Get-Content -LiteralPath $pidFile -TotalCount 1)).Trim(), [ref]$postmasterPid)
            if ($postmasterPid -le 0 -or -not (Get-Process -Id $postmasterPid -ErrorAction SilentlyContinue)) {
                $staleName = 'postmaster.pid.stale-' + (Get-Date -Format 'yyyyMMddHHmmss')
                Move-Item -LiteralPath $pidFile -Destination (Join-Path $pgData $staleName)
            }
        }
        # Keep PostgreSQL outside the launcher's console process group. Otherwise
        # closing or recycling the cmd/PowerShell window sends CTRL_C_EVENT to
        # postgres on Windows and the web services never get a chance to start.
        $pgStart = Start-Process -FilePath $pgCtl -ArgumentList @(
            '-D', ('"' + $pgData + '"'),
            '-l', ('"' + $pgLog + '"'),
            '-o', ('"-p ' + $pgPort + ' -h 127.0.0.1"'),
            '-w', '-t', '30', 'start'
        ) -WindowStyle Hidden -Wait -PassThru
        if ($pgStart.ExitCode -ne 0) {
            throw "AR local PostgreSQL failed to start. See $pgLog"
        }
        & $pgReady -h 127.0.0.1 -p $pgPort -q
        if ($LASTEXITCODE -ne 0) { throw "AR local PostgreSQL started but is not accepting connections. See $pgLog" }
    }

    $exists = & $psql -h 127.0.0.1 -p $pgPort -U $pgUser -d postgres -tA -c "SELECT 1 FROM pg_database WHERE datname = '$pgDatabase'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the AR local PostgreSQL database.' }
    $databaseExists = @($exists) | Where-Object { ([string]$_).Trim() -eq '1' }
    if (-not $databaseExists) {
        & $createdb -h 127.0.0.1 -p $pgPort -U $pgUser $pgDatabase
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the AR local PostgreSQL database.' }
    }

    $env:DATABASE_URL = "postgresql://${pgUser}@127.0.0.1:${pgPort}/${pgDatabase}"
}
