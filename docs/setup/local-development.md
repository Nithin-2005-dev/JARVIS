# Local Development

Requirements for the pinned Stage 10 toolchain: Python 3.12, Node.js 22, npm, and SQLite (bundled with Python). Install backend HTTP dependencies using a virtual environment and `python -m pip install -r requirements-stage9.txt`; install frontend dependencies with `cd frontend && npm ci`.

Set a development `JARVIS_DATABASE_URL=sqlite:///data/demo.sqlite` and `JARVIS_FRONTEND_ORIGINS=http://localhost:3000` in the backend terminal. Authentication is enabled by default. Generate deterministic records and provision an account using:

```bash
python scripts/demo_pipeline.py --database data/demo.sqlite --events data/demo_events.jsonl --reset
python -m payflow_simulator.http_api.auth_cli create-user --username admin --role admin
JARVIS_DATABASE_URL=sqlite:///data/demo.sqlite python -m uvicorn payflow_simulator.http_api.app:app --host 127.0.0.1 --port 8000
```

Run the frontend from another terminal with `cd frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev`. Development API docs are available at `http://localhost:8000/api/docs`. The API should remain bound to loopback; development defaults are not suitable for untrusted network exposure.
