#!/usr/bin/env pwsh
# go.ps1 -- launch Foreman's headless live engine rooted in a project.
#
# This is the canonical "run Foreman" entry point. It drives run-live.mjs, which
# spawns fresh-context `claude -p --permission-mode acceptEdits` sub-agents (so
# their file edits never prompt) while the orchestrator owns the ground-truth
# gate and all git. Reads git branch + budget from the project's
# foreman.config.json so you don't have to repeat them.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads a BOM-less .ps1 as
# the ANSI codepage, so a non-ASCII char (e.g. an em-dash) inside a string can be
# misdecoded into a smart-quote and break parsing.
#
#   powershell -File foreman\bin\go.ps1 -Project <path>
#   & <path>                  # uses the current directory
#   & <path> -Resume          # continue from the checkpoint
#
param(
  [string]$Project = (Get-Location).Path,
  [int]$Reviewers = 2,
  [int]$Cap = 0,          # 0 => take from foreman.config.json budget, else default 3
  [int]$MaxWaves = 0,     # 0 => take from foreman.config.json budget (unbounded if absent)
  [int]$MaxWallMin = 0,   # 0 => unbounded
  [switch]$Resume         # continue from the on-disk checkpoint (clears a halt once its blocker is resolved)
)
$ErrorActionPreference = 'Stop'

$proj = (Resolve-Path $Project).Path
$engine = Join-Path $PSScriptRoot 'run-live.mjs'
if (-not (Test-Path $engine)) { throw "engine not found: $engine" }

# Subscription usage requires NO ANTHROPIC_API_KEY in the child env (run-live.mjs
# header). Clear it for this launch so Foreman runs on the Pro/Max subscription,
# not metered API billing. Scoped to this process; your shell is unaffected.
$env:ANTHROPIC_API_KEY = $null

# MUST enable live agents to prevent 'live agent seam is disabled' halts
$env:CRUCIBLE_AGENT_LIVE = "1"

# Auto-detect host environment for robust driver selection
if ($env:ANTIGRAVITY_AGENT) {
  $env:TRIO_DRIVER = "gemini-cli"
}

$gitArgs = @()
$WorkBranch = $null
$cfgPath = Join-Path $proj 'foreman.config.json'
if (Test-Path $cfgPath) {
  $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
  if ($cfg.git -and $cfg.git.enabled) {
    $gitArgs += '--git'
    if ($cfg.git.branch) { $gitArgs += @('--branch', $cfg.git.branch); $WorkBranch = $cfg.git.branch }
  }
  if ($MaxWaves -le 0 -and $cfg.budget -and $cfg.budget.max_waves_per_run) {
    $MaxWaves = [int]$cfg.budget.max_waves_per_run
  }
  if ($Cap -le 0 -and $cfg.budget -and $cfg.budget.max_fix_iters_per_wave) {
    $Cap = [int]$cfg.budget.max_fix_iters_per_wave
  }
}
if ($Cap -le 0) { $Cap = 3 }

$cliArgs = @("`"$engine`"", "`"$proj`"", '--reviewers', $Reviewers, '--cap', $Cap) + $gitArgs
if ($MaxWaves -gt 0)   { $cliArgs += @('--max-waves', $MaxWaves) }
if ($MaxWallMin -gt 0) { $cliArgs += @('--max-wallclock-min', $MaxWallMin) }

# -Resume: continue from the checkpoint. If the checkpoint is HALTED, the engine refuses to
# auto-resume until the blocker is cleared. If the project defines a pre-registration gate
# (bin/preregistration.mjs), it must pass (human-committed thresholds) before the halt clears.
if ($Resume) {
  $preregModule = Join-Path $proj 'bin/preregistration.mjs'
  if (Test-Path $preregModule) {
    Write-Host "Resume: validating pre-registration (I6 no-gamed-gates) before clearing the halt..."
    & node $preregModule
    if ($LASTEXITCODE -ne 0) {
      Write-Host ""
      Write-Warning "REFUSING TO RESUME: pre-registration is still pending/invalid (exit $LASTEXITCODE)."
      Write-Host "Edit $proj\preregistration.json (replace every '__PREREGISTER__' with a real committed value; ranges in bin/preregistration.mjs), then re-run with -Resume."
      exit 1
    }
    Push-Location $proj
    try {
      if ($WorkBranch) {
        $cur = (git rev-parse --abbrev-ref HEAD)
        if ($cur -ne $WorkBranch) {
          Write-Host "Switching to work branch '$WorkBranch' (was '$cur')..."
          git checkout $WorkBranch
          if (-not $?) { Write-Error "Could not checkout '$WorkBranch'; resolve manually, then re-run -Resume."; exit 1 }
        }
      }
      $pendingPrereg = git status --porcelain -- preregistration.json
      if ($pendingPrereg) {
        git add -- preregistration.json
        git commit -m "wave 1: commit pre-registered thresholds (human attestation, I6 no-gamed-gates)"
        if ($?) { Write-Host "Committed the pre-registered thresholds (human attestation)." }
      } else {
        Write-Host "Pre-registration already committed; clearing the halt and resuming."
      }
    } finally { Pop-Location }
  }
  $cliArgs += @('--resume', '--clear-halt')
}

# cf-slick / journal 0027: do NOT use Start-Process -WindowStyle Hidden (parent can
# vanish and kill mid-await children). Stay in THIS process tree with Wait.
Write-Host "Foreman (headless, subscription) -> node $($cliArgs -join ' ')"
Write-Host "lifecycle: parent-owned node (no detached Hidden Start-Process)"
$argList = @()
foreach ($a in $cliArgs) { $argList += $a }
# -NoNewWindow keeps console shared; -Wait keeps Job lifetime with this shell
$proc = Start-Process -FilePath "node" -ArgumentList $argList -NoNewWindow -RedirectStandardOutput "_foreman-output.log" -RedirectStandardError "_foreman-error.log" -PassThru -Wait
$LASTEXITCODE = $proc.ExitCode
exit $LASTEXITCODE
