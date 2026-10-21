"""Cloud Interactive mention bot.

When someone in the server mentions a dev, the bot sends that dev a DM with
who mentioned them, where, a short preview and a link to the message.

- At most one DM per person every COOLDOWN_SECONDS (default 5 minutes).
  Pings that land in between are grouped into one summary DM when the wait ends,
  so nothing is lost.
- The first time the bot DMs someone, it says what it is first.

Settings come from environment variables (see .env.example).
"""

import asyncio
import logging
import os
import time

import discord


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}


TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)            # 0 = any server the bot is in
ROLE_MENTIONS = env_bool("ROLE_MENTIONS", False)            # also DM everyone in a mentioned role
COOLDOWN = int(os.getenv("COOLDOWN_SECONDS", "300") or 300) # min seconds between DMs to the same person
IGNORE_CHANNELS = env_ids("IGNORE_CHANNEL_IDS")             # channels where pings are not forwarded
IGNORE_USERS = env_ids("IGNORE_USER_IDS")                   # people who never get DMs (opt out)
PREVIEW_CHARS = 300
SUMMARY_PREVIEW_CHARS = 90
SUMMARY_MAX_LINES = 10

INTRO = (
    "Hey! This bot just lets you know when someone pings you in the **Cloud Interactive** server, "
    "so you don't miss anything. You don't need to reply here, just open the link to see the message."
)

log = logging.getLogger("mention-bot")

intents = discord.Intents.default()
intents.message_content = True      # needed for the preview text
intents.members = ROLE_MENTIONS     # needed to list who is in a role

client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())

_last_sent: dict[int, float] = {}                    # user id -> when we last DMed them
_pending: dict[int, list[discord.Message]] = {}      # user id -> pings waiting for the cooldown
_flush_tasks: dict[int, asyncio.Task] = {}           # user id -> scheduled summary
_introduced: set[int] = set()                        # users we know already got the intro


def recipients(message: discord.Message) -> list[discord.abc.User]:
    """People to DM for this message, without duplicates."""
    people: dict[int, discord.abc.User] = {}
    for user in message.mentions:
        people[user.id] = user
    if ROLE_MENTIONS and message.guild:
        for role in message.role_mentions:
            for member in role.members:
                people[member.id] = member
    out = []
    for user in people.values():
        if user.bot or user.id == message.author.id or user.id in IGNORE_USERS:
            continue
        out.append(user)
    return out


def can_see(user: discord.abc.User, channel) -> bool:
    """Only DM people who can actually read the channel, so private channels stay private."""
    if not isinstance(user, discord.Member):
        return False
    try:
        return channel.permissions_for(user).read_messages
    except Exception:
        return False


def preview(message: discord.Message, limit: int) -> str:
    text = " ".join(message.clean_content.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    if not text:
        text = "(attachment or embed)" if (message.attachments or message.embeds) else "(no text)"
    return text


def build_embed(message: discord.Message) -> discord.Embed:
    channel_name = getattr(message.channel, "name", "a channel")
    embed = discord.Embed(
        title=f"You were pinged in #{channel_name}",
        description=preview(message, PREVIEW_CHARS),
        url=message.jump_url,
        color=0x5865F2,
        timestamp=message.created_at,
    )
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    embed.add_field(name="Open the message", value=f"[Jump to it]({message.jump_url})", inline=False)
    if message.guild:
        embed.set_footer(text=message.guild.name)
    return embed


def build_summary(messages: list[discord.Message]) -> discord.Embed:
    lines = []
    for m in messages[-SUMMARY_MAX_LINES:]:
        channel_name = getattr(m.channel, "name", "a channel")
        lines.append(f"**{m.author.display_name}** in #{channel_name}: {preview(m, SUMMARY_PREVIEW_CHARS)} [Jump]({m.jump_url})")
    extra = len(messages) - SUMMARY_MAX_LINES
    if extra > 0:
        lines.append(f"…and {extra} more")
    count = len(messages)
    embed = discord.Embed(
        title=f"You were pinged {count} time{'s' if count != 1 else ''} in the last few minutes",
        description="\n".join(lines),
        color=0x5865F2,
    )
    guild = messages[-1].guild
    if guild:
        embed.set_footer(text=guild.name)
    return embed


async def is_first_dm(user: discord.abc.User) -> bool:
    """True if the bot has never DMed this person (checks the DM history, so it survives restarts)."""
    if user.id in _introduced:
        return False
    try:
        dm = user.dm_channel or await user.create_dm()
        async for _ in dm.history(limit=1):
            _introduced.add(user.id)
            return False
    except discord.HTTPException:
        return False
    return True


async def deliver(user: discord.abc.User, embed: discord.Embed) -> None:
    try:
        if await is_first_dm(user):
            await user.send(INTRO)
            _introduced.add(user.id)
        await user.send(embed=embed)
    except discord.Forbidden:
        log.info("Cannot DM %s (DMs closed)", user)
    except discord.HTTPException as e:
        log.warning("DM to %s failed: %s", user, e)
    finally:
        _last_sent[user.id] = time.monotonic()


async def flush_later(user: discord.abc.User, delay: float) -> None:
    try:
        await asyncio.sleep(max(0.0, delay))
        messages = _pending.pop(user.id, [])
        if messages:
            embed = build_embed(messages[0]) if len(messages) == 1 else build_summary(messages)
            await deliver(user, embed)
    finally:
        _flush_tasks.pop(user.id, None)


async def notify(user: discord.abc.User, message: discord.Message) -> None:
    now = time.monotonic()
    wait = COOLDOWN - (now - _last_sent.get(user.id, -COOLDOWN))
    if wait <= 0 and user.id not in _pending:
        _last_sent[user.id] = now  # reserve the slot before awaiting so bursts queue up
        await deliver(user, build_embed(message))
        return
    queue = _pending.setdefault(user.id, [])
    if all(m.id != message.id for m in queue):
        queue.append(message)
    if user.id not in _flush_tasks:
        _flush_tasks[user.id] = asyncio.create_task(flush_later(user, wait))


@client.event
async def on_ready():
    log.info("Logged in as %s (%s). Cooldown %ss, role mentions: %s", client.user, client.user.id, COOLDOWN, ROLE_MENTIONS)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if GUILD_ID and message.guild.id != GUILD_ID:
        return
    if message.channel.id in IGNORE_CHANNELS:
        return
    if not message.mentions and not (ROLE_MENTIONS and message.role_mentions):
        return

    for user in recipients(message):
        if can_see(user, message.channel):
            await notify(user, message)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set")
    client.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
