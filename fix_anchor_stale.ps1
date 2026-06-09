#requires -Version 5.1
<#
  fix_anchor_stale.ps1 — one-shot, self-verifying repair for the Anchor
  "stale server on port 8777" problem. RUN ELEVATED (Terminal as Admin).

  ROOT CAUSE (found by adversarial diagnosis):
    There are TWO NSSM services that each run an Anchor server in C:\dev\Anchor:
      * `anchor`         — the legitimate supervisor (C:\Tools\nssm\nssm.exe)
      * `Anchor-Server`  — a ROGUE DUPLICATE service (WinGet nssm), created
                           2026-05-16, running OLD code.
    The old code bound the port with SO_REUSEADDR, so BOTH servers could listen
    on 8777 at once and requests randomly hit the old or new one. `nssm restart
    anchor` can never fix this — it only restarts one of the two supervisors,
    and the rogue one respawns its old-code child within ~2s.

    NOTE: those NSSM/LocalSystem children expose an EMPTY command line even to
    an elevated query, so we reap by PORT/PID, never by command-line match.

  WHAT THIS DOES (idempotent, safe to re-run):
    1. Verify `Anchor-Server` really is the rogue Anchor duplicate, then STOP +
       REMOVE it (so it stops respawning). Leaves `anchor` and `ledger` alone.
    2. Stop `anchor`, reap every PID still listening on 8777 (only python/pythonw
       anchor servers — reports anything else instead of killing).
    3. Start `anchor` so its NEW-code child binds 8777 as the sole owner.
    4. PROVE the new code is live: GET /api/rnd/tail must be 400 (not 404) and
       GET / must contain the R&D UI. Prints RESULT: NEW UI LIVE / STILL STALE.

  Leaves untouched: `anchor` (legit), `ledger` (legit, ledger_gui.py on 8778),
  the claude-code-bridge and aurora python processes.
#>

$ErrorActionPreference = 'Continue'
$Port = 8777
$Base = "http://127.0.0.1:$Port"
$AnchorDir = 'C:\dev\Anchor'

function Step($m){ Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "    [ok]   $m" -ForegroundColor Green }
function Warn($m){ Write-Host "    [warn] $m" -ForegroundColor Yellow }
function Fail($m){ Write-Host "    [FAIL] $m" -ForegroundColor Red }

# --- elevation check -------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin){ Fail "Not elevated. Re-run from Terminal (Admin)."; exit 2 }

# --- resolve an nssm.exe (any one can control a service by name) ------------
$Nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $Nssm){
  foreach($c in @("C:\Tools\nssm\nssm.exe",
                  "$env:LOCALAPPDATA\Microsoft\WinGet\Links\nssm.exe",
                  "C:\Windows\System32\nssm.exe")){ if(Test-Path $c){ $Nssm=$c; break } }
}
if (-not $Nssm){ Fail "nssm.exe not found."; exit 2 }
Ok "Using nssm: $Nssm"

function PortOwners {
  @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique)
}

# === 1. Remove the rogue Anchor-Server service =============================
Step "1/4  Checking for the rogue 'Anchor-Server' service"
$rogue = Get-Service -Name 'Anchor-Server' -ErrorAction SilentlyContinue
if ($rogue){
  $rp = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Anchor-Server\Parameters' -ErrorAction SilentlyContinue
  Write-Host "    Anchor-Server params: App=$($rp.Application) Dir=$($rp.AppDirectory) Params=$($rp.AppParameters)"
  $isAnchor = ($rp.AppParameters -match 'anchor_gui\.py') -and ($rp.AppDirectory -ieq $AnchorDir)
  if ($isAnchor){
    & $Nssm stop   Anchor-Server 2>&1 | ForEach-Object { "    $_" }
    & $Nssm remove Anchor-Server confirm 2>&1 | ForEach-Object { "    $_" }
    Start-Sleep -Milliseconds 800
    if (Get-Service -Name 'Anchor-Server' -ErrorAction SilentlyContinue){
      Warn "Anchor-Server still present; trying sc.exe delete"; & sc.exe delete Anchor-Server | Out-Null
    }
    Ok "Rogue 'Anchor-Server' removed."
  } else {
    Warn "A service named 'Anchor-Server' exists but its params are NOT anchor_gui.py in $AnchorDir."
    Warn "Refusing to remove it. Inspect manually before continuing."
  }
} else { Ok "No 'Anchor-Server' service present (already removed)." }

# === 2. Stop legit service + reap any 8777 squatters (by PORT/PID) =========
Step "2/4  Stopping 'anchor' and freeing port $Port"
& $Nssm stop anchor 2>&1 | ForEach-Object { "    $_" }
Start-Sleep -Milliseconds 800
foreach($procId in PortOwners){
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
  if ($p -and $p.Name -in @('python.exe','pythonw.exe')){
    Write-Host "    killing 8777 owner PID $procId ($($p.Name))" -ForegroundColor Magenta
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  } elseif ($p){
    Warn "Port $Port held by NON-python PID $procId ($($p.Name)) — NOT killing. Free it manually."
  }
}
$deadline = (Get-Date).AddSeconds(10)
while ((PortOwners).Count -gt 0 -and (Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 400 }
if ((PortOwners).Count -gt 0){ Fail "Port $Port still held by PID(s): $((PortOwners) -join ', '). RESULT: STILL STALE"; exit 1 }
Ok "Port $Port is free."

# === 3. Start the legit service ===========================================
Step "3/4  Starting 'anchor'"
& $Nssm start anchor 2>&1 | ForEach-Object { "    $_" }
$deadline = (Get-Date).AddSeconds(20)
while ((PortOwners).Count -eq 0 -and (Get-Date) -lt $deadline){ Start-Sleep -Milliseconds 500 }
if ((PortOwners).Count -eq 0){ Fail "Service did not bind $Port within 20s. RESULT: STILL STALE"; exit 1 }
Ok "anchor is listening on $Port (PID $((PortOwners) -join ','))."

# === 4. Verify the NEW code is serving ====================================
Step "4/4  Verifying new code is live"
function TailCode {
  try { return [int](Invoke-WebRequest "$Base/api/rnd/tail" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop).StatusCode }
  catch [System.Net.WebException] { if($_.Exception.Response){ return [int]$_.Exception.Response.StatusCode } return -1 }
  catch { return -1 }
}
$code = -1
for($i=0; $i -lt 12; $i++){ $code = TailCode; if($code -eq 400 -or $code -eq 404){ break }; Start-Sleep -Milliseconds 600 }
$tailOk = ($code -eq 400)
if ($code -eq 400){ Ok "/api/rnd/tail -> 400 (new route present)." }
elseif ($code -eq 404){ Fail "/api/rnd/tail -> 404 (OLD code still serving)." }
else { Fail "/api/rnd/tail unreachable (code $code)." }

$uiOk = $false
try {
  $h = (Invoke-WebRequest "$Base/" -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop).Content
  $uiOk = ($h -match "showView\('rnd'\)") -and ($h -match 'New Project')
  if ($uiOk){ Ok "Dashboard HTML has the R&D tab + New Project." } else { Fail "Dashboard HTML missing R&D markers." }
} catch { Fail "GET / failed: $($_.Exception.Message)" }

Write-Host ""
if ($tailOk -and $uiOk){ Write-Host "RESULT: NEW UI LIVE  (hard-refresh the browser: Ctrl+Shift+R)" -ForegroundColor Green; exit 0 }
else { Write-Host "RESULT: STILL STALE" -ForegroundColor Red; exit 1 }
