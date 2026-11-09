# Demo Environment

## Docker Compose demo

Copy `.env.example` to a private `.env`, set a strong unique `JARVIS_SECRET_KEY`, and start the demo stack:

```bash
docker compose up --build -d
docker compose exec api python scripts/demo_pipeline.py --database /data/jarvis.sqlite --events /data/demo_events.jsonl --reset
docker compose exec api python -m payflow_simulator.http_api.auth_cli create-user --username admin --role admin
```

The dataset and database are written into the Compose named volume. `--reset` is scoped to `/data/jarvis.sqlite` inside this isolated demo volume; it is not a backup/restore procedure. The account CLI prompts for the password. The frontend is available at `http://localhost:3000`; API docs are disabled in demo mode. The API and frontend ports bind to host loopback.

## Host-process demo

To use local processes instead, generate data with the simulator pipeline, set `JARVIS_DATABASE_URL=sqlite:///data/demo.sqlite` and `JARVIS_FRONTEND_ORIGINS=http://localhost:3000`, create the user with the auth CLI, then run Uvicorn on loopback and the frontend with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`. The application uses actual persisted records and presents empty states when none exist.
