#requires -Version 5.1
# restart_anchor.ps1 - the CANONICAL warm restart for the Anchor service.
# RUN ELEVATED (Terminal as Admin) - nssm start/stop require it.
#
# WHY THIS EXISTS (rearch W3, Phase-2 durable saving):
#   A bare `nssm restart anchor` kills the server process and every live PTY it
#   owns - so any open terminal session loses its context ("cold" on reopen).
#   This wrapper first runs the pre-designed GRACEFUL DRAIN
#   (tools/pre_restart_drain.py) WHILE THE SERVICE IS STILL UP, which for every
#   live session: parks it (close_session -> STATUS_IDLE, worktree kept),
#   PERSISTS its produced docs into the main project, and CACHES its warm-resume
#   summary - all to disk, so it survives the stop. THEN it restarts the service.
#   Result: a deploy/restart is warm-by-design - clicking a parked tile after the
#   restart resumes WARM (continue_session finds the persisted docs + cached
#   summary), never dead context.
#
#   The drain is best-effort and per-session timeout-bounded (a wedged model call
#   can never block the restart); it never raises. If it fails entirely the
#   restart still proceeds (fail-open) - a warm restart is a bonus, not a gate.
#
# Idempotent / safe to re-run. Leaves 'ledger', bridge, aurora untouched.

$ErrorActionPreference = 'Continue'
$Port = 8777
$Base = "http://127.0.0.1:$Port"
$AnchorDir = 'C:\dev\Anchor'

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "[FAIL] Not elevated. Re-run from Terminal (Admin)." -ForegroundColor Red; exit 2 }

$Nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $Nssm) {
  foreach ($c in @("C:\Tools\nssm\nssm.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\nssm.exe", "C:\Windows\System32\nssm.exe")) {
    if (Test-Path $c) { $Nssm = $c; break }
  }
}
if (-not $Nssm) { Write-Host "[FAIL] nssm.exe not found." -ForegroundColor Red; exit 2 }
Write-Host "[ok] Using nssm: $Nssm" -ForegroundColor Green

$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }

function Get-PortOwners {
  return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

# 1. WARM DRAIN (while the service is still up) - park every live session warm.
Write-Host "`n==> 1/3 Warm drain (park live sessions, persist docs + cache summaries)" -ForegroundColor Cyan
if ($Py) {
  Push-Location $AnchorDir
  try {
    # No ANCHOR_TOKEN needed: the drain reads the on-disk registry directly.
    & $Py "tools\pre_restart_drain.py" 2>&1 | ForEach-Object { "    $_" }
    if ($LASTEXITCODE -ne 0) { Write-Host "[warn] drain exited $LASTEXITCODE; proceeding with restart (fail-open)." -ForegroundColor Yellow }
    else { Write-Host "[ok] Warm drain complete." -ForegroundColor Green }
  } catch {
    Write-Host "[warn] drain threw ($($_.Exception.Message)); proceeding with restart (fail-open)." -ForegroundColor Yellow
  } finally { Pop-Location }
} else {
  Write-Host "[warn] python not found; skipping warm drain (cold restart)." -ForegroundColor Yellow
}

# 2. Restart the service.
Write-Host "`n==> 2/3 Restarting 'anchor'" -ForegroundColor Cyan
& $Nssm stop anchor 2>&1 | ForEach-Object { "    $_" }
$deadline = (Get-Date).AddSeconds(10)
while ((Get-PortOwners).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 400 }
& $Nssm start anchor 2>&1 | ForEach-Object { "    $_" }
$deadline = (Get-Date).AddSeconds(20)
while ((Get-PortOwners).Count -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
if ((Get-PortOwners).Count -eq 0) {
  Write-Host "[FAIL] Service did not bind $Port within 20s." -ForegroundColor Red
  Write-Host "RESULT: RESTART FAILED" -ForegroundColor Red; exit 1
}
Write-Host ("[ok] anchor is listening on {0} (PID {1})." -f $Port, ((Get-PortOwners) -join ',')) -ForegroundColor Green

# 3. Verify the service is serving.
Write-Host "`n==> 3/3 Verifying the dashboard is live" -ForegroundColor Cyan
$AuthHeaders = @{}
if ($env:ANCHOR_TOKEN) { $AuthHeaders['Authorization'] = "Bearer $($env:ANCHOR_TOKEN)" }
$uiOk = $false
for ($i = 0; $i -lt 12; $i++) {
  try {
    $h = (Invoke-WebRequest "$Base/" -Headers $AuthHeaders -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop).Content
    if ($h.Contains("showView('rnd')") -and $h.Contains('New Project')) { $uiOk = $true; break }
  } catch { }
  Start-Sleep -Milliseconds 600
}
Write-Host ""
if ($uiOk) {
  Write-Host "RESULT: ANCHOR RESTARTED WARM  (parked tiles resume warm; hard-refresh browser Ctrl+Shift+R)" -ForegroundColor Green
  exit 0
} else {
  Write-Host "[FAIL] Dashboard did not return the expected markers." -ForegroundColor Red
  Write-Host "RESULT: RESTART FAILED" -ForegroundColor Red; exit 1
}
