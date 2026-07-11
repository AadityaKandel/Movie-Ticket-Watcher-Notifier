#!/usr/bin/env python3
"""
Ticket Watcher  v2
==================
Monitors a movie-ticketing website in a live Chromium browser and alerts
the user the moment a film appears on the page.

What's new in v2
----------------
1. DPI / resolution aware window sizing (Windows + Linux/X11). The window
   measures the real display resolution AND the OS scaling percentage, then
   sizes itself so every widget fits. If the screen is still too small, a
   scrollbar appears automatically — nothing ever gets cut off.
2. Hotkey *recorder*: press the combination instead of typing it.
   Uses `pynput` on Linux and `keyboard` on Windows. A Clear button resets it.
3. Selectable detection engine (Full-page / Section-based / Both) with a
   "?" explainer button.
4. Selectable alert behaviour (Notify once / Repeat / Repeat + re-check)
   with a "?" explainer button. Repeat cadence reuses the refresh interval.
5. Profile system: File ▸ Open (Ctrl+O), Save (Ctrl+S), Save As (Ctrl+Alt+S).
   First Ctrl+S behaves like Save As; afterwards it saves silently.
6. ntfy.sh guide dialog now contains a "Copy Topic Key" button
   (pyperclip if available, Tk clipboard as fallback).
7. The blocking in-app popup now always fires LAST so it can no longer
   delay the desktop / phone notifications.

Requirements (install once):
    pip install selenium requests
    Linux   : pip install pynput
    Windows : pip install keyboard
    Optional: pip install pyperclip

Chromium / Chrome is launched automatically when the app starts.
If the executable cannot be found automatically, use the Browse button.
"""

import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from tkinter import *
from tkinter import filedialog, messagebox, ttk

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

# ── Optional-dependency guards ────────────────────────────────────────────────
_MISSING = []

try:
    import requests as _requests
except ImportError:
    _requests = None          # type: ignore
    _MISSING.append("requests")

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as _ChromeOptions
    from selenium.webdriver.common.by import By
    _SELENIUM_OK = True
except ImportError:
    _SELENIUM_OK = False
    _MISSING.append("selenium")

# Hotkey backend: pynput on Linux, keyboard on Windows (compatibility).
_PYNPUT_OK = _KEYBOARD_OK = False
_pynput_kb = _keyboard = None
if IS_WINDOWS:
    try:
        import keyboard as _keyboard          # type: ignore
        _KEYBOARD_OK = True
    except ImportError:
        _MISSING.append("keyboard")
else:
    try:
        from pynput import keyboard as _pynput_kb   # type: ignore
        _PYNPUT_OK = True
    except ImportError:
        _MISSING.append("pynput")

# Clipboard helper (optional — Tk clipboard is the fallback).
try:
    import pyperclip as _pyperclip            # type: ignore
    _PYPERCLIP_OK = True
except ImportError:
    _pyperclip = None
    _PYPERCLIP_OK = False

# ── Constants ─────────────────────────────────────────────────────────────────
_DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(_DIR, "config.json")     # app-level settings only
PROFILE_DIR  = os.path.join(_DIR, "chromium_session")
DEBUG_PORT   = 9222

# Detection engine identifiers
DET_SIMPLE  = "simple"
DET_SECTION = "section"
DET_BOTH    = "both"
DET_LABELS = {
    DET_SIMPLE:  "Full-page match  (simple)",
    DET_SECTION: "Section-based match  (Now Showing zone)",
    DET_BOTH:    "Both  (alert if either matches)",
}
DET_FROM_LABEL = {v: k for k, v in DET_LABELS.items()}

# Alert behaviour identifiers
MODE_ONCE    = "once"
MODE_REPEAT  = "repeat"
MODE_RECHECK = "recheck"
MODE_LABELS = {
    MODE_ONCE:    "Notify once, then stop",
    MODE_REPEAT:  "Repeat notifications  (check once)",
    MODE_RECHECK: "Repeat notifications + keep re-checking",
}
MODE_FROM_LABEL = {v: k for k, v in MODE_LABELS.items()}

# Section-detection keywords (from the original commented logic)
KEYWORDS_NOW    = ["now showing", "showing now", "current release"]
KEYWORDS_COMING = ["coming soon", "upcoming", "next release"]


# ═════════════════════════════════════════════════════════════════════════════
# Display metrics  (resolution + scaling percentage)
# ═════════════════════════════════════════════════════════════════════════════
def _windows_display_metrics():
    """Return (res_w, res_h, scale) on Windows using ctypes."""
    import ctypes
    user32 = ctypes.windll.user32

    # Become DPI-aware so GetSystemMetrics reports *physical* pixels and
    # Tk is not lied to by DPI virtualisation.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    res_w = user32.GetSystemMetrics(0)
    res_h = user32.GetSystemMetrics(1)

    scale = 1.0
    try:
        dpi = user32.GetDpiForSystem()                   # Win10 1607+
        scale = dpi / 96.0
    except Exception:
        try:
            hdc = user32.GetDC(0)
            LOGPIXELSX = 88
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
            user32.ReleaseDC(0, hdc)
            scale = dpi / 96.0
        except Exception:
            pass
    return res_w, res_h, scale


def _linux_display_metrics():
    """Return (res_w, res_h, scale) on Linux (X11)."""
    res_w = res_h = None
    scale = None

    # Resolution — primary/active mode from xrandr, e.g. "1920x1080*"
    try:
        out = subprocess.run(["xrandr", "--current"], capture_output=True,
                             text=True, timeout=3).stdout
        m = re.search(r"(\d{3,5})x(\d{3,5})\s+\d[\d.]*\*", out)
        if m:
            res_w, res_h = int(m.group(1)), int(m.group(2))
    except Exception:
        pass

    # Scaling — try Xft.dpi first (respects fractional scaling on X11) …
    try:
        out = subprocess.run(["xrdb", "-query"], capture_output=True,
                             text=True, timeout=3).stdout
        m = re.search(r"Xft\.dpi:\s*([\d.]+)", out)
        if m:
            scale = float(m.group(1)) / 96.0
    except Exception:
        pass

    # … then GNOME's integer scaling-factor × text-scaling-factor.
    if scale is None:
        try:
            sf = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface",
                 "scaling-factor"],
                capture_output=True, text=True, timeout=3).stdout
            tf = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface",
                 "text-scaling-factor"],
                capture_output=True, text=True, timeout=3).stdout
            m_sf = re.search(r"(\d+)\s*$", sf.strip())
            m_tf = re.search(r"([\d.]+)\s*$", tf.strip())
            s = int(m_sf.group(1)) if m_sf else 0
            t = float(m_tf.group(1)) if m_tf else 1.0
            scale = (s if s > 0 else 1) * t
        except Exception:
            pass

    return res_w, res_h, (scale or 1.0)


def get_display_metrics(root):
    """
    Return (res_w, res_h, scale) for the current display.
    Falls back to Tk's own report if OS probing fails.
    """
    res_w = res_h = None
    scale = 1.0
    try:
        if IS_WINDOWS:
            res_w, res_h, scale = _windows_display_metrics()
        elif IS_LINUX:
            res_w, res_h, scale = _linux_display_metrics()
    except Exception as err:
        print(f"[display] probe error: {err}")

    if not res_w or not res_h:
        res_w = root.winfo_screenwidth()
        res_h = root.winfo_screenheight()
    if not scale or scale <= 0:
        try:   # Tk reports pixels-per-inch: dpi/96 = scaling percentage
            scale = root.winfo_fpixels("1i") / 96.0
        except Exception:
            scale = 1.0
    return res_w, res_h, scale


# ═════════════════════════════════════════════════════════════════════════════
# Cross-platform hotkey helpers
# ═════════════════════════════════════════════════════════════════════════════
_MODIFIER_ALIASES = {
    # pynput / keyboard raw names        → canonical
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "left ctrl": "ctrl", "right ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "left alt": "alt", "right alt": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "left shift": "shift", "right shift": "shift",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
    "windows": "cmd", "left windows": "cmd", "right windows": "cmd",
    "super": "cmd", "super_l": "cmd", "super_r": "cmd",
}
_MOD_ORDER = {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}


def _canon_mod(name: str):
    return _MODIFIER_ALIASES.get(name.lower().strip())


def combo_to_pynput(combo: str) -> str:
    """'ctrl+alt+t' → '<ctrl>+<alt>+t'   (named keys get wrapped too)."""
    parts = combo.split("+")
    return "+".join(f"<{p}>" if len(p) > 1 else p for p in parts)


def combo_to_keyboard(combo: str) -> str:
    """'ctrl+alt+t' → 'ctrl+alt+t'  (keyboard lib uses 'windows' for cmd)."""
    return "+".join("windows" if p == "cmd" else p for p in combo.split("+"))


class HotkeyRecorder:
    """
    Records one key combination (modifiers + a final regular key).
    on_update(combo_str_or_None, finished_bool) is invoked from a background
    thread — callers must marshal to the Tk thread themselves.
    """

    def __init__(self, on_update):
        self.on_update = on_update
        self._mods = set()
        self._listener = None
        self._hooked = False

    # -- shared -----------------------------------------------------------
    def _emit(self, key_name):
        mods = sorted(self._mods, key=lambda m: _MOD_ORDER.get(m, 9))
        combo = "+".join(mods + [key_name])
        self.on_update(combo, True)

    def _preview(self):
        mods = sorted(self._mods, key=lambda m: _MOD_ORDER.get(m, 9))
        self.on_update("+".join(mods) + ("+…" if mods else ""), False)

    # -- pynput backend (Linux) --------------------------------------------
    def _py_name(self, key):
        try:
            if hasattr(key, "char") and key.char:
                return key.char.lower()
            return key.name.lower()          # Key.f5 → 'f5', Key.space → 'space'
        except Exception:
            return None

    def _py_press(self, key):
        name = self._py_name(key)
        if not name:
            return
        mod = _canon_mod(name)
        if mod:
            self._mods.add(mod)
            self._preview()
        else:
            self._emit(name)

    def _py_release(self, key):
        name = self._py_name(key)
        mod = _canon_mod(name) if name else None
        if mod and mod in self._mods:
            self._mods.discard(mod)
            self._preview()

    # -- keyboard backend (Windows) ------------------------------------------
    def _kb_event(self, event):
        name = (event.name or "").lower()
        mod = _canon_mod(name)
        if event.event_type == "down":
            if mod:
                self._mods.add(mod)
                self._preview()
            elif name:
                self._emit(name)
        elif event.event_type == "up" and mod:
            self._mods.discard(mod)
            self._preview()

    # -- lifecycle ------------------------------------------------------------
    def start(self):
        self._mods.clear()
        if IS_WINDOWS and _KEYBOARD_OK:
            _keyboard.hook(self._kb_event)
            self._hooked = True
        elif _PYNPUT_OK:
            self._listener = _pynput_kb.Listener(
                on_press=self._py_press, on_release=self._py_release)
            self._listener.daemon = True
            self._listener.start()

    def stop(self):
        if self._hooked:
            try:
                _keyboard.unhook(self._kb_event)
            except Exception:
                pass
            self._hooked = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


# ═════════════════════════════════════════════════════════════════════════════
# Chromium executable discovery
# ═════════════════════════════════════════════════════════════════════════════
_LINUX_CMDS = [
    "chromium-browser", "chromium",
    "google-chrome-stable", "google-chrome",
]
_WIN_PATHS = [
    r"Chromium\Application\chrome.exe",
    r"Google\Chrome\Application\chrome.exe",
]


def _find_chromium(saved: str = "") -> str:
    """Return a usable Chromium/Chrome executable path, or '' if none found."""
    if saved and os.path.isfile(saved):
        return saved

    if IS_LINUX:
        for cmd in _LINUX_CMDS:
            found = shutil.which(cmd)
            if found:
                return found

    elif IS_WINDOWS:
        bases = list(filter(None, [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]))
        for base in bases:
            for suffix in _WIN_PATHS:
                full = os.path.join(base, suffix)
                if os.path.isfile(full):
                    return full
        for name in ("chrome", "chromium"):
            found = shutil.which(name)
            if found:
                return found

    return ""


def _port_open(port: int = DEBUG_PORT) -> bool:
    """Return True if something is listening on the given localhost port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.8):
            return True
    except OSError:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Main Application
# ═════════════════════════════════════════════════════════════════════════════
class TicketWatcher:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Ticket Watcher")

        # ── Runtime state ──────────────────────────────────────────────────
        self.is_running        = False
        self.monitor_thread    = None
        self.hotkey_listener   = None      # pynput listener object
        self.kb_hotkey_handle  = None      # keyboard lib remove-handle
        self.chromium_proc     = None
        self.profile_path      = None      # current .json profile (feature 5)
        self._popup_open       = False     # avoid stacking blocking popups

        # ── Persistent state ───────────────────────────────────────────────
        self.saved_hotkey  = ""            # canonical, e.g. "ctrl+alt+t"
        self.ntfy_topic    = ""
        self.chromium_path = ""

        # ── Tkinter variables ──────────────────────────────────────────────
        self.chrom_var      = StringVar()
        self.url_var        = StringVar()
        self.interval_var   = StringVar(value="60")
        self.movie_var      = StringVar()
        self.hide_var       = IntVar()
        self.msg_var        = StringVar()
        self.act_inapp_var  = IntVar()
        self.act_sys_var    = IntVar()
        self.act_silent_var = IntVar()
        self.act_ntfy_var   = IntVar()
        self.det_var        = StringVar(value=DET_LABELS[DET_SIMPLE])
        self.mode_var       = StringVar(value=MODE_LABELS[MODE_ONCE])

        # Abort if critical libraries are missing
        if _MISSING:
            messagebox.showerror(
                "Missing Libraries",
                "The following Python libraries must be installed before running:\n\n" +
                "\n".join(f"    pip install {lib}" for lib in _MISSING) +
                "\n\nInstall them and restart the app."
            )
            root.after(0, root.destroy)
            return

        # 1) Measure the display FIRST so fonts/widgets are built at the
        #    correct scale, then build the UI, then fit the window to it.
        self.res_w, self.res_h, self.scale = get_display_metrics(root)
        self._apply_tk_scaling()

        self._build_menu()
        self._build_ui()
        self._load_app_config()

        # Fit the window once every widget has computed its requested size.
        root.after(50, self._fit_window_to_display)
        # Attempt Chromium auto-launch after the event loop is ready.
        root.after(350, self._auto_launch_chromium)

    # ─────────────────────────────────────────────────────────────────────────
    # Feature 1 — Display-aware sizing
    # ─────────────────────────────────────────────────────────────────────────
    def _apply_tk_scaling(self):
        """
        Tell Tk the real pixels-per-point so text renders at the size the OS
        scaling percentage asks for.  tk scaling = (96 × scale) / 72.
        """
        try:
            self.root.tk.call("tk", "scaling", (96.0 * self.scale) / 72.0)
        except Exception as err:
            print(f"[display] tk scaling error: {err}")

    def _fit_window_to_display(self):
        """
        Auto-size the window from the widgets' requested size, clamped to the
        usable desktop area (resolution ÷ margins for taskbar / panel).
        If the content is taller than the screen, the scrollbar handles it.
        """
        self.root.update_idletasks()

        req_w = self.inner.winfo_reqwidth()
        req_h = self.inner.winfo_reqheight()

        sbar_w  = self.vbar.winfo_reqwidth() + 4
        margin  = int(30 * self.scale)                    # window chrome
        avail_w = int(self.res_w * 0.96)
        avail_h = int(self.res_h * 0.90) - margin         # leave taskbar room

        w = min(req_w + sbar_w + margin, avail_w)
        h = min(req_h + margin, avail_h)

        x = max((self.res_w - w) // 2, 0)
        y = max((self.res_h - h) // 2 - int(10 * self.scale), 0)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(w, avail_w), min(int(300 * self.scale), avail_h))

        pct = round(self.scale * 100)
        print(f"[display] {self.res_w}x{self.res_h} @ {pct}% "
              f"→ window {w}x{h} (content wants {req_w}x{req_h})")

    # ─────────────────────────────────────────────────────────────────────────
    # Feature 5 — Menu bar & profile shortcuts
    # ─────────────────────────────────────────────────────────────────────────
    def _build_menu(self):
        menubar = Menu(self.root)
        filemenu = Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open Profile…", accelerator="Ctrl+O",
                             command=self._profile_open)
        filemenu.add_command(label="Save Profile", accelerator="Ctrl+S",
                             command=self._profile_save)
        filemenu.add_command(label="Save Profile As…", accelerator="Ctrl+Alt+S",
                             command=self._profile_save_as)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

        # Global accelerators (bind_all so they work with any widget focused).
        # The more specific Ctrl+Alt+S binding wins over Ctrl+S in Tk.
        self.root.bind_all("<Control-o>", lambda e: self._profile_open())
        self.root.bind_all("<Control-O>", lambda e: self._profile_open())
        self.root.bind_all("<Control-s>", lambda e: self._profile_save())
        self.root.bind_all("<Control-S>", lambda e: self._profile_save())
        self.root.bind_all("<Control-Alt-s>", lambda e: self._profile_save_as())
        self.root.bind_all("<Control-Alt-S>", lambda e: self._profile_save_as())

    # ─────────────────────────────────────────────────────────────────────────
    # UI Construction (inside a scrollable frame so nothing is ever cut off)
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Scroll container: Canvas + inner Frame + auto-hiding scrollbar
        outer = Frame(self.root)
        outer.pack(fill=BOTH, expand=True)

        self.canvas = Canvas(outer, highlightthickness=0)
        self.vbar   = ttk.Scrollbar(outer, orient=VERTICAL,
                                    command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side=RIGHT, fill=Y)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)

        self.inner = Frame(self.canvas)
        self._inner_id = self.canvas.create_window((0, 0), window=self.inner,
                                                   anchor="nw")

        def _sync_scrollregion(_=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        def _sync_width(event):
            self.canvas.itemconfigure(self._inner_id, width=event.width)
        self.inner.bind("<Configure>", _sync_scrollregion)
        self.canvas.bind("<Configure>", _sync_width)

        # Mouse-wheel support (Windows: <MouseWheel>, X11: Button-4/5)
        def _wheel(event):
            if event.num == 4 or event.delta > 0:
                self.canvas.yview_scroll(-2, "units")
            elif event.num == 5 or event.delta < 0:
                self.canvas.yview_scroll(2, "units")
        self.canvas.bind_all("<MouseWheel>", _wheel)
        self.canvas.bind_all("<Button-4>", _wheel)
        self.canvas.bind_all("<Button-5>", _wheel)

        body = self.inner                    # everything below packs into this
        P  = dict(padx=14, pady=(9, 2))      # standard label padding
        P2 = dict(padx=14, pady=2)           # standard widget padding

        # ── Section: Chromium executable ──────────────────────────────────
        Label(body, text="Chromium / Chrome Executable:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)

        chrom_row = Frame(body)
        chrom_row.pack(fill=X, **P2)
        self.chrom_entry = Entry(chrom_row, textvariable=self.chrom_var, width=52)
        self.chrom_entry.pack(side=LEFT, fill=X, expand=True)
        self.browse_btn = Button(chrom_row, text="Browse…",
                                 command=self._browse_chromium)
        self.browse_btn.pack(side=LEFT, padx=(6, 0))

        self.lbl_chrom = Label(body, text="  Detecting…",
                               fg="orange", font=("Arial", 9))
        self.lbl_chrom.pack(anchor=W, padx=14, pady=(1, 4))

        Frame(body, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=6)

        # ── Section: Target URL ───────────────────────────────────────────
        Label(body,
              text="Target URL  (full path, e.g. https://example.com/now-showing):",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        self.url_entry = Entry(body, textvariable=self.url_var, width=66)
        self.url_entry.pack(fill=X, **P2)

        # ── Section: Refresh interval ─────────────────────────────────────
        Label(body, text="Refresh Interval — seconds  (min 30 · max 300):",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        self.interval_entry = Entry(body, textvariable=self.interval_var, width=14)
        self.interval_entry.pack(anchor=W, **P2)

        # ── Section: Movie name ───────────────────────────────────────────
        movie_hdr = Frame(body)
        movie_hdr.pack(fill=X, padx=14, pady=(9, 2))
        Label(movie_hdr, text="Movie / Text to Detect:",
              font=("Arial", 10, "bold")).pack(side=LEFT)
        Button(movie_hdr, text=" ? ", relief=RIDGE, font=("Arial", 8),
               command=self._tip_movie_name).pack(side=LEFT, padx=5)

        self.movie_entry = Entry(body, textvariable=self.movie_var, width=66)
        self.movie_entry.pack(fill=X, **P2)

        # ── Section: Detection engine  (Feature 3) ────────────────────────
        det_hdr = Frame(body)
        det_hdr.pack(fill=X, padx=14, pady=(9, 2))
        Label(det_hdr, text="Detection Method:",
              font=("Arial", 10, "bold")).pack(side=LEFT)

        det_row = Frame(body)
        det_row.pack(fill=X, **P2)
        self.det_combo = ttk.Combobox(det_row, textvariable=self.det_var,
                                      values=list(DET_LABELS.values()),
                                      state="readonly", width=44)
        self.det_combo.pack(side=LEFT)
        self.det_help_btn = Button(det_row, text=" ? ", relief=RIDGE,
                                   font=("Arial", 8),
                                   command=self._tip_detection)
        self.det_help_btn.pack(side=LEFT, padx=5)

        Frame(body, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=8)

        # ── Section: Hide window / hotkey  (Feature 2) ────────────────────
        hide_frame = Frame(body, bd=1, relief=GROOVE)
        hide_frame.pack(fill=X, padx=14, pady=4, ipady=4)

        hide_top = Frame(hide_frame)
        hide_top.pack(fill=X, padx=8, pady=(4, 2))
        self.hide_chk = Checkbutton(hide_top, text="Hide window while monitoring",
                                    variable=self.hide_var,
                                    command=self._on_hide_toggled)
        self.hide_chk.pack(side=LEFT)
        self.linux_guide_btn = Button(hide_top, text="Linux Hotkey Guide",
                                      font=("Arial", 8),
                                      command=self._guide_linux_hotkey)
        self.linux_guide_btn.pack(side=RIGHT)

        self.lbl_hotkey = Label(hide_frame, text="Hotkey: [Not configured]",
                                fg="red", font=("Arial", 9))
        self.lbl_hotkey.pack(anchor=W, padx=8, pady=(0, 4))

        Frame(body, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=6)

        # ── Section: Alert actions ────────────────────────────────────────
        Label(body, text="Alert Actions on Detection:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        act_frame = Frame(body, bd=1, relief=GROOVE)
        act_frame.pack(fill=X, padx=14, pady=4, ipady=4)

        self.chk_inapp = Checkbutton(
            act_frame,
            text="In-app popup  (unhides window automatically — fires last)",
            variable=self.act_inapp_var)
        self.chk_inapp.pack(anchor=W, padx=8, pady=2)

        self.chk_sys = Checkbutton(
            act_frame,
            text="System desktop notification",
            variable=self.act_sys_var)
        self.chk_sys.pack(anchor=W, padx=8, pady=2)

        self.chk_silent = Checkbutton(
            act_frame,
            text="    ↳  Silent / low-priority notification",
            variable=self.act_silent_var)
        self.chk_silent.pack(anchor=W, padx=8, pady=1)

        ntfy_row = Frame(act_frame)
        ntfy_row.pack(anchor=W, padx=8, pady=2)
        self.chk_ntfy = Checkbutton(
            ntfy_row,
            text="Send push notification to phone via ntfy.sh",
            variable=self.act_ntfy_var)
        self.chk_ntfy.pack(side=LEFT)
        Button(ntfy_row, text=" ? ", relief=RIDGE, font=("Arial", 8),
               command=self._guide_ntfy).pack(side=LEFT, padx=4)

        # ── Section: Alert behaviour  (Feature 4) ─────────────────────────
        Label(body, text="Alert Behaviour:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        mode_row = Frame(body)
        mode_row.pack(fill=X, **P2)
        self.mode_combo = ttk.Combobox(mode_row, textvariable=self.mode_var,
                                       values=list(MODE_LABELS.values()),
                                       state="readonly", width=44)
        self.mode_combo.pack(side=LEFT)
        self.mode_help_btn = Button(mode_row, text=" ? ", relief=RIDGE,
                                    font=("Arial", 8),
                                    command=self._tip_alert_mode)
        self.mode_help_btn.pack(side=LEFT, padx=5)
        Label(body,
              text="Repeat cadence = the Refresh Interval above (no separate timer).",
              fg="gray", font=("Arial", 8)).pack(anchor=W, padx=14)

        # ── Section: Custom message ───────────────────────────────────────
        Label(body, text="Custom Alert Message:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        self.msg_entry = Entry(body, textvariable=self.msg_var, width=66)
        self.msg_entry.pack(fill=X, **P2)
        Label(body,
              text='Leave blank → auto: "<Movie> is open for tickets. BUY THEM NOW!"',
              fg="gray", font=("Arial", 8)).pack(anchor=W, padx=14)

        Frame(body, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=8)

        # ── Start / Stop button ───────────────────────────────────────────
        self.ctrl_btn = Button(body, text="▶  Start Monitoring",
                               bg="green", fg="white",
                               font=("Arial", 11, "bold"),
                               height=2, command=self._toggle_engine)
        self.ctrl_btn.pack(fill=X, padx=14, pady=(0, 14))

        # All widgets that must be disabled while monitoring
        self._input_widgets = [
            self.chrom_entry, self.browse_btn,
            self.url_entry, self.interval_entry, self.movie_entry,
            self.det_combo, self.det_help_btn,
            self.hide_chk, self.linux_guide_btn,
            self.chk_inapp, self.chk_sys, self.chk_silent, self.chk_ntfy,
            self.mode_combo, self.mode_help_btn,
            self.msg_entry,
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # Info / guide dialogs
    # ─────────────────────────────────────────────────────────────────────────
    def _tip_movie_name(self):
        messagebox.showinfo(
            "How to enter the movie name",
            "Use the exact title shown on the website under 'Coming Soon',\n"
            "not the title from Google or IMDb.\n\n"
            "Matching is case-insensitive — any capitalisation works.\n\n"
            "Tip: if the full title is a common phrase, use a distinctive\n"
            "word that only appears in that film's listing."
        )

    def _tip_detection(self):
        """Feature 3 — explain the currently selected detection method."""
        sel = DET_FROM_LABEL.get(self.det_var.get(), DET_SIMPLE)
        blurbs = {
            DET_SIMPLE: (
                "FULL-PAGE MATCH (simple)\n"
                "─────────────────────────\n"
                "Searches the movie name anywhere in the visible text of the\n"
                "whole page.\n\n"
                "✔ Works on almost any website front-end.\n"
                "✘ May alert early: many sites list upcoming films under\n"
                "   'Coming Soon' on the same page, and this method cannot\n"
                "   tell the sections apart."
            ),
            DET_SECTION: (
                "SECTION-BASED MATCH (Now Showing zone)\n"
                "───────────────────────────────────────\n"
                "First locates a heading such as 'Now Showing' / 'Showing\n"
                "Now' / 'Current Release', then a heading such as 'Coming\n"
                "Soon' / 'Upcoming' / 'Next Release', and only searches the\n"
                "text BETWEEN those two headings.\n\n"
                "✔ Ignores films that are merely announced as upcoming.\n"
                "✘ Only works if the page actually contains those headings in\n"
                "   that order. If the headings are missing, nothing is ever\n"
                "   detected."
            ),
            DET_BOTH: (
                "BOTH (alert if either matches)\n"
                "───────────────────────────────\n"
                "Runs the Section-based match first; if it finds nothing, the\n"
                "Full-page match is tried as a fallback.\n\n"
                "✔ Best coverage when you are unsure how the website is built.\n"
                "✘ Inherits the early-alert risk of the Full-page method on\n"
                "   sites that list upcoming films on the same page."
            ),
        }
        messagebox.showinfo(
            f"Detection Method — {DET_LABELS[sel]}",
            blurbs[sel] +
            "\n\nYou can change the method any time before starting."
        )

    def _tip_alert_mode(self):
        """Feature 4 — explain the currently selected alert behaviour."""
        sel = MODE_FROM_LABEL.get(self.mode_var.get(), MODE_ONCE)
        blurbs = {
            MODE_ONCE: (
                "NOTIFY ONCE, THEN STOP\n"
                "───────────────────────\n"
                "The moment the movie is detected, every selected alert fires\n"
                "one single time and monitoring stops completely.\n\n"
                "Best when one heads-up is all you need."
            ),
            MODE_REPEAT: (
                "REPEAT NOTIFICATIONS (check once)\n"
                "──────────────────────────────────\n"
                "Once the movie is detected, the page is NOT checked again.\n"
                "Instead, the selected alerts are re-sent over and over, once\n"
                "per Refresh Interval, until you press Stop.\n\n"
                "Best when you might miss the first notification — the app\n"
                "keeps nagging you without wasting page reloads."
            ),
            MODE_RECHECK: (
                "REPEAT NOTIFICATIONS + KEEP RE-CHECKING\n"
                "────────────────────────────────────────\n"
                "Even after the first detection, the page keeps being reloaded\n"
                "and re-checked every Refresh Interval. Each time the movie is\n"
                "still found, the alerts fire again. Until you press Stop.\n\n"
                "Best when listings appear and disappear (e.g. shows selling\n"
                "out) and you want live confirmation with every alert."
            ),
        }
        messagebox.showinfo(
            f"Alert Behaviour — {MODE_LABELS[sel]}",
            blurbs[sel] +
            "\n\nThe repeat cadence always reuses the Refresh Interval you\n"
            "entered above — there is no separate timer to configure."
        )

    def _guide_linux_hotkey(self):
        messagebox.showinfo(
            "Linux Only — Enabling Global Hotkeys",
            "Modern Linux desktops use Wayland by default, which blocks\n"
            "background keyboard listeners for security reasons.\n\n"
            "To use global hotkeys, switch your session to X11 / Xorg:\n\n"
            "1. Log out of your current desktop session.\n"
            "2. On the login screen, click the gear ⚙ icon (bottom-right).\n"
            "3. Choose 'Ubuntu on Xorg' (or any 'X11' / 'Xorg' option).\n"
            "4. Log back in.\n\n"
            "If X11 is not listed, install it first:\n"
            "    sudo apt install xorg\n\n"
            "For a permanent switch, edit  /etc/gdm3/custom.conf  and set:\n"
            "    WaylandEnable=false\n"
            "Then reboot.\n\n"
            "Windows users: no action needed — hotkeys work out of the box."
        )

    # ── Feature 6 — ntfy guide with a Copy Topic Key button ────────────────
    def _guide_ntfy(self):
        """
        messagebox dialogs cannot host extra buttons, so this is a custom
        Toplevel: same text as before + 'Copy Topic Key' inside the dialog.
        """
        dlg = Toplevel(self.root)
        dlg.title("Phone Notifications — ntfy.sh Setup")
        dlg.transient(self.root)
        dlg.resizable(False, False)

        Label(dlg, justify=LEFT, anchor=W, font=("Arial", 10), text=(
            "1. Install the free 'ntfy' app:\n"
            "      Android → Google Play Store\n"
            "      iOS     → Apple App Store\n\n"
            "2. Open the app → tap '+' → 'Subscribe to topic'.\n"
            "3. Enter your unique topic key shown below.\n"
        )).pack(padx=16, pady=(12, 4), anchor=W)

        key_row = Frame(dlg)
        key_row.pack(fill=X, padx=16, pady=4)
        Label(key_row, text="Your topic key:",
              font=("Arial", 10, "bold")).pack(side=LEFT)
        key_entry = Entry(key_row, width=24, font=("Consolas", 10))
        key_entry.insert(0, self.ntfy_topic)
        key_entry.config(state="readonly")
        key_entry.pack(side=LEFT, padx=(8, 6))

        feedback = Label(dlg, text=" ", fg="green", font=("Arial", 9))

        def _copy():
            ok = self._copy_to_clipboard(self.ntfy_topic)
            feedback.config(
                text="✔ Copied to clipboard!" if ok
                else "✘ Copy failed — select the key and copy manually.",
                fg="green" if ok else "red")

        Button(key_row, text="Copy Topic Key", command=_copy).pack(side=LEFT)
        feedback.pack(anchor=W, padx=16)

        Label(dlg, justify=LEFT, anchor=W, fg="#555", font=("Arial", 9), text=(
            "This key is stored in config.json — keep it private.\n"
            "Anyone who knows it can receive your notifications."
        )).pack(padx=16, pady=(4, 4), anchor=W)

        Button(dlg, text="Close", width=10,
               command=dlg.destroy).pack(pady=(4, 12))

        # Safe modal grab (this is what crashed before when done too early:
        # X11 refuses grab_set() until the window is actually viewable).
        try:
            dlg.wait_visibility()
            dlg.grab_set()
        except Exception:
            pass
        dlg.focus_set()

    def _copy_to_clipboard(self, text: str) -> bool:
        """pyperclip when available, Tk clipboard as fallback."""
        if _PYPERCLIP_OK:
            try:
                _pyperclip.copy(text)
                return True
            except Exception as err:
                print(f"[clipboard] pyperclip error: {err}")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()          # keep contents after dialogs close
            return True
        except Exception as err:
            print(f"[clipboard] tk error: {err}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Chromium auto-launch
    # ─────────────────────────────────────────────────────────────────────────
    def _browse_chromium(self):
        """Let the user manually locate the Chromium / Chrome executable."""
        if IS_WINDOWS:
            filetypes = [("Executable", "*.exe"), ("All files", "*.*")]
        else:
            filetypes = [("All files", "*")]

        path = filedialog.askopenfilename(
            title="Select Chromium or Chrome executable",
            filetypes=filetypes,
        )
        if path:
            self.chrom_var.set(path)
            self.chromium_path = path
            self._kill_chromium_proc()
            self._auto_launch_chromium()

    def _auto_launch_chromium(self):
        if _port_open():
            self.lbl_chrom.config(
                text="  ✔ Debug port active (9222) — Chromium is ready",
                fg="green"
            )
            return

        exe = _find_chromium(self.chrom_var.get().strip() or self.chromium_path)
        if exe:
            self._launch_exe(exe)
        else:
            self.lbl_chrom.config(
                text="  ✘ Chromium not found — use Browse to locate it",
                fg="red"
            )
            messagebox.showwarning(
                "Chromium Not Found",
                "Could not locate Chromium or Chrome automatically on this system.\n\n"
                "Please click Browse and point to your Chromium or Chrome executable."
            )

    def _launch_exe(self, exe: str):
        os.makedirs(PROFILE_DIR, exist_ok=True)
        # For now it is working as intended. If it doesn't work in the background
        # and keeps on requiring main application focus, you can also apply this flag
        # --headless=new
        cmd = [
        exe,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling",
        ]
        try:
            self.chromium_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.chromium_path = exe
            self.chrom_var.set(exe)
            self.lbl_chrom.config(text="  Chromium launching…", fg="orange")
            self.root.after(900, self._poll_port)
        except Exception as err:
            self.lbl_chrom.config(
                text=f"  ✘ Launch failed — {err}",
                fg="red"
            )

    def _poll_port(self, attempt: int = 0):
        if _port_open():
            self.lbl_chrom.config(
                text="  ✔ Chromium ready (port 9222)",
                fg="green"
            )
        elif attempt < 18:
            self.root.after(700, lambda: self._poll_port(attempt + 1))
        else:
            self.lbl_chrom.config(
                text="  ✘ Chromium did not respond — try Browse & relaunch",
                fg="red"
            )

    def _kill_chromium_proc(self):
        if self.chromium_proc and self.chromium_proc.poll() is None:
            try:
                self.chromium_proc.terminate()
            except Exception:
                pass
        self.chromium_proc = None

    # ─────────────────────────────────────────────────────────────────────────
    # Feature 2 — Hide-window / hotkey RECORDER dialog
    # ─────────────────────────────────────────────────────────────────────────
    def _on_hide_toggled(self):
        if self.hide_var.get() == 1:
            self._open_hotkey_dialog()
        else:
            self.saved_hotkey = ""
            self.lbl_hotkey.config(text="Hotkey: [Not configured]", fg="red")

    def _open_hotkey_dialog(self):
        dlg = Toplevel(self.root)
        dlg.title("Record Hotkey")
        dlg.resizable(False, False)
        dlg.transient(self.root)

        Label(dlg, text="Press the key combination you want to use:",
              font=("Arial", 10, "bold")).pack(padx=16, pady=(12, 6))
        Label(dlg, text="Hold one or more modifiers (Ctrl / Alt / Shift / Win)\n"
                        "and press a regular key — it is captured automatically.",
              fg="#555", font=("Arial", 9), justify=CENTER).pack(padx=16)

        rec_row = Frame(dlg)
        rec_row.pack(padx=16, pady=10)
        hk_var = StringVar(value=self.saved_hotkey or "…waiting for keys…")
        hk_entry = Entry(rec_row, textvariable=hk_var, width=30,
                         font=("Consolas", 11), justify=CENTER,
                         state="readonly", readonlybackground="#f4f4f4")
        hk_entry.pack(side=LEFT)

        captured = {"combo": self.saved_hotkey or ""}

        def _clear():
            captured["combo"] = ""
            hk_var.set("…waiting for keys…")

        Button(rec_row, text="Clear", command=_clear).pack(side=LEFT, padx=(6, 0))

        status = Label(dlg, text="Recorder active — this works even while the\n"
                                 "dialog is not focused.",
                       fg="gray", font=("Arial", 8))
        status.pack()

        # The recorder runs in a background thread → marshal updates via after
        def _on_update(combo, finished):
            def _apply():
                if finished:
                    captured["combo"] = combo
                    hk_var.set(combo)
                else:
                    hk_var.set(combo if combo else "…waiting for keys…")
            try:
                dlg.after(0, _apply)
            except Exception:
                pass

        recorder = HotkeyRecorder(_on_update)
        recorder.start()

        def _close(save: bool):
            recorder.stop()
            if save and captured["combo"] and "…" not in captured["combo"]:
                self.saved_hotkey = captured["combo"]
                self.lbl_hotkey.config(text=f"Hotkey: {self.saved_hotkey}",
                                       fg="green")
            else:
                if save:
                    messagebox.showwarning(
                        "No Hotkey Recorded",
                        "No key combination was captured, so the hide option\n"
                        "has been switched off.", parent=dlg)
                if not self.saved_hotkey:
                    self.hide_var.set(0)
                    self.lbl_hotkey.config(text="Hotkey: [Not configured]",
                                           fg="red")
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        bf = Frame(dlg)
        bf.pack(pady=(6, 12))
        Button(bf, text="Save",   width=11,
               command=lambda: _close(True)).pack(side=LEFT, padx=5)
        Button(bf, text="Cancel", width=11,
               command=lambda: _close(False)).pack(side=LEFT, padx=5)
        dlg.protocol("WM_DELETE_WINDOW", lambda: _close(False))

        # grab_set() only after the window is viewable — the unguarded call
        # was what crashed the old dialog on X11.
        try:
            dlg.wait_visibility()
            dlg.grab_set()
        except Exception:
            pass
        dlg.focus_set()

    # ── Runtime global hotkey listener (pynput on Linux, keyboard on Win) ──
    def _start_hotkey_listener(self):
        if self.hotkey_listener or self.kb_hotkey_handle or not self.saved_hotkey:
            return
        try:
            if IS_WINDOWS and _KEYBOARD_OK:
                self.kb_hotkey_handle = _keyboard.add_hotkey(
                    combo_to_keyboard(self.saved_hotkey),
                    lambda: self.root.after(0, self._unhide))
            elif _PYNPUT_OK:
                self.hotkey_listener = _pynput_kb.GlobalHotKeys(
                    {combo_to_pynput(self.saved_hotkey):
                     lambda: self.root.after(0, self._unhide)})
                self.hotkey_listener.start()
        except Exception as err:
            print(f"[hotkey] listener start failed: {err}")

    def _stop_hotkey_listener(self):
        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass
            self.hotkey_listener = None
        if self.kb_hotkey_handle is not None:
            try:
                _keyboard.remove_hotkey(self.kb_hotkey_handle)
            except Exception:
                pass
            self.kb_hotkey_handle = None

    def _unhide(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ─────────────────────────────────────────────────────────────────────────
    # Feature 5 — Profile system (Open / Save / Save As)
    # ─────────────────────────────────────────────────────────────────────────
    def _collect_profile(self) -> dict:
        """Everything the UI knows, in one dictionary."""
        return {
            "url":            self.url_var.get().strip(),
            "interval":       self.interval_var.get().strip(),
            "movie_name":     self.movie_var.get().strip(),
            "custom_message": self.msg_var.get().strip(),
            "detection":      DET_FROM_LABEL.get(self.det_var.get(), DET_SIMPLE),
            "alert_mode":     MODE_FROM_LABEL.get(self.mode_var.get(), MODE_ONCE),
            "act_inapp":      self.act_inapp_var.get(),
            "act_sys":        self.act_sys_var.get(),
            "act_silent":     self.act_silent_var.get(),
            "act_ntfy":       self.act_ntfy_var.get(),
            "hide_window":    self.hide_var.get(),
            "hotkey":         self.saved_hotkey if self.hide_var.get() == 1 else "",
            "ntfy_topic":     self.ntfy_topic,
            "chromium_path":  self.chromium_path,
        }

    def _apply_profile(self, c: dict):
        """Push a loaded profile dictionary into every widget."""
        self.url_var.set(c.get("url", ""))
        self.interval_var.set(str(c.get("interval", "60")))
        self.movie_var.set(c.get("movie_name", ""))
        self.msg_var.set(c.get("custom_message", ""))
        self.det_var.set(DET_LABELS.get(c.get("detection", DET_SIMPLE),
                                        DET_LABELS[DET_SIMPLE]))
        self.mode_var.set(MODE_LABELS.get(c.get("alert_mode", MODE_ONCE),
                                          MODE_LABELS[MODE_ONCE]))
        self.act_inapp_var.set(c.get("act_inapp", 0))
        self.act_sys_var.set(c.get("act_sys", 0))
        self.act_silent_var.set(c.get("act_silent", 0))
        self.act_ntfy_var.set(c.get("act_ntfy", 0))

        if c.get("ntfy_topic"):
            self.ntfy_topic = c["ntfy_topic"]
        if c.get("chromium_path"):
            self.chromium_path = c["chromium_path"]
            self.chrom_var.set(self.chromium_path)

        hk = c.get("hotkey", "")
        if c.get("hide_window") and hk:
            self.saved_hotkey = hk
            self.hide_var.set(1)
            self.lbl_hotkey.config(text=f"Hotkey: {hk}", fg="green")
        else:
            self.saved_hotkey = ""
            self.hide_var.set(0)
            self.lbl_hotkey.config(text="Hotkey: [Not configured]", fg="red")

    def _set_title(self):
        name = os.path.basename(self.profile_path) if self.profile_path else ""
        self.root.title(f"Ticket Watcher — {name}" if name else "Ticket Watcher")

    def _profile_open(self):
        if self.is_running:
            messagebox.showwarning("Monitoring Active",
                                   "Stop monitoring before opening a profile.")
            return
        path = filedialog.askopenfilename(
            title="Open Profile",
            filetypes=[("Ticket Watcher profile", "*.json"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path) as f:
                self._apply_profile(json.load(f))
            self.profile_path = path
            self._set_title()
            self._save_app_config()
        except Exception as err:
            messagebox.showerror("Open Failed",
                                 f"Could not load the profile:\n\n{err}")

    def _profile_save(self):
        """
        Ctrl+S — first press in this session acts like Save As;
        every later press saves silently to the remembered file.
        """
        if not self.profile_path:
            self._profile_save_as()
            return
        self._write_profile(self.profile_path)

    def _profile_save_as(self):
        """Ctrl+Alt+S — always opens the directory dialog."""
        path = filedialog.asksaveasfilename(
            title="Save Profile As",
            defaultextension=".json",
            initialfile=os.path.basename(self.profile_path)
                        if self.profile_path else "watcher_profile.json",
            filetypes=[("Ticket Watcher profile", "*.json"),
                       ("All files", "*.*")],
        )
        if not path:
            return
        self._write_profile(path)

    def _write_profile(self, path: str):
        try:
            with open(path, "w") as f:
                json.dump(self._collect_profile(), f, indent=4)
            self.profile_path = path
            self._set_title()
            self._save_app_config()
            # brief, non-blocking confirmation in the title bar
            self.root.title(f"Ticket Watcher — {os.path.basename(path)}  ✔ saved")
            self.root.after(1600, self._set_title)
        except Exception as err:
            messagebox.showerror("Save Failed",
                                 f"Could not save the profile:\n\n{err}")

    # ─────────────────────────────────────────────────────────────────────────
    # App-level config (config.json) — machine settings, not the profile.
    # Keeps the ntfy topic / Chromium path / last profile path between runs.
    # ─────────────────────────────────────────────────────────────────────────
    def _load_app_config(self):
        last_profile = ""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    c = json.load(f)
                self.ntfy_topic    = c.get("ntfy_topic", "")
                self.chromium_path = c.get("chromium_path", "")
                last_profile       = c.get("last_profile", "")
                if self.chromium_path:
                    self.chrom_var.set(self.chromium_path)
            except Exception as err:
                print(f"[config] load error: {err}")

        if not self.ntfy_topic:
            self.ntfy_topic = secrets.token_hex(8)[:15]

        # Convenience: re-open the profile used last time, if it still exists.
        if last_profile and os.path.isfile(last_profile):
            try:
                with open(last_profile) as f:
                    self._apply_profile(json.load(f))
                self.profile_path = last_profile
                self._set_title()
            except Exception as err:
                print(f"[config] last-profile reload error: {err}")

    def _save_app_config(self):
        c = {
            "ntfy_topic":    self.ntfy_topic,
            "chromium_path": self.chromium_path,
            "last_profile":  self.profile_path or "",
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(c, f, indent=4)
        except Exception as err:
            print(f"[config] save error: {err}")

    # ─────────────────────────────────────────────────────────────────────────
    # Input validation
    # ─────────────────────────────────────────────────────────────────────────
    def _validate(self) -> bool:
        url = self.url_var.get().strip()
        if not url.startswith("http"):
            messagebox.showwarning(
                "Missing URL",
                "Please enter a valid URL (must start with http or https)."
            )
            return False

        try:
            iv = int(self.interval_var.get().strip())
            if not (30 <= iv <= 300):
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Invalid Interval",
                "Refresh interval must be a whole number between 30 and 300 seconds."
            )
            return False

        if not self.movie_var.get().strip():
            messagebox.showwarning(
                "Missing Movie Name",
                "Please enter the movie or text you want to detect."
            )
            return False

        if not (self.act_inapp_var.get() or
                self.act_sys_var.get() or
                self.act_ntfy_var.get()):
            messagebox.showwarning(
                "No Action Selected",
                "Please select at least one alert action."
            )
            return False

        if self.hide_var.get() == 1 and not self.saved_hotkey:
            messagebox.showwarning(
                "No Hotkey Recorded",
                "'Hide window' is enabled but no hotkey is recorded.\n"
                "Record one, or untick the hide option."
            )
            return False

        if not _port_open():
            messagebox.showerror(
                "Chromium Not Ready",
                f"Remote debug port {DEBUG_PORT} is not responding.\n\n"
                "Chromium has not started yet, or failed to launch.\n"
                "If auto-detection failed, use Browse to locate the executable\n"
                "and wait for the status line to turn green before retrying."
            )
            return False

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Widget state management
    # ─────────────────────────────────────────────────────────────────────────
    def _set_ui_state(self, state):
        for widget in self._input_widgets:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.config(state="readonly" if state == NORMAL
                                  else "disabled")
                else:
                    widget.config(state=state)
            except TclError:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Engine toggle (Start / Stop)
    # ─────────────────────────────────────────────────────────────────────────
    def _toggle_engine(self):
        if not self.is_running:
            if not self._validate():
                return
            self._save_app_config()
            self.is_running = True
            self.ctrl_btn.config(text="⏹  Stop Monitoring", bg="red")
            self._set_ui_state(DISABLED)

            if self.hide_var.get() == 1 and self.saved_hotkey:
                self._start_hotkey_listener()
                self.root.withdraw()

            self.monitor_thread = threading.Thread(
                target=self._scan_loop, daemon=True
            )
            self.monitor_thread.start()
        else:
            self._stop_engine()

    def _stop_engine(self):
        self.is_running = False
        self.ctrl_btn.config(text="▶  Start Monitoring", bg="green")
        self._set_ui_state(NORMAL)
        self._stop_hotkey_listener()
        self._unhide()

    # ─────────────────────────────────────────────────────────────────────────
    # Feature 3 — Detection engines
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _detect_simple(body: str, pattern: str) -> bool:
        """Original active logic: the pattern anywhere in the page text."""
        return pattern in body

    @staticmethod
    def _detect_section(body: str, pattern: str) -> bool:
        """
        Original commented logic, fixed: locate the 'Now Showing' heading and
        the 'Coming Soon' heading, search only the slice between them.
        """
        idx_now = -1
        for kw in KEYWORDS_NOW:
            idx_now = body.find(kw)
            if idx_now != -1:
                break

        idx_coming = -1
        for kw in KEYWORDS_COMING:
            idx_coming = body.find(kw)
            if idx_coming != -1:
                break

        if idx_now == -1:
            return False
        if idx_coming != -1 and idx_coming > idx_now:
            zone = body[idx_now:idx_coming]
        else:
            zone = body[idx_now:]
        return pattern in zone

    def _detect(self, body: str, pattern: str, engine: str) -> bool:
        if engine == DET_SIMPLE:
            return self._detect_simple(body, pattern)
        if engine == DET_SECTION:
            return self._detect_section(body, pattern)
        # DET_BOTH — section first (more precise), full-page as fallback
        return (self._detect_section(body, pattern) or
                self._detect_simple(body, pattern))

    # ─────────────────────────────────────────────────────────────────────────
    # Core scanning loop  (runs in a daemon background thread)
    # ─────────────────────────────────────────────────────────────────────────
    def _scan_loop(self):
        opts = _ChromeOptions()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")

        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as err:
            self.root.after(0, lambda e=str(err): self._on_driver_fail(e))
            return
        
        # ── Make every page believe it is visible & focused ─────────────
        _SPOOF_JS = """
            Object.defineProperty(document, 'visibilityState', {get: () => 'visible'});
            Object.defineProperty(document, 'hidden',        {get: () => false});
            Object.defineProperty(document, 'webkitHidden',  {get: () => false});
            document.hasFocus = () => true;
            document.addEventListener('visibilitychange',
                e => e.stopImmediatePropagation(), true);
            window.addEventListener('blur',
                e => e.stopImmediatePropagation(), true);
            window.addEventListener('pagehide',
                e => e.stopImmediatePropagation(), true);
            window.requestAnimationFrame =
                cb => setTimeout(() => cb(performance.now()), 16);
        """
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": _SPOOF_JS})
        except Exception as err:
            print(f"[scan] visibility spoof injection failed: {err}")

        url     = self.url_var.get().strip()
        pattern = self.movie_var.get().strip().lower()
        iv      = int(self.interval_var.get().strip())
        movie   = self.movie_var.get().strip()
        engine  = DET_FROM_LABEL.get(self.det_var.get(), DET_SIMPLE)
        mode    = MODE_FROM_LABEL.get(self.mode_var.get(), MODE_ONCE)
        detected = False

        try:
            driver.get(url)
        except Exception:
            pass

        while self.is_running:
            # Feature 4B: once detected in 'repeat' mode, stop touching the
            # page entirely — only the notifications keep firing below.
            check_page = (not detected) or (mode == MODE_RECHECK)
            found_now  = False

            if check_page:
                try:
                    if driver.current_url.rstrip("/") != url.rstrip("/"):
                        driver.get(url)
                    else:
                        driver.refresh()

                    time.sleep(4)  # Let the page fully render

                    # body = driver.find_element(By.TAG_NAME, "body").text.lower()
                    # print(body)  # For debugging only
                    body = driver.execute_script(
                        "var t = document.body.innerText;"
                        "return (t && t.trim().length > 40)"
                        "    ? t : document.body.textContent;"
                    ).lower()

                    found_now = self._detect(body, pattern, engine)
                    if found_now:
                        detected = True
                except Exception as loop_err:
                    print(f"[scan] error: {loop_err}")

            if detected:
                if mode == MODE_ONCE:
                    # 4A — alert once, then everything stops.
                    self.root.after(0, lambda m=movie: self._fire_alerts(m))
                    break
                elif mode == MODE_REPEAT:
                    # 4B — no more page checks; alert every interval.
                    self.root.after(0, lambda m=movie: self._fire_alerts(m))
                elif mode == MODE_RECHECK and found_now:
                    # 4C — page is still checked every cycle; alert whenever
                    # the movie is (still) found.
                    self.root.after(0, lambda m=movie: self._fire_alerts(m))

            # Interruptible wait so Stop button responds immediately
            for _ in range(iv):
                if not self.is_running:
                    break
                time.sleep(1)

        # 'Once' mode ends the session automatically; repeat modes run until
        # the user presses Stop (which already resets the UI itself).
        if detected and mode == MODE_ONCE:
            self.root.after(0, self._stop_engine)

    def _on_driver_fail(self, msg: str):
        self._stop_engine()
        messagebox.showerror(
            "WebDriver Error",
            f"Could not attach to Chromium on port {DEBUG_PORT}.\n\n"
            f"{msg}\n\n"
            "Make sure Chromium launched correctly.\n"
            "Check that the status line shows the port as active before starting."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Alert dispatch  (Feature 7: the blocking in-app popup ALWAYS fires last)
    # ─────────────────────────────────────────────────────────────────────────
    def _fire_alerts(self, movie: str):
        raw = self.msg_var.get().strip()
        msg = raw if raw else f"{movie} is open for tickets. BUY THEM NOW!"
        ttl = "Ticket Alert!"

        # 1) Non-blocking alerts first — each in its own thread.
        if self.act_sys_var.get():
            silent = bool(self.act_silent_var.get())
            threading.Thread(
                target=self._os_notify,
                args=(ttl, msg, silent),
                daemon=True,
            ).start()

        if self.act_ntfy_var.get():
            threading.Thread(
                target=self._ntfy_push,
                args=(msg,),
                daemon=True,
            ).start()

        # 2) The in-app popup LAST. messagebox.showinfo blocks the Tk thread,
        #    so it is deferred one tick to let the threads above dispatch,
        #    and guarded so repeat modes don't stack popups on top of popups.
        if self.act_inapp_var.get() and not self._popup_open:
            def _popup():
                self._popup_open = True
                try:
                    self._unhide()
                    messagebox.showinfo(ttl, msg)
                finally:
                    self._popup_open = False
            self.root.after(150, _popup)

    def _os_notify(self, title: str, msg: str, silent: bool):
        try:
            if IS_LINUX:
                cmd = ["notify-send", title, msg]
                if silent:
                    cmd += ["-u", "low", "-t", "3000"]
                subprocess.run(cmd,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            elif IS_WINDOWS:
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$n = New-Object System.Windows.Forms.NotifyIcon;"
                    "$n.Icon = [System.Drawing.SystemIcons]::Information;"
                    f"$n.BalloonTipTitle = '{title}';"
                    f"$n.BalloonTipText  = '{msg}';"
                    "$n.Visible = $true;"
                    "$n.ShowBalloonTip(6000);"
                )
                subprocess.run(
                    ["powershell", "-Command", ps],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as err:
            print(f"[notify] OS error: {err}")

    def _ntfy_push(self, msg: str):
        try:
            _requests.post(
                f"https://ntfy.sh/{self.ntfy_topic}",
                data=msg.encode("utf-8"),
                headers={"Title": "Ticket Alert", "Priority": "high"},
                timeout=10,
            )
        except Exception as err:
            print(f"[notify] ntfy error: {err}")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = Tk()
    TicketWatcher(root)
    root.mainloop()
