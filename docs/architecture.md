# Loop MVP architecture

Next.js provides the dashboard. FastAPI orchestrates agent runs, stores evidence, and coordinates Playwright with the AI decision maker. The browser agent can test a configured product URL that the user is allowed to audit.

## Current backend API

| Resource | Endpoint | Purpose |
| --- | --- | --- |
| Health | `GET /health` | Confirm the API is running. |
| Applications | `POST /api/applications` | Register a target application. |
| Applications | `GET /api/applications` | List registered applications. |
| Journeys | `POST /api/applications/{id}/journeys` | Create a goal-driven journey. |
| Runs | `POST /api/journeys/{id}/runs` | Start a journey run. |
| Runs | `GET /api/journeys/{id}/runs` | List a journey's previous test sessions. |
| Run control | `POST /api/runs/{id}/stop` | Stop an active test while retaining its evidence. |
| Run data | `GET /api/runs/{id}/actions` | Read the action timeline. |
| Evidence | `GET /api/runs/{id}/evidence` | Read screenshots and user-impacting diagnostics. |

For implementation and setup details, see the repository README.
