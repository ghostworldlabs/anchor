$file = "C:\dev\Anchor\lib\entanglement.mjs"
for ($i = 0; $i -lt 120; $i++) {
    if (Test-Path $file) {
        (Get-Item $file).LastWriteTime = (Get-Date)
    }
    Start-Sleep -Seconds 3
}
