"""A small, auditable Playwright interface for the Synthetic User agent.

The agent should call these methods instead of writing browser automation itself.
This keeps browser behavior predictable and makes every action easy to record.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


@dataclass(frozen=True)
class PageObservation:
    """The useful state of a page after a browser action."""

    url: str
    title: str
    visible_text: str


class BrowserService:
    """Own one local Chromium session for a single Loop run."""

    def __init__(self, screenshot_directory: Path, headless: bool = True) -> None:
        self._screenshot_directory = screenshot_directory
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.network_failures: list[str] = []
        self._pending_request_ids: set[int] = set()

    async def start(self) -> None:
        """Launch Chromium and prepare a fresh browser page."""
        self._screenshot_directory.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(viewport={"width": 1440, "height": 960})
        self._page = await self._context.new_page()
        self._page.on("request", self._track_request_started)
        self._page.on("requestfinished", self._track_request_finished)
        self._page.on("requestfailed", self._track_request_finished)
        self._page.on("response", self._capture_failed_response)

    async def stop(self) -> None:
        """Close all browser resources, even after a failed journey."""
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._pending_request_ids.clear()

    async def open_url(self, url: str) -> PageObservation:
        """Navigate to a URL without rejecting a usable, slow public page.

        Some production sites finish rendering a usable document but never emit a
        timely ``domcontentloaded`` event because of redirects, analytics, or
        long-running scripts. In that case, the visible body is stronger evidence
        than the lifecycle event, so the Synthetic User can inspect the page.
        """
        page = self._require_page()
        try:
            await self._goto_with_recovery(page, url)
        except PlaywrightTimeoutError as navigation_error:
            try:
                body = page.locator("body")
                await body.wait_for(state="attached", timeout=5_000)
                visible_text = await body.inner_text(timeout=5_000)
            except PlaywrightTimeoutError:
                raise navigation_error

            if not visible_text.strip():
                raise navigation_error
        except PlaywrightError as navigation_error:
            fallback_url = self._www_fallback_url(url, navigation_error)
            if fallback_url is None:
                raise
            await self._goto_with_recovery(page, fallback_url)
        return await self.observe()

    async def click(self, selector: str) -> PageObservation:
        """Click an accessible control while recovering from responsive-nav overlaps."""
        target = await self._clickable_target(selector)
        try:
            await target.click(timeout=5_000)
        except PlaywrightTimeoutError as error:
            if not self._is_pointer_interception(error):
                raise
            alternative = await self._destination_link_target(selector)
            if alternative is None:
                raise
            await alternative.click(timeout=5_000)
        await self.wait_for_settled_state()
        return await self.observe()

    async def type_text(self, selector: str, text: str) -> PageObservation:
        """Fill a labelled form field first, then fall back to a CSS selector."""
        await (await self._form_target(selector)).fill(text)
        await self.wait_for_settled_state()
        return await self.observe()

    async def select_option(self, selector: str, value: str) -> PageObservation:
        """Select a value using an accessible field name or CSS selector."""
        await (await self._form_target(selector)).select_option(value)
        await self.wait_for_settled_state()
        return await self.observe()

    async def scroll(self, pixels: int = 600) -> PageObservation:
        """Scroll by a bounded amount to reveal more page content."""
        page = self._require_page()
        bounded_pixels = max(-1_500, min(pixels, 1_500))
        await page.evaluate("pixels => window.scrollBy(0, pixels)", bounded_pixels)
        await page.wait_for_timeout(100)
        return await self.observe()

    async def go_back(self) -> PageObservation:
        """Return to the previous page in the same browser session."""
        page = self._require_page()
        await page.go_back(wait_until="domcontentloaded")
        await self.wait_for_settled_state()
        return await self.observe()

    async def wait_for_settled_state(self) -> None:
        """Wait for immediate UI work and any request started by an interaction.

        A click can synchronously change a React page or start an asynchronous
        request. Reading the page immediately after the click creates a stale
        observation, which can make an agent repeat an action that is no longer
        available. Explicit request tracking is more reliable than Playwright's
        network-idle state for fetches started by a React event handler.
        """
        page = self._require_page()
        await page.wait_for_timeout(350)
        deadline = monotonic() + 5
        while self._pending_request_ids and monotonic() < deadline:
            await page.wait_for_timeout(100)
        # Let React paint the response state after the last request finishes.
        await page.wait_for_timeout(100)

    async def observe(self) -> PageObservation:
        """Return text that is useful for the agent's next decision."""
        page = self._require_page()
        visible_text = await page.locator("body").inner_text()
        return PageObservation(url=page.url, title=await page.title(), visible_text=visible_text[:12_000])

    async def get_accessibility_snapshot(self) -> str:
        """Return an accessible DOM representation without private browser state."""
        page = self._require_page()
        try:
            return await page.locator("body").aria_snapshot(timeout=8_000)
        except PlaywrightTimeoutError:
            # Accessibility context improves decisions, but visible page text is enough
            # to continue safely when a dynamic page delays this optional snapshot.
            return ""

    async def get_interactive_controls(self) -> str:
        """Return a compact, visible control map for accurate low-token decisions.

        Labels are intentionally human-readable rather than CSS selectors. The
        decision model can choose one exact label, while the browser service keeps
        responsibility for resolving it safely and unambiguously.
        """
        page = self._require_page()
        controls = page.locator(
            "button, a[href], [role='button'], input:not([type='hidden']), textarea, select"
        )
        metadata = await controls.evaluate_all(
            """elements => elements.filter(element => element.getClientRects().length).slice(0, 40).map(element => {
                const labels = element.labels
                    ? Array.from(element.labels).map(label => label.textContent?.trim() || "").join(" ")
                    : "";
                const label = [
                    labels,
                    element.getAttribute("aria-label"),
                    element.getAttribute("title"),
                    element.getAttribute("placeholder"),
                    element.getAttribute("value"),
                    element.innerText || element.textContent,
                ].find(Boolean) || "";
                const tag = element.tagName.toLowerCase();
                const type = element.getAttribute("type");
                const kind = element.getAttribute("role") || (tag === "a" ? "link" : tag === "button" ? "button" : type || tag);
                return { kind, label: label.replace(/\\s+/g, " ").trim(), disabled: Boolean(element.disabled) };
            })"""
        )
        unique_controls: list[str] = []
        for item in metadata:
            label = str(item["label"]).strip()
            if not label:
                continue
            suffix = " (disabled)" if item["disabled"] else ""
            description = f"- {item['kind']}: {label[:160]}{suffix}"
            if description not in unique_controls:
                unique_controls.append(description)
        return "\n".join(unique_controls)[:4_000]

    async def take_screenshot(self, name: str) -> Path:
        """Save visual evidence, falling back to a viewport capture if needed."""
        page = self._require_page()
        safe_name = self._safe_file_stem(name)
        output_path = self._screenshot_directory / f"{safe_name}.png"

        try:
            await page.screenshot(
                path=str(output_path),
                full_page=True,
                animations="disabled",
                caret="hide",
                timeout=15_000,
            )
        except PlaywrightError:
            # Full-page capture is occasionally unavailable on dynamically sized pages.
            # A viewport screenshot is still strong evidence and avoids losing the run.
            await page.wait_for_timeout(250)
            await page.screenshot(
                path=str(output_path),
                full_page=False,
                animations="disabled",
                caret="hide",
                timeout=10_000,
            )
        return output_path

    async def take_feedback_screenshot(self, name: str, finding: str) -> Path:
        """Capture the specific visible control named by a UX finding.

        Full-page screenshots are useful for replaying a journey, but make a poor
        attachment for a single piece of feedback. When the finding identifies one
        unique visible label, capture that element only. Otherwise preserve the
        current viewport, which provides useful context without a long-page image.
        """
        page = self._require_page()
        safe_name = self._safe_file_stem(name)
        output_path = self._screenshot_directory / f"{safe_name}.png"
        focus = await self._feedback_focus_locator(finding)

        if focus is not None:
            try:
                await focus.scroll_into_view_if_needed(timeout=5_000)
                await focus.screenshot(
                    path=str(output_path),
                    animations="disabled",
                    caret="hide",
                    timeout=10_000,
                )
                return output_path
            except PlaywrightError:
                # A DOM update can detach the inspected element. The viewport is
                # still evidence of the state the agent was reviewing.
                pass

        await page.screenshot(
            path=str(output_path),
            full_page=False,
            animations="disabled",
            caret="hide",
            timeout=10_000,
        )
        return output_path

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserService.start() must be called before browser actions.")
        return self._page

    async def _feedback_focus_locator(self, finding: str) -> Locator | None:
        """Find one unambiguous label mentioned in the feedback text."""
        page = self._require_page()
        candidates = self._feedback_focus_terms(finding)
        for candidate in candidates:
            for locator in (
                page.get_by_role("button", name=candidate, exact=False),
                page.get_by_role("link", name=candidate, exact=False),
                page.get_by_text(candidate, exact=False),
            ):
                try:
                    if await locator.count() == 1 and await locator.is_visible():
                        return locator
                except PlaywrightError:
                    continue
        return None

    @staticmethod
    def _feedback_focus_terms(finding: str) -> list[str]:
        """Extract quoted visible labels without guessing from arbitrary prose."""
        quoted = re.findall(r"[“\"']([^”\"']{3,80})[”\"']", finding)
        backticked = re.findall(r"`([^`]{3,80})`", finding)
        terms: list[str] = []
        for term in [*quoted, *backticked]:
            normalized = " ".join(term.split())
            if normalized and normalized not in terms:
                terms.append(normalized)
        return terms

    def _capture_failed_response(self, response: object) -> None:
        status = getattr(response, "status", 0)
        # A login redirect can legitimately produce a 401/403 before presenting
        # an interactive sign-in page. Let the agent inspect that page and ask for
        # a human handoff rather than treating authentication as a product defect.
        if isinstance(status, int) and status >= 400 and status not in {401, 403}:
            url = str(getattr(response, "url", "Unknown URL"))
            self.network_failures.append(f"{status} {url}")


    def _track_request_started(self, request: object) -> None:
        """Track only requests that can change what a user sees next."""
        if getattr(request, "resource_type", None) in {"document", "fetch", "xhr"}:
            self._pending_request_ids.add(id(request))

    def _track_request_finished(self, request: object) -> None:
        """Remove a tracked request once its response or failure is complete."""
        self._pending_request_ids.discard(id(request))

    @staticmethod
    def _safe_file_stem(name: str) -> str:
        """Prevent screenshot names from escaping the evidence directory."""
        stem = Path(name).stem
        safe_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        sanitized = "".join(character if character in safe_characters else "-" for character in stem)
        return sanitized.strip("-") or "screenshot"

    @staticmethod
    def _www_fallback_url(url: str, error: Exception) -> str | None:
        """Retry a bare public domain through its common ``www`` hostname.

        Some DNS or network paths can reach ``www.example.com`` while the bare
        hostname is temporarily unreachable, even when the site normally redirects
        between them. This is limited to connection-level failures and never changes
        an already-``www`` URL, a local address, or the path/query the user supplied.
        """
        if not any(code in str(error) for code in ("ERR_ADDRESS_UNREACHABLE", "ERR_NAME_NOT_RESOLVED")):
            return None

        parts = urlsplit(url)
        hostname = parts.hostname
        if not hostname or hostname.startswith("www.") or hostname in {"localhost", "127.0.0.1", "::1"}:
            return None

        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, f"www.{hostname}{port}", parts.path, parts.query, parts.fragment))

    @staticmethod
    def _is_chrome_error_interruption(error: Exception) -> bool:
        """Recognize Chromium's transient internal error-page navigation race."""
        return "chrome-error://chromewebdata" in str(error)

    async def _goto_with_recovery(self, page: Page, url: str) -> None:
        """Navigate once, then retry after Chromium finishes an internal error page.

        A failed host can cause Chromium to navigate to ``chrome-error://`` slightly
        after Playwright raises. A canonical-host retry issued in that tiny window is
        interrupted by the internal navigation. Waiting briefly and retrying is safe:
        the destination is still the exact URL Loop already approved.
        """
        for attempt in range(2):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                return
            except PlaywrightError as error:
                if attempt == 0 and self._is_chrome_error_interruption(error):
                    await page.wait_for_timeout(350)
                    continue
                raise

    async def _clickable_target(self, target: str) -> Locator:
        """Resolve a visible control without treating human text as CSS."""
        page = self._require_page()
        # Links take priority for a plain navigation label such as "Store".
        # Many responsive navigation bars keep a menu button and destination
        # link in the same visual region; the link is the user-facing action.
        exact_match = await self._unique_locator((
            page.get_by_role("link", name=target, exact=True),
            page.get_by_role("button", name=target, exact=True),
            page.get_by_text(target, exact=True),
        ))
        if exact_match is not None:
            return exact_match

        # Product cards often expose a longer accessible name than the visible
        # purchase control. Try an unambiguous accessible-name match before using
        # token matching below.
        partial_match = await self._unique_locator((
            page.get_by_role("link", name=target, exact=False),
            page.get_by_role("button", name=target, exact=False),
        ))
        if partial_match is not None:
            return partial_match

        fuzzy_match = await self._find_fuzzy_clickable_target(target)
        if fuzzy_match is not None:
            return fuzzy_match

        if self._looks_like_css_selector(target):
            css_candidate = page.locator(target)
            if await css_candidate.count() == 1:
                return css_candidate

        available = ", ".join(await self._describe_clickable_controls()) or "none visible"
        raise RuntimeError(
            f"Could not find one clickable control matching '{target}'. "
            f"Available clickable controls: {available}."
        )

    async def _destination_link_target(self, target: str) -> Locator | None:
        """Use a visible matching link when an overlapping menu button blocks a click."""
        page = self._require_page()
        return await self._unique_locator((
            page.get_by_role("link", name=target, exact=True),
            page.get_by_role("link", name=target, exact=False),
        ))

    @staticmethod
    def _is_pointer_interception(error: Exception) -> bool:
        """Recognize an automation-only overlap, not a user-visible product failure."""
        return "intercepts pointer events" in str(error).lower()

    async def _find_fuzzy_clickable_target(self, target: str) -> Locator | None:
        """Match a product-card description to one unambiguous real control."""
        page = self._require_page()
        controls = page.locator(
            "button, a[href], [role='button'], input[type='button'], input[type='submit']"
        )
        metadata = await controls.evaluate_all(
            """elements => elements.map((element, index) => ({
                index,
                description: [
                    element.getAttribute('aria-label'),
                    element.getAttribute('title'),
                    element.getAttribute('value'),
                    element.innerText || element.textContent,
                ].filter(Boolean).join(' '),
                visible: Boolean(element.getClientRects().length),
            }))"""
        )
        match_index = self._best_clickable_match(
            target,
            [item for item in metadata if item["visible"] and item["description"]],
        )
        return controls.nth(match_index) if match_index is not None else None

    async def _describe_clickable_controls(self) -> list[str]:
        """Return concise visible control labels for a useful recovery message."""
        page = self._require_page()
        controls = page.locator(
            "button, a[href], [role='button'], input[type='button'], input[type='submit']"
        )
        descriptions = await controls.evaluate_all(
            """elements => elements.filter(element => element.getClientRects().length).slice(0, 12)
                .map(element => element.getAttribute('aria-label') || element.getAttribute('title')
                  || element.getAttribute('value') || element.innerText || element.textContent || '')"""
        )
        return [" ".join(description.split())[:100] for description in descriptions if description.strip()]

    async def _form_target(self, target: str) -> Locator:
        """Resolve a form field by its accessible name, aliases, or safe CSS.

        Public sites often label the same field differently (for example,
        "Email", "Your email", or an aria-label rather than "Email address").
        We only choose a fuzzy match when it identifies one control, preventing
        a Synthetic User from filling the wrong field on an unfamiliar site.
        """
        page = self._require_page()
        for _ in range(16):
            candidate = await self._find_form_target(target)
            if candidate is not None:
                return candidate
            await page.wait_for_timeout(150)

        available_fields = await self._describe_form_controls()
        available = ", ".join(available_fields) or "none visible"
        raise RuntimeError(
            f"Could not find a unique form field for '{target}'. Available form fields: {available}."
        )

    async def _find_form_target(self, target: str) -> Locator | None:
        """Return one safe matching control, without guessing between duplicates."""
        page = self._require_page()
        exact_candidates = (
            page.get_by_label(target, exact=True),
            page.get_by_placeholder(target, exact=True),
            page.get_by_role("textbox", name=target, exact=True),
            page.get_by_role("combobox", name=target, exact=True),
        )
        exact_match = await self._unique_locator(exact_candidates)
        if exact_match is not None:
            return exact_match

        controls = page.locator("input:not([type='hidden']), textarea, select")
        controls_metadata = await controls.evaluate_all(
            """elements => elements.map((element, index) => {
                const labels = element.labels
                  ? Array.from(element.labels).map(label => label.textContent?.trim() || "").join(" ")
                  : "";
                return {
                  index,
                  description: [
                    labels,
                    element.getAttribute("aria-label"),
                    element.getAttribute("placeholder"),
                    element.getAttribute("name"),
                    element.getAttribute("id"),
                    element.getAttribute("type"),
                  ].filter(Boolean).join(" "),
                };
            })"""
        )
        aliases = self._field_aliases(target)
        matching_indices = [
            field["index"]
            for field in controls_metadata
            if any(alias in self._normalized_text(field["description"]) for alias in aliases)
        ]
        if len(matching_indices) == 1:
            return controls.nth(matching_indices[0])

        if self._looks_like_css_selector(target):
            css_candidate = page.locator(target)
            if await css_candidate.count() == 1:
                return css_candidate
        return None

    async def _describe_form_controls(self) -> list[str]:
        """Summarise visible user-input controls for a diagnostic evidence item."""
        page = self._require_page()
        controls = page.locator("input:not([type='hidden']), textarea, select")
        descriptions = await controls.evaluate_all(
            """elements => elements.slice(0, 12).map(element => {
                const labels = element.labels
                  ? Array.from(element.labels).map(label => label.textContent?.trim() || "").join(" ")
                  : "";
                return labels || element.getAttribute("aria-label") || element.getAttribute("placeholder")
                  || element.getAttribute("name") || element.getAttribute("id") || element.tagName.toLowerCase();
            })"""
        )
        return [description for description in descriptions if description]

    async def _unique_locator(self, candidates: tuple[Locator, ...]) -> Locator | None:
        """Return one visible candidate, never a hidden responsive duplicate."""
        for candidate in candidates:
            if await candidate.count() == 1 and await candidate.is_visible():
                return candidate
        return None

    @staticmethod
    def _field_aliases(target: str) -> tuple[str, ...]:
        """Common public-form vocabulary, ordered from most to least specific."""
        normalized = BrowserService._normalized_text(target)
        aliases = [normalized]
        known_aliases = {
            "email address": ("email", "e mail"),
            "e mail address": ("email", "e mail"),
            "phone number": ("phone", "mobile", "telephone"),
            "full name": ("name",),
            "first name": ("given name",),
            "last name": ("surname", "family name"),
            "company name": ("company", "organisation", "organization"),
        }
        aliases.extend(known_aliases.get(normalized, ()))
        return tuple(dict.fromkeys(alias for alias in aliases if alias))

    @staticmethod
    def _normalized_text(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    @staticmethod
    def _best_clickable_match(target: str, candidates: list[dict[str, object]]) -> int | None:
        """Choose a strong, unique token match; never guess between similar controls."""
        target_words = set(BrowserService._normalized_text(target).split())
        if not target_words:
            return None
        action_words = {"add", "buy", "cart", "checkout", "continue", "next", "order", "select", "start"}
        scored: list[tuple[float, int]] = []
        for candidate in candidates:
            description = str(candidate["description"])
            words = set(BrowserService._normalized_text(description).split())
            overlap = target_words & words
            if len(words) < 2 or len(overlap) < 2:
                continue
            coverage = len(overlap) / len(words)
            if coverage < 0.65:
                continue
            action_bonus = len(action_words & overlap) * 10
            score = coverage * 100 + len(overlap) + action_bonus
            scored.append((score, int(candidate["index"])))

        if not scored:
            return None
        scored.sort(reverse=True)
        best_score, best_index = scored[0]
        if len(scored) > 1 and best_score - scored[1][0] < 5:
            return None
        return best_index

    @staticmethod
    def _looks_like_css_selector(target: str) -> bool:
        return target.startswith(("#", ".", "[", ":")) or bool(
            re.match(r"^(input|textarea|select|button|form)\b", target)
        )
