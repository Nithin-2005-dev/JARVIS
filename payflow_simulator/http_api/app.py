"""FastAPI boundary for the local J.A.R.V.I.S. Command Center."""
from __future__ import annotations

import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import JSONResponse

from .config import Settings, load_settings
from .security import AuthStore, initialize_database
from .service import DashboardService
from .schemas import IncidentDetailResponse, OverviewResponse, Page, Record, ServiceListResponse
from ..processing.logging_config import JSONLogFormatter

logger = logging.getLogger("jarvis.http_api")


class StatusUpdate(BaseModel):
    status: Literal["acknowledged", "in_progress", "completed", "dismissed", "superseded"]
    reason: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=4000)


class Feedback(BaseModel):
    outcome_status: Literal["successful", "unsuccessful", "inconclusive", "not_attempted"]
    observed_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    responder_notes: str = Field(default="", max_length=4000)
    actual_result: str = Field(default="", max_length=2000)
    related_incident_state: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["admin", "responder", "viewer"]


class UserUpdate(BaseModel):
    role: Literal["admin", "responder", "viewer"] | None = None
    active: bool | None = None


class FixedWindowLimiter:
    """Per-process rate limiter; intended for the documented single-instance deployment."""
    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self.hits) > 10000:
            for old in [k for k, values in self.hits.items() if not values or values[-1] <= now - self.window]:
                self.hits.pop(old, None)
        return True


class RequestSizeLimitMiddleware:
    """Enforce body limits while ASGI chunks arrive, including chunked requests."""
    def __init__(self, app, max_bytes: int): self.app, self.max_bytes = app, max_bytes
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send); return
        total = 0
        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    headers = dict(scope.get("headers", []))
                    request_id = headers.get(b"x-request-id", b"").decode("ascii", "ignore")
                    response = JSONResponse(status_code=413, content={"error":{"code":"request_too_large","message":"Request body exceeds the configured limit."}}, headers={"X-Request-ID":request_id} if request_id else None)
                    await response(scope, receive, send)
                    raise _RequestTooLarge
            return message
        try: await self.app(scope, limited_receive, send)
        except _RequestTooLarge: return


class _RequestTooLarge(Exception): pass


def create_app(database: str | None = None, *, allowed_origins: list[str] | None = None,
               auth_enabled: bool | None = None, settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    db_path = database or config.database_path
    # An explicit database path is the established test factory interface. The deployed
    # module-level app uses validated settings and keeps auth enabled by default.
    auth_on = (auth_enabled if auth_enabled is not None else (False if database is not None else config.auth_enabled))
    origins = tuple(x.rstrip("/") for x in (allowed_origins if allowed_origins is not None else config.frontend_origins))
    docs_enabled = config.environment in {"development", "testing"}
    app = FastAPI(title="J.A.R.V.I.S. Command Center API", version="1.0.0",
                  docs_url="/api/docs" if docs_enabled else None,
                  redoc_url="/api/redoc" if docs_enabled else None,
                  openapi_url="/api/openapi.json" if docs_enabled else None)
    initialize_database(db_path)
    auth_store = AuthStore(db_path)
    service = DashboardService(db_path)
    signer = URLSafeTimedSerializer(config.secret_key, salt="jarvis-command-center-session-v1")
    limiter = FixedWindowLimiter(config.rate_limit_per_minute)
    metrics: dict[str, Any] = {"requests_total":0,"errors_total":0,"latency_ms":deque(maxlen=2048)}
    _configure_logging(config)
    app.state.settings = config
    app.state.auth_enabled = auth_on
    app.state.dashboard_service = service
    app.state.metrics = metrics
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=config.max_request_bytes)

    @app.middleware("http")
    async def secure_requests(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "")
        if not request_id or len(request_id) > 100 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in request_id):
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.user = None
        path = request.url.path
        method = request.method.upper()
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > config.max_request_bytes:
                    from starlette.responses import JSONResponse
                    response = JSONResponse(status_code=413, content={"error":{"code":"request_too_large","message":"Request body exceeds the configured limit."}})
                    response.headers["X-Request-ID"] = request_id
                    return _secure_headers(response, request_id, secure=config.production)
            except ValueError:
                from starlette.responses import JSONResponse
                return _secure_headers(JSONResponse(status_code=400, content={"error":{"code":"invalid_content_length","message":"Invalid request length."}}), request_id, secure=config.production)
        open_paths = {"/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready", "/api/v1/auth/login", "/api/v1/auth/csrf"}
        exempt = method == "OPTIONS" or path in open_paths or path.startswith("/api/docs") or path.startswith("/api/openapi") or path.startswith("/api/redoc")
        user = None
        cookie = request.cookies.get("jarvis_session")
        if auth_on and cookie:
            try:
                payload = signer.loads(cookie, max_age=config.session_ttl_seconds)
                user = auth_store.get_user(str(payload.get("sub", "")))
                if user and not user["active"]: user = None
            except (BadSignature, SignatureExpired, ValueError, TypeError):
                user = None
        elif not auth_on:
            user = {"user_id":"local", "username":"local-demo", "role":"admin", "active":1}
        request.state.user = user

        client = request.client.host if request.client else "unknown"
        sensitive = (path == "/api/v1/auth/login" or path.startswith("/api/v1/recommendations/") and method in {"PATCH", "POST"})
        if sensitive and not limiter.allow(f"{client}:{path.split('/')[-1]}"):
            from starlette.responses import JSONResponse
            response = JSONResponse(status_code=429, headers={"Retry-After":"60"}, content={"error":{"code":"rate_limited","message":"Too many requests. Try again later."}})
            response.headers["X-Request-ID"] = request_id
            return _secure_headers(response, request_id, secure=config.production)

        if auth_on and not exempt:
            if user is None:
                from starlette.responses import JSONResponse
                response = JSONResponse(status_code=401, headers={"WWW-Authenticate":"Session"}, content={"error":{"code":"authentication_required","message":"Sign in to access this resource."}})
                return _secure_headers(response, request_id, secure=config.production)
            if method in {"POST", "PATCH", "PUT", "DELETE"}:
                origin = request.headers.get("origin", "").rstrip("/")
                csrf_cookie = request.cookies.get("jarvis_csrf", "")
                csrf_header = request.headers.get("x-csrf-token", "")
                import hmac
                if origin not in origins or not csrf_cookie or not hmac.compare_digest(csrf_cookie, csrf_header):
                    from starlette.responses import JSONResponse
                    response = JSONResponse(status_code=403, content={"error":{"code":"csrf_rejected","message":"Request origin or CSRF token was rejected."}})
                    return _secure_headers(response, request_id, secure=config.production)
            role = user["role"]
            if path.startswith("/api/v1/admin/") and role != "admin":
                auth_store.audit("authorization_denied", username=user["username"], role=role, request_id=request_id, details={"path":path})
                logger.warning("authorization_denied", extra={"request_id":request_id,"role":role,"path":path})
                from starlette.responses import JSONResponse
                response = JSONResponse(status_code=403, content={"error":{"code":"forbidden","message":"Administrator role is required."}})
                return _secure_headers(response, request_id, secure=config.production)
            if (path.startswith("/api/v1/recommendations/") and method in {"PATCH", "POST"}) and role == "viewer":
                auth_store.audit("authorization_denied", username=user["username"], role=role, request_id=request_id, details={"path":path})
                logger.warning("authorization_denied", extra={"request_id":request_id,"role":role,"path":path})
                from starlette.responses import JSONResponse
                response = JSONResponse(status_code=403, content={"error":{"code":"forbidden","message":"This role cannot change recommendation state."}})
                return _secure_headers(response, request_id, secure=config.production)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            raise
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter()-started)*1000:.2f}"
        duration = (time.perf_counter()-started)*1000
        metrics["requests_total"] += 1
        metrics["errors_total"] += int(response.status_code >= 500)
        metrics["latency_ms"].append(duration)
        if path.startswith("/api/v1/"):
            logger.info("api_request", extra={"request_id":request_id,"method":method,"path":path,"status_code":response.status_code,"duration_ms":round((time.perf_counter()-started)*1000,2),"role":(user or {}).get("role")})
        response = _secure_headers(response, request_id, secure=config.production)
        return response

    # Add CORS after the auth middleware so it wraps early 401/403/413 responses too.
    app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_methods=["GET", "PATCH", "POST", "PUT", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"], allow_credentials=True)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled API error", extra={"request_id":getattr(request.state,"request_id",None),"path":request.url.path})
        response = __import__("fastapi").responses.JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "The request could not be completed."}})
        return _secure_headers(response, getattr(request.state,"request_id",None), secure=config.production)

    def missing(kind: str, identifier: str):
        raise HTTPException(404, detail={"code": "not_found", "message": f"{kind} '{identifier}' was not found."})

    @app.get("/api/v1/auth/csrf")
    def csrf_token(response: Response):
        token = secrets.token_urlsafe(32)
        response.set_cookie("jarvis_csrf", token, httponly=False, secure=config.production, samesite="strict", path="/", max_age=config.session_ttl_seconds)
        return {"csrf_token": token}

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        origin = request.headers.get("origin", "").rstrip("/")
        if origin and origin not in origins:
            auth_store.audit("login_origin_denied", username=None, role=None, request_id=request.state.request_id)
            raise HTTPException(403, detail={"code":"origin_rejected","message":"Request origin is not allowed."})
        csrf_cookie = request.cookies.get("jarvis_csrf", "")
        csrf_header = request.headers.get("x-csrf-token", "")
        import hmac
        if not csrf_cookie or not hmac.compare_digest(csrf_cookie, csrf_header):
            auth_store.audit("login_csrf_denied", username=None, role=None, request_id=request.state.request_id)
            raise HTTPException(403, detail={"code":"csrf_rejected","message":"Fetch a CSRF token before signing in."})
        user = auth_store.verify(payload.username, payload.password)
        if user is None:
            auth_store.audit("login_failed", username=payload.username[:80], role=None, request_id=request.state.request_id)
            logger.warning("authentication_failed", extra={"request_id":request.state.request_id,"username":payload.username[:80]})
            raise HTTPException(401, detail={"code":"invalid_credentials","message":"Username or password is incorrect."})
        session = signer.dumps({"sub":user["user_id"], "iat":int(time.time())})
        response.set_cookie("jarvis_session", session, httponly=True, secure=config.production, samesite="strict", path="/", max_age=config.session_ttl_seconds)
        response.set_cookie("jarvis_csrf", csrf_cookie, httponly=False, secure=config.production, samesite="strict", path="/", max_age=config.session_ttl_seconds)
        auth_store.audit("login_succeeded", username=user["username"], role=user["role"], request_id=request.state.request_id)
        return {"user":{"user_id":user["user_id"],"username":user["username"],"role":user["role"]},"expires_in":config.session_ttl_seconds}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response):
        user = request.state.user or {}
        if auth_on and user.get("user_id"):
            auth_store.audit("logout", username=user.get("username"), role=user.get("role"), request_id=request.state.request_id)
        response.delete_cookie("jarvis_session", path="/", secure=config.production, httponly=True, samesite="strict")
        response.delete_cookie("jarvis_csrf", path="/", secure=config.production, httponly=False, samesite="strict")
        return {"status":"logged_out"}

    @app.get("/api/v1/auth/me")
    def current_user(request: Request):
        user = request.state.user
        if user is None:
            raise HTTPException(401, detail={"code":"authentication_required","message":"Sign in to access this resource."})
        return {"authenticated":True,"auth_enabled":auth_on,"user":{"user_id":user["user_id"],"username":user["username"],"role":user["role"]}}

    @app.get("/api/v1/admin/users")
    def list_users():
        return {"items":auth_store.list_users()}

    @app.post("/api/v1/admin/users", status_code=201)
    def create_user(payload: UserCreate, request: Request):
        try:
            user = auth_store.create_user(payload.username, payload.password, payload.role)
        except ValueError as exc:
            raise HTTPException(409, detail={"code":"user_conflict","message":str(exc)}) from exc
        auth_store.audit("user_created", username=payload.username, role=payload.role, request_id=request.state.request_id)
        user.pop("password_hash", None)
        return user

    @app.patch("/api/v1/admin/users/{user_id}")
    def update_user(user_id: str, payload: UserUpdate, request: Request):
        try: user = auth_store.set_user(user_id, role=payload.role, active=payload.active)
        except ValueError as exc: raise HTTPException(422, detail={"code":"invalid_user_update","message":str(exc)}) from exc
        if user is None: missing("user", user_id)
        auth_store.audit("user_updated", username=user["username"], role=user["role"], request_id=request.state.request_id,
                         details={"changed_role":payload.role is not None,"changed_active":payload.active is not None})
        return user

    @app.get("/api/v1/health/live")
    @app.get("/api/v1/health")
    def health(): return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    def readiness():
        try:
            import sqlite3
            db = sqlite3.connect(db_path, timeout=1)
            db.execute("SELECT 1").fetchone()
            db.close()
            return {"status":"ready"}
        except Exception:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=503, content={"status":"not_ready"})

    @app.get("/api/v1/admin/metrics")
    def operational_metrics():
        samples=sorted(metrics["latency_ms"])
        def percentile(p:float)->float|None:
            if not samples:return None
            return round(samples[min(len(samples)-1,int((len(samples)-1)*p))],2)
        return {"requests_total":metrics["requests_total"],"server_errors_total":metrics["errors_total"],
                "latency_sample_count":len(samples),"latency_ms":{"p50":percentile(.50),"p95":percentile(.95)},
                "note":"In-process measurements; reset on restart and not a distributed metrics backend."}

    @app.get("/api/v1/overview", response_model=OverviewResponse)
    def overview(): return service.overview()

    @app.get("/api/v1/incidents", response_model=Page[Record])
    def incidents(status: str | None = None, severity: str | None = None, service_id: str | None = None,
                  search: str | None = Query(default=None, max_length=200), sort: Literal["activity", "severity"] = "activity",
                  start_time: datetime | None = None, end_time: datetime | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        rows = service.incidents(status=status)
        if severity: rows = [x for x in rows if str(x.get("severity", "")).lower() == severity.lower()]
        if service_id: rows = [x for x in rows if service_id in _incident_service_ids(service, x["incident_id"])]
        if search: rows = [x for x in rows if search.lower() in str(x.get("summary", "")).lower() or search.lower() in x["incident_id"].lower()]
        if start_time: rows = [x for x in rows if _time_in_range(x.get("first_observed_at"), start_time, lower=True)]
        if end_time: rows = [x for x in rows if _time_in_range(x.get("last_observed_at"), end_time, lower=False)]
        ranks = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        if sort == "severity": rows.sort(key=lambda x: (ranks.get(str(x.get("severity", "unknown")).lower(), 4), x.get("updated_at", "")))
        else: rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "page": page, "page_size": page_size, "total": len(rows)}

    @app.get("/api/v1/incidents/{incident_id}", response_model=IncidentDetailResponse)
    def incident(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return result

    @app.get("/api/v1/incidents/{incident_id}/events")
    def incident_events(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["events"], "correlation_evidence": result["correlation_evidence"]}

    @app.get("/api/v1/incidents/{incident_id}/rca")
    def incident_rca(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"report": result["rca"]}

    @app.get("/api/v1/incidents/{incident_id}/blast-radius")
    def incident_blast_radius(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["blast_radius"]}

    @app.get("/api/v1/incidents/{incident_id}/intelligence")
    def incident_intelligence(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["intelligence"]}

    @app.get("/api/v1/incidents/{incident_id}/recommendations")
    def incident_recommendations(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["recommendations"]}

    @app.get("/api/v1/services", response_model=ServiceListResponse)
    def services():
        items = service.services()
        return {"items": items, "total": len(items), "service_health_available": False}

    @app.get("/api/v1/services/{service_id}")
    def service_detail(service_id: str):
        result = service.service(service_id)
        if result is None: missing("service", service_id)
        return result

    @app.get("/api/v1/services/{service_id}/dependencies")
    def service_dependencies(service_id: str):
        result = service.service(service_id)
        if result is None: missing("service", service_id)
        return {"incoming": result["incoming_dependencies"], "outgoing": result["outgoing_dependencies"], "direction": "A -> B means A depends on B"}

    @app.get("/api/v1/services/{service_id}/recommendations")
    def service_recommendations(service_id: str):
        result = service.service(service_id)
        if result is None: missing("service", service_id)
        return {"items": result["recommendations"]}

    @app.get("/api/v1/intelligence/findings")
    def findings(limit: int = Query(100, ge=1, le=500), service_id: str | None = None, finding_type: str | None = None):
        rows = service.findings(limit=limit)
        if service_id: rows = [x for x in rows if service_id in x.get("affected_service_ids", [])]
        if finding_type: rows = [x for x in rows if x.get("finding_type") == finding_type]
        return {"items": rows, "total": len(rows)}

    @app.get("/api/v1/intelligence/findings/{finding_id}")
    def finding(finding_id: str):
        result = service.finding(finding_id)
        if result is None: missing("finding", finding_id)
        return result

    @app.get("/api/v1/recommendations")
    def recommendations(status: str | None = None, category: str | None = None, priority: str | None = None,
                        risk: str | None = None, service_id: str | None = None, incident_id: str | None = None,
                        limit: int = Query(100, ge=1, le=500)):
        rows = service.recommendations(status=status, service_id=service_id, incident_id=incident_id, limit=limit)
        for field, value in (("recommendation_type", category), ("priority", priority), ("risk_level", risk)):
            if value: rows = [x for x in rows if x.get(field) == value]
        return {"items": rows, "total": len(rows)}

    @app.get("/api/v1/recommendations/{recommendation_id}")
    def recommendation(recommendation_id: str):
        result = service.recommendation(recommendation_id)
        if result is None: missing("recommendation", recommendation_id)
        return {"recommendation": result, "history": service.recommendation_history(recommendation_id)}

    @app.patch("/api/v1/recommendations/{recommendation_id}/status")
    def update_status(recommendation_id: str, payload: StatusUpdate):
        try: return service.update_recommendation(recommendation_id, payload.status, payload.reason, payload.notes)
        except KeyError: missing("recommendation", recommendation_id)
        except ValueError as exc: raise HTTPException(409, detail={"code": "invalid_transition", "message": str(exc)}) from exc

    @app.post("/api/v1/recommendations/{recommendation_id}/feedback", status_code=201)
    def feedback(recommendation_id: str, payload: Feedback):
        data = payload.model_dump() | {"recommendation_id": recommendation_id}
        try: return service.feedback(data)
        except KeyError: missing("recommendation", recommendation_id)

    @app.get("/api/v1/history")
    def history(limit: int = Query(100, ge=1, le=500)): return service.history(limit)

    return app


def _secure_headers(response: Response, request_id: str | None = None, *, secure: bool = False):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if secure: response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request_id: response.headers.setdefault("X-Request-ID", request_id)
    return response


def _configure_logging(config: Settings) -> None:
    root = logging.getLogger()
    deployment = config.environment in {"demo", "production"}
    if not root.handlers:
        handler=logging.StreamHandler()
        root.addHandler(handler)
    formatter = (JSONLogFormatter() if deployment else
                 logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for handler in root.handlers:
        handler.setFormatter(formatter)
    root.setLevel(getattr(logging,config.log_level,logging.INFO))


def _incident_service_ids(service: DashboardService, incident_id: str) -> set[str]:
    value = service.incident(incident_id)
    return {str((e.get("original_event") or e).get("service") or e.get("service_id")) for e in (value or {}).get("events", [])}


def _time_in_range(value: str | None, bound: datetime, *, lower: bool) -> bool:
    if not value: return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None: observed = observed.replace(tzinfo=timezone.utc)
        if bound.tzinfo is None: bound = bound.replace(tzinfo=timezone.utc)
        return observed >= bound if lower else observed <= bound
    except ValueError:
        return False


app = create_app()
