"""The actual browser steps. Each one is wrapped in `status.step()` so a failed
run tells you exactly where it broke and how long every step took."""
from playwright.async_api import Page, expect


class PortalError(Exception):
    """The portal rejected our input (shown in its error banner). Not worth retrying."""


async def check_for_error(page: Page):
    banner = page.locator("#error")
    if await banner.count():
        raise PortalError(await banner.inner_text())


async def login(page: Page, base_url, username, password):
    await page.goto(f"{base_url}/login")
    await page.fill("#username", username)
    await page.fill("#password", password)
    await page.click("#sign-in")
    await page.wait_for_load_state("domcontentloaded")
    await check_for_error(page)
    await expect(page).to_have_url(f"{base_url}/filing/company")


async def fill_company(page: Page, req):
    await page.fill("#company_name", req.company_name)
    await page.select_option("#state", req.state)
    await page.fill("#email", req.email)
    await page.click("#next")
    await page.wait_for_load_state("domcontentloaded")
    await check_for_error(page)


async def fill_agent(page: Page, req):
    await expect(page.locator("#agent_name")).to_be_visible()
    await page.fill("#agent_name", req.agent_name)
    await page.fill("#agent_address", req.agent_address)
    await page.fill("#agent_zip", req.agent_zip)
    await page.click("#next")
    await page.wait_for_load_state("domcontentloaded")
    await check_for_error(page)


async def review_and_submit(page: Page, req):
    summary = await page.locator("#summary").inner_text()
    # make sure the portal kept what we typed before we pay/submit anything
    for value in (req.company_name, req.state, req.agent_zip):
        if value not in summary:
            raise PortalError(f"review page is missing {value!r}")
    await page.click("#submit")
    confirmation = page.locator("#confirmation")
    await expect(confirmation).to_be_visible(timeout=30_000)
    return (await confirmation.inner_text()).strip()


async def run_filing(page: Page, base_url, creds, req, status):
    with status.step("login"):
        await login(page, base_url, creds["username"], creds["password"])
    with status.step("company"):
        await fill_company(page, req)
    with status.step("agent"):
        await fill_agent(page, req)
    with status.step("submit"):
        return await review_and_submit(page, req)
