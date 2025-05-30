# bot.py - Versatile Discord bot for R/D triggering and tag raiding
# Authored by Merethin, licensed under the BSD-2-Clause license.

from dotenv import dotenv_values
import discord, sqlite3, argparse, asyncio, typing, math, sys, sans
from discord.ext import commands
import utility as util

from cogs.blacklist import BlacklistManager
from cogs.db import Database
from cogs.finder import RegionFinder
from cogs.guilds import GuildManager
from cogs.tag import TagManager
from cogs.triggers import TriggerManager
from cogs.update import UpdateListener
from cogs.lock import TargetLock

VERSION = "0.2.0"

class EverblazeBot(commands.Bot):
    def __init__(self, bot_db: sqlite3.Connection, everblaze_db: sqlite3.Connection, exit_delay: typing.Optional[int]):
        intents: discord.Intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="%",
            intents=intents
        )

        self.bot_db = bot_db
        self.everblaze_db = everblaze_db
        self.exit_delay = exit_delay

    async def sse_loop(self):
        client = sans.AsyncClient()
        async for event in sans.serversent_events(client, "admin", "endo", "member"):
            response = parse_sse_event(event)

            if response is None:
                continue
                
            (event, data) = response

            self.dispatch(event, data)

    async def setup_hook(self):
        loop = asyncio.get_event_loop()
        loop.set_task_factory(asyncio.eager_task_factory)

        await self.add_cog(Database(self, self.bot_db, self.everblaze_db))
        await self.add_cog(GuildManager(self))
        await self.add_cog(BlacklistManager(self))
        await self.add_cog(TriggerManager(self))
        await self.add_cog(RegionFinder(self))
        await self.add_cog(TagManager(self))
        await self.add_cog(TargetLock(self))
        await self.add_cog(UpdateListener(self, self.exit_delay))

        self.sse_task = asyncio.create_task(self.sse_loop())

    async def on_ready(self):
        print(f'Everblaze: logged in as {self.user}')

        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash commands")
        except Exception as e:
            print(f"Error syncing commands: {e}")

def parse_sse_event(data: dict) -> typing.Optional[typing.Tuple[str, typing.Tuple[str, int] | typing.Tuple[str, str]]]:
    happening = data["str"]

    match = util.EVENTS["update"].match(happening)
    if match is not None:
        region_name = match.groups()[0]

        print(f"[update] {region_name} updated")

        time = math.floor(data["time"].timestamp())
        return ("region_update", (region_name, time))
    
    match = util.EVENTS["endo"].match(happening)
    if match is not None:
        target = match.groups()[1]

        print(f"[wa] {target} was endorsed")

        return ("wa", ("endo", target))
    
    match = util.EVENTS["unendo"].match(happening)
    if match is not None:
        target = match.groups()[1]

        print(f"[wa] {target} was unendorsed")

        return ("wa", ("unendo", target))
    
    match = util.EVENTS["resign"].match(happening)
    if match is not None:
        target = match.groups()[0]

        print(f"[wa] {target} resigned from the WA")

        return ("wa", ("resign", target))
    
    match = util.EVENTS["newdel"].match(happening)
    if match is not None:
        point = match.groups()[0]
        target = match.groups()[1]

        print(f"[wa] {point} became delegate of {target}")

        return ("delegate", (point, target))
    
    match = util.EVENTS["seizedel"].match(happening)
    if match is not None:
        point = match.groups()[0]
        target = match.groups()[1]

        print(f"[wa] {point} became delegate of {target}")

        return ("delegate", (point, target))
    
    return None

def create_tables_if_needed(bot_db: sqlite3.Connection) -> None:
    bot_cursor = bot_db.cursor()

    table_list = bot_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='guilds'; ").fetchall()

    if table_list == []:
        # Guild list doesn't exist, create it
        bot_cursor.execute("CREATE TABLE guilds(guild_id, setup_role_id, embassy_blacklist, wfe_blacklist)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_guild_id ON guilds (guild_id);")
        bot_db.commit()

    channel_list = bot_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'; ").fetchall()

    if channel_list == []:
        # Channel list doesn't exist, create it
        bot_cursor.execute("CREATE TABLE channels(channel_id, guild_id, setup_role_id, ping_role_id, invisible)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_channel_id ON channels (channel_id);")
        bot_db.commit()

    bot_cursor.close()

def check_positive_integer(value: typing.Any) -> int:
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
    return ivalue

def main() -> None:
    parser = argparse.ArgumentParser(prog="everblaze-bot", description="Everblaze Discord bot for NationStates R/D")
    parser.add_argument("-n", "--nation-name", required=True)
    parser.add_argument("-r", '--regenerate-db', action='store_true')
    parser.add_argument("-e", "--exit-delay", type=check_positive_integer)
    args = parser.parse_args()

    user_agent = f"Everblaze/{VERSION} (Discord bot) by Merethin, used by {args.nation_name}"
    sans.set_agent(user_agent)

    if not util.check_if_nation_exists(args.nation_name):
        print(f"The nation {args.nation_name} does not exist. Try again.")
        sys.exit(1)

    util.bootstrap(args.regenerate_db)

    everblaze_db = sqlite3.connect("regions.db")
    bot_db = sqlite3.connect("bot.db")
    create_tables_if_needed(bot_db)

    bot = EverblazeBot(bot_db, everblaze_db, args.exit_delay)

    settings = dotenv_values(".env")
    bot.run(settings["TOKEN"])

    sys.exit(0)

if __name__ == "__main__":
    main()