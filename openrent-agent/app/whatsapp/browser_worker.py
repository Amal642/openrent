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
SEL_QR = '[data-testid="qr-code"]'
SEL_CHAT_LIST = '[data-testid="chat-list"]'
SEL_INTRO = '[data-testid="intro-title"]'
SEL_UNREAD_BADGE = '[data-testid="icon-unread-count"]'
SEL_CHAT_ITEM = '[data-testid="cell-frame-container"]'
SEL_COMPOSE = '[data-testid="compose-box"]'
SEL_CONV_TITLE = '[data-testid="conversation-info-header-chat-title"]'
SEL_UNREAD_ANCHOR = '[data-testid="unread-messages-anchor"]'

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
        self.last_active: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.error_count: int = 0
        self._seen_message_ids: set[str] = set()

    # ── Proxy ──────────────────────────────────────────────────────────────────

    def _proxy_config(self) -> Optional[dict]:
        if not self.proxy_id:
            return None
        try:
            from app.db.repository import get_proxy
            proxy = get_proxy(self.proxy_id)  # returns a dict
            if not proxy:
                logger.warning(f"WHATSAPP_WEB_PROXY_NOT_FOUND proxy_id={self.proxy_id}")
                return None
            # get_proxy returns a serialized dict
            host = proxy.get("host") if isinstance(proxy, dict) else getattr(proxy, "host", None)
            port = proxy.get("port") if isinstance(proxy, dict) else getattr(proxy, "port", None)
            is_active = proxy.get("is_active", True) if isinstance(proxy, dict) else getattr(proxy, "is_active", True)
            username = proxy.get("username", "") if isinstance(proxy, dict) else (getattr(proxy, "username", "") or "")
            password = proxy.get("password", "") if isinstance(proxy, dict) else (getattr(proxy, "password", "") or "")
            if is_active and host:
                server = f"http://{host}:{port}"
                logger.info(f"WHATSAPP_WEB proxy_server={server} proxy_id={self.proxy_id}")
                return {"server": server, "username": username or "", "password": password or ""}
            logger.warning(f"WHATSAPP_WEB_PROXY_INACTIVE proxy_id={self.proxy_id}")
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_PROXY_LOAD_FAILED error={exc}")
        return None

    def set_proxy(self, proxy_id: Optional[int]) -> None:
        old = self.proxy_id
        self.proxy_id = proxy_id
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
        # Auto-pick a static proxy if none has been explicitly assigned
        if not self.proxy_id:
            self._auto_select_proxy()
        try:
            await self._launch_browser()
            await self._navigate_and_wait()
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
        ]

        # On servers without display use Chrome's new headless (far less detectable
        # than old headless, no Xvfb needed). Set HEADLESS=false + run Xvfb for
        # a true visible window on a desktop.
        headless = settings.WHATSAPP_HEADLESS
        if not headless:
            logger.info("WHATSAPP_WEB_BROWSER headless=False (visible window — needs display)")
        else:
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
                "Chrome/124.0.0.0 Safari/537.36"
            ),
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

        # Mask automation fingerprint
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
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
        await page.goto(WA_URL, wait_until="domcontentloaded", timeout=45000)

        # Wait up to 60s — WhatsApp Web can be slow on first load
        state = "loading"
        for tick in range(120):
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
            # Take a screenshot so we can see what's on the page
            try:
                diag_path = "whatsapp-diag.png"
                await page.screenshot(path=diag_path, full_page=True)
                title = await page.title()
                logger.error(
                    f"WHATSAPP_WEB_LOAD_TIMEOUT title={title!r} "
                    f"screenshot_saved={diag_path} "
                    "reason=page did not reach a known state in 60s — "
                    "check screenshot, may be blocked or JS not loading"
                )
            except Exception as exc:
                logger.error(f"WHATSAPP_WEB_LOAD_TIMEOUT screenshot_failed={exc}")
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
        logger.info("WHATSAPP_WEB_CONNECTED session_saved=True")

    # ── QR capture ────────────────────────────────────────────────────────────

    async def _capture_qr(self) -> None:
        try:
            qr = self._page.locator(SEL_QR)
            await qr.screenshot(path=str(QR_FILE))
            logger.info(f"WHATSAPP_WEB_QR_CAPTURED path={QR_FILE}")
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_QR_CAPTURE_FAILED error={exc}")
            # Fallback: screenshot the full page
            try:
                await self._page.screenshot(path=str(QR_FILE))
                logger.info("WHATSAPP_WEB_QR_FULLPAGE_FALLBACK")
            except Exception:
                pass

    # ── Session persistence ────────────────────────────────────────────────────

    async def _save_session(self) -> None:
        try:
            await self._context.storage_state(path=str(SESSION_FILE))
            logger.info(f"WHATSAPP_WEB_SESSION_SAVED path={SESSION_FILE}")
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_SESSION_SAVE_FAILED error={exc}")

    # ── Poll loop ─────────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        logger.info("WHATSAPP_WEB_POLL_LOOP_STARTED interval=10-25s")
        consecutive_errors = 0

        while True:
            try:
                await asyncio.sleep(random.randint(10, 25))

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
                await self._dispatch_due_replies()
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

    async def _process_unread_chats(self) -> None:
        page = self._page
        try:
            unread_items = await page.locator(
                f"{SEL_CHAT_ITEM}:has({SEL_UNREAD_BADGE})"
            ).all()
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_UNREAD_QUERY_FAILED error={exc}")
            return

        if not unread_items:
            return

        logger.info(f"WHATSAPP_WEB_UNREAD_CHATS count={len(unread_items)}")

        for item in unread_items:
            try:
                await item.click()
                await asyncio.sleep(random.uniform(0.8, 1.5))

                phone = await self._extract_phone_from_current_chat()
                sender_name = await self._extract_name_from_header()

                if not phone:
                    logger.warning(
                        "WHATSAPP_WEB_PHONE_EXTRACT_FAILED — skipping chat, "
                        "could not determine phone from header"
                    )
                    continue

                messages = await self._extract_unread_messages()
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

    async def _extract_unread_messages(self) -> list[tuple[str, str]]:
        """Return list of (unique_id, text) for unread messages in current chat."""
        page = self._page
        try:
            results: list[dict] = await page.evaluate("""
                () => {
                    const results = [];

                    // Find unread anchor — messages after it are new
                    const anchor = document.querySelector('[data-testid="unread-messages-anchor"]');
                    let nodes = [];

                    if (anchor) {
                        let el = anchor.parentElement
                            ? anchor.parentElement.nextElementSibling
                            : anchor.nextElementSibling;
                        while (el) {
                            nodes.push(el);
                            el = el.nextElementSibling;
                        }
                    } else {
                        // No anchor: grab last message as fallback
                        const all = document.querySelectorAll('[data-testid="msg-container"]');
                        if (all.length > 0) nodes = [all[all.length - 1].parentElement];
                    }

                    for (const node of nodes) {
                        const containers = node.querySelectorAll
                            ? node.querySelectorAll('[data-testid="msg-container"]')
                            : [];
                        for (const c of containers) {
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
            wait_until="domcontentloaded",
            timeout=20000,
        )
        await asyncio.sleep(random.uniform(2.5, 4.5))

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
    asyncio.create_task(worker.start(), name="wa-web-start")
    logger.info("WHATSAPP_WEB_WORKER_QUEUED")


async def stop_whatsapp_worker() -> None:
    global _worker
    if _worker:
        await _worker.stop()
