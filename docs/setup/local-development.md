# Local development

Requirements: Python 3.10+, Node.js 18+, npm, and SQLite (bundled with Python). Install backend HTTP requirements into a virtual environment with `python -m pip install -r requirements-stage9.txt`. Install frontend dependencies with `cd frontend && npm install`.

Run backend from the repository root: `JARVIS_DATABASE=data/demo.sqlite python -m uvicorn payflow_simulator.http_api.app:app --host 127.0.0.1 --port 8000`. Run frontend in another terminal: `cd frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev`. The API docs are at `http://localhost:8000/api/docs`.

The local demo has no authentication. The default API binds to loopback and permits the local frontend origin. Do not expose it to an untrusted network without adding authentication and a deployment security review.
