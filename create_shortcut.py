# -*- coding: utf-8 -*-
"""
create_shortcut.py — Создаёт/обновляет ярлык Personal AI на рабочем столе.
Запусти один раз: python create_shortcut.py
"""
import os
import sys
from pathlib import Path

DESKTOP = Path.home() / "Desktop"
BAT_FILE = Path(__file__).parent / "run_personal_ai.bat"
SHORTCUT_PATH = DESKTOP / "Personal AI.lnk"
OLD_SHORTCUT  = DESKTOP / "Bybit Trading Bot.lnk"

def create_via_win32():
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    lnk = shell.CreateShortcut(str(SHORTCUT_PATH))
    lnk.TargetPath     = str(BAT_FILE)
    lnk.WorkingDirectory = str(BAT_FILE.parent)
    lnk.Description    = "Personal AI — Автономный ИИ-Агент"
    lnk.WindowStyle    = 1  # Normal window
    # Иконку ищем рядом
    ico = BAT_FILE.parent / "assets" / "icon.ico"
    if ico.exists():
        lnk.IconLocation = str(ico)
    lnk.save()
    print(f"[OK] Ярлык создан: {SHORTCUT_PATH}")

def create_via_powershell():
    import subprocess
    ico_part = ""
    ico = BAT_FILE.parent / "assets" / "icon.ico"
    if ico.exists():
        ico_part = f'$s.IconLocation = "{ico}";'

    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{SHORTCUT_PATH}')
$s.TargetPath      = '{BAT_FILE}'
$s.WorkingDirectory = '{BAT_FILE.parent}'
$s.Description     = 'Personal AI — Автономный ИИ-Агент'
$s.WindowStyle     = 1
{ico_part}
$s.Save()
Write-Host '[OK] Shortcut saved'
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[OK] Ярлык создан: {SHORTCUT_PATH}")
    else:
        print(f"[!] PowerShell error: {result.stderr}")

def update_old_shortcut():
    """Перенаправить старый ярлык 'Bybit Trading Bot' на новый бат-файл."""
    if not OLD_SHORTCUT.exists():
        return
    try:
        import subprocess
        ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{OLD_SHORTCUT}')
$s.TargetPath      = '{BAT_FILE}'
$s.WorkingDirectory = '{BAT_FILE.parent}'
$s.Description     = 'Personal AI — Автономный ИИ-Агент'
$s.WindowStyle     = 1
$s.Save()
Write-Host '[OK] Old shortcut updated'
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"[OK] Старый ярлык обновлён: {OLD_SHORTCUT}")
        else:
            print(f"[!] Не удалось обновить старый ярлык: {result.stderr}")
    except Exception as e:
        print(f"[!] update_old_shortcut: {e}")


if __name__ == "__main__":
    print("Создаю ярлык Personal AI на рабочем столе...\n")

    # Новый ярлык
    try:
        create_via_win32()
    except ImportError:
        create_via_powershell()
    except Exception as e:
        print(f"[!] win32 failed ({e}), пробуем PowerShell...")
        create_via_powershell()

    # Обновляем старый
    update_old_shortcut()

    print("\nГотово! Теперь нажми дважды на 'Personal AI' (или 'Bybit Trading Bot') на рабочем столе.")
