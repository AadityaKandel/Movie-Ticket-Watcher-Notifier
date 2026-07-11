# 🎬 Ticket Watcher

**Never miss a movie ticket again.** Ticket Watcher quietly monitors a movie-ticketing website in a real Chromium browser and alerts you — on your desktop *and* your phone — the instant your film goes on sale.

It does not scrape. It attaches to **your own browser session**, reads the page text locally in memory, and sends nothing to the website beyond the normal page refreshes at the interval you choose. It even keeps working while Chromium is minimized or buried under other windows.

---

## ✨ Features at a Glance

| | Feature |
|---|---------|
| 🖥️ | **Adaptive UI** — detects your display resolution *and* OS scaling percentage (Windows & Linux/X11) and sizes itself so every widget fits. Scrolls automatically on tiny screens. |
| 🎯 | **Three detection engines** — full-page match, section-based *Now Showing* match, or both. Switch per-website from a dropdown, no code editing. |
| 🔔 | **Three alert behaviours** — notify once and stop, keep repeating the alert, or keep re-checking the page and alerting. |
| ⌨️ | **Hotkey recorder** — press the combination instead of typing it. Global hotkey brings the hidden window back. |
| 💾 | **Profiles** — save complete configurations as files and reload them any time (`Ctrl+S` / `Ctrl+O` / `Ctrl+Alt+S`). |
| 📱 | **Phone push notifications** via [ntfy.sh](https://ntfy.sh) — free, no account, with a one-click *Copy Topic Key* button. |
| 🕶️ | **True background monitoring** — visibility spoofing makes the website render even when Chromium is minimized or unfocused. |

---

## Table of Contents

- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [One-Time Browser Setup](#one-time-browser-setup)
- [Quick Start](#quick-start)
- [The Interface, Top to Bottom](#the-interface-top-to-bottom)
- [Detection Methods Explained](#detection-methods-explained)
- [Alert Behaviours Explained](#alert-behaviours-explained)
- [Profiles: Save & Load Your Setup](#profiles-save--load-your-setup)
- [Phone Notifications via ntfy.sh](#phone-notifications-via-ntfysh)
- [Hotkey Setup on Linux](#hotkey-setup-on-linux)
- [Background Monitoring: How & Why It Works](#background-monitoring-how--why-it-works)
- [Files the App Creates](#files-the-app-creates)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## How It Works

1. The app launches Chromium with the `--remote-debugging-port` flag so Python can read the contents of the browser tab.
2. It navigates to your target URL and refreshes it at the interval you set.
3. After each refresh it reads the full page text **locally in memory** — no extra requests hit the server.
4. Your chosen **detection method** decides where on the page to look for the movie name (whole page, only the *Now Showing* section, or both). Matching is case-insensitive.
5. On detection, your chosen **alert behaviour** takes over: alert once and stop, or keep alerting every interval until you press Stop.

A small script is injected into every page load that makes the website believe its tab is always visible and focused — this is what lets monitoring continue while Chromium is minimized. See [Background Monitoring](#background-monitoring-how--why-it-works).

---

## Requirements

### Python

Python **3.8 or newer** — download from [python.org](https://www.python.org/downloads/).

### Python Libraries

The hotkey backend differs per platform, so install the set for your OS:

**Linux (Ubuntu with X11):**
```bash
pip install selenium requests pynput
```

**Windows:**
```bash
pip install selenium requests keyboard
```

**Optional (both platforms):**
```bash
pip install pyperclip
```
`pyperclip` improves the *Copy Topic Key* button. Without it, the app falls back to Tk's built-in clipboard, which also works — on Linux, installing `xclip` (`sudo apt install xclip`) makes pyperclip functional.

> The app checks for missing libraries at startup and tells you exactly which `pip install` command to run.

### ChromeDriver

Handled **automatically** by Selenium Manager (bundled with Selenium 4.6+). Nothing to download.

Check your version and upgrade if needed:
```bash
pip show selenium
pip install --upgrade selenium
```

### Chromium Browser

Download Chromium from the official page:
**[https://www.chromium.org/getting-started/download-chromium/](https://www.chromium.org/getting-started/download-chromium/)**

> **Google Chrome works too.** The app auto-detects whichever is installed.

---

## Installation

```bash
git clone https://github.com/AadityaKandel/Movie-Ticket-Watcher-Notifier.git
cd ticket-watcher
pip install selenium requests pynput      # Linux
# pip install selenium requests keyboard  # Windows
```

That's it — no build step.

---

## One-Time Browser Setup

**Do this before your first monitoring run.** The app uses a dedicated browser profile so your cookie acceptances and logins persist between runs. If you skip this, consent banners can cover the page during automated refreshes and break detection.

1. Run the app once. It launches Chromium using its own profile folder (`chromium_session`, created next to the script).
2. **In that Chromium window**, navigate to the website you want to monitor.
3. Click through **every** cookie banner, consent notice, and "Got it" popup.
4. If the site requires login to show listings, log in now.
5. Scroll the page and confirm it loads cleanly with no overlays.

You only do this once per website. The acceptances are stored in `chromium_session` — **don't delete that folder**, or you'll have to accept everything again.

---

## Quick Start

```bash
python ticket_watcher.py
```

1. Wait for the status line to turn **green** (`✔ Chromium ready (port 9222)`).
2. Paste the **full URL** of the *Now Showing* page.
3. Set the **refresh interval** (30–300 seconds; `60` is a good default).
4. Type the **movie name** exactly as the website spells it.
5. Pick a **detection method** and an **alert behaviour** (the `?` buttons explain each option).
6. Tick at least one **alert action**.
7. Press **▶ Start Monitoring** — then minimize everything and get on with your day. 🍿

---

## The Interface, Top to Bottom

### Chromium Executable
Shows the detected browser path and a live status:

| Status | Meaning |
|--------|---------|
| 🟠 *Detecting…* | Searching for the executable / waiting for launch |
| 🟢 *✔ Chromium ready (port 9222)* | Connected — you can start monitoring |
| 🔴 *✘ Not found* | Auto-detection failed — click **Browse…** |

Common locations if you need to browse manually:

| Platform | Typical path |
|----------|-------------|
| Linux    | `/usr/bin/chromium-browser` or `/usr/bin/google-chrome` |
| Windows  | `C:\Program Files\Google\Chrome\Application\chrome.exe` |

### Target URL
Enter the **full URL of the listings page**, not the homepage:
```
https://www.example.com/movies/now-showing
```
It's fine if *Now Showing* and *Coming Soon* share one page — the section-based detection method handles that.

### Refresh Interval
How often the page is reloaded and checked, in seconds. Allowed range: **30–300**. This same interval also drives the repeat cadence of the repeat alert behaviours — there is deliberately no second timer to configure.

### Movie / Text to Detect
Type the title **exactly as the website spells it** (not as Google or IMDb spells it). Matching is case-insensitive. If the title is a common phrase, use a distinctive word unique to that film's listing. The `?` button repeats this advice in-app.

### Detection Method
A dropdown with three engines — see [Detection Methods Explained](#detection-methods-explained). The `?` button describes whichever option is currently selected, including its trade-offs.

### Hide Window While Monitoring
Tick this and a **hotkey recorder** opens: hold your modifiers (Ctrl / Alt / Shift / Win) and press a key — the combination is captured automatically, no typing and no syntax to remember. A **Clear** button lets you redo it. When monitoring starts, the window vanishes; press your hotkey any time to bring it back.

> Linux users: global hotkeys need an X11 session — see [Hotkey Setup on Linux](#hotkey-setup-on-linux).

### Alert Actions
Pick one or more (at least one is required):

| Option | What it does |
|--------|-------------|
| **In-app popup** | Unhides the window and shows a dialog. Always fires **last**, so it can never delay the other alerts. |
| **System desktop notification** | Native OS banner (`notify-send` on Linux, PowerShell on Windows). |
| **↳ Silent / low-priority** | Makes the system notification quiet. Only applies when the one above is ticked. |
| **Push to phone via ntfy.sh** | Instant push notification to your phone. The `?` button contains setup steps *and* a **Copy Topic Key** button. |

### Alert Behaviour
A dropdown choosing what happens *after* detection — see [Alert Behaviours Explained](#alert-behaviours-explained).

### Custom Alert Message
Optional. Leave blank for the automatic message:
```
<Movie Name> is open for tickets. BUY THEM NOW!
```

---

## Detection Methods Explained

Different websites structure their pages differently. Instead of editing code per site, pick the engine that fits:

| Method | How it searches | Best for |
|--------|----------------|----------|
| **Full-page match (simple)** | The movie name anywhere in the page's visible text. | Sites with unusual layouts or no clear section headings. ⚠️ May alert early if the film is listed under *Coming Soon* on the same page. |
| **Section-based match** | Finds a *Now Showing / Showing Now / Current Release* heading, then a *Coming Soon / Upcoming / Next Release* heading, and searches **only the text between them**. | Classic ticketing sites. Ignores films that are merely announced. Detects nothing if the headings don't exist. |
| **Both** | Tries the section-based match first; falls back to full-page if it finds nothing. | When you're not sure how the site is built. Inherits the early-alert caveat of full-page on some sites. |

The `?` button beside the dropdown explains the currently selected option in-app.

---

## Alert Behaviours Explained

| Behaviour | After the first detection… | Use when |
|-----------|---------------------------|----------|
| **Notify once, then stop** | Every selected alert fires once, monitoring ends. | One heads-up is enough. |
| **Repeat notifications (check once)** | The page is **not** checked again. Alerts re-fire every refresh interval until you press **Stop**. | You might miss the first ping — the app keeps nagging without wasting reloads. |
| **Repeat + keep re-checking** | The page keeps reloading every interval; alerts fire each time the film is **still** found. | Listings that appear/disappear (shows selling out) and you want live confirmation with every alert. |

The repeat cadence always equals your **Refresh Interval**.

> 📱 Heads-up: in the repeat behaviours, phone pushes also repeat every interval. Your pocket will buzz. That's the point — but maybe not overnight.

---

## Profiles: Save & Load Your Setup

Everything on screen — URL, interval, movie, detection method, alert behaviour, actions, hotkey, custom message — can be saved as a **profile file** and reloaded later. Keep one profile per cinema, per movie, or per use case.

| Action | Menu | Shortcut | Behaviour |
|--------|------|----------|-----------|
| Open a profile | File ▸ Open Profile… | `Ctrl+O` | Pick a `.json` profile; all fields update instantly. |
| Save | File ▸ Save Profile | `Ctrl+S` | **First press** in a session acts like Save As (asks where). Every later press saves **silently** to the same file — a brief *✔ saved* flashes in the title bar. |
| Save As | File ▸ Save Profile As… | `Ctrl+Alt+S` | Always opens the file dialog, e.g. to fork a profile under a new name. |

The app also remembers your **last used profile** and reloads it automatically on the next launch.

---

## Phone Notifications via ntfy.sh

[ntfy.sh](https://ntfy.sh) is a free, open-source push service — no account needed.

1. Install the **ntfy** app:
   - Android → [Google Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   - iOS → [Apple App Store](https://apps.apple.com/app/ntfy/id1625396347)
2. In Ticket Watcher, click the **`?`** next to the ntfy option. The dialog shows your unique topic key with a **Copy Topic Key** button — click it, done.
3. In the phone app, tap **＋ → Subscribe to topic** and paste the key.
4. Tick the ntfy checkbox before starting. Every detection now pushes straight to your phone.

> 🔒 **Keep the topic key private.** It's a random 15-character string; anyone who knows it can receive your notifications.

---

## Hotkey Setup on Linux

Global hotkeys require **X11/Xorg** — Wayland blocks background keyboard listeners by design.

**Switch to X11:**
1. Log out.
2. On the login screen, click the gear **⚙** (bottom-right).
3. Choose **"Ubuntu on Xorg"** (or any X11/Xorg option).
4. Log back in.

**If X11 isn't listed:**
```bash
sudo apt install xorg
```

**Permanent switch** — edit `/etc/gdm3/custom.conf`, uncomment `WaylandEnable=false`, reboot:
```ini
[daemon]
WaylandEnable=false
```

> Windows users: nothing to do — hotkeys work out of the box via the `keyboard` library.

---

## Background Monitoring: How & Why It Works

Modern browsers throttle and even freeze minimized/covered windows, and many websites additionally use the **Page Visibility API** to stop rendering when their tab isn't visible. That combination is why naive automation goes blank the moment you switch apps.

Ticket Watcher counters both layers:

1. **Browser-side:** Chromium is launched with throttling disabled (`--disable-background-timer-throttling`, `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding`, and occlusion detection off).
2. **Website-side:** a script injected before every page load makes the site believe its tab is permanently visible and focused, and keeps `requestAnimationFrame` ticking so JavaScript-rendered content keeps painting.
3. **Reading-side:** page text is read in a paint-independent way, with a `textContent` fallback for anything that hasn't visually rendered.

Result: minimize Chromium, bury it under ten windows, walk away — detection keeps working.

> If a future site update ever reintroduces the problem, a commented `--headless=new` fallback is left in the code: a headless browser always reports itself as visible, so there is no window to focus at all.

---

## Files the App Creates

| File / folder | Purpose | Safe to delete? |
|---------------|---------|-----------------|
| `config.json` | Machine-level settings: ntfy topic key, Chromium path, last used profile. | Deleting regenerates a **new** ntfy topic — you'd need to re-subscribe on your phone. |
| `chromium_session/` | The dedicated browser profile holding your accepted cookies and logins. | Deleting means redoing the [one-time browser setup](#one-time-browser-setup). |
| Your `.json` profiles | Full saved configurations, stored wherever you chose. | Yes — they're just your own save files. |

---

## Troubleshooting

**Chromium doesn't launch automatically**
Use **Browse…** to locate the executable manually (paths listed [above](#chromium-executable)). Make sure Chromium is installed, not just downloaded as an archive.

**Status stays orange / never turns green**
Chromium may be waiting on a first-run prompt ("Make Chromium your default browser?"). Click through it, or close Chromium and click Browse to relaunch.

**"WebDriver Error" on Start**
Python reached the browser but ChromeDriver doesn't match your Chromium version:
```bash
pip install --upgrade selenium
```
Selenium Manager fetches the right driver automatically on the next start.

**The film is detected instantly on the first check**
Your search term probably also appears in the *Coming Soon* section, a recommendation widget, or a footer. Switch the **Detection Method** dropdown to **Section-based match** so only the *Now Showing* region is searched — no code editing required.

**Nothing is ever detected with Section-based match**
The page likely lacks the expected headings (*Now Showing* / *Coming Soon* etc.). Switch to **Full-page** or **Both**. The `?` button explains what each engine expects.

**Detection stops when Chromium is minimized**
This shouldn't happen — background monitoring is built in. If a site update breaks it, enable the commented headless fallback in the code (search for `--headless` in `_launch_exe`).

**Cookie banner keeps reappearing during refreshes**
The [one-time browser setup](#one-time-browser-setup) wasn't completed, or `chromium_session` was deleted. Accept all prompts in the app-launched browser window and try again.

**Global hotkey does nothing on Linux**
You're on Wayland. Follow [Hotkey Setup on Linux](#hotkey-setup-on-linux).

**Hotkey recorder captures nothing**
Linux: confirm `pynput` is installed and you're on X11. Windows: confirm `keyboard` is installed; some setups require running the terminal as Administrator for global hooks.

**No push notification on the phone**
- Verify the phone app is subscribed to the **exact** topic key (use *Copy Topic Key* to avoid typos).
- Check the phone has internet.
- Confirm the ntfy checkbox was ticked **before** pressing Start.
- If you deleted `config.json`, a new key was generated — re-subscribe.

**Ctrl+S opened a file dialog again**
That's by design for the *first* save of each session. Every save after that is silent. `Ctrl+Alt+S` is the one that always asks.

---

## License

MIT — do whatever you want with it, as long as a copy of the license is included in all modifications or copies of the script.
