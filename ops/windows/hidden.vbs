' Starts a PowerShell script with no window at all. Task Scheduler's "powershell.exe -WindowStyle Hidden" still opens
' a console for a moment and takes the focus (the owner saw a blue window every 15 minutes, 2 Nov 2026); wscript
' starts it hidden from the first instant. Usage: wscript.exe hidden.vbs C:\AI\ops\script.ps1 [args...]
' The script's exit code is this launcher's, so Task Scheduler's "Last Run Result" stays true.
Set a = WScript.Arguments
If a.Count < 1 Then WScript.Quit 2
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & a(0) & """"
For i = 1 To a.Count - 1
  cmd = cmd & " """ & a(i) & """"
Next
WScript.Quit CreateObject("WScript.Shell").Run(cmd, 0, True)
