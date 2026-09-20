# Loop

Loop is an AI user that discovers web-application issues, provides evidence for a fix, and re-runs the user journey to verify the result.

## Local development

### Frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`.

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the API documentation.
