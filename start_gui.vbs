' start_gui.vbs
' Запуск Personal AI GUI — без консоли, окно на переднем плане

Dim shell, py, src, cmd
Set shell = CreateObject("WScript.Shell")

src = "C:\Users\ACER\Desktop\cloude\my_personal_ai"
py  = "C:\Users\ACER\Desktop\cloude\bybit-bot\venv\Scripts\python.exe"

Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(py) Then
    MsgBox "Python not found:" & vbCrLf & py, 16, "Personal AI"
    WScript.Quit
End If

shell.Environment("PROCESS")("PYTHONPATH") = src & ";" & "C:\Users\ACER\Desktop\cloude\bybit-bot"
shell.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
shell.Environment("PROCESS")("PYTHONLEGACYWINDOWSSTDIO") = "0"

' 1 = нормальное окно (НЕ 0), True = не ждать
' pythonw скрывает консоль сам, но окно GUI выходит на передний план
cmd = """" & py & """ """ & src & "\launch.py"" --no-telegram"
shell.Run cmd, 1, False
