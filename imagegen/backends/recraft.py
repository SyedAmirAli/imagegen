"""Recraft (recraft.ai) web-UI backend.

Drives an already-signed-in Recraft session in a real Chrome over CDP, so
images come from the user's own subscription/credits rather than a paid API
key. See `_chrome.py` for why Chrome is launched on a dedicated profile as a
plain subprocess rather than through Playwright's own launcher.

Recraft's editor renders every generated image onto a single <canvas> (a
design-tool board, not a DOM gallery) — there are no per-image DOM nodes to
wait on or diff. Instead this backend rides the site's own generation API:
clicking Generate fires a `POST .../queue_recraft/prompt_to_image` whose JSON
response is `{"operationId": ...}`; the pixels for that exact job come back
from one `GET .../poll_recraft?operation_id=...`, whose multipart body holds
a JSON manifest part plus one raw image part per generated image, keyed by
image id. Because the operationId is read directly off the response to OUR
submit request (Playwright pairs a `response` event with the exact request
that produced it), there is no risk of ever picking up a stranger's image —
unlike a DOM diff on a live feed, this match is exact by construction, not a
best-effort guess.

A brand-new project shows a "what would you create today?" quick-start
screen instead of the plain composer; `_ensure_composer` clicks through it
once per project.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..logging_utils import log
from . import _chrome
from .base import Backend, BackendError, FatalBackendError, GenerationResult

DEFAULT_CDP = "http://127.0.0.1:9223"
PROJECTS_URL = "https://www.recraft.ai/projects"
SUBMIT_PATH = "queue_recraft/prompt_to_image"
POLL_PATH = "poll_recraft"
IMAGE_HOST = "img.recraft.ai"

PROMPT_FIELD = '[data-testid="generation-panel-prompt-field"]'
GENERATE_BUTTON = '[data-testid="generation-panel-generate-button"]'
ASPECT_TRIGGER = '[data-testid="prompt-panel-aspect-ratio-trigger"]'
MODEL_TRIGGER = '[data-testid="generation-panel-model-selector"]'
MODEL_LIST = '[data-testid="dropdown-models-list"]'
SETTINGS_TRIGGER = '[data-testid="prompt-panel-generation-settings"]'
NEGATIVE_FIELD = 'textarea[name="negative-prompt"]'

# Recraft's own prompt field silently truncates once a concrete model (e.g.
# "Recraft V3") is picked — confirmed empirically at 1000 chars, not
# documented anywhere, and it may differ per model. No default cap here:
# trimming only happens when --recraft-max-prompt-chars is passed.
BATCH_TRIGGER = '[data-testid="batch-size-trigger"]'
SIGNED_OUT_MARKERS = ("sign in", "log in", "continue with google", "welcome to recraft studio")

# Recraft's own aspect-ratio buttons, label text == button text.
ASPECT_LABELS = (
    "1:1", "4:5", "3:4", "10:14", "2:3", "9:16", "1:2",
    "5:4", "4:3", "14:10", "3:2", "16:9", "2:1",
)


def _ratio_value(text: str) -> float | None:
    m = re.match(r"\s*(\d+)\s*:\s*(\d+)\s*$", text or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return w / h if h else None


def snap_aspect(requested: str | None) -> str | None:
    """Map any ratio onto the closest ratio Recraft actually offers."""
    if not requested:
        return None
    if requested in ASPECT_LABELS:
        return requested
    want = _ratio_value(requested)
    if want is None:
        return None
    return min(ASPECT_LABELS, key=lambda k: abs(_ratio_value(k) - want))


def _describe_poll_body(body: bytes, content_type: str) -> str:
    """A short, log-safe summary of a poll_recraft reply that is not multipart."""
    snippet = body[:200].decode("utf-8", "replace").replace("\n", " ")
    return f"{content_type or 'no content-type'}: {snippet}"


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict, dict[str, tuple[str, bytes]]]:
    """Split poll_recraft's multipart body into (manifest, {image_id: (content_type, bytes)})."""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        raise BackendError(f"poll_recraft response has no multipart boundary ({content_type!r})")
    boundary = ("--" + m.group(1)).encode()
    manifest: dict = {}
    images: dict[str, tuple[str, bytes]] = {}
    for chunk in body.split(boundary)[1:-1]:
        head, _, data = chunk.partition(b"\r\n\r\n")
        data = data[:-2] if data.endswith(b"\r\n") else data  # trailing CRLF before next boundary
        head_text = head.decode("latin-1")
        name_match = re.search(r'name="([^"]+)"', head_text)
        ct_match = re.search(r"Content-Type:\s*([\w/.+-]+)", head_text, re.IGNORECASE)
        name = name_match.group(1) if name_match else ""
        ctype = ct_match.group(1) if ct_match else "application/octet-stream"
        if name == "response":
            manifest = json.loads(data.decode("utf-8"))
        elif name:
            images[name] = (ctype, data)
    return manifest, images


def _parse_poll(body: bytes, content_type: str) -> tuple[dict, dict[str, tuple[str, bytes]]]:
    """Read a poll_recraft reply, whichever of its two shapes it arrives in.

    Recraft answers a finished job one of two ways, and has switched between
    them: an older multipart body carrying the manifest plus the image bytes
    inline, and a plain JSON body that is the manifest alone. Only the first
    has pixels in it; when the reply is JSON the browser fetches the bytes
    separately from img.recraft.ai, so the caller waits for that instead.
    """
    if "multipart/" in (content_type or "").lower():
        return _parse_multipart(body, content_type)
    try:
        manifest = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BackendError(
            f"poll_recraft reply was neither multipart nor JSON "
            f"({content_type!r}): {_describe_poll_body(body, content_type)}"
        )
    if not isinstance(manifest, dict):
        raise BackendError("poll_recraft JSON reply was not an object")
    return manifest, {}


def _image_id_from_url(url: str) -> str | None:
    """Pull the image id out of an img.recraft.ai delivery URL.

    The path is `<signed token>/<transform>/plain/abs://prod/images/<id>`, e.g.
    .../raw:1/plain/abs://prod/images/856c5546-... — and a resized variant may
    tack `@avif`/`@png` onto the id.
    """
    m = re.search(r"abs://prod/images/([\w-]+)", url or "")
    return m.group(1) if m else None


class RecraftBackend(Backend):
    name = "recraft"

    @staticmethod
    def add_arguments(parser) -> None:
        # All flags are --recraft-*, not the generic names ideogram.py uses:
        # cli.py registers every backend's add_arguments on one shared parser
        # regardless of which --backend is selected, so names must be unique
        # across backends, not just within this one.
        g = parser.add_argument_group("recraft backend")
        g.add_argument("--recraft-cdp-url", default=DEFAULT_CDP,
                       help=f"Chrome DevTools endpoint (default: {DEFAULT_CDP})")
        g.add_argument("--recraft-project-url", default=None,
                       help="a specific project to reuse, e.g. "
                            "https://www.recraft.ai/project/<id> (default: create one "
                            "on first run and print its URL for reuse)")
        g.add_argument("--recraft-model", default=None,
                       help="model to select in the Model picker, matched by visible "
                            "name, e.g. 'Recraft V4.1' (default: leave as Auto). "
                            "Selected once when the run starts, not per image")
        g.add_argument("--recraft-model-wait", type=int, default=30, metavar="SECONDS",
                       help="when --recraft-model is not in the picker, how long to wait "
                            "for one to be chosen by hand before carrying on with "
                            "whatever is selected (default: 30s, 0 to skip)")
        g.add_argument("--recraft-chrome-binary", default=None,
                       help="Chrome executable (default: autodetect)")
        g.add_argument("--recraft-chrome-profile", default=str(Path.home() / ".chrome-imagegen-recraft"),
                       help="dedicated Chrome profile directory (must not be the default profile)")
        g.add_argument("--recraft-no-launch-chrome", action="store_true",
                       help="fail instead of starting Chrome when the CDP port is dead")
        g.add_argument("--recraft-gen-timeout", type=int, default=300,
                       help="seconds to wait for one image (default: 300)")
        g.add_argument("--recraft-poll-interval", type=float, default=3.0,
                       help="seconds between poll_recraft retries once submitted")
        g.add_argument("--recraft-max-prompt-chars", type=int, default=None,
                       help="trim prompts to this many characters before typing them in, "
                            "at a word boundary (default: no trimming — send prompts as-is)")

    def __init__(self, args):
        super().__init__(args)
        self._pw = None
        self._browser = None
        self._page = None
        self._submissions: dict[str, dict] = {}   # prompt (normalised) -> {operation_id, at}
        self._poll_bodies: dict[str, tuple[bytes, str]] = {}   # operation_id -> (body, content_type)
        # image_id -> (content_type, bytes, is_raw). The page pulls the pixels
        # from img.recraft.ai itself once the poll reports the job's image ids.
        self._image_bodies: dict[str, tuple[str, bytes, bool]] = {}

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        from playwright.sync_api import sync_playwright

        if not _chrome.cdp_alive(self.args.recraft_cdp_url):
            if self.args.recraft_no_launch_chrome:
                raise FatalBackendError(
                    f"no Chrome DevTools endpoint at {self.args.recraft_cdp_url} "
                    "and --recraft-no-launch-chrome was given"
                )
            self._launch_chrome()

        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.args.recraft_cdp_url)
        except Exception as exc:
            raise FatalBackendError(f"cannot attach to Chrome at {self.args.recraft_cdp_url}: {exc}") from exc

        ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        page = next((p for p in ctx.pages if "recraft.ai" in (p.url or "")), None)
        if page is None:
            page = ctx.new_page()
        self._page = page

        target = self.args.recraft_project_url or PROJECTS_URL
        if target not in (page.url or ""):
            page.goto(target, wait_until="domcontentloaded")
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.bring_to_front()
        page.on("response", self._on_response)

        self._ensure_composer()
        try:
            self._set_batch_size(1)   # a project may default to x2+; we only ever want one
        except BackendError as exc:
            log(f"   warning: {exc} — generations may cost extra credits per image")
        self._select_model_once()
        self._extract_project_id(self._page.url)   # asserts we're in a project, or raises
        if not self.args.recraft_project_url:
            log(f"   FIRST RUN: created {self._page.url} — pass it as "
                f"--recraft-project-url next time to reuse this project")
        log(f"   attached to {self._page.url}")

    def _launch_chrome(self) -> None:
        binary = self.args.recraft_chrome_binary or _chrome.find_chrome_binary()
        if binary is None:
            raise FatalBackendError("no Chrome binary found; pass --recraft-chrome-binary")

        profile = Path(self.args.recraft_chrome_profile).expanduser()
        if any(profile.resolve() == d.resolve() for d in _chrome.default_profile_dirs()):
            raise FatalBackendError(
                "--recraft-chrome-profile must not be Chrome's default profile: Chrome 136+ "
                "silently refuses to open the debugging port there"
            )
        first_run = not profile.exists()
        profile.mkdir(parents=True, exist_ok=True)
        start_url = self.args.recraft_project_url or PROJECTS_URL

        log(f"   launching {binary} (profile: {profile})")
        try:
            _chrome.launch_chrome(binary, profile, self.args.recraft_cdp_url, start_url)
        except RuntimeError as exc:
            raise FatalBackendError(str(exc)) from exc
        log("   Chrome is up and the debugging port is live")
        if first_run:
            log("   FIRST RUN: sign in to Recraft in the new window, then this run continues")

    @staticmethod
    def _extract_project_id(url: str) -> str:
        m = re.search(r"/project/([\w-]+)", url or "")
        if not m:
            raise FatalBackendError(f"not inside a Recraft project (url: {url})")
        return m.group(1)

    def _ensure_composer(self, timeout: int = 60_000) -> None:
        """Reach a project with the plain generate composer visible.

        A fresh project first shows a promo modal and a "what would you
        create today?" quick-start screen instead of the composer used on
        every later run — dismiss/click through both, once.
        """
        page = self._page
        deadline = time.time() + timeout / 1000

        if PROJECTS_URL in (page.url or ""):
            page.wait_for_timeout(1000)
            tile = page.get_by_text("Create new project", exact=True).first
            if tile.count():
                tile.click()

        while time.time() < deadline:
            if page.locator(PROMPT_FIELD).count():
                # The composer mounts before its settings row (aspect/model/
                # batch triggers) finishes hydrating; wait for that too so
                # later clicks on those controls don't race a half-ready DOM.
                try:
                    page.locator(BATCH_TRIGGER).first.wait_for(state="visible", timeout=5_000)
                except Exception:
                    pass
                # A just-created project's settings row is visible before its
                # click handlers finish hydrating; clicks land as no-ops until
                # then. Cheaper to pay a flat settle cost once here than to
                # chase it with per-control retries on every generation.
                page.wait_for_timeout(4_000)
                return
            page.keyboard.press("Escape")   # dismiss any promo modal
            create_tab = page.get_by_text("Create", exact=True).first
            if create_tab.count():
                create_tab.click()
            quick_start = page.get_by_text("Photorealistic image", exact=True).first
            if quick_start.count():
                quick_start.click()
            page.wait_for_timeout(1000)

        body = ""
        try:
            body = (page.inner_text("body") or "")[:600].lower()
        except Exception:
            pass
        if any(marker in body for marker in SIGNED_OUT_MARKERS):
            raise FatalBackendError(
                "this Chrome profile is not signed in to Recraft. Sign in inside "
                "the automation window, confirm a project opens, then rerun."
            )
        raise FatalBackendError(f"the Recraft prompt editor never appeared (url: {page.url})")

    def recover(self) -> None:
        if self._page is None:
            return
        try:
            self._page.reload(wait_until="domcontentloaded")
            self._ensure_composer()
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
        """Capture Recraft's own generation traffic as it happens.

        Three responses matter, all read passively rather than replayed
        ourselves: the queue_recraft response pairs 1:1 with the request that
        produced it (via response.request), so there is no ambiguity about
        whose operationId this is even with several prompts in flight. The
        poll_recraft response cannot be replayed ourselves at all — Recraft's
        SPA attaches an auth token to its own fetch() calls that a bare
        page.request.get() never sees, so a self-issued poll gets HTTP 401.
        Those two only name the job and its image ids; the pixels come last,
        from a signed img.recraft.ai URL the browser fetches once the poll
        reports the job done, so that response is where the bytes are read.
        """
        url = response.url or ""
        if SUBMIT_PATH in url:
            try:
                request_body = json.loads(response.request.post_data or "{}")
                payload = response.json()
            except Exception:
                return
            prompt = self._normalise(request_body.get("prompt", ""))
            operation_id = payload.get("operationId")
            if prompt and operation_id:
                self._submissions[prompt] = {
                    "operation_id": operation_id,
                    "at": time.time(),
                    "ok": response.ok,
                    "status": response.status,
                }
        elif POLL_PATH in url:
            m = re.search(r"[?&]operation_id=([\w-]+)", url)
            if not m or not response.ok:
                return
            try:
                body = response.body()
            except Exception:
                return
            self._poll_bodies[m.group(1)] = (body, response.headers.get("content-type", ""))
        elif IMAGE_HOST in url:
            image_id = _image_id_from_url(url)
            if not image_id or not response.ok:
                return
            # The page fetches the original first and resized/format variants
            # after; keep the original, since a variant may be cropped or lossy.
            raw = "/raw:1/" in url
            held = self._image_bodies.get(image_id)
            if held is not None and held[2] and not raw:
                return
            try:
                body = response.body()
            except Exception:
                return
            self._image_bodies[image_id] = (
                response.headers.get("content-type", ""), body, raw)

    @staticmethod
    def _normalise(text: str) -> str:
        return " ".join((text or "").split())

    @staticmethod
    def _clip_prompt(text: str, limit: int) -> str:
        """Slice down to `limit` chars without cutting mid-word."""
        if len(text) <= limit:
            return text
        clipped = text[:limit]
        cut = clipped.rfind(" ")
        if cut > limit // 2:  # don't butcher it if the last space is way back
            clipped = clipped[:cut]
        return clipped.rstrip(" ,.;:-\n")

    def _set_batch_size(self, n: int) -> None:
        page = self._page
        trigger = page.locator(BATCH_TRIGGER).first
        want = f"×{n}"
        for attempt in range(1, 4):
            if not trigger.count():
                page.wait_for_timeout(500)
                continue
            if trigger.inner_text().strip() == want:
                return
            try:
                trigger.click(timeout=10_000)
            except Exception:
                page.wait_for_timeout(500)
                continue
            page.wait_for_timeout(400)
            # Each option's label sits in a <div> nested inside its <button>,
            # so button:text-is() (smallest-exact-match) matches the div, not
            # the button, and a tag-restricted selector then finds nothing.
            # Click the label directly (the click bubbles to the button),
            # scoped to the open popover so it can't match the trigger's own
            # current-value label (e.g. the trigger also reads "×2").
            popover = page.locator('[role="dialog"]:visible').last
            options = popover.get_by_text(want, exact=True)
            target = next(
                (options.nth(i) for i in range(options.count()) if options.nth(i).is_visible()),
                None,
            )
            if target is None:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                continue
            target.click(timeout=10_000)
            page.wait_for_timeout(300)
            if trigger.inner_text().strip() == want:
                return
        raise BackendError(f"could not set batch size to x{n} (try {attempt}/3)")

    def _set_model(self, name: str) -> None:
        # The model picker is a `role="menu"`, not a `role="dialog"` like the
        # aspect-ratio/batch-size popovers. Most models (e.g. "Recraft V4.1")
        # sit directly in that top-level menu, but older ones (e.g. "Recraft
        # V3") only exist in a per-vendor flyout reached by clicking the
        # vendor's row under "All image models" first.
        page = self._page
        page.locator(MODEL_TRIGGER).first.click()
        page.wait_for_timeout(400)
        menu = page.locator(MODEL_LIST)
        option = menu.get_by_text(name, exact=True).first
        if not option.count():
            vendor = name.split()[0]
            # The vendor row itself carries no text-matchable label: its
            # accessible name is "<vendor>\n<currently-selected variant>"
            # (e.g. "Recraft\nRecraft V4.1"), which also happens to be a
            # substring match of the unrelated top-level "Recraft V4.1"
            # model row — a plain text/role-name lookup grabs that row
            # instead and never opens the flyout. The vendor row's inner
            # div does carry a stable, vendor-specific test id though.
            category = menu.locator(
                f'[data-testid="dropdown-models-list-sub-group-{vendor.lower()}"]'
            ).locator('xpath=ancestor::*[@role="menuitem"][1]').first
            if category.count():
                category.click()
                page.wait_for_timeout(300)
                flyout = page.locator('[role="menu"]:visible').last
                option = flyout.get_by_text(name, exact=True).first
        if not option.count():
            page.keyboard.press("Escape")
            raise BackendError(f"model {name!r} not found in the Model picker")
        option.click()
        page.wait_for_timeout(300)

    def _current_model(self) -> str:
        """Whatever the Model picker is showing now, for reporting."""
        try:
            label = self._page.locator(MODEL_TRIGGER).first.inner_text() or ""
        except Exception:
            return ""
        return " ".join(label.split())

    def _select_model_once(self) -> None:
        """Pick the model once, as the run opens.

        This used to run before every single image. The model does not change
        between them, so that was a picker opened and closed a thousand times
        over a batch — and when the name was not in the list it raised, which
        failed every image in turn rather than the run once.

        A name that is not there is now a warning and a pause: the picker is
        left open for a while so it can be chosen by hand, and the run carries
        on with whatever is selected once that time is up.
        """
        name = self.args.recraft_model
        if not name:
            return

        try:
            self._set_model(name)
            log(f"   model set to {name!r}")
            return
        except BackendError as exc:
            log(f"   warning: {exc}")

        wait = max(0, int(self.args.recraft_model_wait))
        if wait:
            log(f"   pick a model by hand in the browser within {wait}s — "
                f"the run continues on its own after that")
            before = self._current_model()
            deadline = time.time() + wait
            while time.time() < deadline:
                self._page.wait_for_timeout(1000)
                current = self._current_model()
                if current and current != before:
                    log(f"   model picked by hand: {current}")
                    return

        current = self._current_model()
        log(f"   continuing with the model already selected"
            + (f": {current}" if current else ""))

    def _set_negative(self, text: str) -> bool:
        """Use Recraft's own "Negative prompt" field when it's on screen.

        That field (under the settings-gear popover next to the aspect/
        batch-size row) only exists once a concrete model is picked — "Auto"
        has no settings gear at all. Returns False when unavailable, so the
        caller can fall back to folding the negative text into the main
        prompt instead.
        """
        from playwright.sync_api import Error as PWError

        page = self._page
        trigger = page.locator(SETTINGS_TRIGGER).first
        # "Auto" has no settings popover at all: the gear stays in the DOM but
        # hidden. count() alone would then hand Playwright an invisible
        # element, burn its full 30s click timeout, and raise a TimeoutError
        # that the runner does not retry on — aborting the whole run.
        if not trigger.count() or not trigger.is_visible():
            return False
        try:
            trigger.click(timeout=10_000)
            field = page.locator(NEGATIVE_FIELD).first
            field.wait_for(state="visible", timeout=3_000)
            field.click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.keyboard.insert_text(text)
            page.wait_for_timeout(200)
        except PWError:
            page.keyboard.press("Escape")
            return False
        page.keyboard.press("Escape")
        return True

    def _set_aspect(self, ratio: str) -> None:
        page = self._page
        trigger = page.locator(ASPECT_TRIGGER).first
        for attempt in range(1, 4):
            try:
                trigger.click(timeout=10_000)
                page.wait_for_timeout(400)
                popover = page.locator('[role="dialog"]:visible').last
                options = popover.get_by_text(ratio, exact=True)
                target = next(
                    (options.nth(i) for i in range(options.count()) if options.nth(i).is_visible()),
                    None,
                )
                if target is None:
                    page.keyboard.press("Escape")
                    continue
                target.click(timeout=10_000)
                page.wait_for_timeout(300)
                if trigger.inner_text().strip() == ratio:
                    return
            except Exception:
                pass
            log(f"   aspect ratio did not stick (try {attempt}/3)")
            page.wait_for_timeout(500)
        raise BackendError(f"could not set aspect ratio to {ratio}")

    def _set_prompt(self, text: str) -> None:
        # Right after a generation finishes, the composer can still be
        # settling (re-rendering the result, possibly resizing the field
        # itself for long text) — insert_text() on a busy field can silently
        # lose its tail. Re-clicking and re-inserting from scratch, not just
        # re-polling the same insert, is what actually recovers from that.
        page = self._page
        field = page.locator(PROMPT_FIELD).first
        want = "".join(text.split())

        for attempt in range(1, 4):
            field.click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.keyboard.insert_text(text)

            for _ in range(24):
                if "".join((field.input_value() or "").split()) == want:
                    return
                time.sleep(0.25)
            got = len("".join((field.input_value() or "").split()))
            log(f"   prompt not fully entered ({got} of {len(want)} chars) — retry {attempt}/3")

        raise BackendError(f"prompt not fully entered ({got} of {len(want)} chars)")

    def _submit_and_wait(self, prompt: str) -> tuple[dict, dict[str, tuple[str, bytes]]]:
        """Click Generate, then wait for Recraft's OWN poll_recraft response."""
        # Each job's image ids are unique, so anything captured before this
        # click belongs to an earlier generation and would only pile up.
        self._image_bodies.clear()
        key = self._normalise(prompt)
        self._submissions.pop(key, None)
        submitted_at = time.time()
        self.report("submitting", 0.0)
        self._page.locator(GENERATE_BUTTON).first.click()

        accept_deadline = submitted_at + 30
        submission = None
        while time.time() < accept_deadline:
            submission = self._submissions.get(key)
            if submission is not None:
                break
            # A plain time.sleep() here would starve Playwright's dispatcher
            # thread of the chance to actually invoke our page.on("response")
            # callback; wait_for_timeout is a real Playwright call and pumps it.
            self._page.wait_for_timeout(300)
        if submission is None:
            raise BackendError("Recraft never registered the request within 30s of pressing generate")
        if not submission["ok"]:
            raise BackendError(f"Recraft rejected the generation (HTTP {submission['status']})")

        operation_id = submission["operation_id"]
        self._poll_bodies.pop(operation_id, None)
        deadline = submitted_at + self.args.recraft_gen_timeout
        manifest: dict | None = None
        wanted: list[str] = []          # image ids the finished manifest named
        pending = ""
        noted = False
        while time.time() < deadline:
            self.report("downloading" if wanted else "rendering", None)
            cached = self._poll_bodies.pop(operation_id, None)
            if cached is not None:
                body, content_type = cached
                manifest, images = _parse_poll(body, content_type)
                if images:
                    return manifest, images
                wanted = [entry["image_id"] for entry in manifest.get("images", [])]
                if not wanted:
                    # A poll that names no image is a progress reply, not the
                    # finished one; keep waiting rather than aborting a job
                    # that is about to succeed (and burning the retry's credits).
                    pending = _describe_poll_body(body, content_type)
                    if not noted:
                        log(f"   poll_recraft replied in flight — still rendering ({pending})")
                        noted = True
            for image_id in wanted:
                held = self._image_bodies.pop(image_id, None)
                if held is not None:
                    return manifest, {image_id: (held[0], held[1])}
            self._page.wait_for_timeout(int(self.args.recraft_poll_interval * 1000))
        raise BackendError(
            f"image not finished after {self.args.recraft_gen_timeout}s "
            f"(operation {operation_id})"
            + (f"; the manifest named {wanted} but its image bytes never arrived"
               if wanted else f"; last poll reply: {pending}" if pending else "")
        )

    def _dismiss_layer_selection(self) -> None:
        """Deselect any canvas layer left selected from a prior generation.

        Recraft auto-selects the image it just finished rendering. While
        something is selected, the whole left panel is covered by an
        invisible "Apply settings from the selected layer" button that
        swallows every click meant for the model/aspect/batch-size
        controls underneath it — those clicks silently "apply settings"
        instead of opening anything, which then hangs waiting for a menu
        that never appears. Escape drops the selection and the overlay
        with it.
        """
        page = self._page
        if page.get_by_role(
            "button", name="Apply settings from the selected layer"
        ).count():
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

    # -- Backend API -------------------------------------------------------

    def generate(self, job) -> GenerationResult:
        if self._page is None:
            raise FatalBackendError("backend is not open")

        from playwright.sync_api import Error as PWError

        try:
            return self._generate(job)
        except PWError as exc:
            raise BackendError(str(exc)) from exc

    def _generate(self, job) -> GenerationResult:
        self._dismiss_layer_selection()

        prompt = job.prompt
        if job.negative:
            negative = job.negative.strip()
            if negative not in prompt and not self._set_negative(negative):
                # No settings gear (e.g. model left on "Auto") — fall back to
                # folding it into the main prompt text.
                prompt = f"{prompt}\n\nNEGATIVE PROMPT (avoid entirely): {negative}"

        self.report("setting aspect ratio", None)
        ratio = snap_aspect(job.aspect)
        if ratio:
            if ratio != job.aspect:
                log(f"   aspect {job.aspect} -> {ratio} (nearest Recraft offers)")
            self._set_aspect(ratio)

        if self.args.recraft_max_prompt_chars:
            clipped = self._clip_prompt(prompt, self.args.recraft_max_prompt_chars)
            if len(clipped) != len(prompt):
                log(f"   prompt trimmed to fit --recraft-max-prompt-chars "
                    f"({len(prompt)} -> {len(clipped)} chars)")
                prompt = clipped

        self.report("typing prompt", None)
        self._set_prompt(prompt)

        _manifest, images = self._submit_and_wait(prompt)
        if not images:
            raise BackendError("Recraft finished without delivering image bytes")
        image_id = next(iter(images))
        content_type, data = images[image_id]
        self.report("downloading", 1.0)
        return GenerationResult(data=data, provider_image_id=image_id,
                                content_type=content_type)
