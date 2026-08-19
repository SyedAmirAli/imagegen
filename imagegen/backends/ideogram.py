"""Ideogram web-UI backend.

Drives an already-signed-in Ideogram session in a real Chrome over CDP, so the
images come from the user's web subscription rather than a paid API key.

Chrome must run with `--remote-debugging-port` on a NON-default profile: since
Chrome 136 the flag is silently ignored when `--user-data-dir` points at the
default profile — Chrome starts, the flag shows up in the process cmdline, and
the DevTools server never binds. This backend launches such a profile itself.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..logging_utils import log
from .base import Backend, BackendError, FatalBackendError, GenerationResult

DEFAULT_CDP = "http://127.0.0.1:9222"
DEFAULT_URL = "https://ideogram.ai/t/my-images"
ASSET_URLS = (
    "https://ideogram.ai/assets/image/lossless/response/{id}",
    "https://ideogram.ai/assets/image/balanced/response/{id}@2k",
)
SUBMIT_API = "/api/images/sample"
POLL_API = "/api/gallery/retrieve-requests"

EDITOR = ".tiptap-prompt-editor"
ASPECT_TRIGGER = '[data-testid="aspect-ratio-config-container"]'
GENERATE_BUTTON = '[data-testid="generate-button"]'
SIGNED_OUT_MARKERS = ("sign in", "log in", "continue with google", "sign up")

# Ideogram's aspect buttons. The panel labels the square one differently from
# the rest, and an unknown ratio is snapped to the closest of these.
ASPECT_LABELS = {
    "1:1": "1:1 (Square)",
    "16:9": "16:9", "9:16": "9:16",
    "4:3": "4:3", "3:4": "3:4",
    "3:2": "3:2", "2:3": "2:3",
    "16:10": "16:10", "10:16": "10:16",
    "1:3": "1:3", "3:1": "3:1",
}


def _ratio_value(text: str) -> float | None:
    m = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", text or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return w / h if h else None


def snap_aspect(requested: str | None) -> str | None:
    """Map any ratio onto the closest ratio Ideogram actually offers."""
    if not requested:
        return None
    if requested in ASPECT_LABELS:
        return requested
    want = _ratio_value(requested)
    if want is None:
        return None
    return min(ASPECT_LABELS, key=lambda k: abs(_ratio_value(k) - want))


def _find_chrome() -> str | None:
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


def _default_profile_dirs() -> list[Path]:
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


def _cdp_alive(cdp_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return False


class IdeogramBackend(Backend):
    name = "ideogram"

    @staticmethod
    def add_arguments(parser) -> None:
        g = parser.add_argument_group("ideogram backend")
        g.add_argument("--cdp-url", default=DEFAULT_CDP,
                       help=f"Chrome DevTools endpoint (default: {DEFAULT_CDP})")
        g.add_argument("--ideogram-url", default=DEFAULT_URL,
                       help="page to open/return to between generations")
        g.add_argument("--chrome-binary", default=None,
                       help="Chrome executable (default: autodetect)")
        g.add_argument("--chrome-profile", default=str(Path.home() / ".chrome-imagegen"),
                       help="dedicated Chrome profile directory (must not be the default profile)")
        g.add_argument("--no-launch-chrome", action="store_true",
                       help="fail instead of starting Chrome when the CDP port is dead")
        g.add_argument("--accept-timeout", type=int, default=90,
                       help="seconds to wait for Ideogram to register a submitted request")
        g.add_argument("--gen-timeout", type=int, default=420,
                       help="seconds to wait for one image (default: 420)")
        g.add_argument("--poll-interval", type=float, default=3.0,
                       help="seconds between checks for a finished image")
        g.add_argument("--reload-every", type=int, default=25,
                       help="reload the tab every N generations to keep the DOM small (0 = never)")

    def __init__(self, args):
        super().__init__(args)
        self._pw = None
        self._browser = None
        self._page = None
        self._generated = 0
        self._requests: dict[str, dict] = {}
        self._last_submit_status: int | None = None

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        from playwright.sync_api import sync_playwright

        if not _cdp_alive(self.args.cdp_url):
            if self.args.no_launch_chrome:
                raise FatalBackendError(
                    f"no Chrome DevTools endpoint at {self.args.cdp_url} "
                    "and --no-launch-chrome was given"
                )
            self._launch_chrome()

        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.args.cdp_url)
        except Exception as exc:
            raise FatalBackendError(f"cannot attach to Chrome at {self.args.cdp_url}: {exc}") from exc

        ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        page = next((p for p in ctx.pages if "ideogram.ai" in (p.url or "")), None)
        if page is None:
            page = ctx.new_page()
        self._page = page

        if "ideogram.ai" not in (page.url or ""):
            page.goto(self.args.ideogram_url, wait_until="domcontentloaded")
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.bring_to_front()
        page.on("response", self._on_response)
        self._await_editor(timeout=45_000)
        log(f"   attached to {page.url}")

    def _launch_chrome(self) -> None:
        binary = self.args.chrome_binary or _find_chrome()
        if binary is None:
            raise FatalBackendError("no Chrome binary found; pass --chrome-binary")

        profile = Path(self.args.chrome_profile).expanduser()
        if any(profile.resolve() == d.resolve() for d in _default_profile_dirs()):
            raise FatalBackendError(
                "--chrome-profile must not be Chrome's default profile: Chrome 136+ "
                "silently refuses to open the debugging port there"
            )
        first_run = not profile.exists()
        profile.mkdir(parents=True, exist_ok=True)
        port = self.args.cdp_url.rsplit(":", 1)[-1].strip("/")

        log(f"   launching {binary} (profile: {profile})")
        # Chrome must outlive the terminal that started it. POSIX does that with
        # its own session; Windows has no such argument and uses creation flags.
        detach = ({"creationflags": subprocess.DETACHED_PROCESS
                                    | subprocess.CREATE_NEW_PROCESS_GROUP}
                  if os.name == "nt" else {"start_new_session": True})
        subprocess.Popen(
            [binary, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check",
             "--disable-session-crashed-bubble", self.args.ideogram_url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **detach,
        )
        for _ in range(40):
            time.sleep(1)
            if _cdp_alive(self.args.cdp_url):
                log("   Chrome is up and the debugging port is live")
                if first_run:
                    log("   FIRST RUN: sign in to Ideogram in the new window, then this run continues")
                return
        raise FatalBackendError(f"Chrome did not expose {self.args.cdp_url} within 40s")

    def _await_editor(self, timeout: int = 60_000) -> None:
        from playwright.sync_api import TimeoutError as PWTimeout

        try:
            self._page.wait_for_selector(EDITOR, timeout=timeout)
        except PWTimeout:
            body = ""
            try:
                body = (self._page.inner_text("body") or "")[:600].lower()
            except Exception:
                pass
            if any(marker in body for marker in SIGNED_OUT_MARKERS):
                raise FatalBackendError(
                    "this Chrome profile is not signed in to Ideogram. Sign in inside "
                    "the automation window, confirm the generator page loads, then rerun."
                ) from None
            raise FatalBackendError(
                f"the Ideogram prompt editor never appeared (url: {self._page.url})"
            ) from None

    def recover(self) -> None:
        if self._page is None:
            return
        try:
            self._page.reload(wait_until="domcontentloaded")
            self._page.wait_for_selector(EDITOR, timeout=60_000)
        except Exception as exc:
            log(f"   recovery reload failed: {exc}")

    def snapshot(self, path: Path) -> bool:
        if self._page is None:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(path=str(path))
            return True
        except Exception:
            return False

    def close(self) -> None:
        # Only the CDP attachment is dropped; the user's Chrome stays open.
        for closer in (getattr(self._browser, "close", None), getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        self._browser = self._pw = self._page = None

    # -- page interaction --------------------------------------------------

    def _on_response(self, response) -> None:
        """Mirror Ideogram's own generation traffic into self._requests.

        Keying on the API rather than on <img> tags is not a refinement, it is
        a correctness requirement: any page with a live feed (explore, a shared
        gallery, lazy-loaded history) grows new <img> elements on its own, and a
        DOM diff happily returns a stranger's image as "the one we just made".
        """
        url = response.url or ""
        try:
            if SUBMIT_API in url:
                self._last_submit_status = response.status
                if not response.ok:
                    return
            elif POLL_API not in url:
                return
            payload = response.json()
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        for entry in payload.get("sampling_requests") or []:
            request_id = entry.get("request_id")
            if request_id:
                self._requests[request_id] = entry

    @staticmethod
    def _normalise(text: str) -> str:
        return " ".join((text or "").split())

    def _find_request(self, prompt: str, submitted_at: float) -> dict | None:
        """Our generation: same prompt text, created after we pressed the button."""
        wanted = self._normalise(prompt)
        candidates = [
            entry for entry in self._requests.values()
            if self._normalise(entry.get("user_prompt", "")) == wanted
            and float(entry.get("creation_time_float") or 0) >= submitted_at - 5
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: float(e.get("creation_time_float") or 0))

    def _ensure_composer_open(self) -> None:
        """Expand the composer so its settings bar is clickable.

        After a generation the composer collapses: the model/count/aspect
        controls stay in the DOM but are hidden. inner_text() still reads them,
        click() does not — so anything that clicks them must expand first.
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        trigger = self._page.locator(ASPECT_TRIGGER).first
        if trigger.count() and trigger.is_visible():
            return
        self._page.locator(EDITOR).first.click()
        try:
            trigger.wait_for(state="visible", timeout=15_000)
        except PWTimeout:
            self._page.keyboard.press("Escape")
            self._page.locator(EDITOR).first.click()
            trigger.wait_for(state="visible", timeout=15_000)

    def _set_prompt(self, text: str) -> None:
        editor = self._page.locator(EDITOR).first
        editor.click()
        self._page.keyboard.press("Control+a")
        self._page.keyboard.press("Delete")
        self._page.keyboard.insert_text(text)

        want = "".join(text.split())
        for _ in range(24):
            if "".join((editor.inner_text() or "").split()) == want:
                return
            time.sleep(0.25)
        got = len("".join((editor.inner_text() or "").split()))
        raise BackendError(f"prompt not fully entered ({got} of {len(want)} chars)")

    def _set_aspect(self, ratio: str) -> None:
        label = ASPECT_LABELS[ratio]
        self._ensure_composer_open()
        trigger = self._page.locator(ASPECT_TRIGGER).first
        if trigger.inner_text().strip() == ratio:
            return   # Ideogram remembers the last ratio, so this is usually a no-op

        for attempt in range(1, 4):
            self._ensure_composer_open()
            try:
                trigger.scroll_into_view_if_needed(timeout=5_000)
            except Exception:
                pass
            trigger.click(timeout=10_000)
            self._page.wait_for_timeout(600)

            # :text-is() is an exact, whitespace-normalised match. An anchored
            # has_text regex proved brittle: nested spans and hidden duplicates
            # resolve first via .first.
            options = self._page.locator(f'button:text-is("{label}")')
            target = next(
                (options.nth(i) for i in range(options.count()) if options.nth(i).is_visible()),
                None,
            )
            if target is None:
                raise BackendError(f"aspect option {label!r} is in the DOM but not clickable")
            target.click(timeout=10_000)   # a real pointer event; synthetic clicks skip React state
            self._page.wait_for_timeout(600)
            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(300)
            if trigger.inner_text().strip() == ratio:
                return
            log(f"   aspect ratio did not stick (try {attempt}/3)")
        raise BackendError(f"could not set aspect ratio to {ratio}")

    def _submit_and_wait(self, prompt: str) -> tuple[str, dict]:
        """Press generate, then wait for OUR request to reach 100%."""
        self._requests.clear()
        self._last_submit_status = None
        submitted_at = time.time()
        self.report("submitting", 0.0)
        self._page.locator(GENERATE_BUTTON).first.click()

        deadline = submitted_at + self.args.gen_timeout
        entry = None
        while time.time() < deadline:
            self._page.wait_for_timeout(int(self.args.poll_interval * 1000))
            if self._last_submit_status not in (None, 200):
                raise BackendError(
                    f"Ideogram rejected the generation (HTTP {self._last_submit_status}) "
                    "— check the account's credits or rate limit"
                )
            entry = self._find_request(prompt, submitted_at)
            if entry is None:
                self.report("waiting for Ideogram to accept", 0.0)
                if time.time() - submitted_at > self.args.accept_timeout:
                    raise BackendError(
                        f"Ideogram never registered the request within "
                        f"{self.args.accept_timeout}s of pressing generate"
                    )
                continue
            responses = entry.get("responses") or []
            percent = float(entry.get("completion_percentage") or 0)
            self.report("rendering", percent / 100)
            done = percent >= 100
            if done and responses:
                return responses[0]["response_id"], entry

        state = "unknown"
        if entry is not None:
            state = f"{entry.get('completion_percentage')}% complete"
        raise BackendError(f"image not finished after {self.args.gen_timeout}s ({state})")

    def _download(self, image_id: str) -> bytes:
        """Fetch the render through the page, so the session cookies apply."""
        last = ""
        for template in ASSET_URLS:
            url = template.format(id=image_id)
            for attempt in range(1, 4):
                try:
                    response = self._page.request.get(url, timeout=120_000)
                    if response.ok:
                        body = response.body()
                        if body:
                            return body
                        last = "empty body"
                    else:
                        last = f"HTTP {response.status}"
                        if response.status == 404:
                            break   # this rendition does not exist; try the next one
                except Exception as exc:
                    last = f"{type(exc).__name__}: {exc}"
                time.sleep(2 * attempt)
        raise BackendError(f"download failed for {image_id}: {last}")

    # -- Backend API -------------------------------------------------------

    def generate(self, job) -> GenerationResult:
        if self._page is None:
            raise FatalBackendError("backend is not open")

        if self.args.reload_every and self._generated and \
                self._generated % self.args.reload_every == 0:
            log("   periodic tab reload")
            self.recover()

        # Prompt FIRST: a long prompt grows the composer, which pushes the
        # settings bar down out from under the page header. While collapsed the
        # aspect button sits under the header — visible, but it never gets the click.
        prompt = job.prompt
        # Ideogram's current composer has no separate negative field, so a
        # negative that is not already spelled out in the prompt is appended.
        if job.negative and job.negative.strip() not in prompt:
            prompt = f"{prompt}\n\nNEGATIVE PROMPT (avoid entirely): {job.negative.strip()}"
        self._set_prompt(prompt)
        self.report("setting aspect ratio", None)
        ratio = snap_aspect(job.aspect)
        if ratio:
            if ratio != job.aspect:
                log(f"   aspect {job.aspect} -> {ratio} (nearest Ideogram offers)")
            self._set_aspect(ratio)

        self.report("typing prompt", None)
        image_id, entry = self._submit_and_wait(prompt)
        got = entry.get("aspect_ratio")
        if ratio and got and got != ratio:
            log(f"   warning: Ideogram generated {got}, not the requested {ratio}")
        self.report("downloading", 1.0)
        data = self._download(image_id)
        self._generated += 1
        return GenerationResult(data=data, provider_image_id=image_id,
                                content_type="image/png")
