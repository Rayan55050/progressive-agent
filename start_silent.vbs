' Progressive Agent — Silent Starter
' Launches CLIProxyAPI + bot with no visible windows.
' Place a shortcut to this file in Windows Startup folder for auto-boot.

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

Dim projectDir, proxyDir, pythonExe, logFile
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
proxyDir   = projectDir & "\CLIProxyAPI"
pythonExe  = "python"  ' Uses system Python from PATH. Change if needed.
logFile    = projectDir & "\data\bot_startup.log"

' Ensure data directory exists
If Not fso.FolderExists(projectDir & "\data") Then
    fso.CreateFolder(projectDir & "\data")
End If

' Log helper
Sub WriteLog(msg)
    Dim f
    Set f = fso.OpenTextFile(logFile, 8, True)
    f.WriteLine Now & " | " & msg
    f.Close
End Sub

' ---------- 1. Start CLIProxyAPI (if not already running) ----------
Dim isProxyRunning
isProxyRunning = False
Set objWMI = GetObject("winmgmts:\\.\root\cimv2")
Set procs = objWMI.ExecQuery("SELECT Name FROM Win32_Process WHERE Name='cli-proxy-api.exe'")
If procs.Count > 0 Then
    isProxyRunning = True
End If

If Not isProxyRunning Then
    WshShell.CurrentDirectory = proxyDir
    WshShell.Run """" & proxyDir & "\cli-proxy-api.exe""", 0, False
    WriteLog "CLIProxyAPI started"
    ' Wait for proxy to initialize
    WScript.Sleep 5000
Else
    WriteLog "CLIProxyAPI already running, skipping"
End If

' ---------- 2. Start Progressive Agent bot (if not already running) ----------
Dim isBotRunning
isBotRunning = False
Set procs2 = objWMI.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='python.exe'")
For Each p In procs2
    If InStr(LCase(p.CommandLine), "src.main") > 0 Or InStr(LCase(p.CommandLine), "src.watchdog") > 0 Then
        isBotRunning = True
        Exit For
    End If
Next

If Not isBotRunning Then
    WshShell.CurrentDirectory = projectDir
    WshShell.Run """" & pythonExe & """ -m src.watchdog", 0, False
    WriteLog "Progressive Agent bot started (via watchdog)"
Else
    WriteLog "Bot already running, skipping"
End If

WriteLog "Startup sequence complete"
