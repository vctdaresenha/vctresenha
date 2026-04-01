from __future__ import annotations

import logging

import discord

from .config import AppSettings, DiscordBotSettings, load_app_settings


LOGGER = logging.getLogger("vct_resenha.discord_bot")


def _resolve_status(raw_status: str) -> discord.Status:
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "do_not_disturb": discord.Status.dnd,
        "invisible": discord.Status.invisible,
        "offline": discord.Status.invisible,
    }
    return status_map.get(raw_status, discord.Status.online)


def _resolve_activity(bot_settings: DiscordBotSettings) -> discord.BaseActivity | None:
    activity_text = bot_settings.activity_text.strip()
    if not activity_text:
        return None

    activity_type = bot_settings.activity_type
    if activity_type == "playing":
        return discord.Game(name=activity_text)

    activity_type_map = {
        "listening": discord.ActivityType.listening,
        "watching": discord.ActivityType.watching,
        "competing": discord.ActivityType.competing,
    }
    return discord.Activity(
        type=activity_type_map.get(activity_type, discord.ActivityType.watching),
        name=activity_text,
    )


class VCTDiscordBot(discord.Client):
    def __init__(self, settings: AppSettings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.settings = settings

    async def setup_hook(self) -> None:
        LOGGER.info("Inicializando bot do Discord.")

    async def on_ready(self) -> None:
        user = self.user
        if user is None:
            LOGGER.warning("Bot conectado, mas user ainda nao foi resolvido pelo gateway.")
            return

        await self.change_presence(
            status=_resolve_status(self.settings.discord_bot.status),
            activity=_resolve_activity(self.settings.discord_bot),
        )
        LOGGER.info("Bot conectado como %s (%s).", user, user.id)


def _validate_settings(settings: AppSettings) -> None:
    if not settings.discord_bot.enabled:
        raise RuntimeError("discord_bot.enabled esta false em config/app_settings.json.")
    if not settings.discord_bot.token:
        raise RuntimeError("discord_bot.token nao foi preenchido em config/app_settings.json.")


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    settings = load_app_settings()
    _validate_settings(settings)

    bot = VCTDiscordBot(settings)
    bot.run(settings.discord_bot.token, log_handler=None)