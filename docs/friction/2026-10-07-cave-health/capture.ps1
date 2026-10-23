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
    if ($captureHwnd -eq [IntPtr]::Zero) { throw 'The existing Anchor desktop window was not found in this interactive session.' }
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
    @{at=[DateTime]::UtcNow.ToString('o'); session=[System.Diagnostics.Process]::GetCurrentProcess().SessionId; width=$captureWidth; height=$captureHeight; print_window=$capturePrinted; elements=$captureNames} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $captureOut 'existing-client.json') -Encoding UTF8
} catch {
    @{at=[DateTime]::UtcNow.ToString('o'); error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $captureOut 'existing-client.json') -Encoding UTF8
}
