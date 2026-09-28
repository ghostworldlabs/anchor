<#
.SYNOPSIS
  Rotate Anchor's service token (run ELEVATED).

.DESCRIPTION
  Anchor's API is guarded by one shared secret, ANCHOR_TOKEN, held in the NSSM service's environment
  (HKLM:\SYSTEM\CurrentControlSet\Services\anchor\Parameters, AppEnvironmentExtra). Every browser and device that
  talks to Anchor presents it. Rotating = minting a fresh random token, writing it into the service environment
  (every other pair preserved), restarting the service, and putting the NEW token on your clipboard so each
  browser can be given it once when the page asks. The token is never printed to the console or a log.

.PARAMETER Svc
  The service name (default: anchor).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\tools\rotate_token.ps1
#>
param([string]$Svc = 'anchor')

$ErrorActionPreference = 'Stop'
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Run this from an ELEVATED PowerShell (the service environment is under HKLM)." -ForegroundColor Yellow
    exit 2
}
$nssm = if (Test-Path 'C:\Tools\nssm\nssm.exe') { 'C:\Tools\nssm\nssm.exe' } else { (Get-Command nssm -ErrorAction Stop).Source }

# the current pairs, read from the registry (a clean String[]), never `nssm get` (UTF-16 mis-decodes)
$key = "HKLM:\SYSTEM\CurrentControlSet\Services\$Svc\Parameters"
$val = (Get-ItemProperty -Path $key -Name AppEnvironmentExtra -ErrorAction SilentlyContinue).AppEnvironmentExtra
$map = [ordered]@{}
foreach ($line in @($val)) {
    $line = "$line".Trim(); if (-not $line) { continue }
    $i = $line.IndexOf('='); if ($i -lt 1) { continue }
    $map[$line.Substring(0, $i)] = $line.Substring($i + 1)
}
if (-not $map.Contains('ANCHOR_TOKEN')) {
    Write-Host "No ANCHOR_TOKEN is set on the $Svc service (auth is off); nothing to rotate." -ForegroundColor Yellow
    exit 1
}

# a fresh token: 32 random bytes, url-safe base64, no padding
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$new = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
$map['ANCHOR_TOKEN'] = $new

$pairs = @(); foreach ($k in $map.Keys) { $pairs += ("{0}={1}" -f $k, $map[$k]) }
& $nssm set $Svc AppEnvironmentExtra @pairs | Out-Null
Set-Clipboard -Value $new
& $nssm restart $Svc | Out-Null
Start-Sleep -Seconds 3
$up = try { (Invoke-RestMethod -Uri 'http://127.0.0.1:8777/api/version' -TimeoutSec 20).version } catch { $null }
Write-Host ""
Write-Host "Rotated. The new token is on your CLIPBOARD (never printed here)." -ForegroundColor Green
Write-Host "Each browser and device will ask for it once: paste it when the page asks. Service: $(if ($up) { "up, build $up" } else { 'restarting' })."
Write-Host "Old links that carried ?token= are dead now; use the pages' own token prompt."
