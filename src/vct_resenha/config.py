from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TERMS_SECTIONS = [
    {
        "title": "1. Aceite dos Termos",
        "blocks": [
            {
                "type": "paragraph",
                "text": "Ao cadastrar um time no campeonato VCT da Resenha, o responsavel pelo time declara que leu, entendeu e concorda com todos os termos e condicoes descritos neste documento.",
            },
            {
                "type": "paragraph",
                "text": "Caso nao concorde com qualquer parte, o cadastro nao deve ser realizado.",
            },
        ],
    },
    {
        "title": "2. Sobre o Campeonato",
        "blocks": [
            {
                "type": "paragraph",
                "text": "O VCT da Resenha e um campeonato amistoso com foco em entretenimento, porem com premiacao em dinheiro para a equipe vencedora.",
            },
            {
                "type": "paragraph",
                "text": "Duracao: 2 dias (sabado e domingo)",
            },
            {
                "type": "list",
                "title": "Formato:",
                "items": ["Partidas MD1", "Final Upper: MD3", "Final Lower: MD3", "Grande Final: MD5"],
            },
        ],
    },
    {
        "title": "3. Requisitos dos Times",
        "blocks": [
            {
                "type": "list",
                "title": "Cada time devera obrigatoriamente:",
                "items": [
                    "Possuir 5 jogadores titulares + 1 coach (opcional)",
                    "Ter nome e identidade (logo ou representacao)",
                    "Estar presente no Discord oficial do campeonato",
                    "Comparecer a call no horario das partidas",
                ],
            },
            {
                "type": "paragraph",
                "text": "O nao cumprimento desses requisitos pode resultar em punicoes.",
            },
        ],
    },
    {
        "title": "4. Responsabilidade do Capitao e Coach",
        "blocks": [
            {
                "type": "list",
                "title": "O capitao ou coach sera o unico ponto de contato com a organizacao e sera responsavel por:",
                "items": [
                    "Garantir que todos os jogadores estejam presentes",
                    "Receber e repassar informacoes ao time",
                    "Responder a organizacao quando necessario",
                    "Garantir que todos os membros sigam as regras",
                ],
            },
        ],
    },
    {
        "title": "5. Comparecimento e W.O",
        "blocks": [
            {
                "type": "list",
                "items": [
                    "Times devem estar prontos no horario marcado",
                    "Sera tolerado um atraso maximo de 10 minutos",
                    "Apos esse periodo, podera ser aplicado W.O (derrota automatica)",
                ],
            },
        ],
    },
    {
        "title": "6. Conduta e Comportamento",
        "blocks": [
            {
                "type": "paragraph",
                "text": "O campeonato tem como objetivo principal a diversao e resenha, entao zoeiras, provocacoes e brincadeiras sao permitidas.",
            },
            {
                "type": "paragraph",
                "text": "No entanto, existem limites que devem ser respeitados.",
            },
            {
                "type": "list",
                "title": "E permitido:",
                "items": [
                    "Brincadeiras, zoacoes e provocacoes leves entre jogadores",
                    "Trash talk saudavel dentro do contexto do jogo",
                ],
            },
            {
                "type": "list",
                "title": "E proibido:",
                "items": [
                    "Ofensas graves ou ataques pessoais pesados",
                    "Qualquer tipo de preconceito (racismo, homofobia, etc.)",
                    "Ameacas ou comportamento que possa ser considerado crime",
                    "Uso de cheats ou qualquer vantagem indevida",
                    "Atitudes que prejudiquem propositalmente o andamento da partida",
                ],
            },
            {
                "type": "list",
                "title": "Penalidades:",
                "items": ["Advertencia", "Perda de mapa", "Desclassificacao"],
            },
        ],
    },
    {
        "title": "7. Sistema de Cartas",
        "blocks": [
            {
                "type": "list",
                "items": [
                    "Cada time tera 2 cartas por partida",
                    "Em caso de overtime (OT), o time recebe +1 carta",
                    "O uso das cartas deve seguir as regras definidas pela organizacao",
                    "A organizacao se reserva o direito de validar ou negar usos indevidos",
                ],
            },
        ],
    },
    {
        "title": "8. Transmissao",
        "blocks": [
            {
                "type": "paragraph",
                "text": "Todas as partidas poderao ser transmitidas ao vivo.",
            },
            {
                "type": "list",
                "title": "Ao participar, os jogadores autorizam automaticamente:",
                "items": [
                    "Uso de imagem e nickname",
                    "Transmissao das partidas",
                    "Divulgacao de conteudos relacionados ao campeonato",
                ],
            },
        ],
    },
    {
        "title": "9. Premiacao",
        "blocks": [
            {
                "type": "list",
                "items": [
                    "O time vencedor recebera R$ 600,00",
                    "A divisao do premio entre os jogadores e responsabilidade do time",
                    "A organizacao nao se responsabiliza por conflitos internos",
                ],
            },
        ],
    },
    {
        "title": "10. Problemas Tecnicos",
        "blocks": [
            {
                "type": "list",
                "items": [
                    "Cada jogador e responsavel por sua conexao e equipamento",
                    "Em caso de problemas tecnicos, a organizacao avaliara a situacao",
                    "A decisao final sera sempre da organizacao",
                ],
            },
        ],
    },
    {
        "title": "11. Alteracoes e Decisoes",
        "blocks": [
            {
                "type": "list",
                "title": "A organizacao se reserva o direito de:",
                "items": [
                    "Alterar regras, caso necessario",
                    "Resolver casos omissos",
                    "Tomar decisoes finais em situacoes nao previstas",
                ],
            },
            {
                "type": "paragraph",
                "text": "Todas as decisoes da organizacao sao finais e incontestaveis.",
            },
        ],
    },
]


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
        "discord_notice_kicker": "Servidor oficial no Discord",
        "discord_notice_title": "Todos os membros do time precisam entrar no servidor",
        "discord_notice_text": "Antes de enviar ou alterar o elenco, garanta que capitao, coach e jogadores ja estejam no Discord oficial do campeonato.",
        "discord_notice_link_label": "Entrar no servidor",
        "discord_notice_link_url": "https://discord.gg/QtnuVxR2r8",
        "dashboard_form_title_new": "Cadastrar time",
        "dashboard_form_title_edit": "Solicitar alteracao",
        "dashboard_form_helper_text": "O primeiro jogador e o capitao. Toda alteracao enviada volta para analise antes de entrar no painel.",
        "dashboard_submit_label": "Enviar time",
        "dashboard_success_message": "Seu time foi enviado com sucesso. Aguarde enquanto a producao analisa a submissao.",
        "registrations_closed_title": "Inscricoes temporariamente fechadas",
        "registrations_closed_text": "A organizacao pausou novos envios no momento. Aguarde a reabertura para cadastrar ou solicitar alteracoes.",
        "terms_label": "Declaro que as informacoes enviadas sao verdadeiras e aceito a analise da producao antes da aprovacao final.",
        "terms_modal_kicker": "Leitura obrigatoria",
        "terms_modal_title": "Termos e Condicoes - VCT da Resenha",
        "terms_scroll_hint": "Leia ate o final para liberar o aceite.",
        "terms_sections": DEFAULT_TERMS_SECTIONS,
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
    discord_notice_kicker: str
    discord_notice_title: str
    discord_notice_text: str
    discord_notice_link_label: str
    discord_notice_link_url: str
    dashboard_form_title_new: str
    dashboard_form_title_edit: str
    dashboard_form_helper_text: str
    dashboard_submit_label: str
    dashboard_success_message: str
    registrations_closed_title: str
    registrations_closed_text: str
    terms_label: str
    terms_modal_kicker: str
    terms_modal_title: str
    terms_scroll_hint: str
    terms_sections: list[dict[str, object]]
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


def _normalize_terms_sections(raw_sections: object) -> list[dict[str, object]]:
    if not isinstance(raw_sections, list):
        raw_sections = DEFAULT_TERMS_SECTIONS

    normalized_sections: list[dict[str, object]] = []
    for section in raw_sections:
        if not isinstance(section, dict):
            continue

        title = str(section.get("title", "")).strip()
        if not title:
            continue

        blocks_payload = section.get("blocks", [])
        if not isinstance(blocks_payload, list):
            blocks_payload = []

        normalized_blocks: list[dict[str, object]] = []
        for block in blocks_payload:
            if not isinstance(block, dict):
                continue

            block_type = str(block.get("type", "paragraph")).strip().lower()
            if block_type == "list":
                items_payload = block.get("items", [])
                if not isinstance(items_payload, list):
                    items_payload = []
                items = [str(item).strip() for item in items_payload if str(item).strip()]
                if not items:
                    continue
                normalized_blocks.append(
                    {
                        "type": "list",
                        "title": str(block.get("title", "")).strip(),
                        "items": items,
                    }
                )
                continue

            text = str(block.get("text", "")).strip()
            if not text:
                continue
            normalized_blocks.append({"type": "paragraph", "text": text})

        if normalized_blocks:
            normalized_sections.append({"title": title, "blocks": normalized_blocks})

    return normalized_sections or deepcopy(DEFAULT_TERMS_SECTIONS)


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
            discord_notice_kicker=str(site_payload.get("discord_notice_kicker", "Servidor oficial no Discord")).strip(),
            discord_notice_title=str(site_payload.get("discord_notice_title", "Todos os membros do time precisam entrar no servidor")).strip(),
            discord_notice_text=str(site_payload.get("discord_notice_text", "Antes de enviar ou alterar o elenco, garanta que capitao, coach e jogadores ja estejam no Discord oficial do campeonato.")).strip(),
            discord_notice_link_label=str(site_payload.get("discord_notice_link_label", "Entrar no servidor")).strip(),
            discord_notice_link_url=str(site_payload.get("discord_notice_link_url", "https://discord.gg/QtnuVxR2r8")).strip(),
            dashboard_form_title_new=str(site_payload.get("dashboard_form_title_new", "Cadastrar time")).strip(),
            dashboard_form_title_edit=str(site_payload.get("dashboard_form_title_edit", "Solicitar alteracao")).strip(),
            dashboard_form_helper_text=str(site_payload.get("dashboard_form_helper_text", "O primeiro jogador e o capitao. Toda alteracao enviada volta para analise antes de entrar no painel.")).strip(),
            dashboard_submit_label=str(site_payload.get("dashboard_submit_label", "Enviar time")).strip(),
            dashboard_success_message=str(site_payload.get("dashboard_success_message", "Seu time foi enviado com sucesso. Aguarde enquanto a producao analisa a submissao.")).strip(),
            registrations_closed_title=str(site_payload.get("registrations_closed_title", "Inscricoes temporariamente fechadas")).strip(),
            registrations_closed_text=str(site_payload.get("registrations_closed_text", "A organizacao pausou novos envios no momento. Aguarde a reabertura para cadastrar ou solicitar alteracoes.")).strip(),
            terms_label=str(site_payload.get("terms_label", "")).strip(),
            terms_modal_kicker=str(site_payload.get("terms_modal_kicker", "Leitura obrigatoria")).strip(),
            terms_modal_title=str(site_payload.get("terms_modal_title", "Termos e Condicoes - VCT da Resenha")).strip(),
            terms_scroll_hint=str(site_payload.get("terms_scroll_hint", "Leia ate o final para liberar o aceite.")).strip(),
            terms_sections=_normalize_terms_sections(site_payload.get("terms_sections", DEFAULT_TERMS_SECTIONS)),
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