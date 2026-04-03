from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request as FastAPIRequest, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from ..config import AppSettings, load_app_settings
from .db import PortalUser, build_session_factory
from .service import (
    TeamFormPayload,
    approve_submission,
    get_registrations_open,
    get_submission_by_id,
    get_team_by_id,
    get_dashboard_payload,
    get_or_create_portal_user,
    list_approved_teams,
    list_pending_submissions,
    reject_submission,
    save_logo_upload,
    set_registrations_open,
    serialize_team,
    serialize_submission,
    upsert_team_submission,
)


def _friendly_datetime(value: str | None) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return "-"
    try:
        timestamp = raw_value.replace("Z", "+00:00")
        parsed = __import__("datetime").datetime.fromisoformat(timestamp)
    except ValueError:
        return raw_value
    return parsed.strftime("%d/%m/%Y %H:%M")


def create_portal_app(base_path: Path | None = None) -> FastAPI:
    settings = load_app_settings(base_path)
    session_factory = build_session_factory(settings)
    templates_dir = Path(__file__).resolve().parent / "templates"
    static_dir = Path(__file__).resolve().parent / "static"

    app = FastAPI(title=settings.site.title)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.portal.session_secret or "change-me-session-secret",
        same_site="lax",
        https_only=settings.portal.base_url.startswith("https://"),
        max_age=60 * 60 * settings.portal.session_max_age_hours,
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    templates = Jinja2Templates(directory=str(templates_dir))
    templates.env.filters["friendly_datetime"] = _friendly_datetime
    oauth = OAuth()

    if settings.portal.discord_client_id and settings.portal.discord_client_secret:
        oauth.register(
            name="discord",
            client_id=settings.portal.discord_client_id,
            client_secret=settings.portal.discord_client_secret,
            access_token_url="https://discord.com/api/oauth2/token",
            authorize_url="https://discord.com/api/oauth2/authorize",
            api_base_url="https://discord.com/api/",
            client_kwargs={"scope": "identify"},
        )

    def get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def require_admin(request: FastAPIRequest) -> None:
        token = request.headers.get("X-Admin-Token", "").strip()
        if token != settings.portal.admin_token:
            raise HTTPException(status_code=401, detail="Token administrativo invalido.")

    def get_current_user(request: FastAPIRequest, session: Session) -> PortalUser:
        user_id = request.session.get("portal_user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Sessao expirada.")
        user = session.get(PortalUser, int(user_id))
        if user is None:
            request.session.clear()
            raise HTTPException(status_code=401, detail="Usuario nao encontrado.")
        request.session["portal_session_last_seen"] = datetime.now(UTC).isoformat()
        return user

    def build_template_context(request: FastAPIRequest, extra: dict | None = None) -> dict:
        context = {
            "request": request,
            "site": {
                "title": settings.site.title,
                "headline": settings.site.headline,
                "subheadline": settings.site.subheadline,
                "login_eyebrow": settings.site.login_eyebrow,
                "login_title": settings.site.login_title,
                "login_welcome_title": settings.site.login_welcome_title,
                "login_welcome_text": settings.site.login_welcome_text,
                "login_button_label": settings.site.login_button_label,
                "login_help_text": settings.site.login_help_text,
                "discord_missing_message": settings.site.discord_missing_message,
                "dashboard_eyebrow": settings.site.dashboard_eyebrow,
                "dashboard_title": settings.site.dashboard_title,
                "dashboard_subtitle": settings.site.dashboard_subtitle,
                "discord_notice_kicker": settings.site.discord_notice_kicker,
                "discord_notice_title": settings.site.discord_notice_title,
                "discord_notice_text": settings.site.discord_notice_text,
                "discord_notice_link_label": settings.site.discord_notice_link_label,
                "discord_notice_link_url": settings.site.discord_notice_link_url,
                "dashboard_form_title_new": settings.site.dashboard_form_title_new,
                "dashboard_form_title_edit": settings.site.dashboard_form_title_edit,
                "dashboard_form_helper_text": settings.site.dashboard_form_helper_text,
                "dashboard_submit_label": settings.site.dashboard_submit_label,
                "dashboard_success_message": settings.site.dashboard_success_message,
                "registrations_closed_title": settings.site.registrations_closed_title,
                "registrations_closed_text": settings.site.registrations_closed_text,
                "terms_label": settings.site.terms_label,
                "terms_modal_kicker": settings.site.terms_modal_kicker,
                "terms_modal_title": settings.site.terms_modal_title,
                "terms_scroll_hint": settings.site.terms_scroll_hint,
                "terms_sections": settings.site.terms_sections,
                "footer_items": settings.site.footer_items,
            },
            "turnstile_site_key": settings.portal.turnstile_site_key,
            "discord_enabled": bool(settings.portal.discord_client_id and settings.portal.discord_client_secret),
            "captcha_enabled": bool(settings.portal.turnstile_site_key and settings.portal.turnstile_secret_key),
            "brand_logo_url": "/brand/logo",
        }
        if extra:
            context.update(extra)
        return context

    def set_login_message(request: FastAPIRequest, message: str, message_type: str = "info") -> None:
        request.session["portal_login_message"] = message
        request.session["portal_login_message_type"] = message_type

    def clear_oauth_state(request: FastAPIRequest) -> None:
        for key in list(request.session.keys()):
            if key.startswith("_state_"):
                request.session.pop(key, None)

    def verify_turnstile(token: str) -> bool:
        if not settings.portal.turnstile_secret_key:
            return True
        payload = urlencode({
            "secret": settings.portal.turnstile_secret_key,
            "response": token,
        }).encode("utf-8")
        request = Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=10.0) as response:
            result = json.loads(response.read().decode("utf-8"))
        return bool(result.get("success"))

    @app.get("/", response_class=HTMLResponse)
    async def home(request: FastAPIRequest):
        if request.session.get("portal_user_id"):
            return RedirectResponse(url="/portal", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=build_template_context(
                request,
                {
                    "message": request.session.pop("portal_login_message", ""),
                    "message_type": request.session.pop("portal_login_message_type", "info"),
                },
            ),
        )

    @app.post("/auth/captcha")
    async def auth_captcha(
        request: FastAPIRequest,
        cf_turnstile_response: str = Form(default="", alias="cf-turnstile-response"),
    ):
        if settings.portal.turnstile_secret_key and not verify_turnstile(cf_turnstile_response):
            set_login_message(request, "Não foi possível validar o captcha. Resolva novamente e tente entrar de novo.", "error")
            return RedirectResponse(url="/", status_code=303)
        request.session["captcha_ok"] = True
        return RedirectResponse(url="/auth/discord", status_code=303)

    @app.get("/auth/discord")
    async def auth_discord(request: FastAPIRequest):
        if settings.portal.turnstile_secret_key and not request.session.get("captcha_ok"):
            set_login_message(request, "Resolva o captcha antes de entrar, se solicitado.", "info")
            return RedirectResponse(url="/", status_code=303)
        discord_client = oauth.create_client("discord")
        if discord_client is None:
            set_login_message(request, "O login com Discord não está configurado no momento.", "error")
            return RedirectResponse(url="/", status_code=303)
        clear_oauth_state(request)
        redirect_uri = settings.portal.discord_redirect_uri or f"{settings.portal.base_url}/auth/discord/callback"
        return await discord_client.authorize_redirect(request, redirect_uri)

    @app.get("/auth/discord/callback")
    async def auth_discord_callback(request: FastAPIRequest, session: Session = Depends(get_db)):
        discord_client = oauth.create_client("discord")
        if discord_client is None:
            set_login_message(request, "O login com Discord não está configurado no momento.", "error")
            return RedirectResponse(url="/", status_code=303)
        try:
            token = await discord_client.authorize_access_token(request)
        except MismatchingStateError:
            clear_oauth_state(request)
            request.session.pop("captcha_ok", None)
            set_login_message(request, "A sessão de login expirou ou ficou inconsistente. Resolva o captcha novamente e tente entrar de novo.", "error")
            return RedirectResponse(url="/", status_code=303)
        response = await discord_client.get("users/@me", token=token)
        profile = response.json()
        user = get_or_create_portal_user(session, profile)
        request.session["portal_user_id"] = user.id
        request.session.pop("captcha_ok", None)
        clear_oauth_state(request)
        return RedirectResponse(url="/portal", status_code=303)

    @app.get("/logout")
    async def logout(request: FastAPIRequest):
        request.session.clear()
        return RedirectResponse(url="/", status_code=303)

    @app.get("/portal", response_class=HTMLResponse)
    async def portal_dashboard(request: FastAPIRequest, session: Session = Depends(get_db)):
        try:
            user = get_current_user(request, session)
        except HTTPException:
            return RedirectResponse(url="/", status_code=303)

        dashboard = get_dashboard_payload(session, settings, user)
        registrations_open = get_registrations_open(session)
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=build_template_context(
                request,
                {
                    "user": user,
                    "dashboard": dashboard,
                    "registrations_open": registrations_open,
                    "success_message": request.session.pop("portal_success_message", ""),
                    "error_message": request.session.pop("portal_error_message", ""),
                },
            ),
        )

    @app.post("/portal/team")
    async def submit_team(
        request: FastAPIRequest,
        name: str = Form(...),
        coach: str = Form(...),
        captain: str = Form(...),
        player_two: str = Form(...),
        player_three: str = Form(...),
        player_four: str = Form(...),
        player_five: str = Form(...),
        accept_terms: str = Form(default=""),
        logo: UploadFile = File(...),
        session: Session = Depends(get_db),
    ):
        try:
            user = get_current_user(request, session)
        except HTTPException:
            return RedirectResponse(url="/", status_code=303)

        try:
            logo_filename = save_logo_upload(settings, logo)
            payload = TeamFormPayload(
                name=name,
                coach=coach,
                players=[captain, player_two, player_three, player_four, player_five],
                terms_accepted=bool(accept_terms),
            )
            upsert_team_submission(session, settings, user, payload, logo_filename)
        except HTTPException as exc:
            request.session["portal_error_message"] = str(exc.detail)
            return RedirectResponse(url="/portal", status_code=303)

        request.session["portal_success_message"] = settings.site.dashboard_success_message
        return RedirectResponse(url="/portal", status_code=303)

    @app.get("/times/{team_id}", response_class=HTMLResponse)
    async def public_team_view(team_id: int, request: FastAPIRequest, session: Session = Depends(get_db)):
        team = get_team_by_id(session, team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="Time nao encontrado.")
        return templates.TemplateResponse(
            request=request,
            name="team_public.html",
            context=build_template_context(
                request,
                {
                    "team_page_title": team.name,
                    "team_page_status": "Time visivel no portal",
                    "team_page_status_class": "approved",
                    "team_page_description": "Este e o time atualmente aprovado e visivel no portal do campeonato.",
                    "team_payload": serialize_team(settings, team),
                    "team_review_notes": "",
                },
            ),
        )

    @app.get("/envios/{submission_id}", response_class=HTMLResponse)
    async def public_submission_view(submission_id: int, request: FastAPIRequest, session: Session = Depends(get_db)):
        submission = get_submission_by_id(session, submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="Envio nao encontrado.")
        status_map = {
            "pending": ("Envio em analise", "pending", "Este envio ainda esta aguardando a revisao da producao."),
            "approved": ("Envio aprovado", "approved", "Este envio foi aprovado pela producao e pode ser sincronizado no painel."),
            "rejected": ("Envio recusado", "rejected", "Este envio precisa de ajustes antes de uma nova submissao."),
        }
        title, status_class, description = status_map.get(submission.status, ("Envio do time", "idle", "Confira os dados enviados abaixo."))
        return templates.TemplateResponse(
            request=request,
            name="team_public.html",
            context=build_template_context(
                request,
                {
                    "team_page_title": submission.name,
                    "team_page_status": title,
                    "team_page_status_class": status_class,
                    "team_page_description": description,
                    "team_payload": serialize_submission(settings, submission),
                    "team_review_notes": submission.review_notes if submission.status == "rejected" else "",
                },
            ),
        )

    @app.get("/brand/logo")
    async def brand_logo():
        if settings.portal_brand_logo.exists():
            return FileResponse(settings.portal_brand_logo)
        raise HTTPException(status_code=404, detail="Logo nao encontrada.")

    @app.get("/favicon.ico")
    async def favicon_ico():
        if settings.portal_favicon_ico.exists():
            return FileResponse(settings.portal_favicon_ico)
        raise HTTPException(status_code=404, detail="Favicon nao encontrado.")

    @app.get("/favicon.png")
    async def favicon_png():
        if settings.portal_favicon_png.exists():
            return FileResponse(settings.portal_favicon_png)
        raise HTTPException(status_code=404, detail="Favicon nao encontrado.")

    @app.get("/uploads/{file_name}")
    async def upload_file(file_name: str):
        file_path = settings.portal_uploads_dir / file_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")
        return FileResponse(file_path)

    @app.get("/api/admin/submissions")
    async def admin_submissions(request: FastAPIRequest, session: Session = Depends(get_db)):
        require_admin(request)
        return JSONResponse({"items": list_pending_submissions(session, settings)})

    @app.post("/api/admin/submissions/{submission_id}/approve")
    async def admin_approve_submission(submission_id: int, request: FastAPIRequest, session: Session = Depends(get_db)):
        require_admin(request)
        henrik_api_keys = request.headers.get("X-Henrik-Api-Keys", "")
        try:
            submission = approve_submission(session, settings, submission_id, henrik_api_keys)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"item": serialize_submission(settings, submission)})

    @app.post("/api/admin/submissions/{submission_id}/reject")
    async def admin_reject_submission(submission_id: int, request: FastAPIRequest, session: Session = Depends(get_db)):
        require_admin(request)
        payload = await request.json()
        reason = str(payload.get("reason", "")).strip()
        submission = reject_submission(session, submission_id, reason)
        return JSONResponse({"item": serialize_submission(settings, submission)})

    @app.get("/api/admin/teams")
    async def admin_teams(request: FastAPIRequest, session: Session = Depends(get_db)):
        require_admin(request)
        return JSONResponse({"items": list_approved_teams(session, settings)})

    @app.get("/api/admin/settings")
    async def admin_settings(request: FastAPIRequest, session: Session = Depends(get_db)):
        require_admin(request)
        return JSONResponse({"registrations_open": get_registrations_open(session)})

    @app.post("/api/admin/settings/registrations")
    async def admin_set_registrations(request: FastAPIRequest, session: Session = Depends(get_db)):
        require_admin(request)
        payload = await request.json()
        registrations_open = bool(payload.get("open", False))
        return JSONResponse({"registrations_open": set_registrations_open(session, registrations_open)})

    @app.get("/api/health")
    async def healthcheck():
        return {"status": "ok"}

    return app


def run() -> None:
    import uvicorn

    settings = load_app_settings()
    uvicorn.run(create_portal_app(settings.root_path), host="127.0.0.1", port=8000)