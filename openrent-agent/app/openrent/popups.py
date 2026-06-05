from app.utils.logger import logger
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


async def close_verified_tenant_popup(page):

    modal = page.locator("#vt-popup-modal")

    try:

        if await modal.count() == 0:
            return False

        if not await modal.first.is_visible():
            return False

        logger.info("VERIFIED TENANT MODAL DETECTED")
        print("VERIFIED TENANT MODAL DETECTED")

        close_selectors = [
            '#vt-popup-modal button[data-bs-dismiss="modal"]',
            '#vt-popup-modal button:has-text("Not Today")',
            '#vt-popup-modal a:has-text("Not Today")',
            '#vt-popup-modal button:has-text("Close")',
            '#vt-popup-modal a:has-text("Close")',
            '#vt-popup-modal .btn-outline-secondary',
        ]

        closed = False

        for selector in close_selectors:

            try:

                button = page.locator(selector)

                if await button.count() == 0:
                    continue

                visible_button = button.first

                if not await visible_button.is_visible():
                    continue

                await visible_button.click(timeout=3000, force=True)
                closed = True
                break

            except Exception as e:

                logger.warning(
                    f"Verified Tenant modal close attempt failed: "
                    f"{selector} -> {e}"
                )

        if not closed:
            return False

        try:
            await modal.first.wait_for(state="hidden", timeout=5000)
        except PlaywrightTimeoutError:
            await page.wait_for_timeout(500)

        logger.info("VERIFIED TENANT MODAL CLOSED")
        print("VERIFIED TENANT MODAL CLOSED")

        return True

    except Exception as e:

        logger.warning(f"Verified Tenant modal handling failed: {e}")
        return False


async def close_popups(page):

    popup_selectors = [

        # Bootstrap close buttons
        '[data-bs-dismiss="modal"]',
        '.btn-close',
        '.modal .btn-close',

        # Generic close labels
        '[aria-label="Close"]',

        # Cookie banners
        'button:has-text("Accept")',
        'button:has-text("Accept All")',
        'button:has-text("I Understand")',

        # OpenRent specific
        '#show-landlord-contact-details-modal button',
        '#screening-options-modal button'
    ]

    for selector in popup_selectors:

        try:

            elements = page.locator(selector)

            count = await elements.count()

            for i in range(count):

                try:

                    element = elements.nth(i)

                    if await element.is_visible():

                        text = ""

                        try:
                            text = await element.inner_text()
                        except:
                            pass

                        print(
                            f"Closing popup element: "
                            f"{selector} -> {text}"
                        )

                        await element.click(
                            timeout=2000,
                            force=True
                        )

                        await page.wait_for_timeout(500)

                except Exception as e:

                    print(
                        f"Popup element click failed: {e}"
                    )

        except Exception as e:

            print(
                f"Popup selector failed: {selector} -> {e}"
            )

    # Remove leftover modal backdrops
    try:

        await page.evaluate("""
            () => {

                document
                    .querySelectorAll(
                        '.modal-backdrop'
                    )
                    .forEach(el => el.remove())

                document.body.classList.remove(
                    'modal-open'
                )

                document.body.style.overflow = 'auto'
            }
        """)

    except Exception as e:

        print(
            f"Backdrop cleanup failed: {e}"
        )
async def handle_confirmation_popups(page):

    try:

        alertify = page.locator(".alertify")

        if await alertify.count() > 0:

            message = ""

            try:
                message = await page.locator(
                    ".alertify-message"
                ).inner_text()
            except:
                pass

            print(
                f"Confirmation popup detected: {message}"
            )

            ok_button = page.locator("#aOK")

            if await ok_button.count() > 0:

                await ok_button.click(force=True)

                print(
                    "Clicked confirmation OK"
                )

                await page.wait_for_timeout(1000)

                return True

    except Exception as e:

        print(
            f"Confirmation popup failed: {e}"
        )

    return False
