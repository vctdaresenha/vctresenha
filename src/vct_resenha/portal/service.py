from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import AppSettings
from ..valorant_api import HenrikRateLimitError, parse_riot_id, validate_br_riot_id
from .db import PortalSetting, PortalTeam, PortalUser, TeamSubmission


TEAM_NAME_MAX_LENGTH = 10
SUBMISSION_PENDING = "pending"
SUBMISSION_APPROVED = "approved"
SUBMISSION_REJECTED = "rejected"
REGISTRATIONS_OPEN_SETTING_KEY = "registrations_open"


@dataclass(slots=True)
class TeamFormPayload:
    name: str
    coach: str
    players: list[str]
    terms_accepted: bool


def normalize_team_name(value: str) -> str:
    return str(value or "").strip()


def validate_team_form(payload: TeamFormPayload) -> None:
    team_name = normalize_team_name(payload.name)
    if not team_name:
        raise HTTPException(status_code=400, detail="Informe o nome do time.")
    if len(team_name) > TEAM_NAME_MAX_LENGTH:
        raise HTTPException(status_code=400, detail="O nome do time aceita no maximo 10 caracteres.")
    if " " in team_name:
        raise HTTPException(status_code=400, detail="O nome do time nao pode conter espacos.")
    if not team_name.isalnum():
        raise HTTPException(status_code=400, detail="O nome do time aceita apenas letras e numeros.")

    if not str(payload.coach or "").strip():
        raise HTTPException(status_code=400, detail="Informe o coach do time.")

    if len(payload.players) != 5:
        raise HTTPException(status_code=400, detail="Informe exatamente 5 jogadores.")

    for player in payload.players:
        current_player = str(player or "").strip()
        if not current_player or not parse_riot_id(current_player):
            raise HTTPException(status_code=400, detail="Todos os jogadores devem estar no formato Nick#TAG.")

    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail="Aceite os termos antes de enviar o time.")


def _ensure_unique_team_name(session: Session, owner_user_id: int, name: str, current_submission_id: int | None = None) -> None:
    normalized_name = normalize_team_name(name).lower()

    accepted_team = session.scalar(
        select(PortalTeam).where(func.lower(PortalTeam.name) == normalized_name, PortalTeam.owner_user_id != owner_user_id)
    )
    if accepted_team is not None:
        raise HTTPException(status_code=400, detail="Esse nome de time ja esta em uso.")

    submitted_query = select(TeamSubmission).where(
        func.lower(TeamSubmission.name) == normalized_name,
        TeamSubmission.owner_user_id != owner_user_id,
    )
    submitted_team = session.scalar(submitted_query)
    if submitted_team is not None and submitted_team.id != current_submission_id:
        raise HTTPException(status_code=400, detail="Esse nome de time ja foi enviado anteriormente.")


def build_tracker_url(riot_id: str) -> str:
    parsed_riot_id = parse_riot_id(riot_id)
    if not parsed_riot_id:
        return ""
    player_name, player_tag = parsed_riot_id
    encoded_riot_id = quote(f"{player_name}#{player_tag}", safe="")
    return f"https://tracker.gg/valorant/profile/riot/{encoded_riot_id}/overview"


def build_player_entries(players: list[str] | None) -> list[dict[str, str]]:
    return [
        {
            "display_name": str(player or "").strip(),
            "tracker_url": build_tracker_url(str(player or "").strip()),
        }
        for player in list(players or [])
        if str(player or "").strip()
    ]


def get_registrations_open(session: Session) -> bool:
    setting = session.get(PortalSetting, REGISTRATIONS_OPEN_SETTING_KEY)
    if setting is None:
        return True
    return str(setting.value).strip().lower() not in {"0", "false", "off", "no"}


def set_registrations_open(session: Session, is_open: bool) -> bool:
    setting = session.get(PortalSetting, REGISTRATIONS_OPEN_SETTING_KEY)
    if setting is None:
        setting = PortalSetting(key=REGISTRATIONS_OPEN_SETTING_KEY)
        session.add(setting)
    setting.value = "true" if is_open else "false"
    session.commit()
    session.refresh(setting)
    return str(setting.value).strip().lower() == "true"


def save_logo_upload(settings: AppSettings, upload: UploadFile) -> str:
    if upload.content_type not in {"image/png", "image/x-png"}:
        raise HTTPException(status_code=400, detail="A logo precisa ser enviada em PNG.")

    raw_bytes = upload.file.read()
    upload.file.seek(0)

    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Envie a logo do time.")

    try:
        from PIL import Image
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Pillow nao encontrado para validar a logo.") from exc

    with Image.open(BytesIO(raw_bytes)) as image:
        if image.format != "PNG":
            raise HTTPException(status_code=400, detail="A logo precisa ser um arquivo PNG valido.")
        if image.width != image.height:
            raise HTTPException(status_code=400, detail="A logo precisa ser quadrada.")
        if image.width > 512 or image.height > 512:
            raise HTTPException(status_code=400, detail="A logo precisa ter no maximo 512x512.")

    uploads_dir = settings.portal_uploads_dir
    uploads_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{secrets.token_hex(16)}.png"
    target_path = uploads_dir / file_name
    target_path.write_bytes(raw_bytes)
    return file_name


def get_or_create_portal_user(session: Session, discord_payload: dict) -> PortalUser:
    discord_id = str(discord_payload.get("id", "")).strip()
    if not discord_id:
        raise HTTPException(status_code=400, detail="Payload do Discord invalido.")

    user = session.scalar(select(PortalUser).where(PortalUser.discord_id == discord_id))
    if user is None:
        user = PortalUser(discord_id=discord_id, username=str(discord_payload.get("username", "")))
        session.add(user)

    user.username = str(discord_payload.get("username", "")).strip() or user.username
    user.global_name = str(discord_payload.get("global_name", "")).strip()
    user.avatar_hash = str(discord_payload.get("avatar", "")).strip()
    user.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(user)
    return user


def get_dashboard_payload(session: Session, settings: AppSettings, user: PortalUser) -> dict:
    accepted_team = session.scalar(select(PortalTeam).where(PortalTeam.owner_user_id == user.id))
    latest_submission = session.scalar(
        select(TeamSubmission)
        .where(TeamSubmission.owner_user_id == user.id)
        .order_by(TeamSubmission.submitted_at.desc())
    )

    return {
        "accepted_team": serialize_team(settings, accepted_team) if accepted_team else None,
        "latest_submission": serialize_submission(settings, latest_submission) if latest_submission else None,
    }


def upsert_team_submission(
    session: Session,
    settings: AppSettings,
    user: PortalUser,
    payload: TeamFormPayload,
    logo_filename: str,
) -> TeamSubmission:
    validate_team_form(payload)

    if not get_registrations_open(session):
        raise HTTPException(status_code=400, detail="As inscricoes estao fechadas no momento.")

    existing_team = session.scalar(select(PortalTeam).where(PortalTeam.owner_user_id == user.id))
    existing_pending = session.scalar(
        select(TeamSubmission).where(TeamSubmission.owner_user_id == user.id, TeamSubmission.status == SUBMISSION_PENDING)
    )

    _ensure_unique_team_name(session, user.id, payload.name, existing_pending.id if existing_pending else None)

    submission = existing_pending or TeamSubmission(owner_user_id=user.id, team_id=existing_team.id if existing_team else None)
    if existing_pending is None:
        session.add(submission)

    submission.name = normalize_team_name(payload.name)
    submission.coach = str(payload.coach or "").strip()
    submission.players = [str(player or "").strip() for player in payload.players]
    submission.logo_filename = logo_filename
    submission.status = SUBMISSION_PENDING
    submission.terms_accepted = 1 if payload.terms_accepted else 0
    submission.review_notes = ""
    submission.submitted_at = datetime.utcnow()
    submission.reviewed_at = None

    session.commit()
    session.refresh(submission)
    return submission


def approve_submission(session: Session, settings: AppSettings, submission_id: int, api_keys: str | list[str] = "") -> TeamSubmission:
    submission = session.get(TeamSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submissao nao encontrada.")
    if submission.status != SUBMISSION_PENDING:
        raise HTTPException(status_code=400, detail="Essa submissao ja foi analisada.")

    for player in submission.players:
        try:
            validation = validate_br_riot_id(player, api_key=api_keys, timeout=6.0)
        except PermissionError as exc:
            raise HTTPException(
                status_code=400,
                detail="A API HenrikDev recusou a chave configurada. Atualize as chaves no aplicativo antes de aprovar o time.",
            ) from exc
        except HenrikRateLimitError as exc:
            raise HTTPException(
                status_code=429,
                detail="As chaves configuradas da API HenrikDev atingiram o limite de requisicoes. Tente novamente com outra chave.",
            ) from exc
        except HTTPError as exc:
            if exc.code == 401:
                raise HTTPException(
                    status_code=400,
                    detail="A aprovacao precisa de uma chave valida da API HenrikDev para validar os jogadores deste time.",
                ) from exc
            raise HTTPException(
                status_code=400,
                detail=f"Falha ao validar o jogador {player} na API HenrikDev: HTTP {exc.code}.",
            ) from exc
        if not validation:
            raise HTTPException(status_code=400, detail=f"Nao foi possivel validar o jogador {player} na API HenrikDev.")

    team = session.scalar(select(PortalTeam).where(PortalTeam.owner_user_id == submission.owner_user_id))
    if team is None:
        team = PortalTeam(owner_user_id=submission.owner_user_id, name=submission.name, coach=submission.coach, logo_filename=submission.logo_filename, players=submission.players)
        session.add(team)
        session.flush()

    _ensure_unique_team_name(session, submission.owner_user_id, submission.name, submission.id)

    team.name = submission.name
    team.coach = submission.coach
    team.logo_filename = submission.logo_filename
    team.players = list(submission.players)
    team.last_submission_id = submission.id
    team.updated_at = datetime.utcnow()

    submission.team_id = team.id
    submission.status = SUBMISSION_APPROVED
    submission.review_notes = "Time aprovado pela producao."
    submission.reviewed_at = datetime.utcnow()

    session.commit()
    session.refresh(submission)
    return submission


def reject_submission(session: Session, submission_id: int, reason: str) -> TeamSubmission:
    submission = session.get(TeamSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submissao nao encontrada.")
    if submission.status != SUBMISSION_PENDING:
        raise HTTPException(status_code=400, detail="Essa submissao ja foi analisada.")

    submission.status = SUBMISSION_REJECTED
    submission.review_notes = str(reason or "Submissao recusada pela producao.").strip()
    submission.reviewed_at = datetime.utcnow()
    session.commit()
    session.refresh(submission)
    return submission


def serialize_team(settings: AppSettings, team: PortalTeam | None) -> dict | None:
    if team is None:
        return None
    return {
        "id": team.id,
        "owner_user_id": team.owner_user_id,
        "name": team.name,
        "coach": team.coach,
        "players": list(team.players or []),
        "player_entries": build_player_entries(team.players),
        "logo_url": f"/uploads/{team.logo_filename}" if team.logo_filename else "",
        "public_view_url": f"{settings.portal.base_url}/times/{team.id}",
        "updated_at": team.updated_at.isoformat(),
    }


def serialize_submission(settings: AppSettings, submission: TeamSubmission | None) -> dict | None:
    if submission is None:
        return None
    return {
        "id": submission.id,
        "owner_user_id": submission.owner_user_id,
        "team_id": submission.team_id,
        "name": submission.name,
        "coach": submission.coach,
        "players": list(submission.players or []),
        "player_entries": build_player_entries(submission.players),
        "logo_url": f"/uploads/{submission.logo_filename}" if submission.logo_filename else "",
        "status": submission.status,
        "review_notes": submission.review_notes,
        "public_view_url": f"{settings.portal.base_url}/envios/{submission.id}",
        "submitted_at": submission.submitted_at.isoformat(),
        "reviewed_at": submission.reviewed_at.isoformat() if submission.reviewed_at else "",
    }


def list_pending_submissions(session: Session, settings: AppSettings) -> list[dict]:
    items = session.scalars(
        select(TeamSubmission)
        .where(TeamSubmission.status == SUBMISSION_PENDING)
        .order_by(TeamSubmission.submitted_at.asc())
    ).all()
    payloads = []
    for item in items:
        serialized = serialize_submission(settings, item) or {}
        serialized["owner_name"] = item.owner.username
        payloads.append(serialized)
    return payloads


def list_approved_teams(session: Session, settings: AppSettings) -> list[dict]:
    teams = session.scalars(select(PortalTeam).order_by(PortalTeam.updated_at.desc(), PortalTeam.id.asc())).all()
    return [serialize_team(settings, team) for team in teams if team is not None]


def get_team_by_id(session: Session, team_id: int) -> PortalTeam | None:
    return session.get(PortalTeam, team_id)


def get_submission_by_id(session: Session, submission_id: int) -> TeamSubmission | None:
    return session.get(TeamSubmission, submission_id)