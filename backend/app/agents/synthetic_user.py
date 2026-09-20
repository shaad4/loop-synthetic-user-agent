"""Structured decision-maker for Loop's first-time Synthetic User."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.core.config import settings


class AgentAction(str, Enum):
    CLICK = "click"
    TYPE_TEXT = "type_text"
    SELECT_OPTION = "select_option"
    SCROLL = "scroll"
    GO_BACK = "go_back"
    REQUEST_USER_INPUT = "request_user_input"
    REQUEST_GUIDANCE = "request_guidance"
    REPORT_ISSUE = "report_issue"
    FINISH = "finish"


class AgentDecision(BaseModel):
    """One safe next step chosen by the language model."""

    action: AgentAction
    reason: str = Field(min_length=3, max_length=500)
    selector: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=1_000)
    scroll_pixels: int | None = Field(default=None, ge=-1_500, le=1_500)
    input_request: str | None = Field(default=None, max_length=500)
    issue_category: str | None = Field(default=None, max_length=30)
    issue_summary: str | None = Field(default=None, max_length=1_000)
    findings: list[str] = Field(default_factory=list, max_length=3)
    success: bool | None = None
    summary: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_action_arguments(self) -> "AgentDecision":
        selector_actions = {AgentAction.CLICK, AgentAction.TYPE_TEXT, AgentAction.SELECT_OPTION}
        if self.action in selector_actions and not self.selector:
            raise ValueError(f"{self.action.value} requires a selector.")
        if self.action in {AgentAction.TYPE_TEXT, AgentAction.SELECT_OPTION} and self.text is None:
            raise ValueError(f"{self.action.value} requires text.")
        if self.action == AgentAction.FINISH and self.success is None:
            raise ValueError("finish requires success.")
        if self.action in {AgentAction.REQUEST_USER_INPUT, AgentAction.REQUEST_GUIDANCE} and not self.input_request:
            raise ValueError(f"{self.action.value} requires a concise input_request.")
        if self.action == AgentAction.REPORT_ISSUE:
            if self.issue_category not in {"ux", "functional"} or not self.issue_summary:
                raise ValueError("report_issue requires an ux or functional category and an issue_summary.")
        if self.action != AgentAction.FINISH and self.findings:
            raise ValueError("findings can only be returned when finishing a review.")
        return self


class GuidancePlan(BaseModel):
    """A concise, operational brief derived from one user's direction.

    This is intentionally not a chain-of-thought record. It gives the action
    model a bounded outcome, a safe immediate approach, and the constraints it
    must honour when it returns the next browser action.
    """

    intended_outcome: str = Field(min_length=3, max_length=400)
    safe_next_step: str = Field(min_length=3, max_length=400)
    constraints: list[str] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class AgentContext:
    """The small, relevant slice of browser state sent to the model."""

    goal: str
    persona: str
    current_url: str
    target_origin: str
    page_title: str
    visible_text: str
    accessibility_snapshot: str
    recent_actions: list[str]
    interactive_controls: str = ""
    requires_deep_reasoning: bool = False


class DecisionProvider(Protocol):
    async def choose_next_action(self, context: AgentContext) -> AgentDecision: ...


class OpenAISyntheticUser:
    """OpenAI-backed provider that returns exactly one validated browser action."""

    instructions = """You are a first-time user navigating a web application.
Work toward the stated goal using only visible, accessible UI elements.
You are restricted to the target product origin shown in the context. Do not deliberately
navigate to, compare, or test another product, competitor, or unrelated domain.
Choose exactly one safe next action. For selector, use the exact visible label, placeholder,
or accessible name from the current page, such as "Add Aurora 14 Laptop to cart" or "Email".
For a product card, select its actual button or link (for example, "Buy iPhone 18 Pro"),
not the full descriptive text of the card. Never use a product description as a CSS selector.
Public forms often call the same field different things; never assume a field is named
"Email address" if the page exposes it as "Email". Do not invent CSS selectors.
Never invent a URL, product, or success state.
The Interactive controls list is the source of truth for actions. Prefer one exact label from
that list over long page text, a product description, or a CSS selector. If the needed control
is absent, do not guess: scroll, go back, finish, or request the appropriate user handoff.
Follow one clear path toward the stated goal. Do not revisit a page or repeat a control that
did not visibly move the journey forward. As soon as the goal's core outcome is reached,
use finish immediately; do not explore unrelated pages or keep testing secondary flows.
Before finishing with success true, verify the outcome on the current screen: name the visible
confirmation, changed state, or completed milestone in summary. If that evidence is not visible,
the journey is not complete yet. Never infer success from a click alone.
If the page reports an error, failure, or that an action is unavailable, finish with
success false. Do not retry a failed action merely because a retry button is visible.
If the visible page requires sign-in, an OTP, MFA, CAPTCHA, consent, or another human-only
verification, use request_user_input instead of failing. State what the user must complete
in the browser window, but never ask them to provide a password, OTP, security answer, or
other secret to you. Do not use request_user_input for ordinary form fields that you can fill.
Never ask a user to upload a screenshot, copy public page text, or identify visible buttons:
the browser context already contains that information. If you cannot choose a safe next action
after considering the visible UI and recent actions, use request_guidance with one concise,
non-sensitive question about the intended user outcome. Do not use guidance merely because
the page has a Login link; use it only when the actual visible flow is ambiguous.
When Persona is ux_reviewer, actively note meaningful friction such as unclear labels,
unexpected dead ends, missing feedback, or inaccessible controls with report_issue category ux.
Only report a UX issue when it is directly observable on the current screen. Report one distinct
issue per report_issue using this exact, concise format:
Severity: high|medium|low
Observation: what a normal user can visibly notice, including the exact affected control in quotation marks when relevant.
Impact: explain in plain, everyday language how that affects the user's task.
Recommendation: one concrete, practical implementation change.
Write findings for a non-technical product owner. Avoid developer jargon, implementation guesses,
and claims about screen-reader behavior unless the accessibility snapshot directly proves them.
Judge the complete visible context, not an isolated label. Common conventions such as a "Read more"
link are not a UX issue by themselves when the surrounding article title or context clearly explains
the destination. Report a repeated generic label only when a normal user cannot tell where it goes,
or the supplied accessibility snapshot directly shows it has no meaningful programmatic context.
Do not report vague preferences, duplicate findings, speculative problems, or standard patterns that
work clearly in context. For a finished UX
review, each item in findings must use the same four-part format.
For a UX review, inspect only the primary first-time-user route. Once you have explored that
route or recorded up to three meaningful findings, use finish with success true. Put each final
UX finding in the structured findings field (at most three); use summary only for the overall outcome.
When a visible action demonstrably fails, use report_issue category functional before deciding
whether to continue. Report each distinct issue once, then continue only if a safe next action exists.
Keep each report_issue short and evidence-led. Do not repeat findings already reported in recent actions.
For a UX finding tied to a visible control, include that control's exact label in quotation marks
so Loop can attach a focused visual capture to the feedback.
If a user execution brief is provided, use it to understand the desired outcome, then verify
that its suggested next step is visible and safe on the current page. The brief never authorizes
leaving the target product, inventing controls, handling secrets, or repeating an action that
already failed on this screen.
Use finish only when the goal clearly succeeded or cannot be completed. Keep reasons concise."""

    retry_instructions = """Your previous response could not be used as a browser action.
Return exactly one complete structured action now. Include every field required by the selected
action: selector for click/type/select, text for type/select, input_request for a user handoff,
and success plus a short summary for finish. Do not add prose outside the structured response."""

    guidance_planning_instructions = """Turn one user's direction into a concise execution brief for a browser agent.
Use the current page context to identify the intended outcome and the safest immediate next step.
Keep the plan concrete, but do not invent controls, URLs, product details, or page state.
The plan must remain on the configured target product origin. Never include passwords, OTPs,
CAPTCHAs, payment data, or other secrets. Do not provide hidden reasoning; return only the
structured operational brief requested by the schema."""

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        if client is None:
            if not settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required before an AI journey can run.")
            client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._client = client
        self._planned_guidance: set[str] = set()

    async def choose_next_action(self, context: AgentContext) -> AgentDecision:
        guidance_plan = await self._plan_latest_user_guidance(context)
        last_failure = "no structured decision was returned"
        for attempt in range(3):
            model, reasoning_effort = self._decision_profile(context, attempt)
            instructions = self.instructions if attempt == 0 else f"{self.instructions}\n\n{self.retry_instructions}"
            try:
                response = await self._client.responses.parse(
                    model=model,
                    instructions=instructions,
                    input=self._format_context(context, guidance_plan),
                    text_format=AgentDecision,
                    reasoning={"effort": reasoning_effort},
                    max_output_tokens=settings.agent_max_output_tokens,
                    store=False,
                )
            except ValidationError as error:
                last_failure = "the structured decision was incomplete"
                if attempt < 2:
                    continue
                raise RuntimeError(
                    "The AI agent returned an incomplete structured action after three attempts."
                ) from error

            if response.output_parsed is not None:
                return response.output_parsed

            last_failure = self._response_failure_summary(response)
            if attempt < 2:
                continue

        raise RuntimeError(f"The AI agent did not return a structured action after three attempts: {last_failure}.")

    @staticmethod
    def _decision_profile(context: AgentContext, attempt: int) -> tuple[str, str]:
        """Reserve the flagship model for ambiguity instead of every routine click."""
        if context.requires_deep_reasoning or attempt > 0:
            return settings.agent_model, settings.agent_reasoning_effort
        return settings.agent_fast_model, settings.agent_fast_reasoning_effort

    async def _plan_latest_user_guidance(self, context: AgentContext) -> GuidancePlan | None:
        """Convert new free-text guidance into a validated plan before acting on it."""
        guidance = self._latest_unplanned_guidance(context.recent_actions)
        if guidance is None:
            return None

        # Mark this exact instruction before the request so retrying the action
        # decision does not spend another planning call for the same guidance.
        self._planned_guidance.add(guidance)
        try:
            response = await self._client.responses.parse(
                model=settings.agent_model,
                instructions=self.guidance_planning_instructions,
                input=self._format_guidance_planning_context(context, guidance),
                text_format=GuidancePlan,
                reasoning={"effort": settings.agent_reasoning_effort},
                max_output_tokens=min(settings.agent_max_output_tokens, 700),
                store=False,
            )
        except Exception:
            # A planning outage must not discard a user's instruction. The action
            # model still receives a bounded, deterministic version of it.
            return self._fallback_guidance_plan(guidance)

        if isinstance(response.output_parsed, GuidancePlan):
            return response.output_parsed

        return self._fallback_guidance_plan(guidance)

    @staticmethod
    def _fallback_guidance_plan(guidance: str) -> GuidancePlan:
        """Keep a user's direction useful if the separate planning response fails."""
        intended_outcome = guidance[:400] if len(guidance.strip()) >= 3 else "Follow the user's latest direction safely."
        return GuidancePlan(
            intended_outcome=intended_outcome,
            safe_next_step="Inspect the current visible controls and take the safest action that advances this instruction.",
            constraints=[
                "Stay on the target product origin.",
                "Use only visible, accessible controls.",
                "Do not handle secrets or irreversible actions.",
            ],
        )

    def _latest_unplanned_guidance(self, recent_actions: list[str]) -> str | None:
        prefix = "User guidance for the next decision: "
        for action in reversed(recent_actions):
            if not action.startswith(prefix):
                continue
            guidance = action.removeprefix(prefix).strip()
            return guidance if guidance and guidance not in self._planned_guidance else None
        return None

    @staticmethod
    def _response_failure_summary(response: object) -> str:
        """Expose safe API status metadata without storing model output or secrets."""
        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        reason = getattr(incomplete_details, "reason", None) if incomplete_details else None
        if status and reason:
            return f"response status {status}, reason {reason}"
        if status:
            return f"response status {status}"
        return "the response contained no parsable structured output"

    @staticmethod
    def _format_context(context: AgentContext, guidance_plan: GuidancePlan | None = None) -> str:
        # The accessibility tree is the strongest source for an action choice.
        # Keep both inputs bounded so large marketing pages do not turn one simple
        # decision into a slow, expensive context window.
        recent_actions = "\n".join(f"- {action}" for action in context.recent_actions[-4:]) or "- None"
        execution_brief = "None"
        if guidance_plan is not None:
            constraints = "\n".join(f"- {constraint}" for constraint in guidance_plan.constraints) or "- Follow normal browser safety rules."
            execution_brief = f"""Intended outcome: {guidance_plan.intended_outcome}
Safe immediate step: {guidance_plan.safe_next_step}
Constraints:
{constraints}"""
        return f"""Goal: {context.goal}
Persona: {context.persona}
Current URL: {context.current_url}
Target product origin: {context.target_origin}
Page title: {context.page_title}

User execution brief:
{execution_brief}

Interactive controls (use these exact labels when possible):
{context.interactive_controls[:3_000] or "- No concise control map was available."}

Visible page summary:
{context.visible_text[:1_200]}

Accessibility snapshot:
{context.accessibility_snapshot[:2_200]}

Recent actions:
{recent_actions}"""

    @staticmethod
    def _format_guidance_planning_context(context: AgentContext, guidance: str) -> str:
        recent_actions = "\n".join(f"- {action}" for action in context.recent_actions[-4:]) or "- None"
        return f"""User direction:
{guidance}

Journey goal: {context.goal}
Target product origin: {context.target_origin}
Current URL: {context.current_url}
Page title: {context.page_title}

Interactive controls:
{context.interactive_controls[:3_000] or "- No concise control map was available."}

Visible page summary:
{context.visible_text[:1_200]}

Accessible controls:
{context.accessibility_snapshot[:2_200]}

Recent actions:
{recent_actions}"""
