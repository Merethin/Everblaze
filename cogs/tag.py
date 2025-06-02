from discord.ext import commands
from discord import app_commands
from .guilds import GuildManager
from .update import UpdateListener
from .db import Database
from .blacklist import BlacklistManager
from .lock import TargetLock
from .triggers import compose_trigger
import discord, typing, asyncio, re, time, math
import utility as util
from dataclasses import dataclass
from pagination import Pagination

# Stores information about and manages a tagging run.
@dataclass
class TagRun:
    coroutine: typing.Awaitable[None]
    point: typing.Optional[str]
    hits: list[tuple[str, str]]

class TagManager(commands.Cog):
    def __init__(self, bot: commands.Bot, nation: str):
        self.bot = bot
        self.nation = nation
        self.runs: dict[int, TagRun] = {}

    @app_commands.command(description="Start a tag run session.")
    async def tag(self, interaction: discord.Interaction, update: str, point_endos: int, switch_time: int, min_delay: int) -> None:
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        if interaction.channel.id in self.runs.keys():
            await interaction.response.send_message(f"There is already a tag session ongoing in this channel!", ephemeral=True)
            return
        
        run = TagRun(self.run_tag(interaction, update, point_endos, switch_time, min_delay), None, [])
        self.runs[interaction.channel.id] = run

        await run.coroutine

    async def run_tag(self, interaction: discord.Interaction, update: str, point_endos: int, switch_time: int, min_delay: int) -> None:
        update_listener: UpdateListener = self.bot.get_cog('UpdateListener')
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')
        blacklist: BlacklistManager = self.bot.get_cog('BlacklistManager')
        target_lock: TargetLock = self.bot.get_cog('TargetLock')

        run = self.runs[interaction.channel.id]
        
        if update_listener.last_update is None:
            await interaction.response.send_message(f"Waiting for {update} to start (waiting for any region to update)...")
            await self.bot.wait_for(
                "region_update",
                timeout=None,
            )
            await interaction.channel.send(f"Started tag run for {update}. Please post the point and start endorsing.")
        else:
            await interaction.response.send_message(f"Started tag run for {update}. Please post the point and start endorsing.")

        minor = util.is_minor(update)
        nation = ""

        guild = guilds.get_guild(interaction.guild.id)

        cursor = database.everblaze_db.cursor()

        while True:
            op = await self.bot.wait_for(
                "message",
                check=lambda x: x.channel.id == interaction.channel.id
                and (x.content.lower().startswith("t")
                or x.content.lower() == "quit"
                or x.content.lower() == "miss"
                or x.content.lower().startswith("endos")
                or x.content.lower().startswith("delay")
                or x.content.lower().startswith("switch")),
                timeout=None,
            )

            endos = 0

            if op.content.lower().startswith("t"):
                # Point provided. Fetch nation name
                match = re.match(r"t[\s]+http[s]?://(?:fast|www)\.nationstates\.net/nation=([a-zA-Z0-9_\- ]+)", op.content.lower())
                if match is not None:
                    nation = util.format_nation_or_region(match.groups()[0])
                    run.point = nation
                else:
                    continue
            elif op.content.lower() == "miss":
                # Don't wait for all nations to endorse the point, it's already endorsed
                endos = point_endos + 1
            else:
                if op.content.lower() == "quit":
                    await interaction.channel.send(f"Quitting the tag session.")
                    run.session = None
                    run.point = None
                    cursor.close()
                    return
                elif op.content.lower().startswith("endos"):
                    match = re.match(r"endos[\s]+([0-9]+)", op.content.lower())
                    if match is not None:
                        point_endos = int(match.groups()[0])
                        await interaction.channel.send(f"Point endos changed to {point_endos}.")
                elif op.content.lower().startswith("delay"):
                    match = re.match(r"delay[\s]+([0-9]+)", op.content.lower())
                    if match is not None:
                        min_delay = int(match.groups()[0])
                        await interaction.channel.send(f"Minimum delay changed to {min_delay}s (up to {min_delay+2}s)")
                elif op.content.lower().startswith("switch"):
                    match = re.match(r"switch[\s]+([0-9]+)", op.content.lower())
                    if match is not None:
                        switch_time = int(match.groups()[0])
                        await interaction.channel.send(f"Switch time changed to {switch_time}s")
                continue

            message: typing.Optional[discord.WebhookMessage] = None
            if endos < point_endos:
                message = await interaction.channel.send(f"Waiting for everyone to endorse {nation} before posting target... ({endos}/{point_endos})")

            def check_point(data: typing.Tuple[str, str]) -> bool:
                nonlocal nation
                (_, target) = data
                return target == nation
            
            while endos < point_endos:
                task = None
                (event, _) = await self.bot.wait_for(
                    "wa",
                    check=check_point,
                    timeout=None,
                )
                if event == "endo":
                    endos += 1
                    if message is not None:
                        if task is not None:
                            task.cancel()
                        task = asyncio.create_task(message.edit(content=f"Waiting for everyone to endorse {nation} before posting target... ({endos}/{point_endos})"))
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
                assert last_update

                start = last_update.index

                raidable_regions = util.find_raidable_regions(cursor, point_endos, start)

                last_update_time = 0
                if minor:
                    last_update_time = last_update.minor
                else:
                    last_update_time = last_update.major

                time_since_last_update = time.time() - last_update.time
                target_update_time = math.ceil(last_update_time + time_since_last_update + switch_time + min_delay)

                search_start_time = time.time()

                for region in raidable_regions:
                    last_update = update_listener.last_update
                    assert last_update

                    if(region["update_index"] <= last_update.index):
                        continue

                    update_time: int = 0
                    if minor:
                        update_time = region["seconds_minor"]
                    else:
                        update_time = region["seconds_major"]

                    if blacklist.check_blacklist(guild, region):
                        continue

                    # Large region is probably updating. Let's wait until it ends and then find a more reliable trigger/target.
                    while (update_time - target_update_time) > 2 or time_since_last_update > 1.5:
                        await asyncio.sleep(0.1) # Wait for a bit longer before finding a target.

                        last_update = update_listener.last_update
                        assert last_update

                        if minor:
                            last_update_time = last_update.minor
                        else:
                            last_update_time = last_update.major

                        time_since_last_update = time.time() - last_update.time
                        target_update_time = math.ceil(last_update_time + time_since_last_update + switch_time + min_delay)

                    if update_time < target_update_time:
                        continue

                    target = region["api_name"]

                    if not target_lock.lock(interaction.guild.id, compose_trigger("", target=target)):
                        continue

                    search_time = time.time() - search_start_time
                    remaining_time = switch_time - search_time

                    gap_delay = (update_time - target_update_time)

                    if remaining_time > 0:
                        await asyncio.sleep(remaining_time)

                    try:
                        embed = discord.Embed()
                        text = "%" * 400
                        embed.description = f"[{text}](https://fast.nationstates.net/region={target}/template-overall=none?generated_by=everblaze_discord_bot__by_merethin__ran_by_{self.nation})"
                        embed.set_footer(text=f"Move to target: {target}, estimated delay: {gap_delay + min_delay}s - {region["update_index"]}/{update_listener.region_count}")
                        await interaction.channel.send(embed=embed)
                    except Exception:
                        await interaction.channel.send(f"An error occurred, please try again.")
                        break
                    break
                else:
                    await interaction.channel.send(f"No more regions found, update is over! Quitting tag session.")
                    run.session = None
                    run.point = None
                    return

    @commands.Cog.listener()
    async def on_delegate(self, event: typing.Tuple[str, int]):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        (point, region) = event
        
        for channel_id, tag_run in self.runs.items():
            channel = guilds.get_channel(channel_id)
            guild = self.bot.get_guild(channel.guild_id)

            if tag_run.point == point:
                role = guild.get_role(channel.ping_role)
                guild.get_channel(channel_id).send(f"{role.mention} {region} hit!")
                tag_run.hits.append((region, point))
                tag_run.point = None

    @app_commands.command(description="List regions hit during a tag run.")
    async def hits(self, interaction: discord.Interaction, all_channels: bool = False):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return

        hit_list = []
        
        if all_channels:
            for channel_id, run in self.runs.items():
                if guilds.get_channel(channel_id).guild_id == interaction.guild.id:
                    hit_list += run.hits
        else:
            hit_list += self.runs[interaction.guild_id].hits

        if(len(hit_list) == 0):
            await interaction.response.send_message(f"No regions hit!", ephemeral=guilds.should_be_ephemeral(interaction))
            return

        ELEMENTS_PER_PAGE = 10

        if(len(hit_list) > ELEMENTS_PER_PAGE):
            async def get_page(page: int):
                emb = discord.Embed(title="Targets Hit", description="")
                offset = (page-1) * ELEMENTS_PER_PAGE
                for (region, point) in hit_list[offset:offset+ELEMENTS_PER_PAGE]:
                    emb.description += f"[{region}](https://www.nationstates.net/region={region}) hit by {point}\n"
                n = Pagination.compute_total_pages(len(hit_list), ELEMENTS_PER_PAGE)
                emb.set_footer(text=f"Page {page} of {n}")
                return emb, n

            await Pagination(interaction, get_page).navigate()
            return

        list = "\n".join([f"[{region}](https://www.nationstates.net/region={region}) hit by {point}" for (region, point) in hit_list])
        await interaction.response.send_message(list, ephemeral=guilds.should_be_ephemeral(interaction))