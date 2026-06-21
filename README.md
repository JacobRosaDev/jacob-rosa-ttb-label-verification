# TTB Label Verification — Phase 0

A minimal FastAPI backend serving a static frontend and a `/health` endpoint.

## Local run

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install uv
uv sync
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your browser. The page fetches `/health` and displays the backend response.

## Render deployment

1. Push the repository to GitHub.
2. In Render, create a new **Web Service**.
3. Connect the repo and choose the `main` branch.
4. Set the **Root Directory** to `backend`.
5. Use this build command:

```bash
pip install --upgrade pip && pip install uv && uv sync
```

6. Use this start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

7. Deploy. Render will provide a public URL such as `https://<service-name>.onrender.com`.

## Notes

- Do not commit `.env`; only `.env.example` is checked in.
- `uv sync` reads `pyproject.toml` and installs dependencies in a local `.venv`.
- The frontend is served from the same FastAPI service, so no CORS configuration is needed for Phase 0.
