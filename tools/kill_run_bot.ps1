# Завершить все python.exe / pythonw.exe, в командной строке которых есть run_bot.py
$names = @('python.exe', 'pythonw.exe')
foreach ($name in $names) {
    Get-CimInstance Win32_Process -Filter "Name = '$name'" -ErrorAction SilentlyContinue | ForEach-Object {
        $cl = $_.CommandLine
        if ($null -ne $cl -and $cl -match 'run_bot') {
            Write-Host "Killing PID $($_.ProcessId): $cl"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "Done."
