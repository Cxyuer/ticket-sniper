#!/usr/bin/env python3
"""提醒：系统通知 + 模态弹窗 + 语音 + 提示音

三个平台各一套实现，对外只有 notify() 一个入口：
    macOS    osascript / say / afplay
    Windows  PowerShell 通知 / SAPI 语音 / winsound
    Linux    notify-send / espeak（有就用，没有就只响）

都不依赖网页渲染，锁屏也会响，所以它是最可靠的兜底通道。
Windows 启动 PowerShell 要几百毫秒，所以通知一律后台起，不阻塞监控循环。
"""

import base64
import os
import shutil
import subprocess
import sys

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
APP_ID = "Ticket Sniper"      # Windows 通知来源名，会显示在横幅上

# 中文不能直接塞进 powershell -Command（命令行按系统代码页解析，会乱码），
# 所以统一用 -EncodedCommand 传 UTF-16LE 的 base64。
_TOAST = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
         [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $xml.GetElementsByTagName('text')
$t.Item(0).AppendChild($xml.CreateTextNode('{title}')) > $null
$t.Item(1).AppendChild($xml.CreateTextNode('{msg}')) > $null
$n = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}').Show($n)
"""

_POPUP = """
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show('{msg}', '{title}') | Out-Null
"""

_SPEAK = "(New-Object -ComObject SAPI.SpVoice).Speak('{text}')"


def _spawn(argv):
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ps(script):
    """后台跑一段 PowerShell"""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    _spawn(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc])


def _q(text):
    """PowerShell 单引号字符串转义：' → ''"""
    return str(text).replace("'", "''")


def _mac(title, msg, speak, popup):
    _spawn(["osascript", "-e",
            f'display notification "{msg}" with title "{title}" sound name "Glass"'])
    if popup:
        _spawn(["osascript", "-e",
                f'display alert "{title}" message "{msg}" buttons {{"知道了"}} '
                'default button 1 giving up after 120'])
    if speak:
        _spawn(["say", "-r", "215", speak])


def _win(title, msg, speak, popup):
    _ps(_TOAST.format(title=_q(title), msg=_q(msg), app=_q(APP_ID)))
    if popup:
        _ps(_POPUP.format(title=_q(title), msg=_q(msg)))
    if speak:
        _ps(_SPEAK.format(text=_q(speak)))


def _linux(title, msg, speak, popup):
    if shutil.which("notify-send"):
        _spawn(["notify-send", title, msg])
    if speak:
        for cmd in ("spd-say", "espeak"):
            if shutil.which(cmd):
                _spawn([cmd, speak])
                break


def _beep():
    if IS_WIN:
        try:
            import winsound
        except ImportError:
            return
        for _ in range(3):
            try:
                winsound.MessageBeep()
            except Exception:
                break
        return

    for _ in range(3):
        try:
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"],
                           capture_output=True)
        except Exception:
            break


def notify(title, msg, speak=None, popup=True):
    """title/msg: 通知文本；speak: 要念出来的话；popup: 是否弹模态窗"""
    sys.stdout.write("\a")
    sys.stdout.flush()

    try:
        if IS_MAC:
            _mac(title, msg, speak, popup)
        elif IS_WIN:
            _win(title, msg, speak, popup)
        else:
            _linux(title, msg, speak, popup)
    except Exception:
        pass

    _beep()
