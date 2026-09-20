from pathlib import Path
import asyncio
import struct

import pytest

from app.services.browser_service import BrowserService


def test_screenshot_name_is_safe() -> None:
    assert BrowserService._safe_file_stem("checkout failure.png") == "checkout-failure"
    assert BrowserService._safe_file_stem("../../private") == "private"


def test_bare_domain_fallback_preserves_the_requested_page() -> None:
    network_error = RuntimeError("Page.goto: net::ERR_ADDRESS_UNREACHABLE")

    assert BrowserService._www_fallback_url("https://shaad.site/contact?from=loop", network_error) == "https://www.shaad.site/contact?from=loop"
    assert BrowserService._www_fallback_url("https://www.shaad.site/", network_error) is None
    assert BrowserService._www_fallback_url("http://localhost:3000/", network_error) is None


def test_chromium_error_page_navigation_race_is_recognized() -> None:
    error = RuntimeError(
        "Navigation to 'https://www.example.com/' is interrupted by another navigation "
        "to 'chrome-error://chromewebdata/'"
    )

    assert BrowserService._is_chrome_error_interruption(error)
    assert not BrowserService._is_chrome_error_interruption(RuntimeError("net::ERR_TIMED_OUT"))


def test_feedback_focus_terms_only_use_explicit_labels() -> None:
    assert BrowserService._feedback_focus_terms(
        'The “Get started” control is unclear, while `Pricing` is easy to miss.'
    ) == ["Get started", "Pricing"]
    assert BrowserService._feedback_focus_terms("The primary action is unclear.") == []


def test_product_card_description_resolves_to_a_unique_purchase_control() -> None:
    match = BrowserService._best_clickable_match(
        "iPhone 18 Pro 6.3-inch display Buy from $1199 or $49.95 per month",
        [
            {"index": 0, "description": "Buy iPhone 18 Pro", "visible": True},
            {"index": 1, "description": "Buy iPhone Air", "visible": True},
        ],
    )

    assert match == 0
    assert BrowserService._best_clickable_match(
        "Buy a new phone",
        [
            {"index": 0, "description": "Buy iPhone", "visible": True},
            {"index": 1, "description": "Buy iPad", "visible": True},
        ],
    ) is None


def test_browser_actions_require_a_started_browser(tmp_path: Path) -> None:
    service = BrowserService(tmp_path)

    try:
        service._require_page()
    except RuntimeError as error:
        assert "BrowserService.start" in str(error)
    else:
        raise AssertionError("An unstarted browser service must reject browser actions.")


@pytest.mark.browser
def test_form_target_accepts_common_public_site_aliases(tmp_path: Path) -> None:
    """A request for Email address should work when a site labels the field Email."""

    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<main id=app></main><script>setTimeout(() => app.innerHTML = '<label>Email<input name=email></label>', 250)</script>"
            )
            await service.type_text("Email address", "tester@example.com")
            value = await service._require_page().locator("input[name=email]").input_value()
        finally:
            await service.stop()

        assert value == "tester@example.com"

    asyncio.run(run_browser_check())


@pytest.mark.browser
def test_interactive_control_map_contains_only_concise_visible_controls(tmp_path: Path) -> None:
    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<button>Start free trial</button><a href=/pricing>Pricing</a><label>Email<input placeholder='you@example.com'></label><button disabled>Continue</button>"
            )
            return await service.get_interactive_controls()
        finally:
            await service.stop()

    controls = asyncio.run(run_browser_check())

    assert "button: Start free trial" in controls
    assert "link: Pricing" in controls
    assert "Email" in controls
    assert "Continue (disabled)" in controls


@pytest.mark.browser
def test_click_observes_async_ui_state(tmp_path: Path) -> None:
    """A next observation must not contain the pre-click button state."""

    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<button onclick=\"setTimeout(() => document.body.innerHTML = '&lt;main&gt;Checkout unavailable&lt;/main&gt;', 100)\">Complete Purchase</button>"
            )
            observation = await service.click("Complete Purchase")
        finally:
            await service.stop()

        assert "Checkout unavailable" in observation.visible_text
        assert "Complete Purchase" not in observation.visible_text

    asyncio.run(run_browser_check())


@pytest.mark.browser
def test_click_prefers_the_visible_destination_link_over_an_overlapping_menu_button(tmp_path: Path) -> None:
    """Responsive navigation duplicates must not become a false product failure."""

    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<style>%23store-link{position:absolute;inset:0;width:120px;height:42px;z-index:2}</style><button aria-label='Store'>Store menu</button><a id=store-link aria-label='Store' href='/' onclick=\"document.title='Store destination';return false\">Store</a>"
            )
            return await service.click("Store")
        finally:
            await service.stop()

    observation = asyncio.run(run_browser_check())

    assert observation.title == "Store destination"


@pytest.mark.browser
def test_click_resolves_a_product_card_description_to_its_purchase_control(tmp_path: Path) -> None:
    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<button onclick=\"document.body.innerText='Purchased'\">Buy iPhone 18 Pro</button><button>Buy iPhone Air</button>"
            )
            observation = await service.click(
                "iPhone 18 Pro 6.3-inch display Buy from $1199 or $49.95 per month"
            )
        finally:
            await service.stop()

        assert observation.visible_text == "Purchased"

    asyncio.run(run_browser_check())


@pytest.mark.browser
def test_browser_can_capture_a_local_page(tmp_path: Path) -> None:
    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            observation = await service.open_url(
                "data:text/html,<title>Loop Browser Check</title><main>Ready</main>"
            )
            screenshot = await service.take_screenshot("browser-check")
        finally:
            await service.stop()

        assert observation.title == "Loop Browser Check"
        assert screenshot.exists()

    asyncio.run(run_browser_check())


@pytest.mark.browser
def test_scroll_uses_the_requested_pixel_distance(tmp_path: Path) -> None:
    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<div style='height:2400px'>Top</div><main>Lower content</main>"
            )
            await service.scroll(700)
            scroll_position = await service._require_page().evaluate("window.scrollY")
        finally:
            await service.stop()

        assert scroll_position >= 650

    asyncio.run(run_browser_check())


@pytest.mark.browser
def test_feedback_screenshot_crops_to_a_unique_control(tmp_path: Path) -> None:
    async def run_browser_check() -> None:
        service = BrowserService(tmp_path)
        await service.start()
        try:
            await service.open_url(
                "data:text/html,<style>a{display:block;width:260px;height:52px;margin:160px}</style><a href=next>Get started</a>"
            )
            screenshot = await service.take_feedback_screenshot(
                "feedback-focus",
                'The “Get started” call to action does not explain what happens next.',
            )
        finally:
            await service.stop()

        width, height = struct.unpack(">II", screenshot.read_bytes()[16:24])
        assert width < 1440
        assert height < 960

    asyncio.run(run_browser_check())
