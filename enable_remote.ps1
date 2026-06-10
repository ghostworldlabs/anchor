# enable_remote.ps1
# Flip the Anchor R&D control surface to REMOTE (Tailscale) access in one run -
# or revert with -Off. Sets ANCHOR_TOKEN (shared secret) + ANCHOR_BIND (Tailscale
# IP) in the NSSM service env, adds a Tailscale start-dependency, and restarts the
# service (which also loads any new on-disk code).
#
# Run ELEVATED (Administrator). Idempotent. Preserves the existing service env
# (PATH/USERPROFILE/HOME from setup_service_as_john.ps1).
#
#   .\enable_remote.ps1                 # enable; reuse existing token or mint one
#   .\enable_remote.ps1 -Token <tok>    # enable with a specific token
#   .\enable_remote.ps1 -Bind 0.0.0.0   # bind all interfaces instead of tailnet-only
#   .\enable_remote.ps1 -Off            # revert to local-only (loopback, auth off)
#
# SECURITY: the server REFUSES to bind a non-loopback address unless ANCHOR_TOKEN
# is set (enforced in anchor_gui.resolve_bind_host). Mutating endpoints require the
# token; GET endpoints stay open (read-only) to any device that can reach the port.

#requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$Token = "",
    [string]$Bind  = "",
    [switch]$Off
)
$ErrorActionPreference = 'Stop'
$Svc = 'anchor'

# --- locate the nssm that manages the service (install used C:\Tools\nssm) ---
$nssm = if (Test-Path 'C:\Tools\nssm\nssm.exe') { 'C:\Tools\nssm\nssm.exe' }
        else { (Get-Command nssm -ErrorAction Stop).Source }
Write-Host "Using nssm: $nssm" -ForegroundColor DarkGray

# --- read the current AppEnvironmentExtra into an ordered map (preserve it) ---
function Get-ExtraEnv {
    $raw = & $nssm get $Svc AppEnvironmentExtra 2>$null
    $map = [ordered]@{}
    foreach ($line in @($raw)) {
        $line = "$line".Trim()
        if (-not $line) { continue }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { continue }
        $map[$line.Substring(0, $i)] = $line.Substring($i + 1)
    }
    return $map
}
function Set-ExtraEnv($map) {
    $pairs = @()
    foreach ($k in $map.Keys) { $pairs += ("{0}={1}" -f $k, $map[$k]) }
    & $nssm set $Svc AppEnvironmentExtra @pairs | Out-Null
}

$env = Get-ExtraEnv
Write-Host "`n=== current service env keys ===" -ForegroundColor Cyan
($env.Keys -join ', ')

if ($Off) {
    # ---- REVERT to local-only ----
    Write-Host "`nReverting to LOCAL-ONLY (loopback, auth disabled)..." -ForegroundColor Yellow
    $env.Remove('ANCHOR_BIND')   | Out-Null
    $env.Remove('ANCHOR_TOKEN')  | Out-Null
    Set-ExtraEnv $env
    # Drop the Tailscale dependency (set to empty clears it).
    & $nssm set $Svc DependOnService "" | Out-Null
    $bindMsg = "127.0.0.1 (localhost only)"
    $tokenToShow = $null
} else {
    # ---- ENABLE remote ----
    # Bind target: explicit -Bind, else the host's Tailscale IPv4, else known IP.
    if (-not $Bind) {
        try { $Bind = (tailscale ip -4 2>$null | Select-Object -First 1).Trim() } catch {}
        if (-not $Bind) { $Bind = '100.69.215.4' }
    }
    # Token: explicit -Token, else reuse the existing one, else mint a strong one.
    if ($Token) {
        $tok = $Token
    } elseif ($env['ANCHOR_TOKEN']) {
        $tok = $env['ANCHOR_TOKEN']
        Write-Host "Reusing the existing ANCHOR_TOKEN (already configured)." -ForegroundColor DarkGray
    } else {
        $bytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $tok = ([Convert]::ToBase64String($bytes) -replace '[+/=]', '')
    }

    $env['ANCHOR_TOKEN'] = $tok
    $env['ANCHOR_BIND']  = $Bind
    Set-ExtraEnv $env

    # Start after Tailscale so the interface is assignable (server also bind-retries).
    $ts = Get-Service -Name 'Tailscale' -ErrorAction SilentlyContinue
    if ($ts) { & $nssm set $Svc DependOnService Tailscale | Out-Null }
    else { Write-Host "WARNING: no 'Tailscale' service found - skipping start-dependency." -ForegroundColor Yellow }

    $bindMsg = "${Bind}:8777 (tailnet)"
    $tokenToShow = $tok
}

# --- restart under the new config (also loads any new on-disk code) ---
Write-Host "`nRestarting $Svc ..." -ForegroundColor Cyan
& $nssm restart $Svc | Out-Null
Start-Sleep -Seconds 4

# --- verify ---
Write-Host "`n=== AFTER ===" -ForegroundColor Cyan
$after = Get-CimInstance Win32_Service -Filter "Name='$Svc'"
Write-Host ("State    : {0}" -f $after.State)
Write-Host ("Bind     : {0}" -f $bindMsg)
$listen = Get-NetTCPConnection -State Listen -LocalPort 8777 -ErrorAction SilentlyContinue
if ($listen) {
    $listen | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
} else {
    Write-Host "WARNING: nothing listening on 8777 yet - give it a few seconds, then re-check." -ForegroundColor Red
}

if ($tokenToShow) {
    Write-Host "`n================  ACCESS TOKEN (store securely)  ================" -ForegroundColor Green
    Write-Host "  $tokenToShow"
    Write-Host "=================================================================" -ForegroundColor Green
    Write-Host "Open the dashboard at  http://${Bind}:8777  (localhost will NOT" -ForegroundColor Cyan
    Write-Host "respond - the server is bound to the Tailscale interface). In the" -ForegroundColor Cyan
    Write-Host "browser console (or on the first 401) run setAnchorToken() and paste" -ForegroundColor Cyan
    Write-Host "the token above so mutating actions are authorized." -ForegroundColor Cyan
} else {
    Write-Host "`nRemote DISABLED. Dashboard is local-only again at http://localhost:8777" -ForegroundColor Cyan
}
