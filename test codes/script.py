import asyncio
from playwright.async_api import async_playwright


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://hasdata.com/blog/scraping-playwright-and-python")
        
        h1 = await page.text_content("h1")
        print("H1:", h1)


        paragraphs = await page.query_selector_all("p")
        for i, p_tag in enumerate(paragraphs, 1):
            text = await p_tag.inner_text()
            print(f"Paragraph {i}:", text)


        await browser.close()


asyncio.run(run())