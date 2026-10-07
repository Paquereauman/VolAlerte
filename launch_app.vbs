Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")

' Répertoire racine du script
strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Recherche de pythonw.exe dans le venv local ou global
strVenvPythonw = strScriptDir & "\venv\Scripts\pythonw.exe"
strStartServer = strScriptDir & "\start_server.py"

If objFSO.FileExists(strVenvPythonw) Then
    strPythonw = strVenvPythonw
Else
    strPythonw = "pythonw.exe"
End If

' Démarrage du serveur uvicorn en arrière-plan sans aucune fenêtre noire (0 = masqué)
objShell.Run """" & strPythonw & """ """ & strStartServer & """", 0, False

' Attente que le serveur démarre
WScript.Sleep 1500

' Ouverture dans une fenêtre d'application autonome (Edge ou Chrome en mode --app)
strAppUrl = "http://localhost:8765"
strEdge = objShell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")
If Not objFSO.FileExists(strEdge) Then
    strEdge = objShell.ExpandEnvironmentStrings("%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")
End If

strChrome = objShell.ExpandEnvironmentStrings("%ProgramFiles%\Google\Chrome\Application\chrome.exe")
If Not objFSO.FileExists(strChrome) Then
    strChrome = objShell.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe")
End If

If objFSO.FileExists(strEdge) Then
    objShell.Run """" & strEdge & """ --app=" & strAppUrl, 1, False
ElseIf objFSO.FileExists(strChrome) Then
    objShell.Run """" & strChrome & """ --app=" & strAppUrl, 1, False
Else
    objShell.Run strAppUrl, 1, False
End If
