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