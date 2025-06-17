from discord.ext import commands
from discord import app_commands
from .guilds import GuildManager
from .update import UpdateListener, LastUpdate
from .db import Database
from .blacklist import BlacklistManager
from .lock import TargetLock
from .triggers import compose_trigger, TriggerManager
import discord, typing, asyncio, re, time, math, io
import utility as util
from dataclasses import dataclass
from pagination import Pagination

# Stores information about and manages a tagging run.
@dataclass
class TagRun:
    coroutine: typing.Awaitable[None] # The main coroutine of the tagging loop, which waits for commands.
    point: typing.Optional[str] # The current point, to track hits.
    tracked_nation: typing.Optional[str] # The current tracked nation, to track endorsements and WA activity.
    hits: list[tuple[str, str]] # List of registered hits and points who hit said targets.
    jump_point: str # Jump point used for this tag run.
    jp_index: int # Update index of the jump point.
    point_endos: int # Endorsements required to post a target.
    delay_time: float # Delay from target posting to updating.
    trigger_time: float # Optimal trigger time.
    endos: int # Current tracked endorsements on the tracked nation.
    guild_id: int # Guild where the tag run is operating.
    channel_id: int # Channel where the tag run is operating.
    minor: bool # Whether we're doing minor or major update.

class TagManager(commands.Cog):
    def __init__(self, bot: commands.Bot, nation: str):
        self.bot = bot
        self.nation = nation
        self.runs: dict[int, TagRun] = {}

    DEFAULT_DELAY_TIME = 6.0
    DEFAULT_TRIGGER_TIME = 2.5

    @app_commands.command(description="Start a tag run session.")
    async def tag(self, interaction: discord.Interaction, update: str, jump_point: str, point_endos: int) -> None:
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        if interaction.channel.id in self.runs.keys():
            if self.runs[interaction.channel.id].coroutine is not None:
                await interaction.response.send_message(f"There is already a tag session ongoing in this channel!", ephemeral=True)
                return
            
        jump_point = util.format_nation_or_region(jump_point)
        jp_data = database.fetch_region_data(jump_point)
        if jp_data is None:
            await interaction.response.send_message(f"Jump point {jump_point} not found!")
            return
        
        jp_index = jp_data["update_index"]
        
        run = TagRun(self.run_tag(interaction), 
                     None, None, [], 
                     jump_point, 
                     jp_index, 
                     point_endos, 
                     self.DEFAULT_DELAY_TIME, 
                     self.DEFAULT_TRIGGER_TIME, 
                     0, interaction.guild.id, interaction.channel.id, util.is_minor(update))
        
        self.runs[interaction.channel.id] = run

        try:
            await run.coroutine
        finally:
            run.coroutine = None

    # Main loop of a tag run.
    async def run_tag(self, interaction: discord.Interaction) -> None:
        run = self.runs[interaction.channel.id]

        await interaction.response.send_message(f"Set parameters: {run.point_endos} endorsements on point, %.2fs delay (by default), %.2fs trigger (by default). Run eX, dX, or tX to change." % (run.delay_time, run.trigger_time))

        while True:
            op = await self.bot.wait_for(
                "message",
                check=lambda x: x.channel.id == interaction.channel.id
                and (x.content.lower().startswith("http") # TRACK NATION
                or x.content.lower() == "q" # QUIT
                or x.content.lower() == "l" # LAUNCH
                or x.content.lower() == "u" # UNTRACK
                or x.content.lower().startswith("e") # update ENDOS
                or x.content.lower().startswith("d") # update DELAY
                or x.content.lower().startswith("t")), # update TRIGGER
                timeout=None,
            )

            # TRACK NATION: Extract the nation name from a link and start tracking it for WA activity.
            if op.content.lower().startswith("http"):
                if run.tracked_nation is None:
                    match = re.match(r"http[s]?://(?:fast|www)\.nationstates\.net/nation=([a-zA-Z0-9_\- ]+)", op.content.lower())
                    if match is not None:
                        run.endos = 0
                        run.tracked_nation = util.format_nation_or_region(match.groups()[0])
            # LAUNCH: Make the tracked nation point and fetch a target, 
            # regardless of how many endorsements the tracked nation has.
            elif op.content.lower() == "l":
                if run.tracked_nation is not None:
                    run.point = run.tracked_nation
                    run.tracked_nation = None
                    asyncio.create_task(self.select_target(run))
            # UNTRACK: Stop tracking the current tracked nation.
            elif op.content.lower() == "u":
                if run.tracked_nation is not None:
                    nation = run.tracked_nation
                    run.tracked_nation = None
                    asyncio.create_task(interaction.channel.send(f"Stopped tracking {nation} because of manual command."))
            # QUIT: Exit the tag run.
            elif op.content.lower() == "q":
                await interaction.channel.send(f"Quitting the tag session.")
                run.session = None
                run.tracked_nation = None
                run.point = None
                return
            # update ENDOS: Change the required endorsements to post target. 
            # If the tracked nation now fulfills these requirements, post target immediately.
            elif op.content.lower().startswith("e"):
                match = re.match(r"e([0-9]+)", op.content.lower())
                if match is not None:
                    run.point_endos = int(match.groups()[0])
                    asyncio.create_task(op.add_reaction("✅"))
                    if run.endos >= run.point_endos:
                        run.point = run.tracked_nation
                        run.tracked_nation = None
                        asyncio.create_task(self.select_target(run))
            # update DELAY: Updates the minimum delay between sending a target and its update time.
            elif op.content.lower().startswith("d"):
                match = re.match(r"d([0-9]+(?:\.[0-9]+)?)", op.content.lower())
                if match is not None:
                    run.delay_time = float(match.groups()[0])
                    asyncio.create_task(op.add_reaction("✅"))
            # update TRIGGER: Updates the optimal trigger time.
            elif op.content.lower().startswith("t"):
                match = re.match(r"t([0-9]+(?:\.[0-9]+)?)", op.content.lower())
                if match is not None:
                    run.trigger_time = float(match.groups()[0])
                    asyncio.create_task(op.add_reaction("✅"))

    # Look for a target, register it in Everblaze's trigger framework, and post it.
    # Called either when the LAUNCH command is given or the tracked nation reaches the endo requirement.
    async def select_target(self, run: TagRun) -> None:
        update_listener: UpdateListener = self.bot.get_cog('UpdateListener')
        blacklist: BlacklistManager = self.bot.get_cog('BlacklistManager')
        target_lock: TargetLock = self.bot.get_cog('TargetLock')
        triggers: TriggerManager = self.bot.get_cog('TriggerManager')
        database: Database = self.bot.get_cog('Database')
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        cursor = database.everblaze_db.cursor()
        guild = guilds.get_guild(run.guild_id)
        channel = self.bot.get_channel(run.channel_id)

        last_update = update_listener.last_update
        if last_update is None:
            # await channel.send("Can't give you a target, update hasn't started yet!\n"
                            #   "Or at least, Everblaze hasn't gotten any region update events.\n"
                            #   "Please wait until update starts and then run 'l' to launch.")
            # Restore tracked_nation so that we can go back to watching it for WA activity and run L.
            # run.tracked_nation = run.point
            # run.point = None
            # return

            # Yeah just pretend as if update had just started. For testing outside of update's sake.
            last_update = LastUpdate(0, time.time(), 0, 0)
        
        raidable_regions = util.find_raidable_regions(cursor, run.point_endos, last_update.index)

        last_update_time = 0
        if run.minor:
            last_update_time = last_update.minor
        else:
            last_update_time = last_update.major

        time_since_last_update = time.time() - last_update.real_time
        target_minimum_update_time = math.ceil(last_update_time + time_since_last_update + run.delay_time)

        for region in raidable_regions:
            if(region["update_index"] <= last_update.index):
                continue

            if(region["update_index"] > run.jp_index):
                await channel.send(f"No more regions found before jump point! Quitting tag session.")
                run.session.cancel()
                run.session = None
                run.tracked_nation = None
                run.point = None
                break

            update_time: int = 0
            if run.minor:
                update_time = region["seconds_minor"]
            else:
                update_time = region["seconds_major"]

            if update_time < target_minimum_update_time:
                continue

            if update_time < run.trigger_time:
                continue

            if blacklist.check_blacklist(guild, region):
                continue

            target = region["api_name"]

            if not target_lock.lock(run.guild_id, compose_trigger("", target=target)):
                continue

            trigger = util.find_region_updating_at_time(cursor, update_time - run.trigger_time, run.minor, 0.8, 0.4)
            if trigger is None:
                target_lock.unlock(run.guild_id, compose_trigger("", target=target))
                continue

            delay = 0
            if run.minor:
                delay = region["seconds_minor"] - trigger["seconds_minor"]
            else:
                delay = region["seconds_major"] - trigger["seconds_major"]

            time_to_region = update_time - (last_update_time + time_since_last_update)

            targets = triggers.get_trigger_list_from_id(run.channel_id)

            targets.add_trigger(compose_trigger(trigger["api_name"], target=target, delay=delay, message="GO!"))
            targets.sort_triggers(cursor)

            try:
                embed = discord.Embed()
                text = "%" * 400
                embed.description = f"[{text}](https://fast.nationstates.net/region={target}/template-overall=none?generated_by=everblaze_discord_bot__by_merethin__ran_by_{self.nation})"
                embed.set_footer(text=f"Target: {target}, delay: %.2fs, trigger: %.2fs - {region["update_index"]}/{update_listener.region_count}" % (time_to_region, delay))
                await channel.send(embed=embed)
            except Exception:
                await channel.send(f"An error occurred, please try again.")
                break
            break
        else:
            await channel.send(f"No more regions found, update is over! Quitting tag session.")
            run.session.cancel()
            run.session = None
            run.tracked_nation = None
            run.point = None

        cursor.close()

    @commands.Cog.listener()
    async def on_wa(self, event: typing.Tuple[str, str]):
        (happening, nation) = event
        
        for channel_id, tag_run in self.runs.items():
            if tag_run.tracked_nation == nation:
                channel = self.bot.get_channel(channel_id)
                if happening == "endo":
                    tag_run.endos += 1
                    if tag_run.endos >= tag_run.point_endos:
                        tag_run.point = tag_run.tracked_nation
                        tag_run.tracked_nation = None
                        await self.select_target(tag_run)
                elif happening == "unendo":
                    tag_run.tracked_nation = None
                    await channel.send(f"Stopped tracking {nation} as it has been unendorsed.")
                elif happening == "resign":
                    tag_run.tracked_nation = None
                    await channel.send(f"Stopped tracking {nation} as it has resigned from the WA.")

    @commands.Cog.listener()
    async def on_delegate(self, event: typing.Tuple[str, int]):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        (point, region) = event
        
        for channel_id, tag_run in self.runs.items():
            channel = guilds.get_channel(channel_id)
            guild = self.bot.get_guild(channel.guild_id)

            if tag_run.point == point:
                tag_run.point = None
                if tag_run.jump_point != region:
                    tag_run.hits.append((region, point))
                    await guild.get_channel(channel_id).send(f"{region} hit! Good job.")

    @app_commands.command(description="List regions hit during a tag run.")
    async def hits(self, interaction: discord.Interaction, all_channels: bool = False, bbcode: bool = False):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return

        hit_list = []
        
        if all_channels:
            for channel_id, run in self.runs.items():
                if guilds.get_channel(channel_id).guild_id == interaction.guild.id:
                    hit_list += run.hits
        else:
            hit_list += self.runs[interaction.channel.id].hits

        if(len(hit_list) == 0):
            await interaction.response.send_message(f"No regions hit!", ephemeral=guilds.should_be_ephemeral(interaction))
            return
        
        data = ""

        for (region, point) in hit_list:
            if bbcode:
                data += f"[url=https://www.nationstates.net/region={region}]{region}[/url]\n"
            else:
                data += f"https://www.nationstates.net/region={region} hit by https://www.nationstates.net/nation={point}\n"

        buf = io.BytesIO(bytes(data, "utf-8"))
        f = discord.File(buf, "hits.txt")

        await interaction.response.send_message(file=f)