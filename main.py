import os
import sys
import socket
import threading
import ctypes
import time
import json
from pathlib import Path

import requests
import keyboard
import pystray
import tkinter as tk

from tkinter import ttk, messagebox
from PIL import Image
from ctypes import wintypes


# --------------------------------------------------
# APPLICATION SETTINGS
# --------------------------------------------------

APP_NAME = "Kothaify"
API_URL = "https://inputtools.google.com/request"

VK_SPACE = 0x20
VK_BACK = 0x08
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_B = 0x42
VK_A = 0x41
VK_M = 0x4D
VK_Z = 0x5A

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

WH_KEYBOARD_LL = 13
LLKHF_INJECTED = 0x10

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Find bundled resources both when running Python and when frozen as EXE.
def resource_path(filename):
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, filename)


ICON_PATH = resource_path("icon.ico")

# Keep user settings beside the executable when packaged.
if getattr(sys, "frozen", False):
    CONFIG_FILE = Path(sys.executable).resolve().parent / "bangla_phonetic_settings.json"
else:
    CONFIG_FILE = Path(__file__).resolve().parent / "bangla_phonetic_settings.json"


# --------------------------------------------------
# WINDOWS API
# --------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t

user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.c_void_p

user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]

user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = wintypes.BOOL

user32.SendInput.argtypes = [
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_int,
]
user32.SendInput.restype = wintypes.UINT

kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]


INPUT_KEYBOARD = 1

DIGIT_TABLE = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
PUNCTUATION = set("?!.,;:")

HOTKEY_OPTIONS = {
    "Ctrl+Shift+B": (VK_B, VK_CONTROL, VK_SHIFT),
    "Ctrl+Shift+M": (VK_M, VK_CONTROL, VK_SHIFT),
    "Ctrl+Alt+B": (VK_B, VK_CONTROL, VK_MENU),
    "Ctrl+Alt+M": (VK_M, VK_CONTROL, VK_MENU),
}


# --------------------------------------------------
# GLOBAL STATE
# --------------------------------------------------

enabled = True
busy = False
typed = ""
hotkey_latched = False
hook_handle = None
hook_thread_id = None

lock = threading.RLock()
config_lock = threading.RLock()
http = requests.Session()

shutdown_event = threading.Event()
hook_ready = threading.Event()

root = None
tray_icon = None
status_var = None
hotkey_var = None

app_container = None
internet_label = None
internet_connected = None

selected_hotkey = "Ctrl+Shift+B"


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

def load_settings():
    global selected_hotkey

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            settings = json.load(file)

        saved_hotkey = settings.get("hotkey")

        if saved_hotkey in HOTKEY_OPTIONS:
            selected_hotkey = saved_hotkey

    except (OSError, json.JSONDecodeError, TypeError):
        pass


def save_settings():
    with config_lock:
        with CONFIG_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                {"hotkey": selected_hotkey},
                file,
                ensure_ascii=False,
                indent=2,
            )


# --------------------------------------------------
# BANGLA CONVERSION
# --------------------------------------------------

def to_bengali_digits(text):
    return text.translate(DIGIT_TABLE)


def transliterate(word):
    params = {
        "text": word,
        "itc": "bn-t-i0-und",
        "num": 1,
        "cp": 0,
        "cs": 1,
        "ie": "utf-8",
        "oe": "utf-8",
        "app": "demopage",
    }

    response = http.get(API_URL, params=params, timeout=3)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list) and len(data) > 1 and data[0] == "SUCCESS":
        try:
            result = data[1][0][1][0]
            if isinstance(result, str) and result:
                return result
        except (IndexError, TypeError):
            pass

    return None


def send_unicode_text(text):
    """Type Unicode directly without modifying the clipboard."""
    for character in text:
        encoded = character.encode("utf-16-le")

        for index in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[index:index + 2], "little")

            down = INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(
                    wVk=0,
                    wScan=unit,
                    dwFlags=KEYEVENTF_UNICODE,
                    time=0,
                    dwExtraInfo=0,
                ),
            )

            up = INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(
                    wVk=0,
                    wScan=unit,
                    dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=0,
                ),
            )

            user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
            user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


def split_trailing_punctuation(text):
    index = len(text)

    while index > 0 and text[index - 1] in PUNCTUATION:
        index -= 1

    return text[:index], text[index:]


def replace_word(word, target_window):
    global busy

    try:
        core, punctuation = split_trailing_punctuation(word)
        converted = None

        if core:
            try:
                converted = transliterate(core)
            except Exception as exc:
                print("Online conversion failed:", exc)

        replacement = converted if converted else core
        replacement = to_bengali_digits(replacement)
        replacement += punctuation

        if shutdown_event.is_set():
            return

        if user32.GetForegroundWindow() != target_window:
            return

        for _ in word:
            keyboard.press_and_release("backspace")

        send_unicode_text(replacement + " ")

    except Exception as exc:
        print("Replacement error:", exc)

    finally:
        with lock:
            busy = False


def is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# --------------------------------------------------
# KEYBOARD HOOK
# --------------------------------------------------

def keyboard_callback(n_code, w_param, l_param):
    global busy, typed, hotkey_latched

    if n_code < 0 or shutdown_event.is_set():
        return user32.CallNextHookEx(
            hook_handle, n_code, w_param, l_param
        )

    event = ctypes.cast(
        l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)
    ).contents

    if event.flags & LLKHF_INJECTED:
        return user32.CallNextHookEx(
            hook_handle, n_code, w_param, l_param
        )

    vk = event.vkCode
    down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
    up = w_param in (WM_KEYUP, WM_SYSKEYUP)

    with config_lock:
        shortcut = selected_hotkey

    hotkey_vk, modifier1, modifier2 = HOTKEY_OPTIONS[shortcut]

    if (
        vk == hotkey_vk
        and down
        and is_down(modifier1)
        and is_down(modifier2)
    ):
        if not hotkey_latched:
            hotkey_latched = True
            toggle_app()

        return 1

    if vk == hotkey_vk and up and hotkey_latched:
        hotkey_latched = False
        return 1

    with lock:
        if busy:
            return 1

        if not enabled:
            typed = ""
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if not down:
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if is_down(VK_CONTROL) or is_down(VK_MENU):
            typed = ""
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if VK_A <= vk <= VK_Z:
            typed += chr(vk + 32)
            typed = typed[-80:]
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if 0x30 <= vk <= 0x39:
            typed += chr(vk)
            typed = typed[-80:]
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if 0x60 <= vk <= 0x69:
            typed += str(vk - 0x60)
            typed = typed[-80:]
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if vk == VK_BACK:
            typed = typed[:-1]
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if vk in (0xBF, 0xBE, 0xBC, 0xBA, 0x31, 0x32):
            if vk == 0xBF:
                typed += "?" if is_down(VK_SHIFT) else "/"
            elif vk == 0xBE:
                typed += ">" if is_down(VK_SHIFT) else "."
            elif vk == 0xBC:
                typed += "<" if is_down(VK_SHIFT) else ","
            elif vk == 0xBA:
                typed += ":" if is_down(VK_SHIFT) else ";"
            elif vk == 0x31 and is_down(VK_SHIFT):
                typed += "!"
            elif vk == 0x32 and is_down(VK_SHIFT):
                typed += "@"

            typed = typed[-80:]
            return user32.CallNextHookEx(
                hook_handle, n_code, w_param, l_param
            )

        if vk == VK_SPACE and typed:
            word = typed
            typed = ""
            busy = True
            target_window = user32.GetForegroundWindow()

            threading.Thread(
                target=replace_word,
                args=(word, target_window),
                daemon=True,
            ).start()

            return 1

        if vk != VK_SHIFT:
            typed = ""

    return user32.CallNextHookEx(
        hook_handle, n_code, w_param, l_param
    )


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

callback_ref = HOOKPROC(keyboard_callback)


def hook_loop():
    global hook_handle, hook_thread_id

    hook_thread_id = kernel32.GetCurrentThreadId()

    hook_handle = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL,
        ctypes.cast(callback_ref, ctypes.c_void_p),
        None,
        0,
    )

    if not hook_handle:
        error_code = ctypes.get_last_error()
        print(
            "Keyboard hook installation failed:",
            ctypes.WinError(error_code),
        )
        hook_ready.set()
        return

    print("Keyboard hook installed successfully.")
    hook_ready.set()

    message = wintypes.MSG()

    try:
        while not shutdown_event.is_set():
            result = user32.GetMessageW(
                ctypes.byref(message), None, 0, 0
            )

            if result <= 0:
                break

            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    finally:
        if hook_handle:
            user32.UnhookWindowsHookEx(hook_handle)
            hook_handle = None


# --------------------------------------------------
# ICONS
# --------------------------------------------------

def load_app_icon():
    """Load the same icon.ico for the app window and system tray."""
    try:
        if os.path.isfile(ICON_PATH):
            return Image.open(ICON_PATH).convert("RGBA")
    except Exception as exc:
        print("Could not load icon.ico:", exc)

    # Fallback if icon.ico is missing or invalid.
    image = Image.new("RGBA", (64, 64), "#245b9e")
    return image


# --------------------------------------------------
# SYSTEM TRAY AND WINDOW
# --------------------------------------------------

def show_window(icon=None, item=None):
    if root is not None and not shutdown_event.is_set():
        try:
            root.after(0, bring_window_forward)
        except (RuntimeError, tk.TclError):
            pass


def bring_window_forward():
    if root is None or shutdown_event.is_set():
        return

    root.deiconify()
    root.lift()
    root.focus_force()


def hide_window():
    if root is not None and not shutdown_event.is_set():
        root.withdraw()


# --------------------------------------------------
# STATUS AND CONTROLS
# --------------------------------------------------

def update_status():
    if root is None or shutdown_event.is_set():
        return

    def update_widgets():
        if root is None or shutdown_event.is_set():
            return

        status_var.set(
            "Running — Bangla typing ON"
            if enabled
            else "Stopped — Bangla typing OFF"
        )

        if tray_icon is not None:
            tray_icon.title = APP_NAME + (
                " — ON" if enabled else " — OFF"
            )

    try:
        root.after(0, update_widgets)
    except (RuntimeError, tk.TclError):
        pass


def start_app(icon=None, item=None):
    global enabled, typed

    with lock:
        enabled = True
        typed = ""

    print("Bangla transliteration: ON")
    update_status()


def stop_app(icon=None, item=None):
    global enabled, typed

    with lock:
        enabled = False
        typed = ""

    print("Bangla transliteration: OFF")
    update_status()


def toggle_app(icon=None, item=None):
    global enabled, typed

    with lock:
        enabled = not enabled
        typed = ""
        current = enabled

    print(
        "Bangla transliteration:",
        "ON" if current else "OFF",
    )
    update_status()


def save_hotkey():
    global selected_hotkey, hotkey_latched

    new_hotkey = hotkey_var.get()

    if new_hotkey not in HOTKEY_OPTIONS:
        messagebox.showerror(
            "Invalid shortcut",
            "Please select a shortcut from the list.",
        )
        return

    with config_lock:
        old_hotkey = selected_hotkey
        selected_hotkey = new_hotkey
        hotkey_latched = False

        try:
            save_settings()
        except OSError as exc:
            selected_hotkey = old_hotkey
            messagebox.showerror(
                "Settings error",
                f"Could not save the shortcut:\n{exc}",
            )
            return

    messagebox.showinfo(
        "Shortcut saved",
        f"Shortcut changed to {selected_hotkey}.\n"
        "It will be remembered after restarting the app.",
    )


# --------------------------------------------------
# COMPLETE APPLICATION EXIT
# --------------------------------------------------

def exit_app(icon=None, item=None):
    if shutdown_event.is_set():
        return

    shutdown_event.set()

    global enabled

    with lock:
        enabled = False

    if hook_thread_id is not None:
        user32.PostThreadMessageW(
            hook_thread_id, WM_QUIT, 0, 0
        )

    if tray_icon is not None:
        try:
            tray_icon.stop()
        except Exception as exc:
            print("Tray shutdown:", exc)

    if root is not None:
        try:
            root.after(0, root.destroy)
        except (RuntimeError, tk.TclError):
            pass

    try:
        http.close()
    except Exception:
        pass

    print("Kothaify has exited.")


# --------------------------------------------------
# INTERNET CONNECTION MONITOR
# --------------------------------------------------

def has_internet():
    try:
        connection = socket.create_connection(
            ("inputtools.google.com", 443),
            timeout=2,
        )
        connection.close()
        return True
    except OSError:
        return False


def update_internet_status(connected):
    global internet_connected

    if root is None or shutdown_event.is_set():
        return

    if internet_connected is connected:
        return

    internet_connected = connected

    if connected:
        internet_label.pack_forget()
        app_container.pack(fill="both", expand=True)
        root.title(APP_NAME)
    else:
        app_container.pack_forget()
        internet_label.pack(
            fill="both",
            expand=True,
            padx=25,
            pady=25,
        )
        root.title("Kothaify — No Internet")


def check_internet_forever():
    while not shutdown_event.is_set():
        connected = has_internet()

        if shutdown_event.is_set():
            break

        try:
            root.after(0, update_internet_status, connected)
        except (RuntimeError, tk.TclError):
            break

        if shutdown_event.wait(3):
            break


# --------------------------------------------------
# GUI
# --------------------------------------------------

def create_gui():
    global root, status_var, hotkey_var
    global app_container, internet_label

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("440x390")
    root.resizable(False, False)

    # Use icon.ico in the window title bar and taskbar.
    try:
        root.iconbitmap(ICON_PATH)
    except tk.TclError as exc:
        print("Could not set window icon:", exc)

    # Closing X exits the entire app.
    root.protocol("WM_DELETE_WINDOW", exit_app)

    app_container = ttk.Frame(root, padding=20)

    ttk.Label(
        app_container,
        text="Kothaify",
        font=("Nirmala UI", 17, "bold"),
    ).pack(pady=(0, 4))

    ttk.Label(
        app_container,
        text="Bangla Phonetic Typing",
        font=("Segoe UI", 10),
    ).pack()

    status_var = tk.StringVar(
        value="Checking internet connection..."
    )

    ttk.Label(
        app_container,
        textvariable=status_var,
        font=("Segoe UI", 10, "bold"),
    ).pack(pady=15)

    buttons = ttk.Frame(app_container)
    buttons.pack(fill="x", pady=4)

    ttk.Button(
        buttons,
        text="Start",
        command=start_app,
    ).pack(side="left", expand=True, fill="x", padx=3)

    ttk.Button(
        buttons,
        text="Stop",
        command=stop_app,
    ).pack(side="left", expand=True, fill="x", padx=3)

    ttk.Button(
        buttons,
        text="Toggle",
        command=toggle_app,
    ).pack(side="left", expand=True, fill="x", padx=3)

    ttk.Separator(app_container).pack(fill="x", pady=14)

    ttk.Label(
        app_container,
        text="Keyboard Shortcut",
        font=("Segoe UI", 11, "bold"),
    ).pack(anchor="w")

    hotkey_var = tk.StringVar(value=selected_hotkey)

    ttk.Combobox(
        app_container,
        textvariable=hotkey_var,
        values=list(HOTKEY_OPTIONS.keys()),
        state="readonly",
    ).pack(fill="x", pady=7)

    ttk.Button(
        app_container,
        text="Save Shortcut",
        command=save_hotkey,
    ).pack(fill="x")

    ttk.Label(
        app_container,
        text="Closing this window exits Kothaify completely.",
        wraplength=390,
    ).pack(pady=(12, 5))

    ttk.Button(
        app_container,
        text="Exit Application",
        command=exit_app,
    ).pack(fill="x", pady=4)

    internet_label = ttk.Label(
        root,
        text="Please check your internet connection",
        font=("Segoe UI", 12, "bold"),
        anchor="center",
        justify="center",
        wraplength=360,
    )

    app_container.pack(fill="both", expand=True)

    update_status()
    return root


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    global tray_icon

    load_settings()

    threading.Thread(
        target=hook_loop,
        daemon=True,
        name="KeyboardHook",
    ).start()

    hook_ready.wait(timeout=2)

    tray_menu = pystray.Menu(
        pystray.MenuItem(
            "Open Settings",
            show_window,
            default=True,
        ),
        pystray.MenuItem("Start", start_app),
        pystray.MenuItem("Stop", stop_app),
        pystray.MenuItem("Toggle", toggle_app),
        pystray.MenuItem("Exit", exit_app),
    )

    tray_icon = pystray.Icon(
        "Kothaify",
        load_app_icon(),
        APP_NAME,
        tray_menu,
    )

    threading.Thread(
        target=tray_icon.run,
        daemon=True,
        name="SystemTray",
    ).start()

    create_gui()

    threading.Thread(
        target=check_internet_forever,
        daemon=True,
        name="InternetMonitor",
    ).start()

    try:
        root.mainloop()
    finally:
        if not shutdown_event.is_set():
            exit_app()


if __name__ == "__main__":
    main()