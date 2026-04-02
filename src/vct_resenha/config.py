from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SETTINGS = {
    "admin": {
        "username": "VCTADMIN#0000",
        "password": "123456789",
    },
    "discord_bot": {
        "enabled": False,
        "token": "",
        "status": "online",
        "activity_type": "watching",
        "activity_text": "VCT da Resenha",
    },
    "portal": {
        "base_url": "http://127.0.0.1:8000",
        "database_path": "data/portal.sqlite3",
        "admin_token": "change-me-admin-token",
        "session_secret": "change-me-session-secret",
        "session_max_age_hours": 720,
        "discord_client_id": "",
        "discord_client_secret": "",
        "discord_redirect_uri": "http://127.0.0.1:8000/auth/discord/callback",
        "turnstile_site_key": "",
        "turnstile_secret_key": "",
        "logo_asset": "assets/vctdaresenha.png",
    },
    "site": {
        "title": "VCT da Resenha",
        "headline": "Portal dos Capitaes",
        "subheadline": "Cadastre, acompanhe e gerencie seu time em um fluxo unico com o painel da producao.",
        "login_eyebrow": "Campeonato Valorant",
        "login_title": "Inscricao",
        "login_welcome_title": "Bem-vindo(a)",
        "login_welcome_text": "Conecte-se para poder fazer a inscricao do seu time.",
        "login_button_label": "Entrar com o Discord",
        "login_help_text": "Resolva o captcha antes de entrar, se solicitado.",
        "discord_missing_message": "Preencha as credenciais do Discord OAuth em config/app_settings.json antes de publicar o portal.",
        "dashboard_eyebrow": "Portal dos Capitaes",
        "dashboard_title": "Seu time no campeonato",
        "dashboard_subtitle": "Envie o elenco, acompanhe a analise da producao e solicite alteracoes sempre pelo portal.",
        "dashboard_form_title_new": "Cadastrar time",
        "dashboard_form_title_edit": "Solicitar alteracao",
        "dashboard_form_helper_text": "O primeiro jogador e o capitao. Toda alteracao enviada volta para analise antes de entrar no painel.",
        "dashboard_submit_label": "Enviar time",
        "dashboard_success_message": "Seu time foi enviado com sucesso. Aguarde enquanto a producao analisa a submissao.",
        "terms_label": "Declaro que as informacoes enviadas sao verdadeiras e aceito a analise da producao antes da aprovacao final.",
        "footer_items": [
            {"label": "Data", "value": "Em breve"},
            {"label": "Status", "value": "Inscricoes abertas"},
        ],
    },
}


@dataclass(slots=True)
class AdminSettings:
    username: str
    password: str


@dataclass(slots=True)
class DiscordBotSettings:
    enabled: bool
    token: str
    status: str
    activity_type: str
    activity_text: str


@dataclass(slots=True)
class PortalSettings:
    base_url: str
    database_path: str
    admin_token: str
    session_secret: str
    session_max_age_hours: int
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    turnstile_site_key: str
    turnstile_secret_key: str
    logo_asset: str


@dataclass(slots=True)
class SiteSettings:
    title: str
    headline: str
    subheadline: str
    login_eyebrow: str
    login_title: str
    login_welcome_title: str
    login_welcome_text: str
    login_button_label: str
    login_help_text: str
    discord_missing_message: str
    dashboard_eyebrow: str
    dashboard_title: str
    dashboard_subtitle: str
    dashboard_form_title_new: str
    dashboard_form_title_edit: str
    dashboard_form_helper_text: str
    dashboard_submit_label: str
    dashboard_success_message: str
    terms_label: str
    footer_items: list[dict[str, str]]


@dataclass(slots=True)
class AppSettings:
    root_path: Path
    bundled_root_path: Path
    config_path: Path
    admin: AdminSettings
    discord_bot: DiscordBotSettings
    portal: PortalSettings
    site: SiteSettings

    @property
    def portal_database_file(self) -> Path:
        return (self.root_path / self.portal.database_path).resolve()

    @property
    def portal_uploads_dir(self) -> Path:
        return self.root_path / "data" / "portal_uploads"

    @property
    def portal_brand_logo(self) -> Path:
        external_path = self.root_path / self.portal.logo_asset
        if external_path.exists():
            return external_path
        return self.bundled_root_path / self.portal.logo_asset

    @property
    def portal_favicon_ico(self) -> Path:
        external_path = self.root_path / "assets" / "iconresenha.ico"
        if external_path.exists():
            return external_path
        return self.bundled_root_path / "assets" / "iconresenha.ico"

    @property
    def portal_favicon_png(self) -> Path:
        external_path = self.root_path / "assets" / "iconresenha.png"
        if external_path.exists():
            return external_path
        return self.bundled_root_path / "assets" / "iconresenha.png"


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_root_path(base_path: Path | None = None) -> Path:
    if base_path is not None:
        return Path(base_path).resolve()
    return Path(__file__).resolve().parents[2]


def resolve_bundled_root_path(root_path: Path) -> Path:
    bundled_root = getattr(sys, "_MEIPASS", "")
    if bundled_root:
        return Path(bundled_root).resolve()
    return root_path


def load_app_settings(base_path: Path | None = None) -> AppSettings:
    root_path = resolve_root_path(base_path)
    bundled_root_path = resolve_bundled_root_path(root_path)
    config_path = root_path / "config" / "app_settings.json"
    bundled_config_path = bundled_root_path / "config" / "app_settings.json"
    payload = deepcopy(DEFAULT_SETTINGS)

    if config_path.exists():
        raw_payload = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(raw_payload, dict):
            payload = _merge_dicts(payload, raw_payload)
    elif bundled_config_path.exists():
        raw_payload = json.loads(bundled_config_path.read_text(encoding="utf-8"))
        if isinstance(raw_payload, dict):
            payload = _merge_dicts(payload, raw_payload)

    admin_payload = payload.get("admin", {})
    discord_bot_payload = payload.get("discord_bot", {})
    portal_payload = payload.get("portal", {})
    site_payload = payload.get("site", {})

    return AppSettings(
        root_path=root_path,
        bundled_root_path=bundled_root_path,
        config_path=config_path,
        admin=AdminSettings(
            username=str(admin_payload.get("username", "VCTADMIN#0000")).strip(),
            password=str(admin_payload.get("password", "123456789")),
        ),
        discord_bot=DiscordBotSettings(
            enabled=bool(discord_bot_payload.get("enabled", False)),
            token=str(discord_bot_payload.get("token", "")).strip(),
            status=str(discord_bot_payload.get("status", "online")).strip().lower(),
            activity_type=str(discord_bot_payload.get("activity_type", "watching")).strip().lower(),
            activity_text=str(discord_bot_payload.get("activity_text", "VCT da Resenha")).strip(),
        ),
        portal=PortalSettings(
            base_url=str(portal_payload.get("base_url", "http://127.0.0.1:8000")).rstrip("/"),
            database_path=str(portal_payload.get("database_path", "data/portal.sqlite3")),
            admin_token=str(portal_payload.get("admin_token", "change-me-admin-token")),
            session_secret=str(portal_payload.get("session_secret", "change-me-session-secret")),
            session_max_age_hours=max(1, int(portal_payload.get("session_max_age_hours", 720))),
            discord_client_id=str(portal_payload.get("discord_client_id", "")).strip(),
            discord_client_secret=str(portal_payload.get("discord_client_secret", "")).strip(),
            discord_redirect_uri=str(portal_payload.get("discord_redirect_uri", "")).strip(),
            turnstile_site_key=str(portal_payload.get("turnstile_site_key", "")).strip(),
            turnstile_secret_key=str(portal_payload.get("turnstile_secret_key", "")).strip(),
            logo_asset=str(portal_payload.get("logo_asset", "assets/vctdaresenha.png")),
        ),
        site=SiteSettings(
            title=str(site_payload.get("title", "VCT da Resenha")).strip(),
            headline=str(site_payload.get("headline", "Portal dos Capitaes")).strip(),
            subheadline=str(site_payload.get("subheadline", "")).strip(),
            login_eyebrow=str(site_payload.get("login_eyebrow", "Campeonato Valorant")).strip(),
            login_title=str(site_payload.get("login_title", "Inscricao")).strip(),
            login_welcome_title=str(site_payload.get("login_welcome_title", "Bem-vindo(a)")).strip(),
            login_welcome_text=str(site_payload.get("login_welcome_text", "Conecte-se para poder fazer a inscricao do seu time.")).strip(),
            login_button_label=str(site_payload.get("login_button_label", "Entrar com o Discord")).strip(),
            login_help_text=str(site_payload.get("login_help_text", "Resolva o captcha antes de entrar, se solicitado.")).strip(),
            discord_missing_message=str(site_payload.get("discord_missing_message", "Preencha as credenciais do Discord OAuth em config/app_settings.json antes de publicar o portal.")).strip(),
            dashboard_eyebrow=str(site_payload.get("dashboard_eyebrow", "Portal dos Capitaes")).strip(),
            dashboard_title=str(site_payload.get("dashboard_title", "Seu time no campeonato")).strip(),
            dashboard_subtitle=str(site_payload.get("dashboard_subtitle", "Envie o elenco, acompanhe a analise da producao e solicite alteracoes sempre pelo portal.")).strip(),
            dashboard_form_title_new=str(site_payload.get("dashboard_form_title_new", "Cadastrar time")).strip(),
            dashboard_form_title_edit=str(site_payload.get("dashboard_form_title_edit", "Solicitar alteracao")).strip(),
            dashboard_form_helper_text=str(site_payload.get("dashboard_form_helper_text", "O primeiro jogador e o capitao. Toda alteracao enviada volta para analise antes de entrar no painel.")).strip(),
            dashboard_submit_label=str(site_payload.get("dashboard_submit_label", "Enviar time")).strip(),
            dashboard_success_message=str(site_payload.get("dashboard_success_message", "Seu time foi enviado com sucesso. Aguarde enquanto a producao analisa a submissao.")).strip(),
            terms_label=str(site_payload.get("terms_label", "")).strip(),
            footer_items=[
                {
                    "label": str(item.get("label", "")).strip(),
                    "value": str(item.get("value", "")).strip(),
                }
                for item in site_payload.get("footer_items", [])
                if isinstance(item, dict)
            ],
        ),
    )