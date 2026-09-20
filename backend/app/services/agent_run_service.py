"""Run a bounded Synthetic User loop against one Playwright browser session."""

import asyncio
from contextlib import suppress
from hashlib import sha256
import re

from app.agents.synthetic_user import (
    AgentAction,
    AgentContext,
    AgentDecision,
    DecisionProvider,
    OpenAISyntheticUser,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.services import evidence_service, run_service
from app.services.browser_service import BrowserService, PageObservation
from app.services.user_intervention_service import InterventionResult, user_intervention_service
from app.models.evidence import EvidenceType
from time import time
from urllib.parse import urlsplit


async def execute_agent_run(run_id: str) -> None:
    """Run up to the configured number of goal-driven browser decisions."""
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is None:
            return
        journey = run.journey
        goal, persona, target_url = journey.goal, journey.persona, journey.application.target_url

    try:
        agent = OpenAISyntheticUser()
        await _run_loop(run_id, goal, persona, target_url, agent)
    except Exception as error:
        with SessionLocal() as session:
            run = run_service.get_run(session, run_id)
            if run is not None and run.status.value != "stopped":
                run_service.mark_failed(session, run, f"Agent run failed: {error}")


async def _run_loop(
    run_id: str,
    goal: str,
    persona: str,
    target_url: str,
    agent: DecisionProvider,
) -> None:
    browser = BrowserService(
        settings.storage_directory / "screenshots" / run_id,
        headless=settings.playwright_headless,
    )
    recent_actions: list[str] = []
    attempted_state_actions: set[tuple[str, str]] = set()
    reported_issues: set[str] = set()
    target_origin = _normalized_origin(target_url)
    network_failure_cursor = 0

    try:
        await browser.start()
        if _stop_requested(run_id):
            return
        observation = await browser.open_url(target_url)
        if not _belongs_to_target(observation.url, target_origin):
            _finish_run(run_id, False, "Target redirected outside the configured product origin before the audit could begin.")
            return
        await _record_observation(run_id, browser, "open_url", target_url, "Opened target application")
        network_failure_cursor = _record_new_diagnostics(run_id, browser, network_failure_cursor)
        if network_failure_cursor:
            recent_actions.append(
                "Browser diagnostics were recorded. Continue with a different visible action and keep the evidence for the report."
            )

        for step in range(1, settings.agent_max_steps + 1):
            if _stop_requested(run_id):
                return
            _record_agent_thinking(run_id, step)
            context = AgentContext(
                goal=goal,
                persona=persona,
                current_url=observation.url,
                target_origin=target_origin,
                page_title=observation.title,
                visible_text=observation.visible_text,
                accessibility_snapshot=await browser.get_accessibility_snapshot(),
                recent_actions=recent_actions,
                interactive_controls=await browser.get_interactive_controls(),
                # UX findings need careful interpretation, so use the stronger
                # profile for the entire review. Functional navigation remains
                # fast unless the browser signals ambiguity or failure.
                requires_deep_reasoning=persona == "ux_reviewer" or _needs_deep_reasoning(recent_actions),
            )
            try:
                decision = await _choose_next_action(run_id, agent, context, step)
            except AgentRunStopped:
                return
            except AgentDecisionTimeout:
                if persona == "ux_reviewer":
                    _finish_ux_review(run_id, reported_issues, "Loop could not safely choose another review step.")
                    return
                result = await _pause_for_decision_timeout(run_id, browser, observation)
                if not _apply_intervention_result(run_id, recent_actions, result):
                    return
                recent_actions.append("The previous AI decision timed out; use the user's guidance if provided.")
                continue
            if _stop_requested(run_id):
                return
            if decision.action == AgentAction.REQUEST_GUIDANCE:
                if persona == "ux_reviewer":
                    _finish_ux_review(run_id, reported_issues, "Loop reached the end of the clear first-time-user path.")
                    return
                result = await _pause_for_guidance(
                    run_id,
                    browser,
                    decision.input_request or "What outcome should I work toward from this page?",
                    observation=observation,
                    decision=decision,
                )
                if not _apply_intervention_result(run_id, recent_actions, result):
                    return
                observation = await browser.observe()
                continue
            if decision.action == AgentAction.REPORT_ISSUE:
                issue_key = f"{decision.issue_category}:{decision.issue_summary}"
                if issue_key not in reported_issues:
                    reported_issues.add(issue_key)
                    await _record_reported_issue(run_id, decision)
                    if decision.issue_category == "ux" and decision.issue_summary:
                        await _capture_feedback_screenshot(run_id, browser, decision.issue_summary)
                    recent_actions.append(f"Reported {decision.issue_category} issue: {decision.issue_summary}")
                    if len(reported_issues) >= settings.agent_max_reported_issues:
                        _finish_audit_with_issues(
                            run_id,
                            "Loop completed the focused review after collecting three distinct findings.",
                        )
                        return
                else:
                    recent_actions.append("That issue was already recorded; choose a different safe action.")
                continue
            if decision.action == AgentAction.REQUEST_USER_INPUT:
                if persona == "ux_reviewer":
                    _finish_ux_review(run_id, reported_issues, "The remaining path requires a protected user-only step.")
                    return
                result = await _pause_for_user_input(run_id, browser, decision)
                if not _apply_intervention_result(run_id, recent_actions, result):
                    return
                await browser.wait_for_settled_state()
                observation = await browser.observe()
                continue
            if decision.action == AgentAction.FINISH:
                final_findings = decision.findings
                if persona == "ux_reviewer" and not final_findings and _looks_like_feedback_summary(decision.summary):
                    # Backward-compatible handling for older model responses that put
                    # numbered feedback in summary instead of the structured field.
                    final_findings = [decision.summary] if decision.summary else []
                if persona == "ux_reviewer" and final_findings:
                    for finding in final_findings:
                        await _record_ux_finding(run_id, finding)
                        await _capture_feedback_screenshot(run_id, browser, finding)
                    _finish_audit_with_issues(
                        run_id,
                        f"Loop completed the UX review with {len(final_findings)} recorded finding(s).",
                    )
                    return
                _finish_run(run_id, decision.success, decision.summary or decision.reason)
                return

            signature = _action_signature(decision)
            state_action_key = (_page_fingerprint(observation), signature)
            if state_action_key in attempted_state_actions:
                if persona == "ux_reviewer":
                    _finish_ux_review(run_id, reported_issues, "Loop reached a repeated screen without another safe review action.")
                    return
                result = await _pause_for_guidance(
                    run_id,
                    browser,
                    "This action was already tried on this screen. What should I try instead?",
                    observation=observation,
                    decision=decision,
                    repeated_action=True,
                )
                if not _apply_intervention_result(run_id, recent_actions, result):
                    return
                observation = await browser.observe()
                continue
            attempted_state_actions.add(state_action_key)

            _record_agent_action_started(run_id, decision)
            try:
                observation = await _execute_browser_action_with_recovery(browser, decision)
            except Exception as error:
                if _is_agent_interaction_error(error):
                    _record_agent_interaction_recovery(run_id, decision)
                    recent_actions.append(
                        f"failed agent interaction: {decision.action.value} could not safely target "
                        f"{decision.selector or 'the requested control'}; choose a different visible control."
                    )
                    observation = await browser.observe()
                    continue
                await _record_action_failure(run_id, decision, error)
                recent_actions.append(
                    f"failed {decision.action.value}: {decision.reason}. "
                    "The failure is saved in the report; choose another safe visible action."
                )
                observation = await browser.observe()
                continue
            if not _belongs_to_target(observation.url, target_origin):
                safe_observation = await browser.go_back()
                await _record_observation(
                    run_id,
                    browser,
                    "navigation_blocked",
                    observation.url,
                    "Loop blocked navigation outside the configured product origin and returned to the test target.",
                )
                recent_actions.append("Loop blocked navigation outside the configured product origin.")
                observation = safe_observation
                continue
            description = f"{decision.action.value}: {decision.reason}"
            recent_actions.append(description)
            await _record_observation(run_id, browser, decision.action.value, decision.selector, description)
            previous_network_failure_cursor = network_failure_cursor
            network_failure_cursor = _record_new_diagnostics(run_id, browser, network_failure_cursor)
            if network_failure_cursor > previous_network_failure_cursor:
                recent_actions.append(
                    "The latest action produced browser diagnostics. They were saved as evidence; continue with a different safe action."
                )

        if persona == "ux_reviewer":
            _finish_ux_review(
                run_id,
                reported_issues,
                f"Loop reached the focused {settings.agent_max_steps}-step review limit.",
            )
        elif reported_issues:
            _finish_audit_with_issues(
                run_id,
                f"Loop reached the focused {settings.agent_max_steps}-step limit after recording findings.",
            )
        else:
            _finish_run(run_id, False, f"Agent reached the {settings.agent_max_steps}-step limit.")
    finally:
        await browser.stop()
        user_intervention_service.clear(run_id)


class AgentDecisionTimeout(RuntimeError):
    """The model did not return one browser decision within the run deadline."""


class AgentRunStopped(RuntimeError):
    """The user stopped a run while the model was still deciding."""


async def _choose_next_action(
    run_id: str,
    agent: DecisionProvider,
    context: AgentContext,
    step: int,
) -> AgentDecision:
    """Bound a slow model call and keep the live trail honest while it runs."""
    task = asyncio.create_task(agent.choose_next_action(context))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.agent_decision_timeout_seconds
    heartbeat_sent = False

    try:
        while not task.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AgentDecisionTimeout

            await asyncio.wait(
                {task},
                timeout=min(remaining, settings.agent_decision_heartbeat_seconds),
            )
            if task.done():
                break
            if _stop_requested(run_id):
                raise AgentRunStopped
            if not heartbeat_sent:
                _record_agent_waiting(run_id, step)
                heartbeat_sent = True

        return await task
    except (AgentDecisionTimeout, AgentRunStopped):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise


async def _pause_for_decision_timeout(
    run_id: str, browser: BrowserService, observation: PageObservation
) -> InterventionResult | None:
    """Turn a slow external model response into a recoverable user decision."""
    if _stop_requested(run_id):
        return InterventionResult("stop", None)
    user_intervention_service.begin(run_id)
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is None:
            return None
        run_service.mark_awaiting_user(
            session,
            run,
            "QUESTION\nLoop could not choose the next action in time. What should it try?\n\n"
            f"CONTEXT\nOn {observation.title or 'the current page'}. Your guidance will restart the decision.",
            action_type="agent_guidance_required",
        )
    await _capture_screenshot(run_id, browser, "agent_decision_timeout")
    return await user_intervention_service.wait_for_resolution(
        run_id, settings.agent_user_input_timeout_seconds
    )


async def _execute_browser_action(browser: BrowserService, decision: AgentDecision) -> PageObservation:
    action = decision.action
    if action == AgentAction.CLICK:
        return await browser.click(decision.selector)
    if action == AgentAction.TYPE_TEXT:
        return await browser.type_text(decision.selector, decision.text)
    if action == AgentAction.SELECT_OPTION:
        return await browser.select_option(decision.selector, decision.text)
    if action == AgentAction.SCROLL:
        return await browser.scroll(decision.scroll_pixels or 600)
    if action == AgentAction.GO_BACK:
        return await browser.go_back()
    raise ValueError(f"Unsupported agent action: {action}")


async def _execute_browser_action_with_recovery(
    browser: BrowserService, decision: AgentDecision
) -> PageObservation:
    """Retry one idempotent browser operation before asking the user to intervene.

    Clicks and form submissions are deliberately never replayed because retrying
    them could create duplicate orders or submit user data twice. Scrolling only
    changes the viewport, so it is safe to retry after a transient page update.
    """
    try:
        return await _execute_browser_action(browser, decision)
    except Exception:
        if decision.action != AgentAction.SCROLL:
            raise
        await browser.wait_for_settled_state()
        return await _execute_browser_action(browser, decision)


async def _pause_for_user_input(
    run_id: str,
    browser: BrowserService,
    decision: AgentDecision,
) -> InterventionResult | None:
    """Keep the local browser open while a user completes a sensitive step."""
    if _stop_requested(run_id):
        return InterventionResult("stop", None)
    request = decision.input_request or "Complete the required step in the browser window."
    user_intervention_service.begin(run_id)
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is None:
            return None
        run_service.mark_awaiting_user(session, run, request)

    await _capture_screenshot(run_id, browser, "user_input_required")
    return await user_intervention_service.wait_for_resolution(
        run_id, settings.agent_user_input_timeout_seconds
    )


async def _pause_for_guidance(
    run_id: str,
    browser: BrowserService,
    question: str,
    *,
    observation: PageObservation,
    decision: AgentDecision,
    repeated_action: bool = False,
) -> InterventionResult | None:
    """Pause a confused agent without treating uncertainty as a product defect."""
    if _stop_requested(run_id):
        return InterventionResult("stop", None)
    request = _format_guidance_request(question, observation, decision, repeated_action)
    user_intervention_service.begin(run_id)
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is None:
            return None
        run_service.mark_awaiting_user(session, run, request, action_type="agent_guidance_required")
    await _capture_screenshot(run_id, browser, "agent_guidance_required")
    return await user_intervention_service.wait_for_resolution(
        run_id, settings.agent_user_input_timeout_seconds
    )


def _format_guidance_request(
    question: str,
    observation: PageObservation,
    decision: AgentDecision,
    repeated_action: bool,
) -> str:
    """Make an agent pause answerable at a glance, not an internal debug log."""
    attempted_control = decision.selector or "the current page"
    page_name = observation.title or "the current page"
    if repeated_action:
        question = f"“{attempted_control}” did not move the page forward. What should I try next?"
        context = f"On {page_name}. I tried “{attempted_control}” twice with no visible change."
    else:
        context = (
            f"On {page_name}. I was about to {decision.action.value.replace('_', ' ')} "
            f"“{attempted_control}”."
        )

    return "\n\n".join(
        [
            f"QUESTION\n{question}",
            f"CONTEXT\n{context}",
        ]
    )


async def _record_observation(
    run_id: str,
    browser: BrowserService,
    action_type: str,
    target: str | None,
    outcome: str,
) -> None:
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is None:
            return
        run_service.record_system_action(session, run, action_type, target, outcome)


    await _capture_screenshot(run_id, browser, action_type)


async def _capture_screenshot(run_id: str, browser: BrowserService, action_type: str) -> None:
    """Capture evidence without adding a duplicate action to the timeline."""
    try:
        screenshot = await browser.take_screenshot(f"{action_type}-{int(time() * 1_000)}")
        with SessionLocal() as session:
            evidence_service.record_file(session, run_id, EvidenceType.SCREENSHOT, screenshot)
    except Exception as error:
        with SessionLocal() as session:
            evidence_service.record_text(
                session,
                run_id,
                EvidenceType.BROWSER_ERROR,
                f"Screenshot capture failed after {action_type}: {error}",
            )


async def _capture_feedback_screenshot(run_id: str, browser: BrowserService, finding: str) -> None:
    """Capture the exact screen that led to one UX finding."""
    try:
        screenshot = await browser.take_feedback_screenshot(
            f"ux-feedback-{int(time() * 1_000)}",
            finding,
        )
        with SessionLocal() as session:
            evidence_service.record_file(
                session,
                run_id,
                EvidenceType.SCREENSHOT,
                screenshot,
                content=f"UX feedback: {finding}",
            )
    except Exception as error:
        with SessionLocal() as session:
            evidence_service.record_text(
                session,
                run_id,
                EvidenceType.BROWSER_ERROR,
                f"Screenshot capture failed for UX feedback: {error}",
            )


async def _record_action_failure(run_id: str, decision: AgentDecision, error: Exception) -> None:
    """Save a readable browser diagnostic before asking how the audit should continue."""
    target = decision.selector or "the current page"
    message = f"Could not {decision.action.value} '{target}': {error}"
    with SessionLocal() as session:
        evidence_service.record_text(session, run_id, EvidenceType.BROWSER_ERROR, message)
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(session, run, "action_error", decision.selector, message)


async def _record_reported_issue(run_id: str, decision: AgentDecision) -> None:
    """Persist a distinct product finding without confusing it with an agent error."""
    action_type = "ux_issue" if decision.issue_category == "ux" else "functional_issue"
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(session, run, action_type, decision.selector, decision.issue_summary or "")


async def _record_ux_finding(run_id: str, finding: str) -> None:
    """Persist feedback returned with a completed UX review."""
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(session, run, "ux_issue", None, finding)


def _finish_run(run_id: str, success: bool | None, summary: str) -> None:
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is None:
            return
        if run.status.value == "stopped":
            return
        if success:
            run_service.mark_passed(session, run, summary)
        else:
            run_service.mark_failed(session, run, summary)


def _finish_audit_with_issues(run_id: str, summary: str) -> None:
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.mark_completed_with_issues(session, run, summary)


def _finish_ux_review(run_id: str, reported_issues: set[str], reason: str) -> None:
    """End an exploratory UX audit instead of requesting unnecessary guidance."""
    if reported_issues:
        _finish_audit_with_issues(run_id, f"{reason} {len(reported_issues)} verified finding(s) are in the report.")
        return
    _finish_run(run_id, True, f"{reason} No verified UI or UX issues were found in the reviewed path.")


def _apply_intervention_result(
    run_id: str, recent_actions: list[str], result: InterventionResult | None
) -> bool:
    """Apply a local user's decision without putting their free-text prompt in storage."""
    if result is None:
        _finish_run(run_id, False, "Timed out while waiting for user input.")
        return False
    if result.resolution == "stop":
        return False
    if result.resolution == "finish":
        _finish_audit_with_issues(run_id, "User finished the audit after reviewing the checkpoint.")
        return False
    if result.guidance:
        recent_actions.append(f"User guidance for the next decision: {result.guidance}")
    return True


def _action_signature(decision: AgentDecision) -> str:
    return "|".join(
        value or ""
        for value in (decision.action.value, decision.selector, decision.text, str(decision.scroll_pixels or ""))
    )


def _looks_like_feedback_summary(summary: str | None) -> bool:
    """Recognize legacy final summaries that actually contain a findings list."""
    if not summary:
        return False
    return bool(re.match(r"\s*1\)\s", summary)) or len(summary) > 240


def _page_fingerprint(observation: PageObservation) -> str:
    """Identify the visible screen without storing its full contents in loop guards."""
    visible_text = re.sub(r"\s+", " ", observation.visible_text).strip()[:2_000]
    value = "|".join((observation.url, observation.title, visible_text))
    return sha256(value.encode("utf-8")).hexdigest()


def _normalized_origin(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host


def _belongs_to_target(url: str, target_origin: str) -> bool:
    return _normalized_origin(url) == target_origin


def _stop_requested(run_id: str) -> bool:
    """Check the in-memory signal first, then the persisted state for safety."""
    if user_intervention_service.is_stop_requested(run_id):
        return True
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        return run is None or run.status.value == "stopped"


def _needs_deep_reasoning(recent_actions: list[str]) -> bool:
    """Escalate only after ambiguity, a failed browser action, or user direction."""
    escalation_prefixes = ("failed ", "User guidance for the next decision:", "Reported ")
    return any(action.startswith(escalation_prefixes) for action in recent_actions[-4:])


def _is_agent_interaction_error(error: Exception) -> bool:
    """Keep selector and hit-testing failures out of a product-quality report."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "intercepts pointer events",
            "while parsing css selector",
            "strict mode violation",
            "element is not visible",
            "element is outside of the viewport",
            "could not find one clickable control",
            "could not find a unique form field",
        )
    )


def _record_agent_interaction_recovery(run_id: str, decision: AgentDecision) -> None:
    """Document an agent-only collision without mislabeling the target as broken."""
    target = decision.selector or "the requested control"
    outcome = (
        f"Loop skipped “{target}” because overlapping or ambiguous browser controls prevented a safe click. "
        "This was not added to the product issue report."
    )
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(session, run, "agent_recovery", decision.selector, outcome)


def _record_new_diagnostics(
    run_id: str,
    browser: BrowserService,
    network_failure_cursor: int,
) -> int:
    """Persist user-impacting network failures exactly once.

    JavaScript console output is developer noise and is deliberately excluded
    from product reports. Loop reports only signals that can affect the person
    using the page.
    """
    new_network_failures = browser.network_failures[network_failure_cursor:]

    if new_network_failures:
        with SessionLocal() as session:
            run = run_service.get_run(session, run_id)
            for failure in new_network_failures:
                evidence_service.record_text(session, run_id, EvidenceType.NETWORK_FAILURE, failure)
                if run is not None:
                    run_service.record_system_action(session, run, "network_failure", None, failure)

    return len(browser.network_failures)


def _record_agent_thinking(run_id: str, step: int) -> None:
    """Make model deliberation visible while the next API call is in progress."""
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(
                session,
                run,
                "agent_thinking",
                None,
                f"Synthetic User is deciding the next action (step {step}).",
            )


def _record_agent_waiting(run_id: str, step: int) -> None:
    """Show that a valid but slow API decision is still actively being awaited."""
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(
                session,
                run,
                "agent_waiting",
                None,
                f"Still deciding the next action (step {step}). You can stop the test at any time.",
            )


def _record_agent_action_started(run_id: str, decision: AgentDecision) -> None:
    """Show the exact browser action while Playwright waits for the page."""
    target = decision.selector or "the current page"
    with SessionLocal() as session:
        run = run_service.get_run(session, run_id)
        if run is not None:
            run_service.record_system_action(
                session,
                run,
                "agent_action_started",
                target,
                f"Trying to {decision.action.value.replace('_', ' ')} “{target}”.",
            )
