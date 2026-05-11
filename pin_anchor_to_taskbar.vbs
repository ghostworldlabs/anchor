' Pin Anchor Dashboard to Taskbar
' Run this: double-click pin_anchor_to_taskbar.vbs
' Deletes any old shortcut, clears icon cache, creates a fresh one.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
desktopPath = WshShell.SpecialFolders("Desktop")
iconPath = scriptDir & "\anchor.ico"
shortcutPath = desktopPath & "\Anchor.lnk"

' Also delete any older shortcut variants from earlier iterations
oldShortcut1 = desktopPath & "\Anchor Dashboard.lnk"
If fso.FileExists(oldShortcut1) Then fso.DeleteFile oldShortcut1, True

' Step 1: Delete old shortcut if it exists
If fso.FileExists(shortcutPath) Then
    fso.DeleteFile shortcutPath, True
    WScript.Sleep 500
End If

' Step 2: Clear Windows icon cache
localAppData = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
cacheDir = localAppData & "\Microsoft\Windows\Explorer"
If fso.FolderExists(cacheDir) Then
    For Each f In fso.GetFolder(cacheDir).Files
        If LCase(Left(f.Name, 9)) = "iconcache" Or LCase(Left(f.Name, 10)) = "thumbcache" Then
            On Error Resume Next
            f.Delete True
            On Error GoTo 0
        End If
    Next
End If

' Also clear the legacy cache file
legacyCache = localAppData & "\IconCache.db"
If fso.FileExists(legacyCache) Then
    On Error Resume Next
    fso.DeleteFile legacyCache, True
    On Error GoTo 0
End If

' Step 3: Find pythonw.exe
pythonExe = ""
Dim tryPaths(5)
tryPaths(0) = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\pythonw.exe"
tryPaths(1) = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe"
tryPaths(2) = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python311\pythonw.exe"
tryPaths(3) = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python310\pythonw.exe"
tryPaths(4) = "C:\Python312\pythonw.exe"
tryPaths(5) = "C:\Python311\pythonw.exe"

For Each p In tryPaths
    If fso.FileExists(p) Then
        pythonExe = p
        Exit For
    End If
Next

If pythonExe = "" Then
    Set exec = WshShell.Exec("cmd /c where pythonw.exe 2>nul")
    result = ""
    If Not exec.StdOut.AtEndOfStream Then
        result = Trim(exec.StdOut.ReadLine())
    End If
    If result <> "" Then pythonExe = result
End If

If pythonExe = "" Then
    MsgBox "Could not find pythonw.exe. Please install Python 3 first.", vbCritical, "Anchor Setup"
    WScript.Quit
End If

' Step 4: Create fresh shortcut with the new icon
Set shortcut = WshShell.CreateShortcut(shortcutPath)
shortcut.TargetPath = pythonExe
shortcut.Arguments = """" & scriptDir & "\launch_anchor.pyw"""
shortcut.WorkingDirectory = scriptDir
shortcut.Description = "Launch Anchor"
shortcut.WindowStyle = 7

If fso.FileExists(iconPath) Then
    shortcut.IconLocation = iconPath & ",0"
End If

shortcut.Save

' Step 5: Restart Explorer to flush icon cache
WshShell.Run "cmd /c taskkill /IM explorer.exe /F & start explorer.exe", 0, True
WScript.Sleep 2000

MsgBox "Done! 'Anchor' shortcut is on your Desktop with the new icon." & vbCrLf & vbCrLf & _
       "To pin to taskbar:" & vbCrLf & _
       "1. Double-click 'Anchor' on your Desktop" & vbCrLf & _
       "2. Right-click the anchor icon in the taskbar" & vbCrLf & _
       "3. Click 'Pin to taskbar'", vbInformation, "Anchor Setup"
