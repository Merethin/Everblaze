from discord.ext import commands
from discord import app_commands
from .guilds import GuildManager
from .update import UpdateListener
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
    coroutine: typing.Awaitable[None]
    point: typing.Optional[str]
    hits: list[tuple[str, str]]
    jump_point: str

class TagManager(commands.Cog):
    def __init__(self, bot: commands.Bot, nation: str):
        self.bot = bot
        self.nation = nation
        self.runs: dict[int, TagRun] = {}

    @app_commands.command(description="Start a tag run session.")
    async def tag(self, interaction: discord.Interaction, update: str, jump_point: str, point_endos: int) -> None:
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        if interaction.channel.id in self.runs.keys():
            await interaction.response.send_message(f"There is already a tag session ongoing in this channel!", ephemeral=True)
            return
        
        jp_data = database.fetch_region_data(jump_point)
        if jp_data is None:
            await interaction.response.send_message(f"Jump point {jump_point} not found!")
            return
        
        jp_index = jp_data["update_index"]
        
        run = TagRun(self.run_tag(interaction, update, point_endos, jp_index), None, [], jump_point)
        self.runs[interaction.channel.id] = run

        await run.coroutine

    DEFAULT_DELAY_TIME = 6
    DEFAULT_TRIGGER_TIME = 3

    async def run_tag(self, interaction: discord.Interaction, update: str, point_endos: int, jp_index: int) -> None:
        update_listener: UpdateListener = self.bot.get_cog('UpdateListener')
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')
        blacklist: BlacklistManager = self.bot.get_cog('BlacklistManager')
        target_lock: TargetLock = self.bot.get_cog('TargetLock')
        triggers: TriggerManager = self.bot.get_cog('TriggerManager')

        run = self.runs[interaction.channel.id]

        delay_time = self.DEFAULT_DELAY_TIME
        trigger_time = self.DEFAULT_TRIGGER_TIME

        await interaction.response.send_message(f"Set parameters: {point_endos} endorsements on point, %.2fs delay (by default), %.2fs trigger (by default). Run eX, dX, or tX to change." % (delay_time, trigger_time))
        
        if update_listener.last_update is None:
            await interaction.channel.send(f"Waiting for {update} to start (waiting for any region to update)...")
            await self.bot.wait_for(
                "region_update",
                timeout=None,
            )
            await interaction.channel.send(f"Started tag run for {update}, post the point and start endorsing.")
        else:
            await interaction.channel.send(f"Started tag run for {update}, post the point and start endorsing.")

        minor = util.is_minor(update)
        nation = ""

        guild = guilds.get_guild(interaction.guild.id)

        cursor = database.everblaze_db.cursor()

        while True:
            op = await self.bot.wait_for(
                "message",
                check=lambda x: x.channel.id == interaction.channel.id
                and (x.content.lower().startswith("http")
                or x.content.lower() == "q"
                or x.content.lower() == "m"
                or x.content.lower().startswith("e")
                or x.content.lower().startswith("d")
                or x.content.lower().startswith("t")),
                timeout=None,
            )

            endos = 0

            if op.content.lower().startswith("http"):
                # Point provided. Fetch nation name
                match = re.match(r"http[s]?://(?:fast|www)\.nationstates\.net/nation=([a-zA-Z0-9_\- ]+)", op.content.lower())
                if match is not None:
                    nation = util.format_nation_or_region(match.groups()[0])
                    run.point = nation
                else:
                    continue
            elif op.content.lower() == "m":
                # Don't wait for all nations to endorse the point, it's already endorsed
                endos = point_endos + 1
            else:
                if op.content.lower() == "q":
                    await interaction.channel.send(f"Quitting the tag session.")
                    run.session = None
                    run.point = None
                    cursor.close()
                    return
                elif op.content.lower().startswith("e"):
                    match = re.match(r"e([0-9]+)", op.content.lower())
                    if match is not None:
                        point_endos = int(match.groups()[0])
                        await interaction.channel.send(f"Point endos changed to {point_endos}")
                elif op.content.lower().startswith("d"):
                    match = re.match(r"d([0-9]+(?:\.[0-9]+)?)", op.content.lower())
                    if match is not None:
                        delay_time = float(match.groups()[0])
                        await interaction.channel.send(f"Minimum delay changed to %.2fs" % delay_time)
                elif op.content.lower().startswith("t"):
                    match = re.match(r"t([0-9]+(?:\.[0-9]+)?)", op.content.lower())
                    if match is not None:
                        trigger_time = float(match.groups()[0])
                        await interaction.channel.send(f"Trigger time changed to %.2fs" % trigger_time)
                continue

            def check_point(data: typing.Tuple[str, str]) -> bool:
                nonlocal nation
                (_, target) = data
                return target == nation
            
            while endos < point_endos:
                (event, _) = await self.bot.wait_for(
                    "wa",
                    check=check_point,
                    timeout=None,
                )
                if event == "endo":
                    endos += 1
                elif event == "unendo":
                    asyncio.create_task(interaction.channel.send(f"{nation} has been unendorsed, canceling. Waiting for another command."))
                    run.point = None
                    break
                elif event == "resign":
                    asyncio.create_task(interaction.channel.send(f"{nation} has resigned from the WA, canceling. Waiting for another command."))
                    run.point = None
                    break
            else:
                last_update = update_listener.last_update
                start = last_update.index

                raidable_regions = util.find_raidable_regions(cursor, point_endos, start)

                last_update_time = 0
                if minor:
                    last_update_time = last_update.minor
                else:
                    last_update_time = last_update.major

                time_since_last_update = time.time() - last_update.real_time
                target_minimum_update_time = math.ceil(last_update_time + time_since_last_update + delay_time)

                for region in raidable_regions:
                    if(region["update_index"] <= last_update.index):
                        continue

                    if(region["update_index"] > jp_index):
                        await interaction.channel.send(f"No more regions found before jump point! Quitting tag session.")
                        run.session = None
                        run.point = None
                        cursor.close()
                        return

                    update_time: int = 0
                    if minor:
                        update_time = region["seconds_minor"]
                    else:
                        update_time = region["seconds_major"]

                    if update_time < target_minimum_update_time:
                        continue

                    if update_time < trigger_time:
                        continue

                    if blacklist.check_blacklist(guild, region):
                        continue

                    target = region["api_name"]

                    if not target_lock.lock(interaction.guild.id, compose_trigger("", target=target)):
                        continue

                    trigger = util.find_region_updating_at_time(cursor, update_time - trigger_time, minor, 0, 1)
                    if trigger is None:
                        target_lock.unlock(interaction.guild.id, compose_trigger("", target=target))
                        continue

                    delay = 0
                    if minor:
                        delay = region["seconds_minor"] - trigger["seconds_minor"]
                    else:
                        delay = region["seconds_major"] - trigger["seconds_major"]

                    time_to_region = update_time - (last_update_time + time_since_last_update)

                    targets = triggers.get_trigger_list(interaction)

                    targets.add_trigger(compose_trigger(trigger["api_name"], target=target, delay=delay, message="GO!"))
                    targets.sort_triggers(cursor)

                    try:
                        embed = discord.Embed()
                        text = "%" * 400
                        embed.description = f"[{text}](https://fast.nationstates.net/region={target}/template-overall=none?generated_by=everblaze_discord_bot__by_merethin__ran_by_{self.nation})"
                        embed.set_footer(text=f"Target: {target}, delay: %.2fs, trigger: %.2fs - {region["update_index"]}/{update_listener.region_count}" % (time_to_region, delay))
                        await interaction.channel.send(embed=embed)
                    except Exception:
                        await interaction.channel.send(f"An error occurred, please try again.")
                        break
                    break
                else:
                    await interaction.channel.send(f"No more regions found, update is over! Quitting tag session.")
                    run.session = None
                    run.point = None
                    cursor.close()
                    return

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