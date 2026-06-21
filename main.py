import os
import re
import sqlite3
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import MISSING
from dotenv import load_dotenv

load_dotenv()

# =========================
# AIR SERBIA BOT CONFIG
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

EMBED_COLOR = 0x122E63
DB_PATH = "airserbia_personnel.db"

CHANNELS = {
    "FLIGHT_POST": 1466546720627233053,
    "APPROVALS": 1518123275945906186,
    "COMMAND_LOGS": 1518123298586890250,
    "JOIN_TIME_VOICE": 1518123638841282580,
    "RECRUITMENT": 1518166429138948206,
}

HIGH_RANK_REFERENCE_ROLE_ID = 1466425545880506421
RECRUITMENT_PING_ROLE_ID = 1466425534979510569

QUALIFICATION_ROLES = {
    "cabin_crew": 1466543690121085030,
    "ground_crew": 1466544003343319040,
    "flight_deck": 1466544037262524567,
    "cabin_manager": 1466532500657410280,
    "tarmac_supervisor": 1466532504008917217,
    "supervisor": 1466425547390189599,
}

ROLE_RULES = {
    "supervisor": {"label": "Supervisor", "required_role": QUALIFICATION_ROLES["supervisor"], "max": 1},
    "cabin_manager": {"label": "Cabin Manager", "required_role": QUALIFICATION_ROLES["cabin_manager"], "max": 1},
    "tarmac_supervisor": {"label": "Tarmac Supervisor", "required_role": QUALIFICATION_ROLES["tarmac_supervisor"], "max": 1},
    "captain": {"label": "Captain", "required_role": QUALIFICATION_ROLES["flight_deck"], "max": 1},
    "first_officer": {"label": "First Officer", "required_role": QUALIFICATION_ROLES["flight_deck"], "max": 1},
    "cabin_crew": {"label": "Cabin Crew", "required_role": QUALIFICATION_ROLES["cabin_crew"], "max": 4},
    "ground_crew": {"label": "Ground Crew", "required_role": QUALIFICATION_ROLES["ground_crew"], "max": 3},
}

EMOJIS = {
    "TAIL": "<:airserbiatail:1505191118596477019>",
    "BULLET": "<:WhiteBullet:1505191049272754426>",
    "ARROW_UP_RIGHT": "<:emoji_32:1505190821534634125>",
    "ARROW_RIGHT": "<:emoji_31:1505190807940890635>",
    "ARROW_DOWN": "<:emoji_30:1505190792908640306>",
    "CHAT": "<:emoji_29:1505190763011768440>",
    "GRID": "<:emoji_28:1505190726596694037>",
    "VERIFIED": "<:emoji_27:1505190710238777433>",
    "CIRCLE": "<:emoji_25:1505190674276945970>",
    "PERSON": "<:emoji_24:1505190652206518313>",
    "DATABASE": "<:emoji_23:1505190622292742214>",
    "PLUS": "<:emoji_22:1505190601296183366>",
    "INFO": "<:emoji_21:1505190460636004462>",
    "PLAY": "<:emoji_20:1505190432559206461>",
    "MINUS": "<:emoji_19:1505190409192603699>",
    "LOADING": "<:emoji_18:1505190341354197043>",
    "IDEA": "<:emoji_17:1505190323016568993>",
    "BOOKMARK": "<:emoji_16:1505190304691650560>",
    "MESSAGE": "<:emoji_15:1505190257887412245>",
    "IMAGE": "<:emoji_14:1505190236425027674>",
    "THUMBS_UP": "<:emoji_13:1505190211183841286>",
    "DEPARTMENT": "<:emoji_12:1505190182628884550>",
    "ROBLOX": "<:emoji_11:1505190159526658139>",
    "LIGHTNING": "<:emoji_10:1505190124059758623>",
    "MEDICAL": "<:emoji_9:1505190097232986163>",
    "SUCCESS_STARS": "<:AFP33:1467293527150170278>",
    "PERSONNEL": "<:AFP32:1467293502369955992>",
    "OPERATIONS": "<:AFP31:1467293479326584852>",
    "RECRUITMENT": "<:AFP29:1467293422753812764>",
    "FLIGHT": "<:AFP28:1467293400331059465>",
}

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATABASE
# =========================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees (
                discord_id TEXT PRIMARY KEY,
                roblox_username TEXT,
                roblox_id TEXT,
                rank TEXT,
                employee_id TEXT,
                status TEXT DEFAULT 'Active',
                flight_points INTEGER DEFAULT 0,
                flights_attended INTEGER DEFAULT 0,
                flights_hosted INTEGER DEFAULT 0,
                loas INTEGER DEFAULT 0,
                resignations INTEGER DEFAULT 0,
                warnings INTEGER DEFAULT 0,
                commendations INTEGER DEFAULT 0,
                promotions INTEGER DEFAULT 0,
                demotions INTEGER DEFAULT 0,
                terminations INTEGER DEFAULT 0,
                performance_reviews INTEGER DEFAULT 0,
                latest_rating TEXT,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT,
                action TEXT,
                details TEXT,
                actor_id TEXT,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS flights (
                flight_id TEXT PRIMARY KEY,
                flight_number TEXT,
                route TEXT,
                host_id TEXT,
                join_timestamp INTEGER,
                game_link TEXT,
                thread_id TEXT,
                message_id TEXT,
                join_announced INTEGER DEFAULT 0,
                attendance_dm_sent INTEGER DEFAULT 0,
                attendance_submitted INTEGER DEFAULT 0,
                created_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS flight_assignments (
                flight_id TEXT,
                discord_id TEXT,
                role_key TEXT,
                role_label TEXT,
                PRIMARY KEY (flight_id, discord_id)
            );
            """
        )
        # Add columns safely if the DB was created by an older version.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(employees)").fetchall()}
        needed = {
            "demotions": "INTEGER DEFAULT 0",
            "terminations": "INTEGER DEFAULT 0",
            "performance_reviews": "INTEGER DEFAULT 0",
            "latest_rating": "TEXT",
        }
        for col, ddl in needed.items():
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE employees ADD COLUMN {col} {ddl}")


def make_employee_id(discord_id: int | str) -> str:
    return f"AS-{str(discord_id)[-6:]}"


def clean_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if not re.match(r"^https?://", url):
        return ""
    return url


def roblox_profile_link(roblox_id: str) -> str:
    return f"https://www.roblox.com/users/{roblox_id}/profile"


async def get_roblox_headshot_url(roblox_id: str) -> str | None:
    if not roblox_id or not str(roblox_id).isdigit():
        return None
    url = (
        "https://thumbnails.roblox.com/v1/users/avatar-headshot"
        f"?userIds={roblox_id}&size=420x420&format=Png&isCircular=false"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                data = await response.json()
                return data.get("data", [{}])[0].get("imageUrl")
    except Exception as exc:
        print(f"Roblox thumbnail fetch failed: {exc}")
        return None


def ensure_employee(discord_id: int | str, rank: str = "Not Set"):
    with db() as conn:
        row = conn.execute("SELECT * FROM employees WHERE discord_id = ?", (str(discord_id),)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO employees (discord_id, rank, employee_id, status, created_at)
                VALUES (?, ?, ?, 'Active', ?)
                """,
                (str(discord_id), rank, make_employee_id(discord_id), now_ts()),
            )


def add_record(discord_id: int | str, action: str, details: str, actor_id: int | str | None = None):
    ensure_employee(discord_id)
    with db() as conn:
        conn.execute(
            "INSERT INTO records (discord_id, action, details, actor_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(discord_id), action, details, str(actor_id) if actor_id else None, now_ts()),
        )


def get_employee(discord_id: int | str):
    with db() as conn:
        return conn.execute("SELECT * FROM employees WHERE discord_id = ?", (str(discord_id),)).fetchone()


async def get_channel(guild: discord.Guild, channel_id: int):
    ch = guild.get_channel(channel_id)
    if ch is None:
        ch = await guild.fetch_channel(channel_id)
    return ch


async def send_log(guild: discord.Guild, title: str, description: str):
    try:
        channel = await get_channel(guild, CHANNELS["COMMAND_LOGS"])
        embed = discord.Embed(
            title=f"{EMOJIS['DATABASE']} {title}",
            description=description,
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Air Serbia Bot Logs")
        await channel.send(embeds=[embed], allowed_mentions=discord.AllowedMentions.none())
    except Exception as exc:
        print(f"Failed to send log: {exc}")


async def is_higher_rank(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    reference_role = member.guild.get_role(HIGH_RANK_REFERENCE_ROLE_ID)
    if reference_role is None:
        return False
    return member.top_role.position > reference_role.position


async def require_higher_rank(interaction: discord.Interaction) -> bool:
    member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)
    if await is_higher_rank(member):
        return True
    await interaction.response.send_message(
        embed=error_embed(
            "Access Denied",
            f"{EMOJIS['BULLET']} This command can only be used by personnel above <@&{HIGH_RANK_REFERENCE_ROLE_ID}>.",
        ),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return False

# =========================
# EMBEDS
# =========================
def interface_embed(module: str, command_name: str, lines: list[str]) -> discord.Embed:
    desc = f"{EMOJIS['LOADING']} **Connecting to Air Serbia {module} Core...**\n"
    desc += f"{EMOJIS['BULLET']} Verifying user credentials...\n"
    desc += f"{EMOJIS['BULLET']} Checking command authorization...\n"
    desc += f"{EMOJIS['BULLET']} Preparing `{command_name}` interface...\n\n"
    desc += "\n".join(f"{EMOJIS['BULLET']} {line}" for line in lines)
    embed = discord.Embed(
        title=f"{EMOJIS['TAIL']} Air Serbia Command Interface",
        description=desc,
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Personnel Core")
    return embed


def success_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{EMOJIS['VERIFIED']} {title}",
        description=description,
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Personnel Core")
    return embed


def error_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{EMOJIS['INFO']} {title}",
        description=description,
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Personnel Core")
    return embed

# =========================
# VIEWS
# =========================
class OpenFormView(discord.ui.View):
    def __init__(self, custom_id: str, label: str):
        super().__init__(timeout=180)
        self.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=custom_id))


def approval_view(kind: str, requester_id: int | str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"approval:{kind}:approve:{requester_id}"))
    view.add_item(discord.ui.Button(label="Reject", emoji="✖️", style=discord.ButtonStyle.danger, custom_id=f"approval:{kind}:reject:{requester_id}"))
    return view


class RecruitmentApplyView(discord.ui.View):
    def __init__(self, position: str):
        super().__init__(timeout=None)
        safe_position = position[:80].replace(":", "-")
        self.add_item(discord.ui.Button(label="Apply", style=discord.ButtonStyle.primary, custom_id=f"recruit_apply:{safe_position}"))

# =========================
# MODALS
# =========================
class RegisterModal(discord.ui.Modal, title="Air Serbia Personnel Registration"):
    roblox_username = discord.ui.TextInput(label="Roblox Username", placeholder="Example: ArjunPilot", required=True, max_length=50)
    roblox_id = discord.ui.TextInput(label="Roblox ID", placeholder="Example: 123456789", required=True, max_length=25)
    rank = discord.ui.TextInput(label="Current Rank", placeholder="Example: Cabin Crew", required=True, max_length=80)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.roblox_id.value.isdigit():
            return await interaction.response.send_message(embed=error_embed("Invalid Roblox ID", f"{EMOJIS['BULLET']} Roblox ID must contain numbers only."), ephemeral=True)

        with db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO employees
                (discord_id, roblox_username, roblox_id, rank, employee_id, status, created_at)
                VALUES (?, ?, ?, ?, COALESCE((SELECT employee_id FROM employees WHERE discord_id = ?), ?), 'Pending Review', COALESCE((SELECT created_at FROM employees WHERE discord_id = ?), ?))
                """,
                (str(interaction.user.id), self.roblox_username.value, self.roblox_id.value, self.rank.value,
                 str(interaction.user.id), make_employee_id(interaction.user.id), str(interaction.user.id), now_ts()),
            )
        add_record(interaction.user.id, "Registration Submitted", f"Roblox: {self.roblox_username.value} ({self.roblox_id.value}) | Rank: {self.rank.value}", interaction.user.id)

        embed = discord.Embed(
            title=f"{EMOJIS['PERSONNEL']} New Personnel Registration",
            description=(
                f"{EMOJIS['DATABASE']} **A new personnel registration has been submitted.**\n\n"
                f"{EMOJIS['BULLET']} **Discord User:** {interaction.user.mention}\n"
                f"{EMOJIS['BULLET']} **Discord ID:** `{interaction.user.id}`\n"
                f"{EMOJIS['BULLET']} **Roblox Username:** `{self.roblox_username.value}`\n"
                f"{EMOJIS['BULLET']} **Roblox ID:** `{self.roblox_id.value}`\n"
                f"{EMOJIS['BULLET']} **Rank:** `{self.rank.value}`\n"
                f"{EMOJIS['BULLET']} **Roblox Profile:** [View Profile]({roblox_profile_link(self.roblox_id.value)})\n\n"
                f"{EMOJIS['INFO']} **Status:** Pending Personnel Review"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        headshot = await get_roblox_headshot_url(self.roblox_id.value)
        if headshot:
            embed.set_thumbnail(url=headshot)
        embed.set_footer(text="Air Serbia Personnel Core")

        approval_channel = await get_channel(interaction.guild, CHANNELS["APPROVALS"])
        await approval_channel.send(embeds=[embed], view=approval_view("register", interaction.user.id), allowed_mentions=discord.AllowedMentions.none())

        await interaction.response.send_message(
            embed=success_embed("Registration Submitted", f"{EMOJIS['BULLET']} Your personnel registration has been submitted for review."),
            ephemeral=True,
        )
        await send_log(interaction.guild, "Command Log", f"{EMOJIS['BULLET']} **Command:** `/register`\n{EMOJIS['BULLET']} **User:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Status:** Submitted")


class LOAModal(discord.ui.Modal, title="Leave of Absence Request"):
    reason = discord.ui.TextInput(label="Reason for Leave", style=discord.TextStyle.paragraph, required=True, max_length=900)
    start_date = discord.ui.TextInput(label="Start Date", placeholder="Example: 25 June 2026", required=True, max_length=60)
    end_date = discord.ui.TextInput(label="End Date", placeholder="Example: 30 June 2026", required=True, max_length=60)
    department = discord.ui.TextInput(label="Department / Rank", placeholder="Example: Cabin Crew", required=True, max_length=100)
    contact = discord.ui.TextInput(label="Can you be contacted?", placeholder="Yes / No + extra information", required=True, max_length=150)

    async def on_submit(self, interaction: discord.Interaction):
        ensure_employee(interaction.user.id)
        with db() as conn:
            conn.execute("UPDATE employees SET loas = loas + 1 WHERE discord_id = ?", (str(interaction.user.id),))
        add_record(interaction.user.id, "LOA Submitted", f"{self.start_date.value} to {self.end_date.value} | {self.reason.value}", interaction.user.id)
        embed = discord.Embed(
            title=f"{EMOJIS['PERSONNEL']} LOA Request Submitted",
            description=(
                f"{EMOJIS['DATABASE']} **A Leave of Absence request requires review.**\n\n"
                f"{EMOJIS['BULLET']} **Employee:** {interaction.user.mention}\n"
                f"{EMOJIS['BULLET']} **Department / Rank:** `{self.department.value}`\n"
                f"{EMOJIS['BULLET']} **Start Date:** `{self.start_date.value}`\n"
                f"{EMOJIS['BULLET']} **End Date:** `{self.end_date.value}`\n"
                f"{EMOJIS['BULLET']} **Contact During Leave:** `{self.contact.value}`\n\n"
                f"{EMOJIS['MESSAGE']} **Reason**\n{self.reason.value}"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Air Serbia Personnel Core")
        ch = await get_channel(interaction.guild, CHANNELS["APPROVALS"])
        await ch.send(embeds=[embed], view=approval_view("loa", interaction.user.id), allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message(embed=success_embed("LOA Submitted", f"{EMOJIS['BULLET']} Your LOA request has been sent to Personnel for review."), ephemeral=True)
        await send_log(interaction.guild, "Command Log", f"{EMOJIS['BULLET']} **Command:** `/loa`\n{EMOJIS['BULLET']} **User:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Status:** Submitted")


class ResignationModal(discord.ui.Modal, title="Personnel Resignation Request"):
    reason = discord.ui.TextInput(label="Reason for Resignation", style=discord.TextStyle.paragraph, required=True, max_length=900)
    department = discord.ui.TextInput(label="Department", placeholder="Example: Cabin Crew", required=True, max_length=100)
    rank = discord.ui.TextInput(label="Current Rank", placeholder="Example: Senior Cabin Crew", required=True, max_length=100)
    last_day = discord.ui.TextInput(label="Last Working Day", placeholder="Example: 30 June 2026", required=True, max_length=60)
    comments = discord.ui.TextInput(label="Additional Comments", style=discord.TextStyle.paragraph, required=False, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        ensure_employee(interaction.user.id)
        with db() as conn:
            conn.execute("UPDATE employees SET resignations = resignations + 1 WHERE discord_id = ?", (str(interaction.user.id),))
        add_record(interaction.user.id, "Resignation Submitted", f"Last working day: {self.last_day.value} | Reason: {self.reason.value}", interaction.user.id)
        embed = discord.Embed(
            title=f"{EMOJIS['PERSONNEL']} Resignation Request Submitted",
            description=(
                f"{EMOJIS['DATABASE']} **A resignation request requires review.**\n\n"
                f"{EMOJIS['BULLET']} **Employee:** {interaction.user.mention}\n"
                f"{EMOJIS['BULLET']} **Department:** `{self.department.value}`\n"
                f"{EMOJIS['BULLET']} **Rank:** `{self.rank.value}`\n"
                f"{EMOJIS['BULLET']} **Last Working Day:** `{self.last_day.value}`\n\n"
                f"{EMOJIS['MESSAGE']} **Reason**\n{self.reason.value}\n\n"
                f"{EMOJIS['INFO']} **Additional Comments**\n{self.comments.value or 'None provided.'}"
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Air Serbia Personnel Core")
        ch = await get_channel(interaction.guild, CHANNELS["APPROVALS"])
        await ch.send(embeds=[embed], view=approval_view("resignation", interaction.user.id), allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message(embed=success_embed("Resignation Submitted", f"{EMOJIS['BULLET']} Your resignation request has been sent to Personnel for review."), ephemeral=True)
        await send_log(interaction.guild, "Command Log", f"{EMOJIS['BULLET']} **Command:** `/resignation`\n{EMOJIS['BULLET']} **User:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Status:** Submitted")


class PostFlightModal(discord.ui.Modal, title="Air Serbia Flight Posting"):
    flight_number = discord.ui.TextInput(label="Flight Number", placeholder="Example: AS123", required=True, max_length=25)
    route = discord.ui.TextInput(label="Route", placeholder="Example: BEG → LHR", required=True, max_length=100)
    host_id = discord.ui.TextInput(label="Host Discord ID", placeholder="Paste the host's Discord User ID", required=True, max_length=25)
    join_timestamp = discord.ui.TextInput(label="Join Timestamp", placeholder="Unix timestamp, example: 1750507200", required=True, max_length=20)
    game_link = discord.ui.TextInput(label="Game / Private Server Link", placeholder="https://www.roblox.com/games/...")

    async def on_submit(self, interaction: discord.Interaction):
        if not self.host_id.value.isdigit() or not self.join_timestamp.value.isdigit():
            return await interaction.response.send_message(embed=error_embed("Invalid Details", f"{EMOJIS['BULLET']} Host ID and Join Timestamp must be numbers only."), ephemeral=True)
        game_link = clean_url(self.game_link.value)
        if not game_link:
            return await interaction.response.send_message(embed=error_embed("Invalid Link", f"{EMOJIS['BULLET']} Please provide a valid `https://` game/private server link."), ephemeral=True)

        flight_id = f"{self.flight_number.value.upper()}-{now_ts()}"
        join_ts = int(self.join_timestamp.value)
        host_id = int(self.host_id.value)

        flight_embed = make_flight_embed(self.flight_number.value.upper(), self.route.value, host_id, join_ts, game_link, flight_id)

        flight_channel = await get_channel(interaction.guild, CHANNELS["FLIGHT_POST"])
        message = await flight_channel.send(content="@everyone", embeds=[flight_embed], allowed_mentions=discord.AllowedMentions(everyone=True))
        thread_name = f"{self.flight_number.value.upper()} • {self.route.value}"
        thread = await message.create_thread(name=thread_name[:100], auto_archive_duration=1440)

        with db() as conn:
            conn.execute(
                """
                INSERT INTO flights
                (flight_id, flight_number, route, host_id, join_timestamp, game_link, thread_id, message_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (flight_id, self.flight_number.value.upper(), self.route.value, str(host_id), join_ts, game_link, str(thread.id), str(message.id), now_ts()),
            )

        await thread.send(content="@everyone", embeds=[flight_embed], view=flight_allocation_view(flight_id), allowed_mentions=discord.AllowedMentions(everyone=True))

        await interaction.response.send_message(embed=success_embed("Flight Posted", f"{EMOJIS['BULLET']} Flight `{self.flight_number.value.upper()}` has been posted and the allocation thread has been created."), ephemeral=True)
        await send_log(interaction.guild, "Command Log", f"{EMOJIS['BULLET']} **Command:** `/postflight`\n{EMOJIS['BULLET']} **User:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Flight:** `{self.flight_number.value.upper()}`\n{EMOJIS['BULLET']} **Thread:** <#{thread.id}>\n{EMOJIS['BULLET']} **Status:** Flight posted")

# =========================
# FLIGHT SYSTEM
# =========================
def get_assignments(flight_id: str):
    with db() as conn:
        rows = conn.execute("SELECT * FROM flight_assignments WHERE flight_id = ?", (flight_id,)).fetchall()
    return [dict(r) for r in rows]


def role_counts(assignments: list[dict]) -> dict:
    counts = {key: 0 for key in ROLE_RULES}
    users = {key: [] for key in ROLE_RULES}
    for row in assignments:
        counts[row["role_key"]] = counts.get(row["role_key"], 0) + 1
        users.setdefault(row["role_key"], []).append(f"<@{row['discord_id']}>")
    return {"counts": counts, "users": users}


def role_line(role_key: str, counts_data: dict) -> str:
    rule = ROLE_RULES[role_key]
    users = counts_data["users"].get(role_key, [])
    if rule["max"] == 1:
        return users[0] if users else "Not Assigned"
    return f"{len(users)} / {rule['max']}" + (f" — {', '.join(users)}" if users else "")


def make_flight_embed(flight_number: str, route: str, host_id: int, join_timestamp: int, game_link: str, flight_id: str) -> discord.Embed:
    assignments = get_assignments(flight_id)
    counts_data = role_counts(assignments)
    embed = discord.Embed(
        title=f"{EMOJIS['FLIGHT']} New Flight Scheduled",
        description=(
            f"{EMOJIS['OPERATIONS']} **A new operational flight has been scheduled.**\n\n"
            f"{EMOJIS['BULLET']} **Flight Number:** `{flight_number}`\n"
            f"{EMOJIS['BULLET']} **Route:** `{route}`\n"
            f"{EMOJIS['BULLET']} **Host:** <@{host_id}>\n"
            f"{EMOJIS['BULLET']} **Join Time:** <t:{join_timestamp}:F>\n"
            f"{EMOJIS['BULLET']} **Game Link:** [Join Experience]({game_link})\n\n"
            f"**{EMOJIS['PERSONNEL']} Supervisors**\n"
            f"{EMOJIS['BULLET']} Supervisor: {role_line('supervisor', counts_data)}\n\n"
            f"**{EMOJIS['DEPARTMENT']} Managers**\n"
            f"{EMOJIS['BULLET']} Cabin Manager: {role_line('cabin_manager', counts_data)}\n"
            f"{EMOJIS['BULLET']} Tarmac Supervisor: {role_line('tarmac_supervisor', counts_data)}\n\n"
            f"**{EMOJIS['FLIGHT']} Crew**\n"
            f"{EMOJIS['BULLET']} Captain: {role_line('captain', counts_data)}\n"
            f"{EMOJIS['BULLET']} First Officer: {role_line('first_officer', counts_data)}\n"
            f"{EMOJIS['BULLET']} Cabin Crew: {role_line('cabin_crew', counts_data)}\n"
            f"{EMOJIS['BULLET']} Ground Crew: {role_line('ground_crew', counts_data)}\n\n"
            f"{EMOJIS['INFO']} **Status:** Crew Allocation Open"
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Flight Operations Core")
    return embed


def flight_allocation_view(flight_id: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    options = [discord.SelectOption(label=rule["label"], value=key, description=f"Allocate as {rule['label']}") for key, rule in ROLE_RULES.items()]
    select = discord.ui.Select(custom_id=f"allocate_role:{flight_id}", placeholder="Select your flight position", min_values=1, max_values=1, options=options)
    view.add_item(select)
    return view


async def handle_allocation(interaction: discord.Interaction, flight_id: str, role_key: str):
    if role_key not in ROLE_RULES:
        return await interaction.response.send_message(embed=error_embed("Invalid Position", f"{EMOJIS['BULLET']} This position is not recognized."), ephemeral=True)

    rule = ROLE_RULES[role_key]
    member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)
    member_role_ids = {r.id for r in member.roles}

    if rule["required_role"] not in member_role_ids:
        return await interaction.response.send_message(embed=error_embed("Access Denied", f"{EMOJIS['BULLET']} You do not hold the required qualification for **{rule['label']}**."), ephemeral=True)

    with db() as conn:
        flight = conn.execute("SELECT * FROM flights WHERE flight_id = ?", (flight_id,)).fetchone()
        if not flight:
            return await interaction.response.send_message(embed=error_embed("Flight Not Found", f"{EMOJIS['BULLET']} This flight record could not be found."), ephemeral=True)

        existing = conn.execute("SELECT * FROM flight_assignments WHERE flight_id = ? AND discord_id = ?", (flight_id, str(interaction.user.id))).fetchone()
        if existing:
            return await interaction.response.send_message(embed=error_embed("Already Allocated", f"{EMOJIS['BULLET']} You are already allocated as **{existing['role_label']}** for this flight."), ephemeral=True)

        count = conn.execute("SELECT COUNT(*) AS c FROM flight_assignments WHERE flight_id = ? AND role_key = ?", (flight_id, role_key)).fetchone()["c"]
        if count >= rule["max"]:
            return await interaction.response.send_message(embed=error_embed("Position Full", f"{EMOJIS['BULLET']} **{rule['label']}** is already full."), ephemeral=True)

        conn.execute("INSERT INTO flight_assignments (flight_id, discord_id, role_key, role_label) VALUES (?, ?, ?, ?)", (flight_id, str(interaction.user.id), role_key, rule["label"]))
        updated_flight = dict(flight)

    embed = make_flight_embed(updated_flight["flight_number"], updated_flight["route"], int(updated_flight["host_id"]), int(updated_flight["join_timestamp"]), updated_flight["game_link"], flight_id)
    await interaction.message.edit(embeds=[embed], view=flight_allocation_view(flight_id))
    await interaction.response.send_message(embed=success_embed("Position Allocated", f"{EMOJIS['BULLET']} You have been allocated as **{rule['label']}** for flight `{updated_flight['flight_number']}`."), ephemeral=True)
    await send_log(interaction.guild, "Flight Allocation", f"{EMOJIS['BULLET']} **User:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Flight:** `{updated_flight['flight_number']}`\n{EMOJIS['BULLET']} **Position:** `{rule['label']}`")


async def announce_join_time(guild: discord.Guild, flight: sqlite3.Row):
    try:
        thread = await guild.fetch_channel(int(flight["thread_id"]))
        embed = discord.Embed(
            title=f"{EMOJIS['FLIGHT']} Join Time Commenced",
            description=(
                f"{EMOJIS['OPERATIONS']} **The joining phase for this flight has now started.**\n\n"
                f"{EMOJIS['BULLET']} **Flight Number:** `{flight['flight_number']}`\n"
                f"{EMOJIS['BULLET']} **Route:** `{flight['route']}`\n"
                f"{EMOJIS['BULLET']} **Host:** <@{flight['host_id']}>\n"
                f"{EMOJIS['BULLET']} **Join Time:** <t:{flight['join_timestamp']}:F>\n\n"
                f"{EMOJIS['INFO']} **Game Link:** [Join Experience]({flight['game_link']})\n\n"
                f"{EMOJIS['VERIFIED']} All assigned crew members are requested to join immediately."
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Air Serbia Flight Operations Core")
        await thread.send(content="@everyone", embeds=[embed], allowed_mentions=discord.AllowedMentions(everyone=True))

        voice_channel = await get_channel(guild, CHANNELS["JOIN_TIME_VOICE"])
        if isinstance(voice_channel, discord.VoiceChannel):
            try:
                await voice_channel.connect(self_deaf=False, self_mute=False)
            except discord.ClientException:
                pass
            except Exception as exc:
                print(f"Voice join failed: {exc}")

        with db() as conn:
            conn.execute("UPDATE flights SET join_announced = 1 WHERE flight_id = ?", (flight["flight_id"],))
        await send_log(guild, "Automatic Join Time", f"{EMOJIS['BULLET']} **Flight:** `{flight['flight_number']}`\n{EMOJIS['BULLET']} **Thread:** <#{flight['thread_id']}>\n{EMOJIS['BULLET']} **Status:** Join time announced")
    except Exception as exc:
        print(f"Join-time announcement failed: {exc}")


def attendance_view(flight_id: str, assignments: list[dict]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    if not assignments:
        return view
    options = []
    for row in assignments[:25]:
        options.append(discord.SelectOption(label=f"{row['role_label']} • {row['discord_id']}"[:100], value=str(row["discord_id"]), description="Select if this staff member attended"))
    select = discord.ui.Select(custom_id=f"attendance:{flight_id}", placeholder="Select staff members who attended", min_values=0, max_values=len(options), options=options)
    view.add_item(select)
    return view


async def send_attendance_dm(guild: discord.Guild, flight: sqlite3.Row):
    try:
        host = await guild.fetch_member(int(flight["host_id"]))
        assignments = get_assignments(flight["flight_id"])
        embed = discord.Embed(
            title=f"{EMOJIS['FLIGHT']} Flight Attendance Review",
            description=(
                f"{EMOJIS['OPERATIONS']} **Please submit the attendance record for this flight.**\n\n"
                f"{EMOJIS['BULLET']} **Flight Number:** `{flight['flight_number']}`\n"
                f"{EMOJIS['BULLET']} **Route:** `{flight['route']}`\n"
                f"{EMOJIS['BULLET']} **Host:** <@{flight['host_id']}>\n\n"
                f"{EMOJIS['INFO']} Tick/select the staff who **attended**. Anyone not selected will receive **0 flight points**.\n"
                f"{EMOJIS['INFO']} Selected crew receive **+1 flight point**. Host receives **+2 flight points**."
            ),
            color=EMBED_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Air Serbia Flight Operations Core")
        await host.send(embeds=[embed], view=attendance_view(flight["flight_id"], assignments), allowed_mentions=discord.AllowedMentions.none())
        with db() as conn:
            conn.execute("UPDATE flights SET attendance_dm_sent = 1 WHERE flight_id = ?", (flight["flight_id"],))
        await send_log(guild, "Attendance DM Sent", f"{EMOJIS['BULLET']} **Flight:** `{flight['flight_number']}`\n{EMOJIS['BULLET']} **Host:** <@{flight['host_id']}>`")
    except Exception as exc:
        print(f"Attendance DM failed: {exc}")


async def handle_attendance(interaction: discord.Interaction, flight_id: str, selected_ids: list[str]):
    with db() as conn:
        flight = conn.execute("SELECT * FROM flights WHERE flight_id = ?", (flight_id,)).fetchone()
        if not flight:
            return await interaction.response.send_message(embed=error_embed("Flight Not Found", f"{EMOJIS['BULLET']} This flight record could not be found."), ephemeral=True)
        if str(interaction.user.id) != str(flight["host_id"]):
            return await interaction.response.send_message(embed=error_embed("Access Denied", f"{EMOJIS['BULLET']} Only the flight host can submit attendance."), ephemeral=True)
        if int(flight["attendance_submitted"] or 0) == 1:
            return await interaction.response.send_message(embed=error_embed("Already Submitted", f"{EMOJIS['BULLET']} Attendance has already been submitted for this flight."), ephemeral=True)

        for uid in selected_ids:
            ensure_employee(uid)
            conn.execute("UPDATE employees SET flight_points = flight_points + 1, flights_attended = flights_attended + 1 WHERE discord_id = ?", (str(uid),))
            conn.execute("INSERT INTO records (discord_id, action, details, actor_id, created_at) VALUES (?, ?, ?, ?, ?)", (str(uid), "Flight Attended", f"{flight['flight_number']} | {flight['route']} | +1 point", str(interaction.user.id), now_ts()))

        ensure_employee(flight["host_id"])
        conn.execute("UPDATE employees SET flight_points = flight_points + 2, flights_hosted = flights_hosted + 1 WHERE discord_id = ?", (str(flight["host_id"]),))
        conn.execute("INSERT INTO records (discord_id, action, details, actor_id, created_at) VALUES (?, ?, ?, ?, ?)", (str(flight["host_id"]), "Flight Hosted", f"{flight['flight_number']} | {flight['route']} | +2 points", str(interaction.user.id), now_ts()))
        conn.execute("UPDATE flights SET attendance_submitted = 1 WHERE flight_id = ?", (flight_id,))

    selected_text = "\n".join(f"{EMOJIS['BULLET']} <@{uid}>" for uid in selected_ids) or f"{EMOJIS['BULLET']} No crew selected."
    embed = success_embed(
        "Attendance Submitted",
        f"{EMOJIS['BULLET']} Attendance has been submitted successfully.\n"
        f"{EMOJIS['BULLET']} Selected crew received **+1 flight point**.\n"
        f"{EMOJIS['BULLET']} Host received **+2 flight points**.\n\n"
        f"**Attended Crew**\n{selected_text}",
    )
    await interaction.response.edit_message(embeds=[embed], view=None)
    await send_log(interaction.guild, "Attendance Submitted", f"{EMOJIS['BULLET']} **Flight:** `{flight['flight_number']}`\n{EMOJIS['BULLET']} **Host:** <@{flight['host_id']}>\n{EMOJIS['BULLET']} **Crew Selected:** `{len(selected_ids)}`")


@tasks.loop(seconds=30)
async def flight_scheduler():
    if not bot.guilds:
        return
    guild = bot.get_guild(GUILD_ID) or bot.guilds[0]
    current = now_ts()
    with db() as conn:
        join_rows = conn.execute("SELECT * FROM flights WHERE join_announced = 0 AND join_timestamp <= ?", (current,)).fetchall()
        attendance_rows = conn.execute("SELECT * FROM flights WHERE attendance_dm_sent = 0 AND join_timestamp + 3600 <= ?", (current,)).fetchall()
    for row in join_rows:
        await announce_join_time(guild, row)
    for row in attendance_rows:
        await send_attendance_dm(guild, row)

# =========================
# COMPONENT HANDLERS
# =========================
async def handle_approval(interaction: discord.Interaction, kind: str, decision: str, requester_id: str):
    member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)
    if not await is_higher_rank(member):
        return await interaction.response.send_message(embed=error_embed("Access Denied", f"{EMOJIS['BULLET']} You are not authorized to review this request."), ephemeral=True)

    label = "Approved" if decision == "approve" else "Rejected"
    requester = await interaction.guild.fetch_member(int(requester_id)).catch() if False else None

    with db() as conn:
        if kind == "register":
            conn.execute("UPDATE employees SET status = ? WHERE discord_id = ?", ("Active" if decision == "approve" else "Rejected", str(requester_id)))
        elif kind == "resignation" and decision == "approve":
            conn.execute("UPDATE employees SET status = 'Resigned' WHERE discord_id = ?", (str(requester_id),))
        conn.execute("INSERT INTO records (discord_id, action, details, actor_id, created_at) VALUES (?, ?, ?, ?, ?)", (str(requester_id), f"{kind.title()} {label}", f"Reviewed by {interaction.user.id}", str(interaction.user.id), now_ts()))

    embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(color=EMBED_COLOR)
    embed.color = EMBED_COLOR
    embed.add_field(name=f"{EMOJIS['VERIFIED']} Review Decision", value=f"{EMOJIS['BULLET']} **Decision:** `{label}`\n{EMOJIS['BULLET']} **Reviewer:** {interaction.user.mention}\n{EMOJIS['BULLET']} **Time:** <t:{now_ts()}:F>", inline=False)
    try:
        user = await bot.fetch_user(int(requester_id))
        dm_embed = success_embed(f"Request {label}", f"{EMOJIS['BULLET']} Your **{kind}** request has been **{label.lower()}**.\n{EMOJIS['BULLET']} **Reviewer:** {interaction.user.mention}")
        await user.send(embed=dm_embed)
    except Exception:
        pass
    await interaction.response.edit_message(embeds=[embed], view=None, allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Approval Review", f"{EMOJIS['BULLET']} **Type:** `{kind}`\n{EMOJIS['BULLET']} **Decision:** `{label}`\n{EMOJIS['BULLET']} **Requester:** <@{requester_id}>\n{EMOJIS['BULLET']} **Reviewer:** {interaction.user.mention}")


async def handle_recruit_apply(interaction: discord.Interaction, position: str):
    ch = await get_channel(interaction.guild, CHANNELS["APPROVALS"])
    embed = discord.Embed(
        title=f"{EMOJIS['RECRUITMENT']} New Recruitment Application",
        description=(
            f"{EMOJIS['DATABASE']} **A new applicant has applied for recruitment.**\n\n"
            f"{EMOJIS['BULLET']} **Applicant:** {interaction.user.mention}\n"
            f"{EMOJIS['BULLET']} **Discord ID:** `{interaction.user.id}`\n"
            f"{EMOJIS['BULLET']} **Position:** `{position}`\n\n"
            f"{EMOJIS['INFO']} The department may DM the applicant and conduct the interview manually."
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Recruitment Core")
    await ch.send(content=f"<@&{RECRUITMENT_PING_ROLE_ID}>", embeds=[embed], allowed_mentions=discord.AllowedMentions(roles=True))
    await interaction.response.send_message(embed=success_embed("Application Sent", f"{EMOJIS['BULLET']} Your application for **{position}** has been submitted."), ephemeral=True)
    await send_log(interaction.guild, "Recruitment Application", f"{EMOJIS['BULLET']} **Applicant:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Position:** `{position}`")

# =========================
# SLASH COMMANDS
# =========================
@bot.tree.command(name="register", description="Register yourself in the Air Serbia Personnel Core.")
async def register(interaction: discord.Interaction):
    await interaction.response.send_message(embed=interface_embed("Personnel", "/register", ["Opening personnel registration form.", "Prepare your Roblox username, Roblox ID, and current rank."]), view=OpenFormView("open_register_form", "Open Registration Form"), ephemeral=True)


@bot.tree.command(name="loa", description="Submit a Leave of Absence request.")
async def loa(interaction: discord.Interaction):
    await interaction.response.send_message(embed=interface_embed("Leave Management", "/loa", ["Opening LOA request form.", "Your request will be sent to Personnel approvals."]), view=OpenFormView("open_loa_form", "Open LOA Form"), ephemeral=True)


@bot.tree.command(name="resignation", description="Submit a resignation request.")
async def resignation(interaction: discord.Interaction):
    await interaction.response.send_message(embed=interface_embed("Personnel", "/resignation", ["Opening resignation request form.", "Your request will be sent to Personnel approvals."]), view=OpenFormView("open_resignation_form", "Open Resignation Form"), ephemeral=True)


@bot.tree.command(name="postflight", description="Post a flight sheet and schedule automatic join time.")
async def postflight(interaction: discord.Interaction):
    if not await require_higher_rank(interaction):
        return
    await interaction.response.send_message(embed=interface_embed("Flight Operations", "/postflight", ["Opening flight posting form.", "The flight sheet will ping @everyone.", "Join time will post automatically from this command."]), view=OpenFormView("open_postflight_form", "Open Flight Form"), ephemeral=True)


@bot.tree.command(name="profile", description="View an employee profile.")
@app_commands.describe(user="Employee to view. Leave blank for yourself.")
async def profile(interaction: discord.Interaction, user: discord.Member | None = None):
    target = user or interaction.user
    row = get_employee(target.id)
    if not row:
        return await interaction.response.send_message(embed=error_embed("Profile Not Found", f"{EMOJIS['BULLET']} This user does not have a personnel profile yet."), ephemeral=True)

    embed = discord.Embed(
        title=f"{EMOJIS['PERSONNEL']} Employee Profile",
        description=(
            f"{EMOJIS['DATABASE']} **Personnel Record**\n\n"
            f"{EMOJIS['BULLET']} **Discord User:** {target.mention}\n"
            f"{EMOJIS['BULLET']} **Employee ID:** `{row['employee_id'] or make_employee_id(target.id)}`\n"
            f"{EMOJIS['BULLET']} **Roblox Username:** `{row['roblox_username'] or 'Not Set'}`\n"
            f"{EMOJIS['BULLET']} **Roblox ID:** `{row['roblox_id'] or 'Not Set'}`\n"
            + (f"{EMOJIS['BULLET']} **Roblox Profile:** [View Profile]({roblox_profile_link(row['roblox_id'])})\n" if row["roblox_id"] else "")
            + f"{EMOJIS['BULLET']} **Rank:** `{row['rank'] or 'Not Set'}`\n"
            f"{EMOJIS['BULLET']} **Status:** `{row['status'] or 'Active'}`"
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    if row["roblox_id"]:
        headshot = await get_roblox_headshot_url(row["roblox_id"])
        if headshot:
            embed.set_thumbnail(url=headshot)
    embed.add_field(
        name=f"{EMOJIS['FLIGHT']} Flight Activity",
        value=f"{EMOJIS['BULLET']} **Flight Points:** {row['flight_points']}\n{EMOJIS['BULLET']} **Flights Attended:** {row['flights_attended']}\n{EMOJIS['BULLET']} **Flights Hosted:** {row['flights_hosted']}",
        inline=True,
    )
    embed.add_field(
        name=f"{EMOJIS['PERSONNEL']} Personnel Record",
        value=(
            f"{EMOJIS['BULLET']} **LOAs:** {row['loas']}\n"
            f"{EMOJIS['BULLET']} **Warnings:** {row['warnings']}\n"
            f"{EMOJIS['BULLET']} **Commendations:** {row['commendations']}\n"
            f"{EMOJIS['BULLET']} **Promotions:** {row['promotions']}\n"
            f"{EMOJIS['BULLET']} **Demotions:** {row['demotions']}\n"
            f"{EMOJIS['BULLET']} **Reviews:** {row['performance_reviews']}"
        ),
        inline=True,
    )
    if row["latest_rating"]:
        embed.add_field(name=f"{EMOJIS['SUCCESS_STARS']} Latest Performance Rating", value=f"`{row['latest_rating']}`", inline=False)
    embed.set_footer(text="Air Serbia Personnel Core")
    await interaction.response.send_message(embeds=[embed], allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Command Log", f"{EMOJIS['BULLET']} **Command:** `/profile`\n{EMOJIS['BULLET']} **User:** {interaction.user.mention} `{interaction.user.id}`\n{EMOJIS['BULLET']} **Viewed:** {target.mention} `{target.id}`")


@bot.tree.command(name="recruitment", description="Post a recruitment opening.")
@app_commands.describe(position="The position that is open for recruitment.")
async def recruitment(interaction: discord.Interaction, position: str):
    if not await require_higher_rank(interaction):
        return
    ch = await get_channel(interaction.guild, CHANNELS["RECRUITMENT"])
    embed = discord.Embed(
        title=f"{EMOJIS['RECRUITMENT']} Recruitment Opening",
        description=(
            f"{EMOJIS['DATABASE']} **Air Serbia is now accepting applications for a personnel position.**\n\n"
            f"{EMOJIS['BULLET']} **Position:** `{position}`\n"
            f"{EMOJIS['BULLET']} **Posted By:** {interaction.user.mention}\n\n"
            f"{EMOJIS['INFO']} Click **Apply** below to submit your name to the department. The department may then contact you for an interview."
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Recruitment Core")
    await ch.send(embeds=[embed], view=RecruitmentApplyView(position), allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message(embed=success_embed("Recruitment Posted", f"{EMOJIS['BULLET']} Recruitment for **{position}** has been posted in <#{CHANNELS['RECRUITMENT']}>."), ephemeral=True)
    await send_log(interaction.guild, "Command Log", f"{EMOJIS['BULLET']} **Command:** `/recruitment`\n{EMOJIS['BULLET']} **Position:** `{position}`\n{EMOJIS['BULLET']} **User:** {interaction.user.mention}")


@bot.tree.command(name="promote", description="Change an employee rank in their profile.")
@app_commands.describe(user="Employee", new_rank="New rank to show in their profile")
async def promote(interaction: discord.Interaction, user: discord.Member, new_rank: str):
    if not await require_higher_rank(interaction):
        return
    ensure_employee(user.id)
    with db() as conn:
        old = conn.execute("SELECT rank FROM employees WHERE discord_id = ?", (str(user.id),)).fetchone()["rank"]
        conn.execute("UPDATE employees SET rank = ?, promotions = promotions + 1, status = 'Active' WHERE discord_id = ?", (new_rank, str(user.id)))
    add_record(user.id, "Rank Updated / Promotion", f"Old rank: {old or 'Not Set'} | New rank: {new_rank}", interaction.user.id)
    await interaction.response.send_message(embed=success_embed("Rank Updated", f"{EMOJIS['BULLET']} {user.mention}'s rank has been changed to `{new_rank}`."), allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Promotion / Rank Change", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **New Rank:** `{new_rank}`\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="demote", description="Demote an employee and update their profile rank.")
@app_commands.describe(user="Employee", new_rank="New rank after demotion", reason="Reason for demotion")
async def demote(interaction: discord.Interaction, user: discord.Member, new_rank: str, reason: str):
    if not await require_higher_rank(interaction):
        return
    ensure_employee(user.id)
    with db() as conn:
        old = conn.execute("SELECT rank FROM employees WHERE discord_id = ?", (str(user.id),)).fetchone()["rank"]
        conn.execute("UPDATE employees SET rank = ?, demotions = demotions + 1 WHERE discord_id = ?", (new_rank, str(user.id)))
    add_record(user.id, "Demotion", f"Old rank: {old or 'Not Set'} | New rank: {new_rank} | Reason: {reason}", interaction.user.id)
    await interaction.response.send_message(embed=success_embed("Demotion Recorded", f"{EMOJIS['BULLET']} {user.mention}'s rank has been changed to `{new_rank}`.\n{EMOJIS['BULLET']} **Reason:** {reason}"), allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Demotion", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **New Rank:** `{new_rank}`\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="terminate", description="Terminate an employee profile.")
@app_commands.describe(user="Employee", reason="Reason for termination")
async def terminate(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not await require_higher_rank(interaction):
        return
    ensure_employee(user.id)
    with db() as conn:
        conn.execute("UPDATE employees SET status = 'Terminated', terminations = terminations + 1 WHERE discord_id = ?", (str(user.id),))
    add_record(user.id, "Termination", reason, interaction.user.id)
    await interaction.response.send_message(embed=success_embed("Termination Recorded", f"{EMOJIS['BULLET']} {user.mention} has been marked as **Terminated**.\n{EMOJIS['BULLET']} **Reason:** {reason}"), allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Termination", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **Reason:** `{reason}`\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="warning", description="Issue a warning to an employee.")
@app_commands.describe(user="Employee", category="Warning category", reason="Warning reason", evidence_link="Optional evidence link")
async def warning(interaction: discord.Interaction, user: discord.Member, category: str, reason: str, evidence_link: str | None = None):
    if not await require_higher_rank(interaction):
        return
    ensure_employee(user.id)
    link = clean_url(evidence_link)
    with db() as conn:
        conn.execute("UPDATE employees SET warnings = warnings + 1 WHERE discord_id = ?", (str(user.id),))
    details = f"Category: {category} | Reason: {reason}" + (f" | Evidence: {link}" if link else "")
    add_record(user.id, "Warning", details, interaction.user.id)
    desc = f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **Category:** `{category}`\n{EMOJIS['BULLET']} **Reason:** {reason}"
    if link:
        desc += f"\n{EMOJIS['BULLET']} **Evidence:** [View Evidence]({link})"
    await interaction.response.send_message(embed=success_embed("Warning Issued", desc), allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Warning", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **Category:** `{category}`\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="commendation", description="Give a commendation to an employee.")
@app_commands.describe(user="Employee", category="Commendation category", reason="Reason for commendation")
async def commendation(interaction: discord.Interaction, user: discord.Member, category: str, reason: str):
    if not await require_higher_rank(interaction):
        return
    ensure_employee(user.id)
    with db() as conn:
        conn.execute("UPDATE employees SET commendations = commendations + 1 WHERE discord_id = ?", (str(user.id),))
    add_record(user.id, "Commendation", f"Category: {category} | Reason: {reason}", interaction.user.id)
    await interaction.response.send_message(embed=success_embed("Commendation Recorded", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **Category:** `{category}`\n{EMOJIS['BULLET']} **Reason:** {reason}"), allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Commendation", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **Category:** `{category}`\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="performance", description="Submit a performance review for an employee.")
@app_commands.describe(user="Employee", rating="Overall rating from 1 to 10", strengths="Strengths", improvements="Areas for improvement", comments="Final comments")
async def performance(interaction: discord.Interaction, user: discord.Member, rating: app_commands.Range[int, 1, 10], strengths: str, improvements: str, comments: str):
    if not await require_higher_rank(interaction):
        return
    ensure_employee(user.id)
    with db() as conn:
        conn.execute("UPDATE employees SET performance_reviews = performance_reviews + 1, latest_rating = ? WHERE discord_id = ?", (str(rating), str(user.id)))
    add_record(user.id, "Performance Review", f"Rating: {rating}/10 | Strengths: {strengths} | Improvements: {improvements} | Comments: {comments}", interaction.user.id)
    embed = discord.Embed(
        title=f"{EMOJIS['SUCCESS_STARS']} Performance Review Submitted",
        description=(
            f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n"
            f"{EMOJIS['BULLET']} **Reviewer:** {interaction.user.mention}\n"
            f"{EMOJIS['BULLET']} **Rating:** `{rating}/10`\n\n"
            f"{EMOJIS['SUCCESS_STARS']} **Strengths**\n{strengths}\n\n"
            f"{EMOJIS['INFO']} **Areas for Improvement**\n{improvements}\n\n"
            f"{EMOJIS['MESSAGE']} **Final Comments**\n{comments}"
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Personnel Core")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Performance Review", f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n{EMOJIS['BULLET']} **Rating:** `{rating}/10`\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="backgroundcheck", description="View a background check summary for an employee.")
@app_commands.describe(user="Employee")
async def backgroundcheck(interaction: discord.Interaction, user: discord.Member):
    if not await require_higher_rank(interaction):
        return
    row = get_employee(user.id)
    if not row:
        return await interaction.response.send_message(embed=error_embed("Profile Not Found", f"{EMOJIS['BULLET']} This user has no personnel record."), ephemeral=True)
    embed = discord.Embed(
        title=f"{EMOJIS['DATABASE']} Background Check",
        description=(
            f"{EMOJIS['BULLET']} **Employee:** {user.mention}\n"
            f"{EMOJIS['BULLET']} **Rank:** `{row['rank'] or 'Not Set'}`\n"
            f"{EMOJIS['BULLET']} **Status:** `{row['status'] or 'Active'}`\n"
            f"{EMOJIS['BULLET']} **Warnings:** `{row['warnings']}`\n"
            f"{EMOJIS['BULLET']} **Commendations:** `{row['commendations']}`\n"
            f"{EMOJIS['BULLET']} **LOAs:** `{row['loas']}`\n"
            f"{EMOJIS['BULLET']} **Resignations:** `{row['resignations']}`\n"
            f"{EMOJIS['BULLET']} **Terminations:** `{row['terminations']}`\n"
            f"{EMOJIS['BULLET']} **Flight Points:** `{row['flight_points']}`\n"
        ),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Personnel Core")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Background Check", f"{EMOJIS['BULLET']} **Viewed:** {user.mention}\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")


@bot.tree.command(name="record", description="View an employee personnel timeline.")
@app_commands.describe(user="Employee")
async def record(interaction: discord.Interaction, user: discord.Member):
    if not await require_higher_rank(interaction):
        return
    with db() as conn:
        rows = conn.execute("SELECT * FROM records WHERE discord_id = ? ORDER BY created_at DESC LIMIT 10", (str(user.id),)).fetchall()
    if not rows:
        return await interaction.response.send_message(embed=error_embed("No Records", f"{EMOJIS['BULLET']} No personnel timeline records were found for {user.mention}."), ephemeral=True)
    lines = []
    for r in rows:
        actor = f"<@{r['actor_id']}>" if r["actor_id"] else "System"
        lines.append(f"{EMOJIS['BULLET']} <t:{r['created_at']}:d> **{r['action']}** — {r['details']} *(by {actor})*")
    embed = discord.Embed(
        title=f"{EMOJIS['DATABASE']} Personnel Record Timeline",
        description=f"{EMOJIS['PERSONNEL']} **Employee:** {user.mention}\n\n" + "\n".join(lines),
        color=EMBED_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Air Serbia Personnel Core")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild, "Personnel Record Viewed", f"{EMOJIS['BULLET']} **Viewed:** {user.mention}\n{EMOJIS['BULLET']} **By:** {interaction.user.mention}")

# =========================
# INTERACTION ROUTER
# =========================
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "") if interaction.data else ""

    if custom_id == "open_register_form":
        return await interaction.response.send_modal(RegisterModal())
    if custom_id == "open_loa_form":
        return await interaction.response.send_modal(LOAModal())
    if custom_id == "open_resignation_form":
        return await interaction.response.send_modal(ResignationModal())
    if custom_id == "open_postflight_form":
        member = interaction.user if isinstance(interaction.user, discord.Member) else await interaction.guild.fetch_member(interaction.user.id)
        if not await is_higher_rank(member):
            return await interaction.response.send_message(embed=error_embed("Access Denied", f"{EMOJIS['BULLET']} You are not authorized to post flights."), ephemeral=True)
        return await interaction.response.send_modal(PostFlightModal())

    if custom_id.startswith("allocate_role:"):
        flight_id = custom_id.split(":", 1)[1]
        role_key = interaction.data["values"][0]
        return await handle_allocation(interaction, flight_id, role_key)

    if custom_id.startswith("attendance:"):
        flight_id = custom_id.split(":", 1)[1]
        selected_ids = interaction.data.get("values", [])
        return await handle_attendance(interaction, flight_id, selected_ids)

    if custom_id.startswith("approval:"):
        _, kind, decision, requester_id = custom_id.split(":", 3)
        return await handle_approval(interaction, kind, decision, requester_id)

    if custom_id.startswith("recruit_apply:"):
        position = custom_id.split(":", 1)[1]
        return await handle_recruit_apply(interaction, position)

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    init_db()

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"Synced {len(synced)} slash commands to guild {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global slash commands")
    except Exception as e:
        print(f"Slash command sync failed: {e}")

    if not flight_scheduler.is_running():
        flight_scheduler.start()

    print(f"Logged in as {bot.user} | Air Serbia Personnel Core online")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to Railway variables.")

bot.run(TOKEN)
