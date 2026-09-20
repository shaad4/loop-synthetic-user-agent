"use client";

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { Action, Application, Evidence, evidenceUrl, Journey, loopApi, Run } from "../lib/api";

const journeyTemplates = [
  {
    name: "First visit",
    goal: "Act as a first-time visitor. Understand what this product offers, find the primary next step, and report any point that makes getting started unclear.",
    detail: "New visitor",
    persona: "ux_reviewer",
  },
  {
    name: "Find and compare",
    goal: "Act as a potential customer. Find the key information needed to decide whether this product is suitable, such as features, pricing, plans, or how it works.",
    detail: "Potential customer",
    persona: "first_time_user",
  },
  {
    name: "Get help or contact",
    goal: "Act as a user who needs help. Find the support or contact path and reach the point where a message can be started without submitting personal information.",
    detail: "Support seeker",
    persona: "ux_reviewer",
  },
  {
    name: "Create an account",
    goal: "Act as a new user. Find the sign-up flow, identify the information required, and reach the final safe step without creating an account or submitting personal data.",
    detail: "New account user",
    persona: "first_time_user",
  },
  {
    name: "Complete a core task",
    goal: "Act as a returning user. Find the product's main task or workflow and complete the first safe, reversible part of it. Report clearly if the path is blocked or confusing.",
    detail: "Returning user",
    persona: "first_time_user",
  },
  {
    name: "UX clarity review",
    goal: "Explore the primary first-time-user flow. Report the most important unclear labels, dead ends, missing feedback, and accessibility friction. Do not submit irreversible data.",
    detail: "UX reviewer",
    persona: "ux_reviewer",
  },
];

export default function Dashboard() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [applicationId, setApplicationId] = useState("");
  const [journeyId, setJourneyId] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [actions, setActions] = useState<Action[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeStep, setActiveStep] = useState(1);
  const [journeyName, setJourneyName] = useState("");
  const [journeyGoal, setJourneyGoal] = useState("");
  const [journeyMode, setJourneyMode] = useState<Journey["persona"]>("first_time_user");
  const [guidance, setGuidance] = useState("");
  const [showNewApplication, setShowNewApplication] = useState(false);
  const [showEditApplication, setShowEditApplication] = useState(false);
  const activeRunIdRef = useRef("");

  const currentApplication = applications.find((item) => item.id === applicationId) ?? null;
  const currentJourney = journeys.find((item) => item.id === journeyId) ?? null;
  const currentActions = run ? actions.filter((item) => item.run_id === run.id) : [];
  const currentEvidence = run ? evidence.filter((item) => item.run_id === run.id) : [];
  // Console messages are developer diagnostics, not user-facing audit evidence.
  // Hide legacy entries too, so older runs remain easy to read.
  const visibleEvidence = currentEvidence.filter((item) => item.evidence_type !== "console_error");
  const screenshotEvidence = visibleEvidence.filter((item) => item.evidence_type === "screenshot");
  const liveFrame = [...screenshotEvidence].reverse()[0] ?? null;
  const diagnosticEvidence = visibleEvidence.filter((item) => item.evidence_type !== "screenshot");
  const feedbackScreenshotFor = (feedback: string | null) => screenshotEvidence.find(
    (item) => item.content === `UX feedback: ${feedback ?? ""}`,
  ) ?? null;
  const isRunning = run?.status === "running" || run?.status === "queued" || run?.status === "awaiting_user";
  const isAwaitingUser = run?.status === "awaiting_user";
  const latestIntervention = [...currentActions].reverse().find((action) => ["user_input_required", "agent_guidance_required"].includes(action.action_type));
  const userInputRequest = latestIntervention?.action_type === "user_input_required" ? latestIntervention.outcome : undefined;
  const isGuidanceCheckpoint = latestIntervention?.action_type === "agent_guidance_required";
  const canProvideGuidance = isGuidanceCheckpoint;
  const issueActions = currentActions.filter(isIssueAction);
  const actionFailures = issueActions.filter((action) => action.action_type === "action_error");
  const uxFindings = currentActions.filter((action) => action.action_type === "ux_issue");
  const isUxReview = currentJourney?.persona === "ux_reviewer";
  const completionFeedback = isUxReview
    ? currentActions.filter((action) => action.action_type === "journey_complete" && hasFeedbackSummary(action.outcome))
    : [];
  const uxFeedback = [...uxFindings, ...completionFeedback];
  const functionalFindings = currentActions.filter((action) => action.action_type === "functional_issue");
  const successfulActions = currentActions.filter((action) => actionState(action, isUxReview) === "success");
  const issueCount = actionFailures.length + diagnosticEvidence.length + uxFeedback.length + functionalFindings.length;

  useEffect(() => { void loadApplications(); }, []);
  useEffect(() => { activeRunIdRef.current = run?.id ?? ""; }, [run?.id]);
  useEffect(() => { if (applicationId) void loadJourneys(applicationId); else setJourneys([]); }, [applicationId]);
  useEffect(() => { if (journeyId) void loadRuns(journeyId); else { activeRunIdRef.current = ""; setRuns([]); setRun(null); setActions([]); setEvidence([]); } }, [journeyId]);
  useEffect(() => {
    if (!run) return;
    const refresh = () => void refreshRun(run.id);
    refresh();
    const timer = window.setInterval(refresh, isRunning ? 1000 : 5000);
    return () => window.clearInterval(timer);
  }, [run?.id, isRunning]);

  async function loadApplications() {
    try {
      const items = await loopApi.listApplications();
      setApplications(items);
      setApplicationId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? "");
    } catch (error) { showError(error); }
  }

  async function loadJourneys(id: string) {
    try {
      const items = await loopApi.listJourneys(id);
      setJourneys(items);
      setJourneyId((current) => items.some((item) => item.id === current) ? current : items[0]?.id ?? "");
    } catch (error) { showError(error); }
  }

  async function loadRuns(id: string) {
    try {
      const items = await loopApi.listRuns(id);
      setRuns(items);
      setRun((current) => {
        const nextRun = current?.journey_id === id ? current : items[0] ?? null;
        activeRunIdRef.current = nextRun?.id ?? "";
        return nextRun;
      });
    } catch (error) { showError(error); }
  }

  async function refreshRun(id: string) {
    try {
      const [nextRun, nextActions, nextEvidence] = await Promise.all([
        loopApi.getRun(id), loopApi.listActions(id), loopApi.listEvidence(id),
      ]);
      if (activeRunIdRef.current !== id) return;
      setRun(nextRun);
      setRuns((current) => current.map((item) => item.id === nextRun.id ? nextRun : item));
      setActions(nextActions);
      setEvidence(nextEvidence);
    } catch (error) { showError(error); }
  }

  async function addApplication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const values = new FormData(event.currentTarget);
    const requestedName = String(values.get("name"));
    try {
      const app = await loopApi.createApplication({
        name: requestedName,
        target_url: String(values.get("targetUrl")),
        repository_url: String(values.get("repositoryUrl")) || null,
        repository_branch: String(values.get("branch")) || "main",
      });
      setApplications((current) => [app, ...current]);
      setApplicationId(app.id);
      setShowNewApplication(false);
      setActiveStep(2);
      event.currentTarget.reset();
      setNotice(`${app.name} is ready. Now describe the first user journey.`);
    } catch (error) {
      if (error instanceof Error && error.message.includes("already exists")) {
        const existing = await loopApi.listApplications();
        const match = existing.find((item) => item.name.toLowerCase() === requestedName.toLowerCase());
        if (match) {
          setApplications(existing);
          setApplicationId(match.id);
          setActiveStep(2);
          setNotice(`Continuing with the saved ${match.name} application.`);
          return;
        }
      }
      showError(error);
    } finally { setBusy(false); }
  }

  async function updateApplication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!currentApplication) return;
    setBusy(true);
    const values = new FormData(event.currentTarget);
    try {
      const updatedApplication = await loopApi.updateApplication(currentApplication.id, {
        name: String(values.get("name")),
        target_url: String(values.get("targetUrl")),
        repository_url: String(values.get("repositoryUrl")) || null,
        repository_branch: String(values.get("branch")) || "main",
      });
      setApplications((current) => current.map((item) => item.id === updatedApplication.id ? updatedApplication : item));
      setShowEditApplication(false);
      setNotice(`${updatedApplication.name} was updated. Future runs will use ${updatedApplication.target_url}.`);
    } catch (error) { showError(error); } finally { setBusy(false); }
  }

  async function addJourney(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!applicationId) return;
    setBusy(true);
    try {
      const journey = await loopApi.createJourney(applicationId, {
        name: journeyName,
        goal: journeyGoal,
        persona: journeyMode,
      });
      setJourneys((current) => [journey, ...current]);
      setJourneyId(journey.id);
      setActiveStep(3);
      setNotice("Journey saved. Start the Synthetic User when you are ready.");
    } catch (error) { showError(error); } finally { setBusy(false); }
  }

  async function startRun() {
    if (!journeyId) return;
    setBusy(true);
    try {
      const nextRun = await loopApi.startRun(journeyId);
      activeRunIdRef.current = nextRun.id;
      setRun(nextRun);
      setRuns((current) => [nextRun, ...current]);
      setActions([]);
      setEvidence([]);
      setNotice("Synthetic User started. Loop will refresh the trail as every action happens.");
    } catch (error) { showError(error); } finally { setBusy(false); }
  }

  async function resumeRun(resolution: "continue" | "finish" = "continue") {
    if (!run) return;
    setBusy(true);
    try {
      const nextRun = await loopApi.resumeRun(run.id, resolution, canProvideGuidance ? guidance.trim() : undefined);
      setRun(nextRun);
      setRuns((current) => current.map((item) => item.id === nextRun.id ? nextRun : item));
      setGuidance("");
      setNotice(resolution === "continue" ? "Loop is checking the browser again and will continue the audit." : "Loop is preparing the issue report.");
    } catch (error) { showError(error); } finally { setBusy(false); }
  }

  async function stopRun() {
    if (!run) return;
    setBusy(true);
    try {
      const nextRun = await loopApi.stopRun(run.id);
      setRun(nextRun);
      setRuns((current) => current.map((item) => item.id === nextRun.id ? nextRun : item));
      await refreshRun(nextRun.id);
      setActiveStep(4);
      setNotice("Test stopped. The timeline and all evidence collected so far are ready to review.");
    } catch (error) { showError(error); } finally { setBusy(false); }
  }

  function selectTemplate(template: typeof journeyTemplates[number]) {
    setJourneyName(template.name);
    setJourneyGoal(template.goal);
    setJourneyMode(template.persona);
  }

  function makeAnotherTest() {
    setJourneyName("");
    setJourneyGoal("");
    setJourneyMode("first_time_user");
    setActiveStep(2);
    setNotice("Create a new journey or choose a scenario template. Your previous evidence is still saved in Run history.");
  }

  function showError(error: unknown) {
    setNotice(error instanceof Error ? error.message : "Something went wrong. Please try again.");
  }

  const canOpenStep = (step: number) => step === 1
    || (step === 2 && applications.length > 0)
    || (step === 3 && journeys.length > 0)
    || (step === 4 && run !== null);

  const stepMeta = [
    ["Target", "Where to test"],
    ["Journey", "What to do"],
    ["Run", "Watch it work"],
    ["Review", "Inspect proof"],
  ];

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="wordmark" type="button" onClick={() => setActiveStep(1)} aria-label="Return to the first step">
          <span className="wordmark-mark">↻</span>
          <span>loop</span>
        </button>
        <div className="topbar-status"><span className="status-dot" /> Local workspace <span className="topbar-divider" /> Synthetic user testing</div>
      </header>

      <section className="hero-card">
        <div>
          <p className="kicker">AI QUALITY WORKSPACE</p>
          <h1>Know what your users<br />experience.</h1>
          <p>Loop sends a first-time user through a real product journey, captures proof, and makes a failure easy to reproduce.</p>
        </div>
        <div className="hero-orbit" aria-hidden="true"><span>LIVE</span><i /><b>01</b></div>
      </section>

      {notice && <div className="notice" role="status"><span>✦</span><p>{notice}</p><button aria-label="Dismiss notification" type="button" onClick={() => setNotice("")}>×</button></div>}

      <nav className="progress-nav" aria-label="Set up a Loop journey">
        {stepMeta.map(([label, helper], index) => {
          const step = index + 1;
          const state = activeStep === step ? "active" : step < activeStep ? "complete" : "";
          return <button key={label} type="button" className={state} disabled={!canOpenStep(step)} onClick={() => setActiveStep(step)}>
            <span className="progress-number">{state === "complete" ? "✓" : String(step).padStart(2, "0")}</span>
            <span><strong>{label}</strong><small>{helper}</small></span>
          </button>;
        })}
      </nav>

      {activeStep === 1 && <section className="workspace-stage">
        <StageIntro eyebrow="STEP 01" title="Choose your product" text="Start with a local app or a permitted public URL. Existing products are always reusable." />
        <div className="two-column target-layout">
          <Panel title="Your test target" subtitle="This is the site your Synthetic User will visit.">
            {applications.length ? <div className="selection-card">
              <div className="selection-icon">⌘</div>
              <div><p>SELECTED APPLICATION</p><h3>{currentApplication?.name}</h3><code>{currentApplication?.target_url}</code></div>
              <label className="sr-only" htmlFor="application-select">Select application</label>
              <select id="application-select" value={applicationId} onChange={(event) => setApplicationId(event.target.value)}>
                {applications.map((app) => <option value={app.id} key={app.id}>{app.name}</option>)}
              </select>
            </div> : <EmptyState icon="⌁" title="No product yet" text="Add the app you want Loop to explore." />}
            {currentApplication && <div className="target-details"><span>URL</span><strong>{currentApplication.target_url}</strong><span>Branch</span><strong>{currentApplication.repository_branch}</strong></div>}
            <div className="button-row">
              {currentApplication && <button type="button" onClick={() => setActiveStep(2)}>Use this product <span>→</span></button>}
              {currentApplication && <button type="button" className="ghost-button" onClick={() => setShowEditApplication((value) => !value)}>{showEditApplication ? "Close editor" : "Edit product"}</button>}
              <button type="button" className="ghost-button" onClick={() => setShowNewApplication((value) => !value)}>{showNewApplication ? "Close form" : "Add another product"}</button>
            </div>
          </Panel>
          <aside className="side-note"><span className="side-note-icon">◌</span><h3>Good to know</h3><p>Loop can test any app you are allowed to access. It uses a fresh browser session and does not reuse your personal login.</p><div><span>01</span> Connect a product <span>02</span> Describe one user goal <span>03</span> Watch the proof arrive</div></aside>
        </div>
        {(showNewApplication || !applications.length) && <Panel title="Add a product" subtitle="Use a recognisable name so your evidence stays organised.">
          <form onSubmit={addApplication} className="form-grid">
            <Input label="Product name" name="name" required />
            <Input label="Target URL" name="targetUrl" type="url" required />
            <Input label="Repository URL" name="repositoryUrl" type="url" hint="Optional" />
            <Input label="Branch" name="branch" hint="Optional — defaults to main" />
            <button className="form-submit" disabled={busy}>{busy ? "Saving…" : "Save product and continue →"}</button>
          </form>
        </Panel>}
        {showEditApplication && currentApplication && <Panel title="Edit product" subtitle="Updating the target changes future tests only. Existing journeys and reports stay unchanged.">
          <form key={currentApplication.id} onSubmit={updateApplication} className="form-grid">
            <Input label="Product name" name="name" defaultValue={currentApplication.name} required />
            <Input label="Target URL" name="targetUrl" type="url" defaultValue={currentApplication.target_url} required />
            <Input label="Repository URL" name="repositoryUrl" type="url" defaultValue={currentApplication.repository_url ?? ""} hint="Optional" />
            <Input label="Branch" name="branch" defaultValue={currentApplication.repository_branch} hint="Optional — defaults to main" />
            <div className="form-actions"><button type="button" className="ghost-button" onClick={() => setShowEditApplication(false)}>Cancel</button><button className="form-submit" disabled={busy}>{busy ? "Saving…" : "Save changes →"}</button></div>
          </form>
        </Panel>}
      </section>}

      {activeStep === 2 && <section className="workspace-stage">
        <StageIntro eyebrow="STEP 02" title="Describe one user goal" text="Tell Loop the desired outcome. It decides the individual clicks like a first-time user would." />
        <Panel title="Choose a real-user scenario" subtitle="These are common product journeys, not demo-app tasks. Pick one, then edit the goal for your product.">
          <div className="template-grid">
            {journeyTemplates.map((template) => <button key={template.name} type="button" className={`template-card ${journeyName === template.name ? "selected" : ""}`} onClick={() => selectTemplate(template)}>
              <span>{template.detail}</span><strong>{template.name}</strong><small>{template.goal}</small>
            </button>)}
          </div>
        </Panel>
        <Panel title="Your journey" subtitle={currentApplication ? `This journey will run in ${currentApplication.name}.` : "Choose a product first."}>
          {!applications.length ? <EmptyState icon="←" title="Choose a product first" text="Return to Step 01 to set your test target." /> : <form onSubmit={addJourney} className="journey-form">
            <label>Product<select value={applicationId} onChange={(event) => setApplicationId(event.target.value)}>{applications.map((app) => <option value={app.id} key={app.id}>{app.name}</option>)}</select></label>
            <label>Test session<select value={journeyMode} onChange={(event) => setJourneyMode(event.target.value)}><option value="first_time_user">Functional journey — can complete the goal</option><option value="ux_reviewer">UX review — reports friction separately</option></select><small>Each journey opens a fresh, isolated browser session and keeps its findings separate.</small></label>
            <Input label="Journey name" value={journeyName} onChange={(event) => setJourneyName(event.target.value)} required />
            <label className="goal-field">User goal<textarea rows={5} value={journeyGoal} onChange={(event) => setJourneyGoal(event.target.value)} required /><span>Write the outcome, not the clicks. Example: “Add the Nova 13, apply STUDENT15, then place the order.”</span></label>
            <button disabled={busy}>{busy ? "Saving…" : "Save journey and continue →"}</button>
          </form>}
        </Panel>
      </section>}

      {activeStep === 3 && <section className="workspace-stage run-stage">
        <div className="run-header"><StageIntro eyebrow="STEP 03" title="Watch the journey live" text="Loop runs a private browser session and updates this screen after every action." /><div className="run-picker"><label>Selected journey<select value={journeyId} onChange={(event) => setJourneyId(event.target.value)}>{journeys.map((journey) => <option value={journey.id} key={journey.id}>{journey.name} · {shortGoal(journey.goal)}</option>)}</select></label><button onClick={startRun} disabled={busy || isRunning || !journeyId}>{isRunning ? "Journey in progress" : "Start AI journey"}</button>{isRunning && <button type="button" className="ghost-button stop-button" onClick={stopRun} disabled={busy}>Stop test</button>}</div></div>
        {!journeys.length ? <Panel title="No journey ready" subtitle="Create a journey before running Loop."><EmptyState icon="→" title="Describe a user goal" text="Step 02 creates the mission your Synthetic User will follow." /></Panel> : <>
          {run && <div className="run-summary"><div><span className={`run-pulse ${isRunning && !isAwaitingUser ? "live" : ""}`} /><span>{isAwaitingUser ? "WAITING FOR YOU" : isRunning ? "LIVE RUN" : "LAST RUN"}</span><strong>{currentJourney?.name ?? "Synthetic User journey"}</strong></div><Status status={run.status} /><span>{currentActions.length} recorded actions</span><span>{visibleEvidence.length} evidence items</span></div>}
          {isAwaitingUser && latestIntervention && <section className="intervention" role="dialog" aria-modal="true" aria-labelledby="intervention-title"><span className="intervention-icon">⌁</span><div><p>{isGuidanceCheckpoint ? "LOOP NEEDS YOUR DIRECTION" : "YOUR INPUT NEEDED"}</p><h3 id="intervention-title">{isGuidanceCheckpoint ? "Loop is stuck" : "Complete the protected step"}</h3>{isGuidanceCheckpoint ? <GuidanceBrief prompt={latestIntervention.outcome} /> : <strong>{userInputRequest ?? "Finish the required sign-in or verification step in the browser session."}</strong>}{canProvideGuidance ? <label className="guidance-field">Tell Loop what to do<textarea rows={2} value={guidance} onChange={(event) => setGuidance(event.target.value)} placeholder="Example: Use the menu instead." /><small>Give the next action or desired outcome. Never enter passwords or OTPs.</small></label> : <small>Enter passwords, OTPs, or verification codes only in the target browser. Loop never receives or stores them.</small>}</div>{canProvideGuidance ? <div className="intervention-actions"><button type="button" className="ghost-button" onClick={() => resumeRun("finish")} disabled={busy}>Finish & review</button><button type="button" onClick={() => resumeRun("continue")} disabled={busy || guidance.trim().length < 3}>{busy ? "Saving…" : "Continue →"}</button></div> : <button type="button" onClick={() => resumeRun("continue")} disabled={busy}>{busy ? "Resuming…" : "I’ve completed it →"}</button>}</section>}
          <div className="live-grid">
            <Panel title="Browser view" subtitle={liveFrame ? "Latest frame from Loop’s private browser session." : "The first frame will appear here when the session starts."} className="browser-panel">
              {liveFrame ? <div className="live-frame"><div className="browser-chrome"><span /><span /><span /><code>{currentApplication?.target_url}</code><em>LIVE</em></div><img src={evidenceUrl(liveFrame.file_path) ?? ""} alt="Latest browser state from the Synthetic User" /></div> : <EmptyState icon="◌" title="Preparing the browser" text="Loop is opening a fresh session for this journey." />}
            </Panel>
            <Panel title="Action trail" subtitle={run ? `Status: ${run.status}` : "Actions will appear here as Loop moves."} className="activity-panel">
              {run && <Status status={run.status} />}
              <ActionTimeline actions={currentActions} isUxReview={isUxReview} />
              {run && !isRunning && <button className="wide-button" onClick={() => setActiveStep(4)}>Open complete review <span>→</span></button>}
            </Panel>
          </div>
        </>}
      </section>}

      {activeStep === 4 && <section className="workspace-stage">
        <StageIntro eyebrow="STEP 04" title="Review the evidence" text="Everything needed to understand and reproduce this run stays together." />
        {!run ? <Panel title="No run to review" subtitle="Start a journey and Loop will build the evidence trail."><EmptyState icon="◌" title="Your evidence will live here" text="Screenshots, network failures, and every action are preserved per run." /></Panel> : <>
          <Panel title="Run overview" subtitle="Switch between previous runs without losing the evidence.">
            <div className="review-overview"><label>Run history<select value={run.id} onChange={(event) => { const selected = runs.find((item) => item.id === event.target.value) ?? null; activeRunIdRef.current = selected?.id ?? ""; setRun(selected); setActions([]); setEvidence([]); }}>{runs.map((item) => <option value={item.id} key={item.id}>{item.status.toUpperCase()} · {formatTime(item.created_at)}</option>)}</select></label><Status status={run.status} /><div><span>Session</span><strong>{currentJourney?.persona === "ux_reviewer" ? "UX review" : "Functional"}</strong></div><div><span>Finished</span><strong>{formatTime(run.completed_at)}</strong></div><div><span>Captured</span><strong>{visibleEvidence.length} items</strong></div></div>
          </Panel>
          <Panel title="Audit report" subtitle="A concise summary of what worked and every issue captured during this run.">
            <SessionSummary
              journeyName={currentJourney?.name ?? "this journey"}
              completedActions={successfulActions.length}
              uxFindings={uxFeedback}
              functionalFindings={functionalFindings}
              actionFailures={actionFailures}
              diagnostics={diagnosticEvidence}
            />
            <div className="report-highlights"><ReportMetric label="Completed actions" value={successfulActions.length} tone="good" /><ReportMetric label="Issues found" value={issueCount} tone={issueCount ? "bad" : "neutral"} /><ReportMetric label="UX findings" value={uxFeedback.length} tone={uxFeedback.length ? "warning" : "neutral"} /><ReportMetric label="Evidence captured" value={visibleEvidence.length} tone="neutral" /></div>
            {issueCount ? <div className="report-issues">{[...uxFeedback, ...functionalFindings, ...actionFailures].map((action) => { const tone = actionTone(action); return <article className={tone} key={action.id}>{tone === "ux" ? <FeedbackCard content={action.outcome ?? "No additional detail captured."} evidence={feedbackScreenshotFor(action.outcome)} /> : <><span>×</span><div><strong>Functional issue</strong><FindingList content={action.outcome ?? "No additional detail captured."} /></div></>}</article>; })}{diagnosticEvidence.map((item) => <article className="error" key={item.id}><span>×</span><div><strong>{item.evidence_type.replaceAll("_", " ")}</strong><FindingList content={item.content ?? "Open the attached capture for more detail."} /></div></article>)}</div> : <p className="report-clear">No user-impacting browser, network, functional, or UX issues were captured in this run.</p>}
          </Panel>
          <div className="review-grid">
            <Panel title="Replayable action trail" subtitle="The precise order of user-facing browser actions."><ActionTimeline actions={currentActions} isUxReview={isUxReview} /></Panel>
            <Panel title="Evidence locker" subtitle="Visual proof and technical signals behind the outcome.">
              {liveFrame && <div className="review-featured"><img src={evidenceUrl(liveFrame.file_path) ?? ""} alt="Last browser screenshot from this run" /><a href={evidenceUrl(liveFrame.file_path) ?? ""} target="_blank" rel="noreferrer">Open latest full capture ↗</a></div>}
              <div className="evidence-list">{diagnosticEvidence.length ? diagnosticEvidence.map((item) => <EvidenceRow item={item} key={item.id} />) : <p className="no-diagnostics">No technical errors were captured in this run.</p>}</div>
            </Panel>
          </div>
          <div className="review-actions"><button type="button" onClick={makeAnotherTest}>Make another test <span>→</span></button><p>Create a new user goal while keeping this run and its evidence in history.</p></div>
        </>}
      </section>}
    </main>
  );
}

function StageIntro({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return <div className="stage-intro"><p>{eyebrow}</p><h2>{title}</h2><span>{text}</span></div>;
}

function Panel({ title, subtitle, children, className = "" }: { title: string; subtitle: string; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-heading"><div><p>{title}</p><h3>{title}</h3></div><span>✦</span></div><p className="panel-subtitle">{subtitle}</p>{children}</section>;
}

function Input({ label, hint, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return <label>{label}{hint && <small>{hint}</small>}<input {...props} /></label>;
}

function Status({ status }: { status: Run["status"] }) { return <span className={`status ${status}`}>{status}</span>; }

function EmptyState({ icon, title, text }: { icon: string; title: string; text: string }) {
  return <div className="empty-state"><span>{icon}</span><div><strong>{title}</strong><p>{text}</p></div></div>;
}

function ActionTimeline({ actions, isUxReview = false }: { actions: Action[]; isUxReview?: boolean }) {
  return actions.length ? <ol className="timeline">{actions.map((action, index) => { const state = actionState(action, isUxReview); const isActive = state === "thinking" && index === actions.length - 1; const marker = state === "success" ? "✓" : state === "error" ? "×" : state === "ux" ? "!" : String(index + 1).padStart(2, "0"); return <li className={`${state}-action ${isActive ? "active-action" : ""}`} key={action.id}><span className="timeline-index" aria-label={isActive ? "Loop is working on this step" : undefined}>{isActive ? <span className="timeline-loader" aria-hidden="true" /> : marker}</span><div><time>{formatTime(action.created_at)}<span className={`action-kind ${state}`}>{actionKindLabel(state)}</span></time>{state === "ux" ? <FeedbackCard content={action.outcome ?? action.action_type} /> : state === "error" ? <FindingList content={action.outcome ?? action.action_type} /> : <p>{action.outcome ?? action.action_type}</p>}</div></li>; })}</ol> : <EmptyState icon="…" title="Waiting for the first action" text="The browser trail will update automatically." />;
}

function FeedbackCard({ content, evidence }: { content: string; evidence?: Evidence | null }) {
  const structuredFeedback = parseStructuredFeedback(content);
  const findingCount = splitFindings(content).length;
  const screenshotUrl = evidenceUrl(evidence?.file_path ?? null);
  return <section className="feedback-card"><header><span>UX feedback</span>{structuredFeedback ? <em className={`severity ${structuredFeedback.severity}`}>{structuredFeedback.severity} priority</em> : <em>{findingCount} finding{findingCount === 1 ? "" : "s"}</em>}</header>{structuredFeedback ? <dl className="feedback-details"><div><dt>Observed</dt><dd>{structuredFeedback.observation}</dd></div><div><dt>User impact</dt><dd>{structuredFeedback.impact}</dd></div><div><dt>Recommended fix</dt><dd>{structuredFeedback.recommendation}</dd></div></dl> : <FindingList content={content} />}{screenshotUrl && <a className="feedback-evidence" href={screenshotUrl} target="_blank" rel="noreferrer"><img src={screenshotUrl} alt="Screenshot captured when Loop recorded this UX feedback" /><span>View captured screen ↗</span></a>}</section>;
}

function SessionSummary({
  journeyName,
  completedActions,
  uxFindings,
  functionalFindings,
  actionFailures,
  diagnostics,
}: {
  journeyName: string;
  completedActions: number;
  uxFindings: Action[];
  functionalFindings: Action[];
  actionFailures: Action[];
  diagnostics: Evidence[];
}) {
  const issueCount = uxFindings.length + functionalFindings.length + actionFailures.length + diagnostics.length;
  const uxScore = score(100 - uxFindings.length * 12 - functionalFindings.length * 4 - actionFailures.length * 3);
  const flowScore = score(100 - functionalFindings.length * 18 - actionFailures.length * 14 - diagnostics.length * 8);
  const reliabilityScore = score(100 - actionFailures.length * 18 - diagnostics.length * 15 - functionalFindings.length * 8);
  const overallScore = Math.round((uxScore + flowScore + reliabilityScore) / 3);
  const firstFinding = [
    ...functionalFindings.map((item) => item.outcome),
    ...actionFailures.map((item) => item.outcome),
    ...diagnostics.map((item) => item.content),
    ...uxFindings.map((item) => item.outcome),
  ].find(Boolean);
  const summary = issueCount === 0
    ? `${journeyName} completed with ${completedActions} completed action${completedActions === 1 ? "" : "s"}. Loop did not find a user-facing issue in this session.`
    : `${journeyName} completed ${completedActions} action${completedActions === 1 ? "" : "s"} and found ${issueCount} item${issueCount === 1 ? "" : "s"} to review. Start with: ${plainFinding(firstFinding)}.`;

  return <section className="session-summary" aria-label="Session summary">
    <div className="session-summary-copy"><span>Session summary</span><h4>{scoreLabel(overallScore)}</h4><p>{summary}</p></div>
    <div className="score-grid">
      <ScoreCard label="Overall" score={overallScore} />
      <ScoreCard label="UX" score={uxScore} />
      <ScoreCard label="Flow" score={flowScore} />
      <ScoreCard label="Reliability" score={reliabilityScore} />
    </div>
  </section>;
}

function ScoreCard({ label, score: value }: { label: string; score: number }) {
  return <div className={`score-card ${scoreTone(value)}`}><span>{label}</span><strong>{value}</strong><small>/100</small></div>;
}

function score(value: number) { return Math.max(0, Math.min(100, value)); }
function scoreTone(value: number) { return value >= 85 ? "good" : value >= 65 ? "warning" : "bad"; }
function scoreLabel(value: number) { return value >= 85 ? "Healthy experience" : value >= 65 ? "Needs a few improvements" : "Needs attention"; }
function plainFinding(finding: string | null | undefined) {
  const compact = (finding ?? "an issue in the tested journey")
    .replace(/(?:Severity|Observation|Impact|Recommendation)\s*:/gi, "")
    .replace(/\s+/g, " ")
    .trim();
  const firstSentence = compact.split(/(?<=[.!?])\s/)[0] ?? compact;
  return firstSentence.length > 180 ? `${firstSentence.slice(0, 177).trim()}…` : firstSentence;
}

function FindingList({ content }: { content: string }) {
  const findings = splitFindings(content);
  const visibleFindings = findings.slice(0, 3);
  const remainingFindings = findings.slice(3);
  return <div className="finding-list"><ul>{visibleFindings.map((finding, index) => <li key={`${finding}-${index}`}>{finding}</li>)}</ul>{remainingFindings.length > 0 && <details><summary>Show {remainingFindings.length} more finding{remainingFindings.length === 1 ? "" : "s"}</summary><ul>{remainingFindings.map((finding, index) => <li key={`${finding}-${index}`}>{finding}</li>)}</ul></details>}</div>;
}

function splitFindings(content: string) {
  const findings = content.split(/(?=\s*\d+\)\s)/).map((item) => item.replace(/^\s*\d+\)\s*/, "").trim()).filter(Boolean);
  return findings.length > 1 ? findings : [content.trim() || "No additional detail captured."];
}

function parseStructuredFeedback(content: string) {
  const parts = new Map<string, string>();
  for (const match of content.matchAll(/(?:^|\n)\s*(Severity|Observation|Impact|Recommendation)\s*:\s*([^\n]+)/gi)) {
    parts.set(match[1].toLowerCase(), match[2].trim());
  }
  const severity = parts.get("severity")?.toLowerCase();
  const observation = parts.get("observation");
  const impact = parts.get("impact");
  const recommendation = parts.get("recommendation");
  if (!observation || !impact || !recommendation || !["high", "medium", "low"].includes(severity ?? "")) return null;
  return { severity: severity as "high" | "medium" | "low", observation, impact, recommendation };
}

function GuidanceBrief({ prompt }: { prompt: string | null | undefined }) {
  const brief = summarizeGuidance(prompt);
  return <div className="guidance-brief"><p>{brief.question}</p>{brief.context && <span>{brief.context}</span>}</div>;
}

function summarizeGuidance(prompt: string | null | undefined) {
  const raw = prompt ?? "";
  const compact = raw.replaceAll("\n", " ").replace(/\s+/g, " ").trim();
  const control = raw.match(/(?:tried\s+(?:click\s+)?|click\s+)[“"]([^”"]+)[”"]\s+twice/i)?.[1];
  const page = raw.match(/(?:I am on|On)\s+[“"]?([^”"(\n.]+)[”"]?/i)?.[1]?.trim();
  const repeatedAction = /\btwice\b/i.test(raw);

  if (repeatedAction && control) {
    return {
      question: `“${control}” did not move the page forward. What should Loop try instead?`,
      context: `Tried twice${page ? ` on ${page}` : ""}.`,
    };
  }

  const storedQuestion = raw.match(/QUESTION\s*\n?([\s\S]*?)(?=\n\n(?:CONTEXT|WHAT LOOP OBSERVED|WHAT I NEED FROM YOU)|$)/i)?.[1]
    ?.replace(/\s+/g, " ").trim();
  return {
    question: storedQuestion || "What should Loop try next?",
    context: page ? `Current page: ${page}.` : compact ? "Loop needs a safe next step." : "",
  };
}

function EvidenceRow({ item }: { item: Evidence }) {
  const url = evidenceUrl(item.file_path);
  return <article className="evidence-row"><span>{item.evidence_type === "network_failure" ? "!" : "⌁"}</span><div><strong>{item.evidence_type.replaceAll("_", " ")}</strong>{url ? <a href={url} target="_blank" rel="noreferrer">Open capture ↗</a> : <p>{item.content}</p>}</div></article>;
}

function formatTime(value: string | null) { return value ? new Intl.DateTimeFormat("en-IN", { timeStyle: "medium" }).format(new Date(value)) : "—"; }
function shortGoal(goal: string) { return goal.length > 48 ? `${goal.slice(0, 48)}…` : goal; }
function isIssueAction(action: Action) { return ["action_error", "network_failure", "browser_error", "ux_issue", "functional_issue"].includes(action.action_type); }
function actionTone(action: Action) { return action.action_type === "ux_issue" || (action.action_type === "journey_complete" && hasFeedbackSummary(action.outcome)) ? "ux" : "error"; }
function hasFeedbackSummary(summary: string | null) { return Boolean(summary && (/^\s*1\)\s/.test(summary) || summary.length > 240)); }
function actionState(action: Action, isUxReview = false) { if (action.action_type === "ux_issue" || (isUxReview && action.action_type === "journey_complete" && hasFeedbackSummary(action.outcome))) return "ux"; if (isIssueAction(action)) return "error"; if (["agent_thinking", "agent_waiting", "agent_action_started", "user_input_required", "agent_guidance_required", "user_guidance_added"].includes(action.action_type)) return "thinking"; return "success"; }
function actionKindLabel(state: string) { return state === "ux" ? "UX" : state === "error" ? "ERROR" : state === "success" ? "DONE" : "LIVE"; }
function ReportMetric({ label, value, tone }: { label: string; value: number; tone: "good" | "bad" | "warning" | "neutral" }) { return <div className={`report-metric ${tone}`}><span>{label}</span><strong>{value}</strong></div>; }
