# Loop MVP architecture

Next.js provides the dashboard. FastAPI orchestrates agent runs, stores evidence, and later connects to Playwright and the AI model. The browser agent will test a separate DemoShop application.

## Current backend API

| Resource | Endpoint | Purpose |
| --- | --- | --- |
| Health | `GET /health` | Confirm the API is running. |
| Applications | `POST /api/applications` | Register a target application. |
| Applications | `GET /api/applications` | List registered applications. |
| Journeys | `POST /api/applications/{id}/journeys` | Create a goal-driven journey. |
| Runs | `POST /api/journeys/{id}/runs` | Start a journey run. |
| Timeline | `POST /api/runs/{id}/actions` | Record an action in the run timeline. |

Playwright, evidence collection, issue detection, and the AI agent are intentionally deferred until this core lifecycle is stable.
