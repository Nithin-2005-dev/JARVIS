# J.A.R.V.I.S. — Stages 1–10

J.A.R.V.I.S. combines a deterministic PayFlow simulator, multi-source ingestion, event processing, explainable correlation, evidence-based RCA, service dependency/blast-radius analysis, anomaly intelligence, responder recommendations, and a web Command Center. Python 3.12 and Node 22 are the verified Stage 10 toolchain. Analysis outputs remain heuristics and evidence; correlation and dependency do not establish causation.

## Run the stages

```bash
python3 -m pip install -r requirements-stage9.txt
python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl
python3 -m payflow_simulator.ingest_cli --source json --input data/sample_events.jsonl
python3 -m payflow_simulator.process_cli --database data/events.sqlite
python3 -m unittest discover -s tests -v
```

See the stage-specific architecture and CLI documentation under `docs/`.

## Authenticated Command Center

Copy `.env.example` to a private `.env`, set a strong random `JARVIS_SECRET_KEY`, then start the local demo stack and populate its persistent database:

```bash
docker compose up --build -d
docker compose exec api python scripts/demo_pipeline.py --database /data/jarvis.sqlite --events /data/demo_events.jsonl --reset
docker compose exec api python -m payflow_simulator.http_api.auth_cli create-user --username admin --role admin
```

The account command prompts for a password and stores only an Argon2id hash. The API requires authentication by default. Use responder/viewer accounts for least privilege. For an HTTPS single-host deployment, configure `JARVIS_DOMAIN` and `JARVIS_FRONTEND_ORIGINS=https://your-domain`, then use `docker compose -f compose.yaml -f compose.production.yaml up --build -d`. Never expose the development configuration directly to the internet.

Backup commands and isolated restore instructions are in `docs/operations/backup-recovery.md`. Configuration is documented in `docs/setup/configuration-reference.md`.

## Verification

```bash
python -m unittest discover -s tests -v
cd frontend
npm ci
npm run test
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

`npm run test:e2e` requires a running API/frontend and real seeded demo DB. Root CI workflows run pinned backend/frontend checks. Release deployment is currently single-host SQLite; see [known limitations](docs/troubleshooting/known-issues.md), [production architecture](docs/architecture/production-architecture.md), and the [Stage 10 report](docs/milestones/milestone-10.md).
