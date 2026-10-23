$ErrorActionPreference = 'Stop'
$captureOut = $PSScriptRoot
try {
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class CaveHealthCapture {
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
    [void][CaveHealthCapture]::SetProcessDPIAware()
    $captureHwnd = [CaveHealthCapture]::FindWindow([NullString]::Value, 'Anchor')
    $captureCandidates = @()
    if ($captureHwnd -eq [IntPtr]::Zero) {
        $captureTopWindows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
        for ($captureTopIndex = 0; $captureTopIndex -lt $captureTopWindows.Count; $captureTopIndex++) {
            $captureTop = $captureTopWindows.Item($captureTopIndex).Current
            if ($captureTop.Name -match 'Anchor|Cave of Wonders') {
                $captureCandidates += [pscustomobject]@{name=$captureTop.Name; process_id=$captureTop.ProcessId; handle=$captureTop.NativeWindowHandle}
            }
        }
        if ($captureCandidates.Count -eq 1) { $captureHwnd = [IntPtr]$captureCandidates[0].handle }
    }
    if ($captureHwnd -eq [IntPtr]::Zero) { throw ('No unambiguous existing Anchor or Cave window was found in this interactive session; matching windows: ' + $captureCandidates.Count) }
    $captureRect = New-Object CaveHealthCapture+RECT
    [void][CaveHealthCapture]::GetWindowRect($captureHwnd, [ref]$captureRect)
    $captureWidth = $captureRect.R - $captureRect.L
    $captureHeight = $captureRect.B - $captureRect.T
    $captureBitmap = New-Object System.Drawing.Bitmap $captureWidth, $captureHeight
    $captureGraphics = [System.Drawing.Graphics]::FromImage($captureBitmap)
    $captureDc = $captureGraphics.GetHdc()
    $capturePrinted = [CaveHealthCapture]::PrintWindow($captureHwnd, $captureDc, 2)
    $captureGraphics.ReleaseHdc($captureDc)
    $captureGraphics.Dispose()
    $captureBitmap.Save((Join-Path $captureOut 'existing-anchor.png'), [System.Drawing.Imaging.ImageFormat]::Png)
    $captureBitmap.Dispose()
    $captureWindow = [System.Windows.Automation.AutomationElement]::FromHandle($captureHwnd)
    $captureElements = $captureWindow.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $captureNames = for ($captureIndex = 0; $captureIndex -lt $captureElements.Count; $captureIndex++) {
        $captureCurrent = $captureElements.Item($captureIndex).Current
        if ($captureCurrent.Name -match 'Health check|Anchor Doctor|Cave of Wonders|Warnings') {
            [pscustomobject]@{name=$captureCurrent.Name.Substring(0, [Math]::Min(500, $captureCurrent.Name.Length)); type=$captureCurrent.ControlType.ProgrammaticName; offscreen=$captureCurrent.IsOffscreen}
        }
    }
    @{at=[DateTime]::UtcNow.ToString('o'); session=[System.Diagnostics.Process]::GetCurrentProcess().SessionId; window_name=$captureWindow.Current.Name; process_id=$captureWindow.Current.ProcessId; width=$captureWidth; height=$captureHeight; print_window=$capturePrinted; candidates=$captureCandidates; elements=$captureNames} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $captureOut 'existing-client.json') -Encoding UTF8
} catch {
    @{at=[DateTime]::UtcNow.ToString('o'); session=[System.Diagnostics.Process]::GetCurrentProcess().SessionId; error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $captureOut 'existing-client.json') -Encoding UTF8
}
