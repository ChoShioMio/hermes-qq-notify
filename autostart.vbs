' Start relative to this file. Do not copy this file into the Startup folder;
' use manage_autostart.py install to create a launcher targeting this directory.
Set fs = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
py = fs.BuildPath(root, ".venv\Scripts\pythonw.exe")
supervisor = fs.BuildPath(root, "supervisor.py")
If Not fs.FileExists(py) Then WScript.Quit 2
sh.CurrentDirectory = root
sh.Run Chr(34) & py & Chr(34) & " " & Chr(34) & supervisor & Chr(34), 0, False
