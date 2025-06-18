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
    update: str # Whether we're doing minor or major update.
    fast: bool # Whether to use fast.nationstates.net links.

class TagManager(commands.Cog):
    def __init__(self, bot: commands.Bot, nation: str):
        self.bot = bot
        self.nation = nation
        self.runs: dict[int, TagRun] = {}

    DEFAULT_DELAY_TIME = 6.0
    DEFAULT_TRIGGER_TIME = 2.5

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')

        if message.channel.id not in guilds.channels.keys():
            return

        if not guilds.get_channel(message.channel.id).tag:
            return
        
        if not message.channel.id in self.runs.keys():
            run = TagRun(None, None, [], "", 0, 1, 
                     self.DEFAULT_DELAY_TIME, 
                     self.DEFAULT_TRIGGER_TIME, 
                     0, message.guild.id, message.channel.id, "", True)
            self.runs[message.channel.id] = run

        run = self.runs[message.channel.id]

        # TRACK NATION: Extract the nation name from a link and start tracking it for WA activity.
        if message.content.lower().startswith("http"):
            if run.update == "":
                await message.channel.send("Update is not configured.\n"
                                           "Please type `set update minor` or `set update major` to select update.\n"
                                           "Type `c` to view all settings for the current run.")
                return
            if run.jp_index == 0:
                await message.channel.send("Jump point is not configured.\n"
                                           "Please type `set jp [NAME]` to select jump point.\n"
                                           "Type `c` to view all settings for the current run.")
                return
            if run.tracked_nation is None:
                match = re.match(r"http[s]?://(?:fast|www)\.nationstates\.net/nation=([a-z0-9_\- ]+)", message.content.lower())
                if match is not None:
                    run.endos = 0
                    run.tracked_nation = util.format_nation_or_region(match.groups()[0])
        # LAUNCH: Make the tracked nation point and fetch a target, 
        # regardless of how many endorsements the tracked nation has.
        elif message.content.lower() == "l":
            if run.tracked_nation is not None:
                run.point = run.tracked_nation
                run.tracked_nation = None
                await self.select_target(run)
        # UNTRACK: Stop tracking the current tracked nation.
        elif message.content.lower() == "u":
            if run.tracked_nation is not None:
                nation = run.tracked_nation
                run.tracked_nation = None
                await message.channel.send(f"Stopped tracking {nation} because of manual command.")
        # CONFIG: View configuration and status.
        elif message.content.lower() == "c":
            update = run.update
            if update == "":
                update = "[unset]"
            jump_point = run.jump_point
            if jump_point == "":
                jump_point = "[unset]"
            domain = "www"
            if run.fast:
                domain = "fast"
            wa_nation = run.tracked_nation
            point_nation = run.point
            if wa_nation is None:
                wa_nation = "[none]"
            if point_nation is None:
                point_nation = "[none]"
            await message.channel.send(f"Point endos: {run.point_endos}, minimum delay: %.2fs, trigger time: %.2fs\n"
                                       f"Update: {update}, jump point: {jump_point}\n"
                                       f"NS domain: {domain}.nationstates.net\n"
                                       f"Currently watching: {wa_nation} for endorsements ({run.endos}/{run.point_endos}), {point_nation} for delegacy changes" % (run.delay_time, run.trigger_time))
        # WWW: Set NS link domain to www.nationstates.net.
        elif message.content.lower() == "www":
            run.fast = False
            await message.channel.send(f"Set NS domain to www.nationstates.net")
        # FAST: Set NS link domain to fast.nationstates.net.
        elif message.content.lower() == "fast":
            run.fast = True
            await message.channel.send(f"Set NS domain to fast.nationstates.net")
        # update ENDOS: Change the required endorsements to post target. 
        # If the tracked nation now fulfills these requirements, post target immediately.
        elif message.content.lower().startswith("e"):
            match = re.match(r"e([0-9]+)", message.content.lower())
            if match is not None:
                run.point_endos = int(match.groups()[0])
                await message.channel.send(f"Point endos set to {run.point_endos}")
                if run.tracked_nation is not None:
                    if run.endos >= run.point_endos:
                        run.point = run.tracked_nation
                        run.tracked_nation = None
                        await self.select_target(run)
        # update DELAY: Updates the minimum delay between sending a target and its update time.
        elif message.content.lower().startswith("d"):
            match = re.match(r"d([0-9]+(?:\.[0-9]+)?)", message.content.lower())
            if match is not None:
                run.delay_time = float(match.groups()[0])
                await message.channel.send("Minimum delay time set to %.2fs" % run.delay_time)
        # update TRIGGER: Updates the optimal trigger time.
        elif message.content.lower().startswith("t"):
            match = re.match(r"t([0-9]+(?:\.[0-9]+)?)", message.content.lower())
            if match is not None:
                run.trigger_time = float(match.groups()[0])
                await message.channel.send("Trigger time set to %.2fs" % run.trigger_time)
        # set update|jp NAME: Set update and jump point settings.
        elif message.content.lower().startswith("set"):
            match = re.match(r"set\s(update|jp)\s([a-z0-9_\- ]+)", message.content.lower())
            if match is not None:
                subcommand = match.groups()[0]
                if subcommand == "update":
                    if util.is_minor(match.groups()[1]):
                        run.update = "minor"
                    else:
                        run.update = "major"
                    await message.channel.send(f"Update set to {run.update}")
                else:
                    jump_point = util.format_nation_or_region(match.groups()[1])
                    jp_data = database.fetch_region_data(jump_point)
                    if jp_data is None:
                        await message.channel.send(f"Jump point {jump_point} not found!")
                        return
                    
                    run.jump_point = jump_point
                    run.jp_index = jp_data["update_index"]
                    await message.channel.send(f"Jump point set to {jump_point}")

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

        minor = util.is_minor(run.update)

        last_update = update_listener.last_update
        if last_update is None:
            await channel.send("Can't give you a target, update hasn't started yet!\n"
                               "Or at least, Everblaze hasn't gotten any region update events.\n"
                               "Please wait until update starts and then run 'l' to launch.")
            # Restore tracked_nation so that we can go back to watching it for WA activity and run L.
            run.tracked_nation = run.point
            run.point = None
            return
        
        raidable_regions = util.find_raidable_regions(cursor, run.point_endos, last_update.index)

        last_update_time = 0
        if minor:
            last_update_time = last_update.minor
        else:
            last_update_time = last_update.major

        time_since_last_update = time.time() - last_update.real_time
        target_minimum_update_time = math.ceil(last_update_time + time_since_last_update + run.delay_time)

        for region in raidable_regions:
            if(region["update_index"] <= last_update.index):
                continue

            if(region["update_index"] > run.jp_index):
                await channel.send(f"No more regions found before jump point! Stopped watching nations.")
                run.tracked_nation = None
                run.point = None
                break

            update_time: int = 0
            if minor:
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

            trigger = util.find_region_updating_at_time(cursor, update_time - run.trigger_time, minor, 0.8, 0.4)
            if trigger is None:
                target_lock.unlock(run.guild_id, compose_trigger("", target=target))
                continue

            delay = 0
            if minor:
                delay = region["seconds_minor"] - trigger["seconds_minor"]
            else:
                delay = region["seconds_major"] - trigger["seconds_major"]

            time_to_region = update_time - (last_update_time + time_since_last_update)

            targets = triggers.get_trigger_list_from_id(run.channel_id)

            targets.add_trigger(compose_trigger(trigger["api_name"], target=target, delay=delay, message="GO!"))
            targets.sort_triggers(cursor)

            domain_prefix = "www"
            if run.fast:
                domain_prefix = "fast"

            try:
                embed = discord.Embed()
                text = "%" * 400
                embed.description = f"[{text}](https://{domain_prefix}.nationstates.net/region={target}/template-overall=none?generated_by=everblaze_discord_bot__by_merethin__ran_by_{self.nation})"
                embed.set_footer(text=f"Target: {target}, delay: %.2fs, trigger: %.2fs - {region["update_index"]}/{update_listener.region_count}" % (time_to_region, delay))
                await channel.send(embed=embed)
            except Exception:
                await channel.send(f"An error occurred, please try again.")
                break
            break
        else:
            await channel.send(f"No more regions found, update is over! Stopped watching nations.")
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
        (point, region) = event
        
        for channel_id, tag_run in self.runs.items():
            if tag_run.point == point:
                channel = self.bot.get_channel(channel_id)
                tag_run.point = None
                if tag_run.jump_point != region:
                    tag_run.hits.append((region, point))
                    await channel.send(f"{region} hit! Good job.")

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