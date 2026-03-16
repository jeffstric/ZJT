Option Explicit

Dim objShell, objFSO, strScriptDir, strBatFile
Dim intReturn

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
' start.bat 在根目录，不在 scripts/tools 目录
strBatFile = strScriptDir & "\..\..\start.bat"

If Not objFSO.FileExists(strBatFile) Then
    MsgBox "Error: start.bat not found" & vbCrLf & vbCrLf & _
           "Path: " & strBatFile, vbCritical, "ComfyUI Server"
    WScript.Quit 1
End If

' 使用 ChrW 函数显示中文，避免编码问题
' 智剧通 = ChrW(26234) & ChrW(21095) & ChrW(36890)
Dim strTitle, strMsg
strTitle = ChrW(26234) & ChrW(21095) & ChrW(36890)
strMsg = strTitle & " " & ChrW(27491) & ChrW(22312) & ChrW(21551) & ChrW(21160) & ChrW(65292) & _
         ChrW(31245) & ChrW(21518) & ChrW(20250) & ChrW(33258) & ChrW(21160) & ChrW(25171) & ChrW(24320) & _
         ChrW(27983) & ChrW(35272) & ChrW(22120) & ChrW(36827) & ChrW(20837) & vbCrLf & vbCrLf & _
         "http://localhost:9003"
MsgBox strMsg, vbInformation, strTitle

intReturn = objShell.Run("""" & strBatFile & """", 0, False)

Set objFSO = Nothing
Set objShell = Nothing

WScript.Quit 0
