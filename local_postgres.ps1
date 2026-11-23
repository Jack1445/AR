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
        & $pgCtl -D $pgData -l $pgLog -o "-p $pgPort -h 127.0.0.1" -w -t 30 start
        if ($LASTEXITCODE -ne 0) {
            throw "AR local PostgreSQL failed to start. See $pgLog"
        }
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
