export type Application = { id: string; name: string; target_url: string; repository_url: string | null; repository_branch: string; created_at: string };
export type Journey = { id: string; application_id: string; name: string; goal: string; persona: string; created_at: string };
export type Run = { id: string; journey_id: string; status: "queued" | "running" | "awaiting_user" | "completed_with_issues" | "stopped" | "passed" | "failed"; started_at: string | null; completed_at: string | null; created_at: string };
export type Action = { id: string; run_id: string; action_type: string; target: string | null; outcome: string | null; created_at: string };
export type Evidence = { id: string; run_id: string; evidence_type: "screenshot" | "console_error" | "network_failure" | "browser_error"; content: string | null; file_path: string | null; created_at: string };

const apiBaseUrl = process.env.NEXT_PUBLIC_LOOP_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}/api${path}`, { ...options, headers: { "Content-Type": "application/json", ...options?.headers } });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}.`);
  }
  return response.json() as Promise<T>;
}

export const loopApi = {
  listApplications: () => request<Application[]>("/applications"),
  createApplication: (payload: Omit<Application, "id" | "created_at">) => request<Application>("/applications", { method: "POST", body: JSON.stringify(payload) }),
  updateApplication: (applicationId: string, payload: Omit<Application, "id" | "created_at">) => request<Application>(`/applications/${applicationId}`, { method: "PUT", body: JSON.stringify(payload) }),
  listJourneys: (applicationId: string) => request<Journey[]>(`/applications/${applicationId}/journeys`),
  createJourney: (applicationId: string, payload: Pick<Journey, "name" | "goal" | "persona">) => request<Journey>(`/applications/${applicationId}/journeys`, { method: "POST", body: JSON.stringify(payload) }),
  listRuns: (journeyId: string) => request<Run[]>(`/journeys/${journeyId}/runs`),
  startRun: (journeyId: string) => request<Run>(`/journeys/${journeyId}/runs`, { method: "POST" }),
  executeRun: (runId: string) => request<Run>(`/runs/${runId}/execute`, { method: "POST" }),
  resumeRun: (runId: string, resolution: "continue" | "finish", guidance?: string) => request<Run>(`/runs/${runId}/resume`, { method: "POST", body: JSON.stringify({ resolution, guidance: guidance || null }) }),
  stopRun: (runId: string) => request<Run>(`/runs/${runId}/stop`, { method: "POST" }),
  getRun: (runId: string) => request<Run>(`/runs/${runId}`),
  listActions: (runId: string) => request<Action[]>(`/runs/${runId}/actions`),
  listEvidence: (runId: string) => request<Evidence[]>(`/runs/${runId}/evidence`),
};

export function evidenceUrl(filePath: string | null): string | null {
  if (!filePath) return null;
  const path = filePath.replaceAll("\\", "/");
  const storageIndex = path.indexOf("storage/");
  return storageIndex === -1 ? null : `${apiBaseUrl}/${path.slice(storageIndex)}`;
}
