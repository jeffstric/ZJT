Option Explicit

Dim objShell, objFSO, objDesktop
Dim strScriptDir, strDesktopPath, strShortcutPath
Dim objShortcut

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strDesktopPath = objShell.SpecialFolders("Desktop")

strShortcutPath = strDesktopPath & "\ComfyUI Server Start.lnk"
Set objShortcut = objShell.CreateShortcut(strShortcutPath)
objShortcut.TargetPath = strScriptDir & "\start.bat"
objShortcut.WorkingDirectory = strScriptDir
objShortcut.Description = "Start ComfyUI Server"
objShortcut.IconLocation = "shell32.dll,137"
objShortcut.Save

strShortcutPath = strDesktopPath & "\ComfyUI Server Start (Silent).lnk"
Set objShortcut = objShell.CreateShortcut(strShortcutPath)
objShortcut.TargetPath = strScriptDir & "\start_silent.vbs"
objShortcut.WorkingDirectory = strScriptDir
objShortcut.Description = "Start ComfyUI Server (Silent Mode)"
objShortcut.IconLocation = "shell32.dll,137"
objShortcut.Save

strShortcutPath = strDesktopPath & "\ComfyUI Server Stop.lnk"
Set objShortcut = objShell.CreateShortcut(strShortcutPath)
objShortcut.TargetPath = strScriptDir & "\stop.bat"
objShortcut.WorkingDirectory = strScriptDir
objShortcut.Description = "Stop ComfyUI Server"
objShortcut.IconLocation = "shell32.dll,132"
objShortcut.Save

MsgBox "Desktop shortcuts created successfully!" & vbCrLf & vbCrLf & _
       "Created shortcuts:" & vbCrLf & _
       "1. ComfyUI Server Start" & vbCrLf & _
       "2. ComfyUI Server Start (Silent)" & vbCrLf & _
       "3. ComfyUI Server Stop" & vbCrLf & vbCrLf & _
       "Please check your desktop.", vbInformation, "ComfyUI Server"

Set objShortcut = Nothing
Set objFSO = Nothing
Set objShell = Nothing

WScript.Quit 0
