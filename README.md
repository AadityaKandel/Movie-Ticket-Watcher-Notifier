# Ticket Watcher

A lightweight Python desktop application that monitors a movie-ticketing website in a live Chromium browser and instantly alerts you the moment a film appears in the **Now Showing** section — so you can buy tickets before they sell out.

It does not scrape. It attaches to your own running browser session, reads the page text locally on your machine, and never sends any additional requests to the website's server beyond normal page refreshes at the interval you set.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [One-Time Browser Setup](#one-time-browser-setup)
- [Running the App](#running-the-app)
- [Using the Interface](#using-the-interface)
  - [Chromium Executable](#chromium-executable)
  - [Target URL](#target-url)
  - [Refresh Interval](#refresh-interval)
  - [Movie / Text to Detect](#movie--text-to-detect)
  - [Hide Window While Monitoring](#hide-window-while-monitoring)
  - [Alert Actions](#alert-actions)
  - [Custom Alert Message](#custom-alert-message)
- [Configuration File](#configuration-file)
- [Hotkey Setup on Linux](#hotkey-setup-on-linux)
- [Phone Notifications via ntfy.sh](#phone-notifications-via-ntfysh)
- [Troubleshooting](#troubleshooting)

---

## How It Works

1. The app launches Chromium with a special `--remote-debugging-port` flag that allows Python to read the contents of the browser tab.
2. It navigates to the URL you provide (e.g. the "Now Showing" page of a ticketing site) and refreshes it at your chosen interval.
3. After each refresh it reads the full page text **locally in memory** — no additional network request is made to the server.
4. It locates the `Now Showing` section of the text and slices out everything up to the `Coming Soon` section. Your search term is then checked against only that region, case-insensitively.
5. The moment your film is found in the **Now Showing** slice, your chosen alert actions fire and monitoring stops.

---

## Requirements

### Python

Python **3.8 or newer** is required. Download it from [python.org](https://www.python.org/downloads/).

### Python Libraries

Install all three libraries with a single command:

```bash
pip install selenium requests pynput
```

Or individually:

```bash
pip install selenium
pip install requests
pip install pynput
```

### ChromeDriver

ChromeDriver is downloaded **automatically** by Selenium's built-in Selenium Manager (included with Selenium 4.6 and above). You do not need to install or manage it manually as long as you have Selenium 4.6+.

Verify your Selenium version after installing:

```bash
pip show selenium
```

If the version shown is below 4.6, upgrade it:

```bash
pip install --upgrade selenium
```

### Chromium Browser

Download and install Chromium from the official source:

**[https://www.chromium.org/getting-started/download-chromium/](https://www.chromium.org/getting-started/download-chromium/)**

> **Note:** Google Chrome also works. The app will detect it automatically if Chromium is not found. The instructions below apply equally to both.

---

## Installation

1. Clone or download this repository.

```bash
git clone https://github.com/AadityaKandel/Movie-Ticket-Watcher-Notifier.git
cd ticket-watcher
```

2. Install the required libraries:

```bash
pip install selenium requests pynput
```

3. That is all. No build step is needed.

---

## One-Time Browser Setup

This is the most important step and must be done **before you start monitoring**.

The app attaches to your real browser session so that any cookies, accepted terms, and login states are already in place. If you skip this, the website may show cookie banners, popups, or login walls during automated refreshes, which will interfere with page text detection.

**Steps:**

1. Open the `chromium_session` folder that the app creates in the same directory as `ticket_watcher.py` after its first launch. This is the dedicated browser profile the app uses.

   > Alternatively, just run the app once and let it launch Chromium, then proceed with the steps below in that browser window.

2. In the Chromium window opened by the app, navigate to the website you want to monitor, for example:

   ```
   https://www.example.com/now-showing
   ```

3. **Accept all cookie banners, consent notices, and terms-of-service popups** that appear. Click every "Accept", "I Agree", or "Got it" button you see. These acceptances are stored in the `chromium_session` profile folder.

4. If the website requires you to be logged in to see movie listings, log in now and make sure the session is active.

5. Scroll through the page and confirm it is fully loaded with no remaining popups or overlays.

6. You only need to do this once per website. From the second run onwards, the saved session in `chromium_session` will already have your accepted cookies and the page will load cleanly.

> **Important:** Do not delete the `chromium_session` folder after completing setup. Deleting it will erase your saved cookies and you will need to accept everything again.

---

## Running the App

```bash
python ticket_watcher.py
```

On first launch, the app will:

1. Try to locate your Chromium or Chrome executable automatically.
2. Launch it in the background with remote debugging enabled on port `9222`.
3. Wait for the browser to be ready, shown by the status line turning green.

If Chromium is not found automatically, a warning will appear and you can use the **Browse** button to point to the executable manually. See [Chromium Executable](#chromium-executable) below.

---

## Using the Interface

### Chromium Executable

The top row shows the path to the Chromium or Chrome executable and a status indicator.

- **Detecting…** (orange) — the app is searching for the executable.
- **✔ Chromium ready (port 9222)** (green) — the browser is running and the app is connected.
- **✘ Not found** (red) — automatic detection failed.

If detection fails, click **Browse…** and navigate to the Chromium or Chrome binary on your system.

Common locations:

| Platform | Typical path |
|----------|-------------|
| Linux    | `/usr/bin/chromium-browser` or `/usr/bin/google-chrome` |
| Windows  | `C:\Program Files\Google\Chrome\Application\chrome.exe` |

Once you select a path and the status turns green, you are ready to proceed.

---

### Target URL

Enter the **full URL** of the page you want to monitor, including the directory path. Do not enter just the homepage — go to the specific section of the website that lists Now Showing and Coming Soon films, for example:

```
https://www.example.com/movies/now-showing
```

The more specific the URL, the better. If the Now Showing and Coming Soon listings are both on a single page, that is perfectly fine — the app handles that automatically by reading only the text between those two section headings.

---

### Refresh Interval

Enter how often (in seconds) the page should be refreshed and checked. The allowed range is **30 to 300 seconds** (30 seconds to 5 minutes).

- Values below 30 or above 300 will fail validation and the app will not start.
- A value of `60` (one minute) is a reasonable default for most use cases.

---

### Movie / Text to Detect

Enter the name of the film exactly as it appears on the website's Now Showing or Coming Soon listing — **not** as it appears on Google or IMDb.

- Matching is **case-insensitive**. You can type in uppercase, lowercase, or a mix.
- If the film's full title is a common phrase that might appear elsewhere on the page, use a distinctive word or partial phrase that uniquely identifies it in the listing.
- Click the **`?`** button next to the label to see this reminder at any time.

---

### Hide Window While Monitoring

Check this box if you want the app window to disappear from the screen once monitoring starts, running silently in the background.

When you check this box, a small dialog will open asking for a **global hotkey** to bring the window back.

- Enter a key combination using the format `<ctrl>+<alt>+t` or `<ctrl>+h`.
- Both parts must be present — a modifier key (e.g. `<ctrl>`, `<alt>`, `<shift>`) and a regular key.
- If you enter an invalid hotkey or close the dialog without saving, the checkbox will automatically uncheck itself.
- A valid hotkey is saved to `config.json` and will be remembered the next time you run the app.

> **Linux users:** Global hotkeys require an X11 session. Click the **Linux Hotkey Guide** button for step-by-step instructions. See also [Hotkey Setup on Linux](#hotkey-setup-on-linux).

---

### Alert Actions

Select one or more actions to trigger when the film is detected. At least one must be chosen.

| Option | Description |
|--------|-------------|
| **In-app popup** | Brings the window back to focus (if hidden) and shows a popup dialog. |
| **System desktop notification** | Sends a native OS banner notification (uses `notify-send` on Linux, PowerShell on Windows). |
| **↳ Silent / low-priority** | Modifier for the system notification — sends it quietly without sound. Only applies when system notification is also checked. |
| **Send push to phone via ntfy.sh** | Sends a push notification to your phone through [ntfy.sh](https://ntfy.sh). See [Phone Notifications via ntfy.sh](#phone-notifications-via-ntfysh). |

---

### Custom Alert Message

Type a custom message to be sent with all alert actions. Leave it blank to use the automatic message:

```
<Movie Name> is open for tickets. BUY THEM NOW!
```

---

## Configuration File

The app automatically creates a `config.json` file in the same directory as the script. It saves:

- The last used URL, refresh interval, and movie name
- Your chosen alert actions and custom message
- Your global hotkey (if set)
- Your `ntfy.sh` topic key (auto-generated on first run)
- The path to your Chromium executable

All of these fields are restored the next time the app is launched. You do not need to re-enter anything after the first run.

---

## Hotkey Setup on Linux

Global hotkeys require the display server to be **X11 / Xorg**, not Wayland. Wayland blocks background keyboard listeners for security reasons.

**To switch to an X11 session:**

1. Log out of your current desktop session.
2. On the login screen, click the gear icon **⚙** (usually in the bottom-right corner).
3. Select **"Ubuntu on Xorg"**, **"X11"**, or **"Xorg"** from the list.
4. Log back in.

**If X11 does not appear in the list, install it first:**

```bash
sudo apt install xorg
```

**For a permanent switch** (disables Wayland system-wide):

```bash
sudo nano /etc/gdm3/custom.conf
```

Find the line `#WaylandEnable=false`, uncomment it, and save. Then reboot.

```ini
[daemon]
WaylandEnable=false
```

> Windows users do not need to do anything. Global hotkeys work natively.

---

## Phone Notifications via ntfy.sh

[ntfy.sh](https://ntfy.sh) is a free, open-source push notification service that requires no account.

**Setup:**

1. Install the **ntfy** app on your phone:
   - Android: [Google Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   - iOS: [Apple App Store](https://apps.apple.com/app/ntfy/id1625396347)

2. Open the app, tap **"+"** or **"Subscribe to topic"**.

3. Enter your unique topic key. You can find it by clicking the **`?`** button next to the ntfy option in the app, or by opening `config.json` and looking for the `ntfy_topic` field.

4. From now on, whenever the film is detected, a push notification will arrive on your phone immediately.

> **Keep your topic key private.** It is a randomly generated 15-character string. Anyone who knows this key can subscribe to your notifications.

---

## Troubleshooting

**Chromium does not launch automatically**

Use the Browse button to manually locate the executable. Common locations are listed in the [Chromium Executable](#chromium-executable) section. Make sure Chromium is fully installed, not just downloaded as an archive.

**Status stays orange / never turns green**

Chromium may have opened a window asking for confirmation (e.g. "Make Chromium your default browser?"). Click through any prompts in the browser window, or close Chromium manually and click Browse again to relaunch it.

**"WebDriver Error" on Start**

This means Python connected to the browser but the ChromeDriver version does not match your Chromium version. Run:

```bash
pip install --upgrade selenium
```

Selenium Manager will then fetch the correct ChromeDriver automatically on the next start.

**The film is detected immediately on the first check**

Your search term may be present in the Coming Soon section rather than Now Showing. The app will only alert if the text appears between the `Now Showing` heading and the `Coming Soon` heading on the page. Double-check that the name you entered matches the Now Showing listing exactly, and not something else on the page (e.g. a recommendation widget or a footer banner).

_Note:The script is currently modified to scan the entire body but if you want it to scan the Now Showing section only, you can follow the instructions in the code line no 720._

**The popup or cookie banner keeps appearing during refreshes**

You have not completed the one-time browser setup. Go back to [One-Time Browser Setup](#one-time-browser-setup) and accept all consent prompts in the `chromium_session` browser window before starting monitoring.

**Global hotkey does not work on Linux**

Your session is likely running on Wayland. Follow the steps in [Hotkey Setup on Linux](#hotkey-setup-on-linux) to switch to an X11 session.

**No push notification received on phone**

- Confirm the ntfy app is subscribed to the correct topic key (check `config.json`).
- Make sure your phone has an active internet connection.
- Check that the **Send push notification to phone via ntfy.sh** checkbox is selected before pressing Start.

---

## License

MIT — do whatever you want with it. However, make sure that the copy of the license is provided in all the modifications or copies of the script. 
