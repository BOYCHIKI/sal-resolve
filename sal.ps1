<#
SAL Resolve: local shortcuts (Windows PowerShell 5.1+).

    .\sal setup    first time: venv, packages, .env, database, demo data
    .\sal start    database + API + worker + web, opens http://localhost:3000
    .\sal backend  database + API + worker only (API docs: http://127.0.0.1:8000/docs)
    .\sal web      web only, opens http://localhost:3000 (needs the backend running)
    .\sal dev      like start, but the web reloads on every code change (slower pages, for development)
    .\sal stop     stops what "start" opened (the database keeps its data)
    .\sal status   what is running
    .\sal seed     add the demo cases again
    .\sal test     run backend tests (own database sal_test; demo data is untouched)
    .\sal eval     score the agent; extra options pass through, e.g.
                   .\sal eval --split real_format --roles llm
#>
param(
    [ValidateSet("setup", "start", "backend", "web", "dev", "stop", "status", "seed", "test", "eval", "help")][string]$Command = "help",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Api = Join-Path $Root "apps\api"
$Web = Join-Path $Root "apps\web"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$EnvFile = Join-Path $Api ".env"
$PidFile = Join-Path $Root ".sal\pids.txt"

function Say($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "x $text" -ForegroundColor Red; exit 1 }

function Need($tool, $hint) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "$tool not found. $hint" }
}

function Run($exe, [string[]]$argv, $dir = $Root) {
    Push-Location $dir
    try { & $exe @argv; if ($LASTEXITCODE -ne 0) { Fail "$exe $($argv -join ' ') failed (exit $LASTEXITCODE)" } }
    finally { Pop-Location }
}

function UseLocalPostgres {
    # A PostgreSQL installed on Windows (port 15432) instead of Docker: no Linux VM, far less memory and disk.
    # Chosen when SAL_DB_MODE=local, or when Docker is missing or its engine is not running.
    if ($env:SAL_DB_MODE -eq "local") { return $true }
    if ($env:SAL_DB_MODE -eq "docker") { return $false }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $true }
    try { & docker info *> $null } catch { return $true }   # the engine's stderr is fatal under ErrorAction Stop
    return ($LASTEXITCODE -ne 0)
}

function PsqlPath {
    # psql on PATH, else the standard PostgreSQL for Windows install folder (no PATH change needed).
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $found = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
    Fail "psql not found. Install PostgreSQL 16 for Windows (port 15432, Command Line Tools), or start Docker Desktop."
}

function LocalPsql([string[]]$argv) {
    # The postgres superuser password is the dev-only one from docker-compose.yml unless overridden.
    $env:PGPASSWORD = if ($env:SAL_PG_SUPERUSER_PASSWORD) { $env:SAL_PG_SUPERUSER_PASSWORD } else { "postgres_dev_only" }
    $env:PGOPTIONS = "-c client_min_messages=warning"   # NOTICEs on stderr would be fatal under ErrorAction Stop
    $ErrorActionPreference = "Continue"                  # this function only; failures are read from $LASTEXITCODE
    try { & (PsqlPath) -h 127.0.0.1 -p 15432 -U postgres -v ON_ERROR_STOP=1 @argv 2>$null }
    finally { Remove-Item Env:PGPASSWORD, Env:PGOPTIONS }
}

function Database {
    if (UseLocalPostgres) {
        Say "Using local PostgreSQL on port 15432 (no Docker)"
        $out = LocalPsql @("-d", "postgres", "-tAc", "SELECT 1 FROM pg_roles WHERE rolname = 'sal_migrator'")
        if ($LASTEXITCODE -ne 0) { Fail "Cannot reach PostgreSQL on 127.0.0.1:15432. Is the postgresql service running?" }
        if (-not ($out -match "1")) {   # first run: roles and the sal database, same script Docker runs once
            LocalPsql @("-q", "-d", "postgres", "-f", (Join-Path $Api "db\init\00_roles.sql"))
            if ($LASTEXITCODE -ne 0) { Fail "Creating SAL roles failed" }
        }
        LocalPsql @("-q", "-d", "postgres", "-f", (Join-Path $Api "db\init\01_test_db.sql")) *> $null
    } else {
        Say "Starting PostgreSQL (Docker)"
        Run docker @("compose", "up", "-d", "--wait")
        # Test database for pytest (created on first start; this covers volumes made before it existed).
        try { & docker compose exec -T db psql -q -U postgres -f /docker-entrypoint-initdb.d/01_test_db.sql *> $null } catch {}
    }
    Say "Applying database migrations"
    Run $Py @("-m", "alembic", "upgrade", "head") $Api
}

function Seed {
    Say "Adding demo cases"
    Push-Location $Api
    try { $out = & $Py -m app.seed_demo } finally { Pop-Location }
    $out | Write-Host
    if ($LASTEXITCODE -ne 0) { Fail "seed_demo failed" }
    # First run: seed_demo creates a merchant and prints its id; store it so the API knows who the demo user is.
    $m = $out | Select-String -Pattern "SAL_DEMO_MERCHANT_ID=([0-9a-f-]{36})" | Select-Object -First 1
    if ($m) {
        $id = $m.Matches[0].Groups[1].Value
        $lines = @(Get-Content $EnvFile | Where-Object { $_ -notmatch "^SAL_DEMO_MERCHANT_ID=" }) + "SAL_DEMO_MERCHANT_ID=$id"
        [IO.File]::WriteAllLines($EnvFile, $lines, (New-Object Text.UTF8Encoding $false))
        Say "Saved the demo merchant id in apps/api/.env"
    }
}

function Setup {
    Need python "Install Python 3.12+ from python.org (tick 'Add to PATH')."
    Need npm "Install Node.js 20+ from nodejs.org."
    if (-not (Test-Path $Py)) { Say "Creating Python environment (.venv)"; Run python @("-m", "venv", ".venv") }
    Say "Installing backend packages"
    Run $Py @("-m", "pip", "install", "-q", "-r", "apps\api\requirements.lock")  # exact, tested versions
    if (-not (Test-Path $EnvFile)) {
        Copy-Item (Join-Path $Api ".env.example") $EnvFile
        Say "Created apps/api/.env (fill PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET for PayPal sandbox)"
    }
    Say "Installing web packages"
    Run npm @("install", "--no-fund", "--no-audit") $Web
    Database
    Seed
    Say "Done. Next: .\sal start"
}

function Window($title, $dir, $cmd) {
    $line = "`$host.UI.RawUI.WindowTitle = 'SAL $title'; Set-Location '$dir'; $cmd"
    (Start-Process powershell -ArgumentList "-NoExit", "-Command", $line -PassThru).Id
}

function Remember($id) {
    New-Item -ItemType Directory -Force (Split-Path $PidFile) | Out-Null
    Add-Content $PidFile $id
}

function Listening($port) {
    $tcp = New-Object Net.Sockets.TcpClient
    try { $up = $tcp.ConnectAsync("127.0.0.1", $port).Wait(500) -and $tcp.Connected } catch { $up = $false }
    $tcp.Close()
    $up
}

function Start-Backend {
    if (-not (Test-Path $Py)) { Fail "Run .\sal setup first." }
    if (Listening 8000) { Say "API already running on :8000"; return }
    Database
    Say "Opening API and worker in their own windows"
    Remember (Window "API :8000" $Api "& '$Py' -m uvicorn app.main:app --port 8000")
    Remember (Window "worker" $Api "& '$Py' -m app.worker")
    foreach ($i in 1..30) { if (Listening 8000) { break }; Start-Sleep 1 }
    if (-not (Listening 8000)) { Fail "API did not start. Look at the 'SAL API :8000' window for the error." }
    Say "Backend running. API docs http://127.0.0.1:8000/docs  Stop: .\sal stop"
}

# The production build by default: every page is compiled once, so the first click on each page doesn't wait for
# it. -Dev reloads on every code change instead.
function Start-Web([switch]$Dev) {
    if (-not (Test-Path (Join-Path $Web "node_modules"))) { Fail "Run .\sal setup first." }
    if (-not (Listening 3000)) {
        if (-not (Listening 8000)) { Say "Note: the API is not running, the web will say it can't reach its server. Run .\sal backend" }
        if ($Dev) {
            Say "Opening web (development) in its own window"
            Remember (Window "web :3000" $Web "npm run dev")
        } else {
            Say "Building the web and opening it in its own window (about a minute the first time)"
            Remember (Window "web :3000" $Web "npm run build; if (`$LASTEXITCODE -eq 0) { npm run start }")
        }
        Say "Waiting for the web page"
        foreach ($i in 1..120) {
            try { Invoke-WebRequest "http://localhost:3000" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
            catch { Start-Sleep 2 }
        }
    }
    Start-Process "http://localhost:3000"
    Say "Web running at http://localhost:3000  Stop: .\sal stop"
}

function Start-All {
    if (Test-Path $PidFile) { Stop-All }
    Start-Backend
    Start-Web
}

function Stop-All {
    if (Test-Path $PidFile) {
        foreach ($id in Get-Content $PidFile) { try { & taskkill /PID $id /T /F *> $null } catch {} }
        Remove-Item $PidFile
        Say "Stopped API, worker and web"
    } else { Say "Nothing started by .\sal start, backend or web" }
}

function Status {
    foreach ($p in @(@{n = "Database"; port = 15432 }, @{n = "API"; port = 8000 }, @{n = "Web"; port = 3000 })) {
        Write-Host ("{0,-9} {1}" -f $p.n, $(if (Listening $p.port) { "running" } else { "stopped" }))
    }
    $worker = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*app.worker*" }
    Write-Host ("{0,-9} {1}" -f "Worker", $(if ($worker) { "running" } else { "stopped" }))
}

switch ($Command) {
    "setup"  { Setup }
    "start"  { Start-All }
    "backend" { Start-Backend }
    "web"    { Start-Web }
    "dev"    { if (Test-Path $PidFile) { Stop-All }; Start-Backend; Start-Web -Dev }
    "stop"   { Stop-All }
    "status" { Status }
    "seed"   { Seed }
    "test"   { Database; Run $Py @("-m", "pytest", "-q") $Api }
    "eval"   { Run $Py (@("-m", "app.agent.evaluate") + $Rest) $Api }
    default  { Get-Help $PSCommandPath; Write-Host "Usage: .\sal setup | start | backend | web | dev | stop | status | seed | test | eval" }
}
