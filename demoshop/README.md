# DemoShop

DemoShop is the deliberately imperfect target application used by Loop's demo.

## Run locally

```bash
npm install
npm run dev
```

It starts at `http://localhost:3001`.

## Seeded defects

1. `POST /api/checkout` waits three seconds and returns HTTP 500.
2. The checkout UI provides no loading indicator while that request is pending.

Loop should discover the functional failure, capture its evidence, and flag the lack of feedback as a UX issue.
