import asyncio
import datetime
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env.discord"
load_dotenv(os.getenv("DISCORD_BOT_ENV_FILE", str(DEFAULT_ENV_PATH)))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("registar-discord-bot")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
SERVER_ID = discord.Object(id=int(os.getenv("SERVER_ID", "0")))
REGISTAR_API_URL = os.getenv("REGISTAR_API_URL", "").rstrip("/")
DISCORD_BOT_API_KEY = os.getenv("DISCORD_BOT_API_KEY", "")
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)
VERIFY_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 2

MEMBERSHIP_ROLES = {
    "PRIDRUZENO": "Plavi",
    "PUNOPRAVNO": "Narančasti",
    "POCASNO": "Crveni",
}

SECTION_ROLES = {
    "biciklistička": "Bike",
    "disco": "Disco",
    "dramska": "Dramska",
    "foto": "Foto",
    "glazbena": "Glazbena",
    "media": "Media",
    "planinarska": "Pi",
    "računarska": "Comp",
    "tehnička": "Tech",
    "video": "Video",
}
KOMBI_ROLE_NAME = "Kombi tim"

STATUS_CHECK_LOCK = asyncio.Lock()
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


class APIError(Exception):
    def __init__(self, status: int | None = None):
        self.status = status
        super().__init__("Registar API request failed.")


def validate_configuration() -> None:
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN nije postavljen.")
    if SERVER_ID.id <= 0:
        raise RuntimeError("SERVER_ID mora biti pozitivan Discord server ID.")
    if not DISCORD_BOT_API_KEY or len(DISCORD_BOT_API_KEY) < 32:
        raise RuntimeError("DISCORD_BOT_API_KEY mora imati najmanje 32 znaka.")

    parsed = urlsplit(REGISTAR_API_URL)
    is_local_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (parsed.scheme != "https" and not is_local_http)
    ):
        raise RuntimeError("REGISTAR_API_URL mora koristiti HTTPS (osim lokalnog razvoja).")


def api_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {DISCORD_BOT_API_KEY}"}


async def api_request(
    session: aiohttp.ClientSession,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    params: dict | None = None,
):
    try:
        async with session.request(
            method,
            f"{REGISTAR_API_URL}/api/discord{path}",
            json=payload,
            params=params,
            headers=api_headers(),
        ) as response:
            if response.status < 200 or response.status >= 300:
                raise APIError(response.status)
            return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        raise APIError() from error


async def wait_for_verification(
    session: aiohttp.ClientSession, state: str
) -> dict | None:
    deadline = asyncio.get_running_loop().time() + VERIFY_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        result = await api_request(
            session,
            "POST",
            "/verification/status",
            payload={"state": state},
        )
        status = result.get("status")
        if status == "SUCCESS":
            return result.get("member")
        if status in {"FAILED", "EXPIRED"}:
            return None
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return None


def role_named(guild: discord.Guild, name: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=name)


async def replace_managed_roles(
    member: discord.Member,
    role_names: set[str],
    expected_role_name: str | None,
    reason: str,
) -> None:
    managed_roles = [
        role for role in member.guild.roles if role.name in role_names
    ]
    expected_role = role_named(member.guild, expected_role_name) if expected_role_name else None
    if expected_role_name and expected_role is None:
        logger.warning(
            "Configured Discord role %r is missing; leaving managed roles unchanged",
            expected_role_name,
        )
        return
    remove_roles = [
        role
        for role in managed_roles
        if role in member.roles and role != expected_role
    ]
    add_roles = [expected_role] if expected_role and expected_role not in member.roles else []

    if not remove_roles and not add_roles:
        return
    try:
        if add_roles:
            await member.add_roles(*add_roles, reason=reason)
        if remove_roles:
            await member.remove_roles(*remove_roles, reason=reason)
    except discord.Forbidden:
        logger.warning("Missing role permissions for Discord member %s", member.id)
    except discord.HTTPException:
        logger.exception("Discord role update failed for member %s", member.id)


async def apply_member_data(member: discord.Member, data: dict) -> None:
    level = data.get("status_clanstva")
    if level in MEMBERSHIP_ROLES or level == "STARO":
        await replace_managed_roles(
            member,
            set(MEMBERSHIP_ROLES.values()),
            MEMBERSHIP_ROLES.get(level),
            "Member status synchronized from Registar",
        )
    else:
        logger.warning("Unknown membership level received for Discord member %s", member.id)

    section = data.get("section")
    if isinstance(section, str):
        expected_section_role = SECTION_ROLES.get(section.strip().casefold())
        if expected_section_role:
            await replace_managed_roles(
                member,
                set(SECTION_ROLES.values()),
                expected_section_role,
                "Home section synchronized from Registar",
            )
        else:
            logger.warning("No Discord role mapping configured for section %r", section)

    if isinstance(data.get("transport_volunteer"), bool):
        await replace_managed_roles(
            member,
            {KOMBI_ROLE_NAME},
            KOMBI_ROLE_NAME if data["transport_volunteer"] else None,
            "Kombi team status synchronized from Registar",
        )

    full_name = data.get("full_name")
    if isinstance(full_name, str) and 0 < len(full_name) <= 32 and member.nick != full_name:
        try:
            await member.edit(nick=full_name, reason="Member name synchronized from Registar")
        except discord.Forbidden:
            logger.warning("Missing nickname permission for Discord member %s", member.id)
        except discord.HTTPException:
            logger.exception("Discord nickname update failed for member %s", member.id)


async def synchronize_members() -> None:
    if STATUS_CHECK_LOCK.locked():
        raise RuntimeError("Sinkronizacija je već u tijeku.")

    async with STATUS_CHECK_LOCK:
        guild = bot.get_guild(SERVER_ID.id)
        if guild is None:
            raise RuntimeError("Bot nije pronašao konfigurirani Discord server.")

        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            members = await api_request(session, "GET", "/members")

        for item in members:
            discord_id = item.get("discord_id")
            if not isinstance(discord_id, str) or not discord_id.isdigit():
                logger.warning("Skipping malformed Discord member record from API")
                continue
            member = guild.get_member(int(discord_id))
            if member is not None:
                await apply_member_data(member, item)

        logger.info("Synchronized %d linked member records", len(members))


@tasks.loop(time=datetime.time(hour=6))
async def daily_status_check() -> None:
    try:
        await synchronize_members()
    except Exception:
        logger.exception("Daily member synchronization failed")


@bot.tree.command(
    name="hello",
    description="Provjera je li bot aktivan.",
    guild=SERVER_ID,
)
@app_commands.guild_only()
async def hello(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "Pozdrav, Discord bot je aktivan.", ephemeral=True
    )


@bot.tree.command(
    name="prijavi-se",
    description="Poveži Discord račun s članstvom putem Google verifikacije.",
    guild=SERVER_ID,
)
@app_commands.guild_only()
async def register(interaction: discord.Interaction) -> None:
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "Ovu naredbu možete koristiti samo na KSET Discord serveru.",
            ephemeral=True,
        )
        return
    guild = interaction.guild
    if guild and role_named(guild, "Crveni") in member.roles:
        await interaction.response.send_message(
            "Korisnici sa statusom Crveni ne mogu ponovno povezati račun.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            start = await api_request(
                session,
                "POST",
                "/verification/start",
                payload={"discordId": str(member.id)},
            )
            oauth_url = start.get("oauthUrl")
            state = start.get("state")
            if not isinstance(oauth_url, str) or not isinstance(state, str):
                raise APIError()

            register_view = discord.ui.View(timeout=VERIFY_TIMEOUT_SECONDS)
            register_view.add_item(
                discord.ui.Button(
                    label="Verificiraj se",
                    url=oauth_url,
                    style=discord.ButtonStyle.link,
                )
            )
            result_message = await interaction.followup.send(
                "Otvorite poveznicu za sigurnu verifikaciju Google računom. "
                "Poveznica vrijedi pet minuta.",
                view=register_view,
                ephemeral=True,
            )
            verified_member = await wait_for_verification(session, state)

        try:
            await result_message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        if verified_member is None:
            await interaction.followup.send(
                "Verifikacija nije uspjela ili je istekla. Pokrenite naredbu ponovo.",
                ephemeral=True,
            )
            return

        await apply_member_data(member, verified_member)
        await interaction.followup.send(
            "Discord račun je uspješno povezan s članstvom.",
            ephemeral=True,
        )
    except APIError as error:
        if error.status == 409:
            message = "Ovaj Discord račun je već povezan s članstvom."
        elif error.status == 429:
            message = "Previše pokušaja. Pričekajte nekoliko minuta pa pokušajte ponovo."
        else:
            logger.warning("Registar API unavailable during registration (status=%s)", error.status)
            message = "Verifikacijski servis trenutačno nije dostupan. Pokušajte kasnije."
        await interaction.followup.send(message, ephemeral=True)
    except Exception:
        logger.exception("Discord registration failed for member %s", member.id)
        await interaction.followup.send(
            "Došlo je do greške. Pokušajte ponovo kasnije ili kontaktirajte administraciju.",
            ephemeral=True,
        )


def is_uprava_or_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        return (
            interaction.user.guild_permissions.administrator
            or any(role.name == "Uprava" for role in interaction.user.roles)
        )

    return app_commands.check(predicate)


@bot.tree.command(
    name="check_status",
    description="Sinkronizira statuse članova sa stranicom.",
    guild=SERVER_ID,
)
@app_commands.guild_only()
@is_uprava_or_admin()
async def check_status_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await synchronize_members()
        await interaction.followup.send(
            "Sinkronizacija članstva je završena.", ephemeral=True
        )
    except APIError as error:
        logger.warning("Manual member synchronization failed (status=%s)", error.status)
        await interaction.followup.send(
            "Stranica trenutačno nije dostupna. Pokušajte kasnije.",
            ephemeral=True,
        )
    except Exception:
        logger.exception("Manual member synchronization failed")
        await interaction.followup.send(
            "Sinkronizacija nije uspjela. Pokušajte kasnije.",
            ephemeral=True,
        )


@bot.event
async def on_ready() -> None:
    logger.info("Bot connected as %s", bot.user)
    try:
        synced = await bot.tree.sync(guild=SERVER_ID)
        logger.info("Synchronized %d guild commands", len(synced))
    except discord.HTTPException:
        logger.exception("Discord command synchronization failed")

    if not daily_status_check.is_running():
        daily_status_check.start()


if __name__ == "__main__":
    validate_configuration()
    bot.run(DISCORD_BOT_TOKEN)
