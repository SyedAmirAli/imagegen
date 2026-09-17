"""Shared plumbing for backends that drive a real, signed-in Chrome over CDP.

Chrome must run with `--remote-debugging-port` on a NON-default profile: since
Chrome 136 the flag is silently ignored when `--user-data-dir` points at the
default profile — Chrome starts, the flag shows up in the process cmdline, and
the DevTools server never binds. Every such backend launches its own dedicated
profile via `launch_chrome` below.

Chrome is launched as a plain subprocess, never through Playwright's own
launcher (`chromium.launch`/`launch_persistent_context`): Playwright's
launcher adds automation fingerprints (`navigator.webdriver`, missing
feature flags) that bot-detection such as Cloudflare Turnstile flags on
sign-in. A normally-launched Chrome that Playwright only *attaches* to
afterward is indistinguishable from one the user opened by hand.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def find_chrome_binary() -> str | None:
    """Locate a Chrome-family browser.

    On Linux the browsers put themselves on PATH, so `which` is enough. On
    Windows and macOS they do not, and the installer paths are the only
    reliable answer — hence the list of the places they actually land.
    """
    if sys.platform == "win32":
        names = ("chrome", "chromium", "brave", "msedge")
        roots = [os.environ.get(var) for var in
                 ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        relative = (
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        )
        known = [Path(root) / rel for root in roots if root for rel in relative]
    elif sys.platform == "darwin":
        names = ("google-chrome", "chromium")
        known = [Path(prefix) / rel for prefix in ("/Applications",
                                                   Path.home() / "Applications")
                 for rel in (
                     "Google Chrome.app/Contents/MacOS/Google Chrome",
                     "Chromium.app/Contents/MacOS/Chromium",
                     "Brave Browser.app/Contents/MacOS/Brave Browser",
                     "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 )]
    else:
        names = ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "brave-browser")
        known = []

    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for path in known:
        if path.is_file():
            return str(path)
    return None


def default_profile_dirs() -> list[Path]:
    """Chrome's own profile folders, which must never be reused for automation.

    Chrome 136+ ignores --remote-debugging-port when it is pointed at these, so
    a run against one hangs waiting for a port that will never open. Better to
    say so than to time out.
    """
    home = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return [local / "Google" / "Chrome" / "User Data",
                local / "Chromium" / "User Data",
                local / "Microsoft" / "Edge" / "User Data"]
    if sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        return [support / "Google" / "Chrome",
                support / "Chromium",
                support / "Microsoft Edge"]
    return [home / ".config" / "google-chrome",
            home / ".config" / "chromium",
            home / ".config" / "microsoft-edge"]


def cdp_alive(cdp_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return False


def launch_chrome(binary: str, profile: Path, cdp_url: str, start_url: str) -> None:
    """Start a plain Chrome subprocess with the debugging port open.

    Blocks until the CDP port answers or raises RuntimeError after 40s.
    """
    port = cdp_url.rsplit(":", 1)[-1].strip("/")
    # Chrome must outlive the terminal that started it. POSIX does that with
    # its own session; Windows has no such argument and uses creation flags.
    detach = ({"creationflags": subprocess.DETACHED_PROCESS
                                | subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    subprocess.Popen(
        [binary, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check",
         "--disable-session-crashed-bubble", start_url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **detach,
    )
    for _ in range(40):
        time.sleep(1)
        if cdp_alive(cdp_url):
            return
    raise RuntimeError(f"Chrome did not expose {cdp_url} within 40s")
