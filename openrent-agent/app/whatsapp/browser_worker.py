"""
WhatsApp Web browser worker — replaces the Baileys Node.js service.

Uses Playwright (headless=False or --headless=new on servers without display)
to control a real Chrome on web.whatsapp.com.

State machine:
  disconnected → starting → needs_scan ──► connected → polling
                                 ▲                        │
                                 └──── reconnecting ◄─────┘ (on repeated errors)
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.config import settings
from app.utils.logger import logger

# ── Paths ─────────────────────────────────────────────────────────────────────
SESSION_DIR = Path("whatsapp-session")
SESSION_FILE = SESSION_DIR / "storage_state.json"
QR_FILE = Path("whatsapp-qr.png")
WA_URL = "https://web.whatsapp.com"

# ── Stable WhatsApp Web selectors (data-testid preferred over class names) ────
SEL_QR = '[data-testid="link-device-qr-code"]'
SEL_CHAT_LIST = '[data-testid="chat-list"]'
SEL_INTRO = '[data-testid="link-device-qrcode-alt-linking-hint"]'
SEL_UNREAD_BADGE = '[data-testid="icon-unread-count"]'
SEL_CHAT_ITEM = '[data-testid="cell-frame-container"]'
SEL_COMPOSE = '[data-testid="compose-box"]'
SEL_CONV_TITLE = '[data-testid="conversation-info-header-chat-title"]'
SEL_UNREAD_ANCHOR = '[data-testid="unread-messages-anchor"]'
SEL_CONTACT_INFO_HEADER = '[data-testid="conversation-info-header"]'
SEL_CONTACT_INFO_SUBTITLE = '[data-testid="contact-info-subtitle selectable-text"]'
SEL_POPUP = 'div[data-animate-modal-popup="true"], div[role="dialog"]'

# Preferred dismiss-button labels, checked in order (Cancel/Not now before OK,
# so we default to declining nag popups rather than opting into anything).
_POPUP_DISMISS_LABELS = (
    "cancel", "not now", "no thanks", "later", "close", "dismiss", "got it", "ok",
)

def _phone_from_title(title: str) -> Optional[str]:
    """If a chat-list row's title is itself a raw phone number (unsaved
    contact), normalize it the same way an opened chat's header would."""
    digits = re.sub(r"[\s\-\(\)\+]", "", title)
    return digits if re.match(r"^\d{7,15}$", digits) else None


# Max message IDs to keep in memory to prevent duplicates
_MAX_SEEN_IDS = 2000

# Backoff on reconnect
_RECONNECT_BACKOFF_SECONDS = 30


class WhatsAppWebWorker:
    """Singleton worker that keeps a browser on WhatsApp Web and polls for messages."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self._generation: int = 0  # incremented on stop; lets _navigate_and_wait bail early

        self.status: str = "disconnected"
        self.proxy_id: Optional[int] = getattr(settings, "WHATSAPP_PROXY_ID", None)
        self._proxy_user_cleared: bool = False  # True when user explicitly set "No proxy"
        self.last_active: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.error_count: int = 0
        self._seen_message_ids: set[str] = set()

    # ── Proxy ──────────────────────────────────────────────────────────────────

    def _proxy_config(self) -> Optional[dict]:
        if not self.proxy_id:
            return None
        try:
            # Query the ORM directly — get_proxy() serializes to a dict that
            # intentionally omits the password (security). We need the decrypted
            # password, which EncryptedString provides transparently via the model.
            from app.db.models import Proxy as _Proxy
            from app.db.repository import session_scope
            with session_scope() as db:
                proxy = db.query(_Proxy).filter(_Proxy.id == self.proxy_id).first()
                if not proxy:
                    logger.warning(f"WHATSAPP_WEB_PROXY_NOT_FOUND proxy_id={self.proxy_id}")
                    return None
                if not proxy.is_active or not proxy.host:
                    logger.warning(f"WHATSAPP_WEB_PROXY_INACTIVE proxy_id={self.proxy_id}")
                    return None
                server = f"http://{proxy.host}:{proxy.port}"
                username = proxy.username or ""
                password = proxy.password or ""
                logger.info(
                    f"WHATSAPP_WEB proxy_server={server} proxy_id={self.proxy_id} "
                    f"has_auth={bool(username)}"
                )
                return {"server": server, "username": username, "password": password}
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_PROXY_LOAD_FAILED error={exc}")
        return None

    def set_proxy(self, proxy_id: Optional[int]) -> None:
        old = self.proxy_id
        self.proxy_id = proxy_id
        self._proxy_user_cleared = (proxy_id is None)  # remember explicit "no proxy" choice
        logger.info(f"WHATSAPP_WEB_PROXY_CHANGED old={old} new={proxy_id}")

    def _auto_select_proxy(self) -> None:
        """Pick a random active static proxy on first start if none is configured."""
        try:
            from app.db.repository import get_proxies
            proxies = get_proxies()
            candidates = [
                p for p in proxies
                if p.get("proxy_type") == "static" and p.get("is_active")
            ]
            if candidates:
                chosen = random.choice(candidates)
                self.proxy_id = chosen["id"]
                logger.info(
                    f"WHATSAPP_WEB_AUTO_PROXY selected proxy_id={self.proxy_id} "
                    f"host={chosen.get('host')}"
                )
            else:
                logger.warning(
                    "WHATSAPP_WEB_AUTO_PROXY no active static proxies found — "
                    "starting without proxy"
                )
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_AUTO_PROXY_FAILED error={exc}")

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.status in ("connected", "starting", "needs_scan", "reconnecting"):
            logger.info(f"WHATSAPP_WEB_START_SKIPPED status={self.status}")
            return
        self.status = "starting"
        logger.info("WHATSAPP_WEB_STARTING")
        try:
            await self._launch_browser()
            await self._navigate_and_wait()
            if self.status == "connected":
                # Disabled 2026-07-02: _scan_all_chats() re-processed an
                # already-handled contact, mis-extracted a message fragment,
                # and caused an unreviewed reply to go out to a real landlord.
                # Re-enable once that extraction bug is fixed.
                # await self._run_first_scan_if_needed()
                pass
            if self.status in ("connected", "needs_scan"):
                self._poll_task = asyncio.create_task(
                    self._poll_loop(), name="wa-web-poll"
                )
            else:
                logger.error(
                    f"WHATSAPP_WEB_POLL_NOT_STARTED status={self.status} "
                    "reason=browser did not reach connected or needs_scan state"
                )
        except Exception as exc:
            self.status = "error"
            self.last_error = str(exc)
            self.error_count += 1
            logger.error(f"WHATSAPP_WEB_START_FAILED error={exc}")

    async def stop(self) -> None:
        self._generation += 1  # signals any running _navigate_and_wait to abort
        if self._poll_task:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task
        await self._close_browser()
        self.status = "disconnected"
        logger.info("WHATSAPP_WEB_STOPPED")

    async def force_reconnect(self) -> None:
        logger.info("WHATSAPP_WEB_FORCE_RECONNECT")
        await self.stop()
        await asyncio.sleep(2)
        await self.start()

    # ── Browser management ────────────────────────────────────────────────────

    async def _launch_browser(self) -> None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        proxy = self._proxy_config()

        self._playwright = await async_playwright().start()

        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            # Reduce memory footprint on VPS
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--disable-translate",
            "--metrics-recording-only",
            "--no-first-run",
            "--safebrowsing-disable-auto-update",
        ]

        # On servers without display use Chrome's new headless (far less detectable
        # than old headless, no Xvfb needed). Set HEADLESS=false + run Xvfb for
        # a true visible window on a Linux desktop.
        import os as _os
        import sys as _sys
        headless = settings.WHATSAPP_HEADLESS
        if not headless:
            # macOS (and Windows) render native windows directly — the X11
            # DISPLAY/Xvfb requirement below only applies to Linux.
            if _sys.platform == "darwin":
                logger.info("WHATSAPP_WEB_BROWSER headless=False platform=darwin")
            else:
                display = _os.environ.get("DISPLAY", "")
                if not display:
                    # No display available — set :99 (Xvfb) or fall back to headless
                    if _os.path.exists("/tmp/.X11-unix/X99"):
                        _os.environ["DISPLAY"] = ":99"
                        display = ":99"
                        logger.info("WHATSAPP_WEB_DISPLAY_AUTO_SET display=:99")
                    else:
                        logger.warning(
                            "WHATSAPP_WEB_NO_DISPLAY DISPLAY not set and Xvfb :99 not found — "
                            "falling back to headless=new. Run: Xvfb :99 -screen 0 1280x900x24 &"
                        )
                        headless = True
                if not headless:
                    logger.info(f"WHATSAPP_WEB_BROWSER headless=False display={display}")
        if headless:
            launch_args.append("--headless=new")
            logger.info("WHATSAPP_WEB_BROWSER headless=new (server mode)")

        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=launch_args,
        )

        context_kwargs: dict = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "color_scheme": "light",
            "device_scale_factor": 1,
            "ignore_https_errors": True,
        }
        if proxy:
            context_kwargs["proxy"] = proxy

        if SESSION_FILE.exists():
            context_kwargs["storage_state"] = str(SESSION_FILE)
            logger.info(f"WHATSAPP_WEB_SESSION_RESTORED path={SESSION_FILE}")
        else:
            logger.info("WHATSAPP_WEB_NO_SESSION_FILE starting fresh")

        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()

        # Stealth — mask headless/automation signals that WhatsApp detects
        await self._page.add_init_script("""
            // webdriver flag
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // realistic language list
            Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en-US', 'en']});
            // realistic plugin list (Chrome PDF viewer etc.)
            const _plugins = [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
                {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''},
            ];
            Object.defineProperty(navigator, 'plugins', {
                get: () => Object.assign(_plugins, {
                    item: i => _plugins[i],
                    namedItem: n => _plugins.find(p => p.name === n) || null,
                    refresh: () => {},
                    length: _plugins.length,
                }),
            });
            // hardware concurrency & memory — realistic for a laptop
            Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
            Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
            // screen dimensions — must match viewport
            Object.defineProperty(screen, 'width', {get: () => 1280});
            Object.defineProperty(screen, 'height', {get: () => 900});
            Object.defineProperty(screen, 'availWidth', {get: () => 1280});
            Object.defineProperty(screen, 'availHeight', {get: () => 860});
            Object.defineProperty(screen, 'colorDepth', {get: () => 24});
            Object.defineProperty(screen, 'pixelDepth', {get: () => 24});
            Object.defineProperty(window, 'outerWidth', {get: () => 1280});
            Object.defineProperty(window, 'outerHeight', {get: () => 900});
            // chrome runtime object expected by WhatsApp Web
            window.chrome = {
                runtime: {
                    onMessage: {addListener: () => {}, removeListener: () => {}},
                    onConnect: {addListener: () => {}, removeListener: () => {}},
                },
                loadTimes: function() { return {}; },
                csi: function() { return {}; },
                app: { isInstalled: false },
            };
            // notifications permission — avoid returning 'denied' which signals headless
            const _origQuery = window.navigator.permissions.query.bind(navigator.permissions);
            window.navigator.permissions.query = (params) => {
                if (params && params.name === 'notifications') {
                    return Promise.resolve({state: 'default', onchange: null});
                }
                return _origQuery(params);
            };
        """)
        logger.info("WHATSAPP_WEB_BROWSER_LAUNCHED")

    async def _close_browser(self) -> None:
        with suppress(Exception):
            if self._context:
                await self._context.close()
        with suppress(Exception):
            if self._browser:
                await self._browser.close()
        with suppress(Exception):
            if self._playwright:
                await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    # ── State detection ────────────────────────────────────────────────────────

    async def _detect_state(self) -> str:
        """Return current WhatsApp Web state."""
        page = self._page
        if not page:
            return "disconnected"
        try:
            for sel, state in [
                (SEL_QR, "needs_scan"),
                (SEL_INTRO, "needs_scan"),
            ]:
                if await page.locator(sel).is_visible(timeout=500):
                    return state

            disconnected_text = [
                "Keep your phone connected",
                "Your phone is not connected",
                "Phone not connected",
            ]
            for text in disconnected_text:
                if await page.locator(f"text={text}").is_visible(timeout=300):
                    return "phone_disconnected"

            if await page.locator(SEL_CHAT_LIST).is_visible(timeout=500):
                return "connected"
        except Exception as exc:
            logger.debug(f"WHATSAPP_WEB_STATE_CHECK_ERROR error={exc}")
        return "loading"

    # ── Navigate and wait for connection ──────────────────────────────────────

    async def _navigate_and_wait(self) -> None:
        page = self._page
        my_gen = self._generation
        logger.info("WHATSAPP_WEB_NAVIGATING")
        try:
            # wait_until="commit" fires on first byte received — fast even on slow proxies.
            # _detect_state loop below handles waiting for the app to actually render.
            await page.goto(WA_URL, wait_until="commit", timeout=60000)
        except Exception as exc:
            if self._generation != my_gen:
                logger.info("WHATSAPP_WEB_NAVIGATE_SUPERSEDED — reconnect triggered during goto")
                return
            raise

        # Wait up to 120s — WhatsApp Web can be slow on first load through a proxy
        state = "loading"
        for tick in range(240):
            if self._generation != my_gen:
                logger.info("WHATSAPP_WEB_NAVIGATE_SUPERSEDED — reconnect triggered, aborting")
                return
            state = await self._detect_state()
            if state != "loading":
                break
            if tick % 20 == 0 and tick > 0:
                title = await page.title()
                url = page.url
                logger.info(
                    f"WHATSAPP_WEB_STILL_LOADING tick={tick} title={title!r} url={url}"
                )
            await asyncio.sleep(0.5)

        if state == "loading":
            # Dump what's actually on the page so we can diagnose without a screenshot
            try:
                body_text = await page.evaluate(
                    "() => (document.body && document.body.innerText || '').slice(0, 600)"
                )
                testids = await page.evaluate("""() => {
                    const els = document.querySelectorAll('[data-testid]');
                    return Array.from(els).map(e => e.getAttribute('data-testid')).slice(0, 40);
                }""")
                logger.error(
                    f"WHATSAPP_WEB_LOAD_TIMEOUT "
                    f"title={await page.title()!r} "
                    f"body_text={body_text!r} "
                    f"testids={testids}"
                )
            except Exception as exc:
                logger.error(f"WHATSAPP_WEB_LOAD_TIMEOUT diag_failed={exc}")
            try:
                await page.screenshot(path="whatsapp-diag.png", full_page=True, timeout=10000)
            except Exception:
                pass
            state = "loading"

        logger.info(f"WHATSAPP_WEB_INITIAL_STATE state={state}")

        if state == "needs_scan":
            await self._handle_qr_scan()
            return

        if state == "connected":
            await self._on_connected()
            return

        if state == "phone_disconnected":
            self.status = "error"
            self.last_error = "Phone not connected to internet"
            logger.error("WHATSAPP_WEB_PHONE_DISCONNECTED — ensure phone has internet")
            return

        self.status = "error"
        self.last_error = f"Unexpected state after navigation: {state}"
        logger.error(f"WHATSAPP_WEB_UNEXPECTED_STATE state={state}")

    async def _handle_qr_scan(self) -> None:
        self.status = "needs_scan"
        self.last_error = None
        await self._capture_qr()
        logger.warning(
            "WHATSAPP_WEB_AWAITING_QR_SCAN — open dashboard and scan the QR code"
        )

        # Wait up to 5 minutes, refreshing QR every 30s (WhatsApp rotates it)
        for tick in range(300):
            await asyncio.sleep(1)
            state = await self._detect_state()
            if state == "connected":
                await self._on_connected()
                return
            if state == "needs_scan" and tick % 30 == 0 and tick > 0:
                await self._capture_qr()
                logger.info("WHATSAPP_WEB_QR_REFRESHED")

        self.status = "error"
        self.last_error = "QR scan timeout (5 minutes)"
        logger.error("WHATSAPP_WEB_QR_TIMEOUT")

    async def _on_connected(self) -> None:
        self.status = "connected"
        self.last_active = datetime.utcnow()
        self.last_error = None
        # Clear stale QR
        QR_FILE.unlink(missing_ok=True)
        await self._save_session()
        await self._dismiss_popups()
        logger.info("WHATSAPP_WEB_CONNECTED session_saved=True")

    # ── Popup dismissal ──────────────────────────────────────────────────────────

    async def _dismiss_popups(self, max_attempts: int = 3) -> None:
        """Dismiss WhatsApp Web nag/confirmation popups (notification prompts,
        new-feature cards, etc). These can overlay the chat list and intercept
        clicks, which is a common cause of Locator.click timeouts. Prefers
        Cancel/Not now over OK so we never opt into anything."""
        page = self._page
        if not page:
            return

        for _ in range(max_attempts):
            try:
                popup = page.locator(SEL_POPUP).first
                if not await popup.is_visible(timeout=600):
                    return
            except Exception:
                return

            clicked = False
            for label in _POPUP_DISMISS_LABELS:
                try:
                    btn = popup.get_by_role("button", name=re.compile(rf"^{label}$", re.I))
                    if await btn.count() and await btn.first.is_visible(timeout=400):
                        await btn.first.click(timeout=2000)
                        logger.info(f"WHATSAPP_WEB_POPUP_DISMISSED label={label}")
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                try:
                    buttons = popup.locator('div[role="button"], button')
                    count = await buttons.count()
                    if count:
                        await buttons.nth(count - 1).click(timeout=2000)
                        logger.info("WHATSAPP_WEB_POPUP_DISMISSED_FALLBACK")
                        clicked = True
                except Exception:
                    pass

            if not clicked:
                logger.warning("WHATSAPP_WEB_POPUP_DISMISS_FAILED — no clickable button found")
                return

            await asyncio.sleep(random.uniform(0.4, 0.8))

    async def _click_chat_item(self, item) -> bool:
        """Click a chat row robustly. The chat list is virtualized (rows can
        reposition mid-click) and stray popups can intercept the click point,
        so this retries with popup dismissal, a forced click, and finally a
        raw coordinate click before giving up."""
        try:
            await item.scroll_into_view_if_needed(timeout=5000)
            await item.click(timeout=8000)
            return True
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_CHAT_CLICK_RETRY reason={exc}")

        await self._dismiss_popups()
        try:
            await item.click(timeout=5000, force=True)
            return True
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_CHAT_CLICK_FORCE_FAILED reason={exc}")

        try:
            box = await item.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                await self._page.mouse.click(x, y)
                return True
        except Exception as exc:
            logger.error(f"WHATSAPP_WEB_CHAT_CLICK_COORD_FAILED reason={exc}")

        return False

    # ── QR capture ────────────────────────────────────────────────────────────

    async def _capture_qr(self) -> None:
        # Method 1: clip page screenshot to QR bounding box (works in Xvfb, avoids canvas taint)
        try:
            qr_loc = self._page.locator(SEL_QR)
            bbox = await qr_loc.bounding_box(timeout=5000)
            if bbox and bbox["width"] > 10 and bbox["height"] > 10:
                await self._page.screenshot(
                    path=str(QR_FILE),
                    clip={"x": bbox["x"], "y": bbox["y"],
                          "width": bbox["width"], "height": bbox["height"]},
                    timeout=10000,
                )
                logger.info(
                    f"WHATSAPP_WEB_QR_CAPTURED_CLIP size={QR_FILE.stat().st_size} "
                    f"bbox={bbox} path={QR_FILE}"
                )
                return
            logger.warning(f"WHATSAPP_WEB_QR_BBOX_EMPTY bbox={bbox}")
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_QR_CLIP_FAILED error={exc}")

        # Method 2: element screenshot
        try:
            await self._page.locator(SEL_QR).screenshot(path=str(QR_FILE), timeout=10000)
            logger.info(f"WHATSAPP_WEB_QR_CAPTURED_ELEMENT path={QR_FILE}")
            return
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_QR_ELEMENT_FAILED error={exc}")

        # Method 3: full page screenshot
        try:
            await self._page.screenshot(path=str(QR_FILE), timeout=10000)
            logger.info("WHATSAPP_WEB_QR_CAPTURED_FULLPAGE")
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_QR_FULLPAGE_FAILED error={exc}")

    # ── Session persistence ────────────────────────────────────────────────────

    async def _save_session(self) -> None:
        try:
            await self._context.storage_state(path=str(SESSION_FILE))
            logger.info(f"WHATSAPP_WEB_SESSION_SAVED path={SESSION_FILE}")
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_SESSION_SAVE_FAILED error={exc}")

    # ── Poll loop ─────────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        logger.info("WHATSAPP_WEB_POLL_LOOP_STARTED interval=10-15min")
        consecutive_errors = 0

        while True:
            try:
                await asyncio.sleep(random.randint(600, 900))

                if self.status != "connected":
                    continue

                state = await self._detect_state()
                if state != "connected":
                    logger.warning(
                        f"WHATSAPP_WEB_STATE_DRIFT detected={state} was=connected"
                    )
                    self.status = state
                    self.last_error = f"Session drifted to: {state}"
                    if state == "needs_scan":
                        await self._capture_qr()
                        logger.error(
                            "WHATSAPP_WEB_SESSION_EXPIRED — QR saved, check dashboard"
                        )
                    continue

                await self._process_unread_chats()
                await self._dispatch_due_cancellations()
                await self._dispatch_due_replies()
                # Periodic re-scan disabled 2026-07-02: it re-processed a contact
                # that _process_unread_chats() had just handled correctly in the
                # same cycle, extracted a garbled message fragment, and sent an
                # unreviewed reply to a real landlord. Do not re-enable until the
                # extraction bug is fixed and re-processing is gated on the
                # contact not having been touched moments earlier.
                # await self._scan_all_chats()
                consecutive_errors = 0

            except asyncio.CancelledError:
                logger.info("WHATSAPP_WEB_POLL_LOOP_CANCELLED")
                raise
            except Exception as exc:
                consecutive_errors += 1
                self.error_count += 1
                self.last_error = str(exc)
                logger.error(
                    f"WHATSAPP_WEB_POLL_ERROR error={exc} "
                    f"consecutive={consecutive_errors} total={self.error_count}"
                )

                if consecutive_errors >= 5:
                    logger.error(
                        "WHATSAPP_WEB_TOO_MANY_CONSECUTIVE_ERRORS "
                        f"count={consecutive_errors} — attempting reconnect"
                    )
                    await self._reconnect()
                    consecutive_errors = 0

    # ── Incoming message processing ───────────────────────────────────────────

    async def _chat_item_key(self, item) -> Optional[str]:
        """Stable identifier for a chat-list row (its title text), used to
        dedupe across scrolls. Positional locators (.nth(N)) aren't stable
        since the list is virtualized and rows remount at different indices
        as it scrolls."""
        try:
            title_el = item.locator('[data-testid="cell-frame-title"] span[title]').first
            title = await title_el.get_attribute("title", timeout=1500)
            if title:
                return title.strip()
        except Exception:
            pass
        try:
            text = await item.inner_text(timeout=1500)
            text = text.strip()
            return text[:120] or None
        except Exception:
            return None

    async def _scroll_chat_list(self) -> None:
        try:
            await self._page.locator(SEL_CHAT_LIST).evaluate(
                "el => el.scrollBy(0, Math.max(el.clientHeight * 0.85, 300))"
            )
            await asyncio.sleep(random.uniform(0.6, 1.0))
        except Exception as exc:
            logger.debug(f"WHATSAPP_WEB_CHAT_LIST_SCROLL_FAILED error={exc}")

    async def _extract_unread_messages_with_retry(
        self, attempts: int = 3, delay: float = 0.8
    ) -> list[tuple[str, str]]:
        """Message bubbles can still be rendering right after opening a chat
        (especially on a slow proxy), so retry briefly before giving up."""
        for attempt in range(attempts):
            messages = await self._extract_unread_messages()
            if messages:
                return messages
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
        return []

    async def _next_unread_item(self, processed_keys: set[str]):
        """Re-query the unread-chat selector fresh and return the first row
        not yet processed. The selector match set shrinks as each chat's
        badge clears on open, so any previously-fetched batch of locators
        goes stale immediately — this must be queried fresh every time."""
        try:
            unread_items = await self._page.locator(
                f"{SEL_CHAT_ITEM}:has({SEL_UNREAD_BADGE})"
            ).all()
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_UNREAD_QUERY_FAILED error={exc}")
            return None, None

        for item in unread_items:
            key = await self._chat_item_key(item)
            if key and key not in processed_keys:
                return key, item
        return None, None

    async def _process_unread_chats(self) -> None:
        await self._dismiss_popups()

        processed_keys: set[str] = set()
        empty_rounds = 0
        max_iterations = 60

        for _ in range(max_iterations):
            key, item = await self._next_unread_item(processed_keys)

            if item is None:
                empty_rounds += 1
                if empty_rounds >= 2:
                    # Two consecutive scrolls with nothing new -> end of list
                    break
                await self._scroll_chat_list()
                continue

            empty_rounds = 0
            processed_keys.add(key)

            try:
                await self._dismiss_popups()
                if not await self._click_chat_item(item):
                    logger.error("WHATSAPP_WEB_CHAT_CLICK_FAILED — skipping chat")
                    continue
                await asyncio.sleep(random.uniform(0.8, 1.5))

                phone = await self._extract_phone_from_current_chat()
                sender_name = await self._extract_name_from_header()
                if not sender_name:
                    # Header only shows the phone for unsaved contacts — the
                    # WhatsApp push name lives in the contact info panel.
                    sender_name = await self._extract_name_from_contact_panel()

                if not phone:
                    logger.warning(
                        "WHATSAPP_WEB_PHONE_EXTRACT_FAILED — skipping chat, "
                        "could not determine phone from header"
                    )
                    continue

                messages = await self._extract_unread_messages_with_retry()
                logger.info(
                    f"WHATSAPP_WEB_MESSAGES_FOUND phone={phone} count={len(messages)}"
                )

                for msg_id, text in messages:
                    if msg_id in self._seen_message_ids:
                        continue
                    self._seen_message_ids.add(msg_id)
                    if len(self._seen_message_ids) > _MAX_SEEN_IDS:
                        self._seen_message_ids = set(
                            list(self._seen_message_ids)[-_MAX_SEEN_IDS // 2:]
                        )

                    logger.info(
                        f"WHATSAPP_WEB_INCOMING phone={phone} "
                        f"name={sender_name!r} text={text[:80]!r}"
                    )

                    from app.whatsapp.handler import handle_incoming_message
                    await handle_incoming_message(
                        phone_number=phone,
                        message=text,
                        timestamp=int(time.time()),
                        sender_name=sender_name,
                    )

                self.last_active = datetime.utcnow()

            except Exception as exc:
                logger.error(f"WHATSAPP_WEB_CHAT_PROCESS_ERROR error={exc}")

            await asyncio.sleep(random.uniform(0.5, 1.2))

        if processed_keys:
            logger.info(f"WHATSAPP_WEB_UNREAD_CHATS_TOTAL count={len(processed_keys)}")

    async def _next_chat_item(self, processed_keys: set[str]):
        """Like _next_unread_item but walks the ENTIRE chat list (no unread
        filter) — used by the full backfill/re-match scan."""
        try:
            items = await self._page.locator(SEL_CHAT_ITEM).all()
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_CHAT_LIST_QUERY_FAILED error={exc}")
            return None, None

        for item in items:
            key = await self._chat_item_key(item)
            if key and key not in processed_keys:
                return key, item
        return None, None

    async def _scan_all_chats(self) -> None:
        """Walk every chat (not just unread ones) to backfill phone/name and
        attempt property matching for contacts we haven't resolved yet.

        Skips any chat whose contact is already MATCHED or CANCELLED — for
        unsaved contacts (row title is a raw phone number) this is checked
        against the DB without even opening the chat. Used both for the
        one-time first-run backfill and, on every poll cycle, to keep
        re-trying contacts stuck without a property match (e.g. because they
        never answered the "which property?" ask, or a new listing since
        made them matchable).
        """
        from app.whatsapp.repository import get_contact_by_phone

        await self._dismiss_popups()

        processed_keys: set[str] = set()
        empty_rounds = 0
        max_iterations = 300
        visited = 0
        skipped = 0

        for _ in range(max_iterations):
            key, item = await self._next_chat_item(processed_keys)

            if item is None:
                empty_rounds += 1
                if empty_rounds >= 2:
                    # Two consecutive scrolls with nothing new -> end of list
                    break
                await self._scroll_chat_list()
                continue

            empty_rounds = 0
            processed_keys.add(key)

            title_phone = _phone_from_title(key)
            if title_phone:
                existing = await asyncio.to_thread(get_contact_by_phone, title_phone)
                if existing and (
                    existing.match_status == "MATCHED" or existing.status == "CANCELLED"
                ):
                    skipped += 1
                    continue

            try:
                await self._dismiss_popups()
                if not await self._click_chat_item(item):
                    logger.error("WHATSAPP_WEB_CHAT_CLICK_FAILED — skipping chat")
                    continue
                await asyncio.sleep(random.uniform(0.8, 1.5))

                phone = await self._extract_phone_from_current_chat()
                if not phone:
                    logger.warning(
                        "WHATSAPP_WEB_PHONE_EXTRACT_FAILED — skipping chat, "
                        "could not determine phone from header"
                    )
                    continue

                existing = await asyncio.to_thread(get_contact_by_phone, phone)
                if existing and (
                    existing.match_status == "MATCHED" or existing.status == "CANCELLED"
                ):
                    skipped += 1
                    continue

                sender_name = await self._extract_name_from_header()
                if not sender_name:
                    sender_name = await self._extract_name_from_contact_panel()

                messages = await self._extract_unread_messages_with_retry()
                if not messages:
                    logger.info(f"WHATSAPP_WEB_SCAN_NO_MESSAGES phone={phone}")
                    continue

                for msg_id, text in messages:
                    if msg_id in self._seen_message_ids:
                        continue
                    self._seen_message_ids.add(msg_id)
                    if len(self._seen_message_ids) > _MAX_SEEN_IDS:
                        self._seen_message_ids = set(
                            list(self._seen_message_ids)[-_MAX_SEEN_IDS // 2:]
                        )

                    logger.info(
                        f"WHATSAPP_WEB_SCAN_INCOMING phone={phone} "
                        f"name={sender_name!r} text={text[:80]!r}"
                    )

                    from app.whatsapp.handler import handle_incoming_message
                    await handle_incoming_message(
                        phone_number=phone,
                        message=text,
                        timestamp=int(time.time()),
                        sender_name=sender_name,
                    )

                visited += 1
                self.last_active = datetime.utcnow()

            except Exception as exc:
                logger.error(f"WHATSAPP_WEB_SCAN_CHAT_ERROR error={exc}")

            await asyncio.sleep(random.uniform(0.5, 1.2))

        logger.info(
            f"WHATSAPP_WEB_FULL_SCAN_DONE processed={visited} skipped={skipped} "
            f"total_seen={len(processed_keys)}"
        )

    async def _run_first_scan_if_needed(self) -> None:
        from app.db.repository import get_app_setting, set_app_setting

        try:
            done = await asyncio.to_thread(
                get_app_setting, "whatsapp_first_full_scan_done"
            )
            if done:
                return
            logger.info("WHATSAPP_WEB_FIRST_SCAN_STARTING")
            await self._scan_all_chats()
            await asyncio.to_thread(
                set_app_setting, "whatsapp_first_full_scan_done", "true"
            )
            logger.info("WHATSAPP_WEB_FIRST_SCAN_COMPLETE")
        except Exception as exc:
            logger.error(f"WHATSAPP_WEB_FIRST_SCAN_FAILED error={exc}")

    async def _extract_phone_from_current_chat(self) -> Optional[str]:
        page = self._page
        # Method 1: phone is in page URL after clicking a chat
        url = page.url
        m = re.search(r"/(\d{7,15})@", url)
        if m:
            return m.group(1)

        # Method 2: chat title looks like a phone number
        try:
            title_el = page.locator(SEL_CONV_TITLE)
            title = (await title_el.inner_text(timeout=3000)).strip()
            digits = re.sub(r"[\s\-\(\)\+]", "", title)
            if re.match(r"^\d{7,15}$", digits):
                return digits
        except Exception as exc:
            logger.debug(f"WHATSAPP_WEB_TITLE_READ_ERROR error={exc}")

        # Method 3: extract from URL via JS
        try:
            phone_from_url = await page.evaluate("""
                () => {
                    const m = window.location.href.match(/\\/([\\d]{7,15})@/);
                    return m ? m[1] : null;
                }
            """)
            if phone_from_url:
                return phone_from_url
        except Exception:
            pass

        return None

    async def _extract_name_from_header(self) -> Optional[str]:
        try:
            title_el = self._page.locator(SEL_CONV_TITLE)
            title = (await title_el.inner_text(timeout=2000)).strip()
            # Only return as name if it doesn't look like a phone number
            if title and not re.match(r"^[\d\s\+\-\(\)]{7,}$", title):
                return title
        except Exception:
            pass
        return None

    async def _extract_name_from_contact_panel(self) -> Optional[str]:
        """Open the contact info panel and read the WhatsApp push name.
        For unsaved contacts, the conversation header only shows the phone
        number — the self-set display name (e.g. "~Jessy") only appears
        here, next to the phone number in the profile section."""
        page = self._page
        try:
            await self._dismiss_popups()
            await page.locator(SEL_CONTACT_INFO_HEADER).click(timeout=3000)
            await page.locator(SEL_CONTACT_INFO_SUBTITLE).wait_for(
                state="visible", timeout=3000
            )

            name = await page.evaluate("""
                () => {
                    const subtitle = document.querySelector(
                        '[data-testid="contact-info-subtitle selectable-text"]'
                    );
                    if (!subtitle) return null;
                    const scope = subtitle.closest('section') || subtitle.parentElement;
                    if (!scope) return null;
                    const candidates = scope.querySelectorAll('[data-testid="selectable-text"]');
                    for (const el of candidates) {
                        const text = (el.innerText || '').trim();
                        if (text) return text;
                    }
                    return null;
                }
            """)

            await page.keyboard.press("Escape")
            await asyncio.sleep(random.uniform(0.3, 0.6))

            if name:
                # WhatsApp prefixes a self-set (unsaved-contact) name with "~"
                cleaned = name.lstrip("~").strip()
                return cleaned or None
        except Exception as exc:
            logger.debug(f"WHATSAPP_WEB_CONTACT_PANEL_NAME_FAILED error={exc}")
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        return None

    async def _extract_unread_messages(self) -> list[tuple[str, str]]:
        """Return list of (unique_id, text) for the most recent inbound
        messages in the current chat.

        Previously this looked for `[data-testid="unread-messages-anchor"]`
        and only read messages after it. WhatsApp removes that anchor (marks
        the chat read) almost immediately once the conversation view opens,
        so by the time we read the DOM it's frequently already gone — this
        was silently returning zero messages for chats that plainly had new
        text. Instead, just read the last few inbound bubbles unconditionally
        and rely on the caller's `_seen_message_ids` dedup (by data-id) to
        skip anything already processed in a prior poll.
        """
        page = self._page
        try:
            results: list[dict] = await page.evaluate("""
                () => {
                    const results = [];
                    const containers = document.querySelectorAll('[data-testid="msg-container"]');
                    const recent = Array.from(containers).slice(-8);

                    for (const c of recent) {
                        // Skip outgoing messages (fromMe)
                        if (c.closest('[data-id*="true"]')) continue;
                        const textEl = c.querySelector('.copyable-text span[dir="ltr"]')
                            || c.querySelector('span[dir="ltr"]')
                            || c.querySelector('.selectable-text');
                        const text = textEl ? textEl.innerText.trim() : '';
                        if (!text) continue;
                        const dataId = c.closest('[data-id]')
                            ? c.closest('[data-id]').getAttribute('data-id')
                            : null;
                        const msgId = dataId || (Date.now() + Math.random()).toString();
                        results.push({ id: msgId, text: text });
                    }
                    return results;
                }
            """)
            return [(r["id"], r["text"]) for r in (results or [])]
        except Exception as exc:
            logger.error(
                f"WHATSAPP_WEB_EXTRACT_MESSAGES_FAILED error={exc} "
                "reason=JS evaluation failed — selector may have changed"
            )
            return []

    # ── Sending messages ──────────────────────────────────────────────────────

    async def send_message(self, phone: str, text: str) -> bool:
        if self.status != "connected" or not self._page:
            logger.warning(
                f"WHATSAPP_WEB_SEND_SKIPPED status={self.status} phone={phone} "
                "reason=worker not connected"
            )
            return False

        async with self._send_lock:
            try:
                return await self._do_send(phone, text)
            except Exception as exc:
                self.last_error = str(exc)
                self.error_count += 1
                logger.error(
                    f"WHATSAPP_WEB_SEND_ERROR phone={phone} error={exc} "
                    f"reason=send failed after opening chat"
                )
                return False

    async def _do_send(self, phone: str, text: str) -> bool:
        page = self._page
        clean_phone = re.sub(r"\D", "", phone)

        logger.info(
            f"WHATSAPP_WEB_SEND_START phone={clean_phone} text_len={len(text)}"
        )

        # Open chat via direct URL — most reliable
        await page.goto(
            f"{WA_URL}/send?phone={clean_phone}",
            wait_until="commit",
            timeout=30000,
        )
        await asyncio.sleep(random.uniform(2.5, 4.5))
        await self._dismiss_popups()

        # Wait for compose box
        compose = page.locator(SEL_COMPOSE)
        try:
            await compose.wait_for(state="visible", timeout=15000)
        except Exception:
            logger.error(
                f"WHATSAPP_WEB_COMPOSE_NOT_FOUND phone={clean_phone} "
                "reason=compose box selector missing — WhatsApp Web may have updated"
            )
            await page.goto(WA_URL, wait_until="domcontentloaded", timeout=15000)
            return False

        await compose.click()
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # Type with human-like per-character delay
        for char in text:
            await page.keyboard.type(char, delay=random.randint(40, 110))

        # Human pause before send
        await asyncio.sleep(random.uniform(1.0, 2.5))
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(0.8, 1.5))

        await self._save_session()

        # Return to chat list
        await page.goto(WA_URL, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        self.last_active = datetime.utcnow()
        logger.info(f"WHATSAPP_WEB_SENT phone={clean_phone}")
        return True

    # ── Cancellation dispatch ──────────────────────────────────────────────────

    _CANCELLATION_MESSAGES = [
        "Hey, just to let you know we've had to cancel the viewing unfortunately. Really sorry about that!",
        "Hi, bad news from our end — we won't be able to make the viewing. Really sorry for the inconvenience.",
        "Hey, just wanted to give you a heads up — we've had to cancel the viewing. Sorry about that!",
        "Hi, unfortunately something's come up and we can't make the viewing anymore. Really sorry for any hassle.",
        "Hey, just letting you know the viewing's been cancelled on our end. Apologies for any inconvenience!",
    ]

    async def _dispatch_due_cancellations(self) -> None:
        from app.ai.replies import generate_cancellation_message
        from app.db.repository import (
            get_automatic_cancellation_block_reason,
            mark_viewing_cancelled,
            save_message,
        )
        from app.whatsapp.repository import (
            get_contact_messages_for_ai,
            get_contacts_due_for_cancellation,
            get_conversation_for_contact,
            mark_contact_cancelled,
        )

        contacts = await asyncio.to_thread(get_contacts_due_for_cancellation)
        if not contacts:
            return

        logger.info(f"WHATSAPP_WEB_CANCELLATION_DUE count={len(contacts)}")
        for contact in contacts:
            conversation = await asyncio.to_thread(get_conversation_for_contact, contact)
            thread_id = conversation.thread_id if conversation else None

            if thread_id:
                block_reason = await asyncio.to_thread(
                    get_automatic_cancellation_block_reason, thread_id
                )
                if block_reason:
                    logger.info(
                        f"WHATSAPP_WEB_CANCELLATION_BLOCKED phone={contact.phone_number} "
                        f"reason={block_reason}"
                    )
                    continue

            history = await asyncio.to_thread(get_contact_messages_for_ai, contact)
            msg, error = await asyncio.to_thread(generate_cancellation_message, history)
            if not msg or error:
                logger.warning(
                    f"WHATSAPP_WEB_CANCELLATION_AI_FAILED phone={contact.phone_number} "
                    f"error={error} reason=falling back to canned message"
                )
                msg = random.choice(self._CANCELLATION_MESSAGES)

            ok = await self.send_message(contact.phone_number, msg)
            if ok:
                await asyncio.to_thread(mark_contact_cancelled, contact.id)
                if thread_id:
                    await asyncio.to_thread(save_message, thread_id, "outbound", msg)
                    await asyncio.to_thread(mark_viewing_cancelled, thread_id)
                logger.info(
                    f"WHATSAPP_WEB_CANCELLATION_SENT phone={contact.phone_number} "
                    f"contact_id={contact.id}"
                )
            else:
                logger.warning(
                    f"WHATSAPP_WEB_CANCELLATION_SEND_FAILED phone={contact.phone_number} "
                    "reason=send failed — will retry next poll"
                )

    # ── Reply dispatch (replaces the old Baileys dispatcher) ──────────────────

    async def _dispatch_due_replies(self) -> None:
        from app.whatsapp.repository import get_due_contacts, mark_reply_sent, update_contact

        contacts = await asyncio.to_thread(get_due_contacts)
        if not contacts:
            return

        logger.info(f"WHATSAPP_WEB_DISPATCH due_count={len(contacts)}")
        for contact in contacts:
            reply = getattr(contact, "last_ai_reply", None)
            if not reply:
                await asyncio.to_thread(mark_reply_sent, contact.id)
                continue

            ok = await self.send_message(contact.phone_number, reply)
            if ok:
                await asyncio.to_thread(mark_reply_sent, contact.id)
                logger.info(
                    f"WHATSAPP_WEB_REPLY_DISPATCHED phone={contact.phone_number} "
                    f"status={contact.status}"
                )
            else:
                new_time = datetime.utcnow() + timedelta(minutes=5)
                await asyncio.to_thread(
                    update_contact, contact.id, reply_scheduled_at=new_time
                )
                logger.warning(
                    f"WHATSAPP_WEB_REPLY_RESCHEDULED phone={contact.phone_number} "
                    "reason=send failed rescheduled=+5m"
                )

    # ── Reconnect ─────────────────────────────────────────────────────────────

    async def _reconnect(self) -> None:
        self.status = "reconnecting"
        logger.info(
            f"WHATSAPP_WEB_RECONNECT_START backoff={_RECONNECT_BACKOFF_SECONDS}s"
        )
        await self._close_browser()
        await asyncio.sleep(_RECONNECT_BACKOFF_SECONDS)
        try:
            await self._launch_browser()
            await self._navigate_and_wait()
            logger.info("WHATSAPP_WEB_RECONNECT_SUCCESS")
        except Exception as exc:
            self.status = "error"
            self.last_error = str(exc)
            self.error_count += 1
            logger.error(f"WHATSAPP_WEB_RECONNECT_FAILED error={exc}")

    # ── Status ─────────────────────────────────────────────────────────────────

    def get_status_dict(self) -> dict:
        return {
            "status": self.status,
            "proxy_id": self.proxy_id,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "qr_available": QR_FILE.exists() and self.status == "needs_scan",
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_worker: Optional[WhatsAppWebWorker] = None


def get_worker() -> WhatsAppWebWorker:
    global _worker
    if _worker is None:
        _worker = WhatsAppWebWorker()
    return _worker


async def start_whatsapp_worker() -> None:
    worker = get_worker()
    # Auto-select a random static proxy on first boot only (not on reconnects).
    # Skipped if WHATSAPP_PROXY_ID is set in .env or user already chose one.
    if not worker.proxy_id and not worker._proxy_user_cleared and settings.WHATSAPP_USE_PROXY:
        worker._auto_select_proxy()
    asyncio.create_task(worker.start(), name="wa-web-start")
    logger.info("WHATSAPP_WEB_WORKER_QUEUED")


async def stop_whatsapp_worker() -> None:
    global _worker
    if _worker:
        await _worker.stop()
