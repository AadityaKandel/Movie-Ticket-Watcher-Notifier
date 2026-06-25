#!/usr/bin/env python3
"""
Ticket Watcher
==============
Monitors a movie-ticketing website in a live Chromium browser and alerts
the user the moment a film appears in the "Now Showing" section.

Requirements (install once):
    pip install selenium requests pynput

Chromium / Chrome is launched automatically when the app starts.
If the executable cannot be found automatically, use the Browse button.
"""

import json
import os
import platform
import secrets
import shutil
import socket
import subprocess
import threading
import time
from tkinter import *
from tkinter import filedialog, messagebox

# ── Optional-dependency guards ────────────────────────────────────────────────
_MISSING = []

try:
    import requests as _requests
except ImportError:
    _requests = None          # type: ignore
    _MISSING.append("requests")

try:
    from pynput import keyboard as _pynput_kb
    _PYNPUT_OK = True
except ImportError:
    _pynput_kb = None         # type: ignore
    _PYNPUT_OK = False
    _MISSING.append("pynput")

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as _ChromeOptions
    from selenium.webdriver.common.by import By
    _SELENIUM_OK = True
except ImportError:
    _SELENIUM_OK = False
    _MISSING.append("selenium")

# ── Constants ─────────────────────────────────────────────────────────────────
_DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(_DIR, "config.json")
PROFILE_DIR  = os.path.join(_DIR, "chromium_session")
DEBUG_PORT   = 9222

# ── Chromium executable discovery ────────────────────────────────────────────
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
    # 1. Saved path from config
    if saved and os.path.isfile(saved):
        return saved

    if platform.system() == "Linux":
        for cmd in _LINUX_CMDS:
            found = shutil.which(cmd)
            if found:
                return found

    elif platform.system() == "Windows":
        # Check well-known install locations
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
        # Also try PATH
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
        self.root.resizable(False, False)

        # ── Runtime state ──────────────────────────────────────────────────
        self.is_running       = False
        self.monitor_thread   = None
        self.hotkey_listener  = None
        self.chromium_proc    = None

        # ── Persistent state (loaded from / saved to config.json) ──────────
        self.saved_hotkey  = ""
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

        self._build_ui()
        self._load_config()
        # Attempt Chromium auto-launch after the event loop is ready
        root.after(350, self._auto_launch_chromium)

    # ─────────────────────────────────────────────────────────────────────────
    # UI Construction
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        P  = dict(padx=14, pady=(9, 2))   # standard label padding
        P2 = dict(padx=14, pady=2)        # standard widget padding

        # ── Section: Chromium executable ──────────────────────────────────
        Label(self.root, text="Chromium / Chrome Executable:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)

        chrom_row = Frame(self.root)
        chrom_row.pack(fill=X, **P2)
        self.chrom_entry = Entry(chrom_row, textvariable=self.chrom_var, width=52)
        self.chrom_entry.pack(side=LEFT)
        self.browse_btn = Button(chrom_row, text="Browse…",
                                 command=self._browse_chromium)
        self.browse_btn.pack(side=LEFT, padx=(6, 0))

        self.lbl_chrom = Label(self.root, text="  Detecting…",
                               fg="orange", font=("Arial", 9))
        self.lbl_chrom.pack(anchor=W, padx=14, pady=(1, 4))

        Frame(self.root, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=6)

        # ── Section: Target URL ───────────────────────────────────────────
        Label(self.root,
              text="Target URL  (full path, e.g. https://example.com/now-showing):",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        self.url_entry = Entry(self.root, textvariable=self.url_var, width=66)
        self.url_entry.pack(anchor=W, **P2)

        # ── Section: Refresh interval ─────────────────────────────────────
        Label(self.root, text="Refresh Interval — seconds  (min 30 · max 300):",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        self.interval_entry = Entry(self.root, textvariable=self.interval_var, width=14)
        self.interval_entry.pack(anchor=W, **P2)

        # ── Section: Movie name ───────────────────────────────────────────
        movie_hdr = Frame(self.root)
        movie_hdr.pack(fill=X, padx=14, pady=(9, 2))
        Label(movie_hdr, text="Movie / Text to Detect:",
              font=("Arial", 10, "bold")).pack(side=LEFT)
        Button(movie_hdr, text=" ? ", relief=RIDGE, font=("Arial", 8),
               command=self._tip_movie_name).pack(side=LEFT, padx=5)

        self.movie_entry = Entry(self.root, textvariable=self.movie_var, width=66)
        self.movie_entry.pack(anchor=W, **P2)

        Frame(self.root, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=8)

        # ── Section: Hide window / hotkey ─────────────────────────────────
        hide_frame = Frame(self.root, bd=1, relief=GROOVE)
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

        Frame(self.root, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=6)

        # ── Section: Alert actions ────────────────────────────────────────
        Label(self.root, text="Alert Actions on Detection:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        act_frame = Frame(self.root, bd=1, relief=GROOVE)
        act_frame.pack(fill=X, padx=14, pady=4, ipady=4)

        self.chk_inapp = Checkbutton(
            act_frame,
            text="In-app popup  (unhides window automatically)",
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

        # ── Section: Custom message ───────────────────────────────────────
        Label(self.root, text="Custom Alert Message:",
              font=("Arial", 10, "bold")).pack(anchor=W, **P)
        self.msg_entry = Entry(self.root, textvariable=self.msg_var, width=66)
        self.msg_entry.pack(anchor=W, **P2)
        Label(self.root,
              text='Leave blank → auto: "<Movie> is open for tickets. BUY THEM NOW!"',
              fg="gray", font=("Arial", 8)).pack(anchor=W, padx=14)

        Frame(self.root, height=1, bg="#bbbbbb").pack(fill=X, padx=14, pady=8)

        # ── Start / Stop button ───────────────────────────────────────────
        self.ctrl_btn = Button(self.root, text="▶  Start Monitoring",
                               bg="green", fg="white",
                               font=("Arial", 11, "bold"),
                               height=2, command=self._toggle_engine)
        self.ctrl_btn.pack(fill=X, padx=14, pady=(0, 14))

        # All widgets that must be disabled while monitoring
        self._input_widgets = [
            self.chrom_entry, self.browse_btn,
            self.url_entry, self.interval_entry, self.movie_entry,
            self.hide_chk, self.linux_guide_btn,
            self.chk_inapp, self.chk_sys, self.chk_silent, self.chk_ntfy,
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

    def _guide_ntfy(self):
        messagebox.showinfo(
            "Phone Notifications — ntfy.sh Setup",
            "1. Install the free 'ntfy' app:\n"
            "      Android → Google Play Store\n"
            "      iOS     → Apple App Store\n\n"
            "2. Open the app → tap '+' → 'Subscribe to topic'.\n"
            "3. Enter your unique topic key shown below.\n\n"
            f"Your topic key:  {self.ntfy_topic}\n\n"
            "This key is stored in config.json — keep it private.\n"
            "Anyone who knows it can receive your notifications."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Chromium auto-launch
    # ─────────────────────────────────────────────────────────────────────────
    def _browse_chromium(self):
        """Let the user manually locate the Chromium / Chrome executable."""
        if platform.system() == "Windows":
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
            # Kill any previously launched process and relaunch with new path
            self._kill_chromium_proc()
            self._auto_launch_chromium()

    def _auto_launch_chromium(self):
        """
        Attempt to start Chromium with remote-debugging enabled.
        1. If port 9222 is already open → nothing to do.
        2. Try to find the executable automatically (or use saved path).
        3. If still not found → show a warning and ask the user to Browse.
        """
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
        """Start the executable with --remote-debugging-port and a dedicated profile."""
        os.makedirs(PROFILE_DIR, exist_ok=True)
        cmd = [
            exe,
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
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
        """Check every 700 ms whether port 9222 has come online (up to ~13 s)."""
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
        """Terminate a previously launched Chromium process, if any."""
        if self.chromium_proc and self.chromium_proc.poll() is None:
            try:
                self.chromium_proc.terminate()
            except Exception:
                pass
        self.chromium_proc = None

    # ─────────────────────────────────────────────────────────────────────────
    # Hide-window / global hotkey
    # ─────────────────────────────────────────────────────────────────────────
    def _on_hide_toggled(self):
        if self.hide_var.get() == 1:
            self._open_hotkey_dialog()
        else:
            self.saved_hotkey = ""
            self.lbl_hotkey.config(text="Hotkey: [Not configured]", fg="red")

    def _open_hotkey_dialog(self):
        dlg = Toplevel(self.root)
        dlg.title("Configure Hotkey")
        dlg_width = (30 * dlg.winfo_screenwidth()) // 100
        dlg_height = (20* dlg.winfo_screenheight()) // 100
        dlg.geometry(f"{dlg_width}x{dlg_height}")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        # dlg.grab_set()
        dlg.focus_set()

        Label(dlg, text="Enter a hotkey to show the hidden window:",
              font=("Arial", 10, "bold")).pack(pady=10)

        hk_var = StringVar()
        hk_entry = Entry(dlg, textvariable=hk_var, width=36)
        hk_entry.pack()
        hk_entry.focus_set()

        Label(dlg, text="Examples:  <ctrl>+<alt>+t     <ctrl>+h",
              fg="#555").pack(pady=3)

        def _save():
            val = hk_var.get().strip().lower()
            parts = [p.strip() for p in val.split("+") if p.strip()]
            # Must have at least 2 parts; each part is either <modifier> or single char
            valid = (
                len(parts) >= 2 and
                all(
                    (p.startswith("<") and p.endswith(">")) or len(p) == 1
                    for p in parts
                )
            )
            if not valid:
                messagebox.showerror(
                    "Invalid Hotkey",
                    "Enter a valid hotkey, e.g.  <ctrl>+<alt>+t",
                    parent=dlg,
                )
                # Uncheck the checkbox since no valid hotkey was set
                self.hide_var.set(0)
                dlg.grab_release()
                dlg.destroy()
                return
            self.saved_hotkey = val
            self.lbl_hotkey.config(text=f"Hotkey: {val}", fg="green")
            dlg.grab_release()
            dlg.destroy()

        def _cancel():
            if not self.saved_hotkey:
                self.hide_var.set(0)
                self.lbl_hotkey.config(text="Hotkey: [Not configured]", fg="red")
            dlg.grab_release()
            dlg.destroy()

        bf = Frame(dlg)
        bf.pack(pady=10)
        Button(bf, text="Save",   width=11, command=_save).pack(side=LEFT, padx=5)
        Button(bf, text="Cancel", width=11, command=_cancel).pack(side=LEFT, padx=5)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

    def _start_hotkey_listener(self):
        if self.hotkey_listener or not _PYNPUT_OK:
            return
        try:
            self.hotkey_listener = _pynput_kb.GlobalHotKeys(
                {self.saved_hotkey: lambda: self.root.after(0, self._unhide)}
            )
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

    def _unhide(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ─────────────────────────────────────────────────────────────────────────
    # Configuration persistence
    # ─────────────────────────────────────────────────────────────────────────
    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    c = json.load(f)

                self.url_var.set(c.get("url", ""))
                self.interval_var.set(str(c.get("interval", "60")))
                self.movie_var.set(c.get("movie_name", ""))
                self.msg_var.set(c.get("custom_message", ""))
                self.act_inapp_var.set(c.get("act_inapp", 0))
                self.act_sys_var.set(c.get("act_sys", 0))
                self.act_silent_var.set(c.get("act_silent", 0))
                self.act_ntfy_var.set(c.get("act_ntfy", 0))
                self.ntfy_topic    = c.get("ntfy_topic", "")
                self.chromium_path = c.get("chromium_path", "")

                if self.chromium_path:
                    self.chrom_var.set(self.chromium_path)

                hk = c.get("hotkey", "")
                if hk:
                    self.saved_hotkey = hk
                    # Explicitly select the checkbutton and update the label
                    self.hide_var.set(1)
                    self.hide_chk.select()
                    self.lbl_hotkey.config(text=f"Hotkey: {hk}", fg="green")

            except Exception as err:
                print(f"[config] load error: {err}")

        # Generate ntfy topic if not yet stored
        if not self.ntfy_topic:
            self.ntfy_topic = secrets.token_hex(8)[:15]

    def _save_config(self):
        c = {
            "url":            self.url_var.get().strip(),
            "interval":       self.interval_var.get().strip(),
            "movie_name":     self.movie_var.get().strip(),
            "custom_message": self.msg_var.get().strip(),
            "act_inapp":      self.act_inapp_var.get(),
            "act_sys":        self.act_sys_var.get(),
            "act_silent":     self.act_silent_var.get(),
            "act_ntfy":       self.act_ntfy_var.get(),
            "ntfy_topic":     self.ntfy_topic,
            "hotkey":         self.saved_hotkey if self.hide_var.get() == 1 else "",
            "chromium_path":  self.chromium_path,
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
            self._save_config()
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
        """Reset all state back to idle. Safe to call from any thread via root.after."""
        self.is_running = False
        self.ctrl_btn.config(text="▶  Start Monitoring", bg="green")
        self._set_ui_state(NORMAL)
        self._stop_hotkey_listener()
        self._unhide()

    # ─────────────────────────────────────────────────────────────────────────
    # Core scanning loop  (runs in a daemon background thread)
    # ─────────────────────────────────────────────────────────────────────────
    def _scan_loop(self):
        opts = _ChromeOptions()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{DEBUG_PORT}")

        # Selenium 4.6+ ships "Selenium Manager" which auto-downloads chromedriver.
        # Simply call webdriver.Chrome() — no Service / webdriver-manager needed.
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as err:
            self.root.after(0, lambda e=str(err): self._on_driver_fail(e))
            return

        url     = self.url_var.get().strip()
        pattern = self.movie_var.get().strip().lower()
        iv      = int(self.interval_var.get().strip())
        movie   = self.movie_var.get().strip()
        detected = False

        # Navigate to the target page initially
        try:
            driver.get(url)
        except Exception:
            pass

        while self.is_running:
            try:
                # Stay on the correct page; refresh if already there
                if driver.current_url.rstrip("/") != url.rstrip("/"):
                    driver.get(url)
                else:
                    driver.refresh()

                time.sleep(4)  # Let the page fully render

                body = driver.find_element(By.TAG_NAME, "body").text.lower()
                # print(body) # For debugging only

                '''
                # Explanation: Here, the idx_now variable is supposed to find "now showing" string and the 
                # idx_coming variable is supposed to find "coming soon" string. Once found, the script assumes
                # that the movie names will come below/after these strings. If x movie is supposed to be in the 
                # "now showing" section, the script assumes that x movie string will only be found after the index
                # of the "now showing" string to the index of the "coming soon" string. If that's the case for the 
                # website you're aiming, you can un-comment this comment and remove the conditional statement that
                # is written after this comment ends. That conditional statement tries to find the movie name in the 
                # body itself. If you don't know if your movie name comes after the "now showing" string, you can print
                # the body and check for yourself.


                possible_keywords_idx_now = ["now showing", "showing now", "current release"] # Add more keyword if you have to
                possible_keywords_idx_coming = ["coming soon", "upcoming", "next release"] # Add more keyword if you have to

                for keywords in possible_keywords_idx_now:
                    idx_now = body.find(keywords)
                    if idx_now!=-1:
                        break
                
                for keywords in possible_keywords_idx_coming:
                    idx_coming = body.find(keywords)
                    if idx_coming!=-1:
                        break

                if idx_now != -1:
                    # Slice only the "Now Showing" region
                    if idx_coming != -1 and idx_coming > idx_now:
                        zone = body[idx_now:idx_coming]
                    else:
                        zone = body[idx_now:]

                    if pattern in zone:
                        detected = True
                        self.root.after(0, lambda m=movie: self._fire_alerts(m))
                        break   # Stop after first successful detection
                '''

                if pattern in body:
                    detected = True
                    self.root.after(0, lambda m=movie: self._fire_alerts(m))
                    break   # Stop after first successful detection

            except Exception as loop_err:
                print(f"[scan] error: {loop_err}")

            # Interruptible wait so Stop button responds immediately
            for _ in range(iv):
                if not self.is_running:
                    break
                time.sleep(1)

        # Re-enable the UI on the main thread
        if detected:
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
    # Alert dispatch
    # ─────────────────────────────────────────────────────────────────────────
    def _fire_alerts(self, movie: str):
        raw = self.msg_var.get().strip()
        msg = raw if raw else f"{movie} is open for tickets. BUY THEM NOW!"
        ttl = "Ticket Alert!"

        if self.act_inapp_var.get():
            self._unhide()
            messagebox.showinfo(ttl, msg)

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

    def _os_notify(self, title: str, msg: str, silent: bool):
        try:
            if platform.system() == "Linux":
                cmd = ["notify-send", title, msg]
                if silent:
                    cmd += ["-u", "low", "-t", "3000"]
                subprocess.run(cmd,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            elif platform.system() == "Windows":
                # PowerShell tray balloon notification
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
