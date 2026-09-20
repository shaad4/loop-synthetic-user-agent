import asyncio
from dataclasses import replace

import pytest
from pydantic import ValidationError

import app.services.agent_run_service as agent_run_service
import app.agents.synthetic_user as synthetic_user
from app.agents.synthetic_user import AgentAction, AgentContext, AgentDecision, GuidancePlan, OpenAISyntheticUser
from app.services.agent_run_service import (
    _action_signature,
    _belongs_to_target,
    _format_guidance_request,
    _looks_like_feedback_summary,
    _is_agent_interaction_error,
    _normalized_origin,
    _page_fingerprint,
    _needs_deep_reasoning,
    _execute_browser_action_with_recovery,
)
from app.services.browser_service import PageObservation


def test_agent_decision_requires_selector_for_click() -> None:
    with pytest.raises(ValidationError, match="requires a selector"):
        AgentDecision(action=AgentAction.CLICK, reason="I need to continue.")


def test_agent_decision_requires_a_handoff_message_for_human_only_steps() -> None:
    with pytest.raises(ValidationError, match="requires a concise input_request"):
        AgentDecision(action=AgentAction.REQUEST_USER_INPUT, reason="Sign-in is required.")

    decision = AgentDecision(
        action=AgentAction.REQUEST_USER_INPUT,
        reason="The page requires verification.",
        input_request="Complete sign-in in the open browser window.",
    )

    assert decision.action is AgentAction.REQUEST_USER_INPUT


def test_agent_can_record_a_distinct_ux_or_functional_finding() -> None:
    ux_finding = AgentDecision(
        action=AgentAction.REPORT_ISSUE,
        reason="The next step is unclear.",
        issue_category="ux",
        issue_summary="The primary action has no explanatory label.",
    )

    assert ux_finding.issue_category == "ux"

    with pytest.raises(ValidationError, match="report_issue requires"):
        AgentDecision(
            action=AgentAction.REPORT_ISSUE,
            reason="There is a problem.",
            issue_category="unknown",
            issue_summary="Something is unclear.",
        )


def test_target_origin_lock_allows_canonical_host_but_blocks_other_products() -> None:
    origin = _normalized_origin("https://www.example.com/pricing")

    assert _belongs_to_target("https://example.com/dashboard", origin)
    assert not _belongs_to_target("https://another-product.example/dashboard", origin)


def test_repeated_agent_action_has_a_stable_loop_signature() -> None:
    decision = AgentDecision(
        action=AgentAction.CLICK,
        reason="Open the checkout page.",
        selector="Checkout",
    )

    assert _action_signature(decision) == _action_signature(decision)


def test_page_fingerprint_changes_only_when_the_visible_screen_changes() -> None:
    original = PageObservation("https://example.com", "Home", "Welcome   to  Loop")
    whitespace_only_change = PageObservation("https://example.com", "Home", "Welcome to Loop")
    next_screen = PageObservation("https://example.com/contact", "Contact", "Send a message")

    assert _page_fingerprint(original) == _page_fingerprint(whitespace_only_change)
    assert _page_fingerprint(original) != _page_fingerprint(next_screen)


def test_legacy_ux_feedback_in_a_completion_summary_is_detected() -> None:
    assert _looks_like_feedback_summary("1) The primary action has no clear label. 2) Feedback is missing.")
    assert _looks_like_feedback_summary("A" * 241)
    assert not _looks_like_feedback_summary("Primary route reviewed without issues.")


def test_guidance_pause_explains_the_specific_agent_blocker() -> None:
    request = _format_guidance_request(
        "What should I do instead to keep working toward the journey goal?",
        PageObservation(
            url="https://example.com/cart",
            title="Shopping cart",
            visible_text="Checkout",
        ),
        AgentDecision(
            action=AgentAction.CLICK,
            reason="the goal requires moving from the cart to checkout.",
            selector="Checkout",
        ),
        repeated_action=True,
    )

    assert "QUESTION" in request
    assert "CONTEXT" in request
    assert "Shopping cart" in request
    assert "Checkout" in request
    assert "tried" in request


def test_agent_prompt_contains_the_minimum_browser_context() -> None:
    context = AgentContext(
        goal="Complete checkout.",
        persona="first_time_user",
        current_url="http://localhost:3001/cart",
        target_origin="localhost:3001",
        page_title="Cart",
        visible_text="Complete Purchase",
        accessibility_snapshot="button Complete Purchase",
        recent_actions=["click: Added laptop to cart"],
        interactive_controls="- button: Complete Purchase\n- link: Continue shopping",
    )

    prompt = OpenAISyntheticUser._format_context(context)

    assert "Complete checkout" in prompt
    assert "Complete Purchase" in prompt
    assert "Added laptop" in prompt
    assert "Target product origin" in prompt
    assert "Interactive controls" in prompt
    assert "- button: Complete Purchase" in prompt
    assert "Severity: high|medium|low" in OpenAISyntheticUser.instructions
    assert 'Common conventions such as a "Read more"' in OpenAISyntheticUser.instructions


def test_agent_uses_the_fast_profile_for_routine_actions_and_escalates_for_ambiguity(monkeypatch) -> None:
    configured_settings = replace(
        synthetic_user.settings,
        agent_model="strong-model",
        agent_reasoning_effort="high",
        agent_fast_model="fast-model",
        agent_fast_reasoning_effort="medium",
    )
    monkeypatch.setattr(synthetic_user, "settings", configured_settings)
    routine = AgentContext("Explore", "ux_reviewer", "https://example.com", "example.com", "Home", "Ready", "", [])
    ambiguous = replace(routine, requires_deep_reasoning=True)

    assert OpenAISyntheticUser._decision_profile(routine, attempt=0) == ("fast-model", "medium")
    assert OpenAISyntheticUser._decision_profile(ambiguous, attempt=0) == ("strong-model", "high")
    assert OpenAISyntheticUser._decision_profile(routine, attempt=1) == ("strong-model", "high")


def test_recent_failures_or_user_guidance_trigger_deeper_reasoning() -> None:
    assert not _needs_deep_reasoning(["click: Open Pricing"])
    assert _needs_deep_reasoning(["failed click: Open Pricing"])
    assert _needs_deep_reasoning(["User guidance for the next decision: Use the header menu."])


def test_agent_only_locator_collisions_are_not_classified_as_product_failures() -> None:
    assert _is_agent_interaction_error(RuntimeError("A link from the subtree intercepts pointer events"))
    assert _is_agent_interaction_error(RuntimeError("Unexpected token while parsing css selector"))
    assert _is_agent_interaction_error(RuntimeError("Locator.click: element is not visible"))
    assert _is_agent_interaction_error(RuntimeError("Could not find one clickable control matching 'Products'"))
    assert not _is_agent_interaction_error(RuntimeError("The checkout API returned 500"))


def test_agent_retries_one_incomplete_structured_response() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, **_: object):
            self.calls += 1
            if self.calls == 1:
                raise ValidationError.from_exception_data(
                    "AgentDecision", [{"type": "json_invalid", "loc": (), "input": "{", "ctx": {"error": "EOF"}}]
                )
            return type("Response", (), {"output_parsed": AgentDecision(action="finish", reason="The error blocks checkout.", success=False)})()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    agent = OpenAISyntheticUser(client=FakeClient())
    decision = asyncio.run(
        agent.choose_next_action(
            AgentContext("Checkout", "first_time_user", "http://localhost", "localhost", "Checkout", "Unavailable", "", [])
        )
    )

    assert decision.action is AgentAction.FINISH
    assert agent._client.responses.calls == 2


def test_agent_retries_an_empty_parsed_response() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, **_: object):
            self.calls += 1
            if self.calls == 1:
                return type("Response", (), {"output_parsed": None, "status": "incomplete", "incomplete_details": None})()
            return type("Response", (), {"output_parsed": AgentDecision(action="finish", reason="The goal is complete.", success=True)})()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    agent = OpenAISyntheticUser(client=FakeClient())
    decision = asyncio.run(
        agent.choose_next_action(
            AgentContext("Checkout", "first_time_user", "http://localhost", "localhost", "Checkout", "Done", "", [])
        )
    )

    assert decision.success is True
    assert agent._client.responses.calls == 2


def test_agent_plans_new_user_guidance_before_choosing_an_action() -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def parse(self, **kwargs: object):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return type(
                    "Response",
                    (),
                    {
                        "output_parsed": GuidancePlan(
                            intended_outcome="Open the product page for the requested phone.",
                            safe_next_step="Use the visible product result that matches the phone.",
                            constraints=["Stay on the current store."],
                        )
                    },
                )()
            return type(
                "Response",
                (),
                {"output_parsed": AgentDecision(action="click", reason="Open the matching product.", selector="iPhone 18 Pro")},
            )()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    agent = OpenAISyntheticUser(client=FakeClient())
    context = AgentContext(
        "Find the requested phone.",
        "first_time_user",
        "https://store.example/search",
        "store.example",
        "Search",
        "iPhone 18 Pro",
        "link iPhone 18 Pro",
        ["User guidance for the next decision: Open the matching iPhone product."],
    )

    decision = asyncio.run(agent.choose_next_action(context))

    assert decision.selector == "iPhone 18 Pro"
    assert len(agent._client.responses.calls) == 2
    assert "Turn one user's direction" in str(agent._client.responses.calls[0]["instructions"])
    assert "User execution brief" in str(agent._client.responses.calls[1]["input"])
    assert "Open the product page" in str(agent._client.responses.calls[1]["input"])


def test_a_slow_agent_decision_has_a_bounded_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowAgent:
        async def choose_next_action(self, _: AgentContext) -> AgentDecision:
            await asyncio.Event().wait()
            raise AssertionError("The decision task should be cancelled before this point.")

    monkeypatch.setattr(
        agent_run_service,
        "settings",
        replace(agent_run_service.settings, agent_decision_timeout_seconds=0),
    )
    context = AgentContext("Explore", "first_time_user", "http://localhost", "localhost", "Home", "Ready", "", [])

    with pytest.raises(agent_run_service.AgentDecisionTimeout):
        asyncio.run(agent_run_service._choose_next_action("missing-run", SlowAgent(), context, 1))


def test_scroll_is_retried_once_before_the_agent_requests_user_help() -> None:
    class BrowserWithTransientScrollFailure:
        def __init__(self) -> None:
            self.scroll_attempts = 0
            self.settle_calls = 0

        async def scroll(self, _: int) -> PageObservation:
            self.scroll_attempts += 1
            if self.scroll_attempts == 1:
                raise RuntimeError("Transient evaluation failure")
            return PageObservation("https://example.com", "Page", "Scrolled")

        async def wait_for_settled_state(self) -> None:
            self.settle_calls += 1

    browser = BrowserWithTransientScrollFailure()
    observation = asyncio.run(
        _execute_browser_action_with_recovery(
            browser, AgentDecision(action=AgentAction.SCROLL, reason="Reveal lower page content.", scroll_pixels=600)
        )
    )

    assert observation.visible_text == "Scrolled"
    assert browser.scroll_attempts == 2
    assert browser.settle_calls == 1
