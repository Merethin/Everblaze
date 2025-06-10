from discord.ext import commands
from discord import app_commands
from .guilds import GuildManager
from .db import Database
from .triggers import TriggerManager
from .lock import TargetLock
import discord, typing, asyncio, sys
import utility as util
from dataclasses import dataclass

# Stores information about a region update event, specifically the last one that happened.
# It stores the update index of the region, the UNIX timestamp of when it updated, and the previously predicted minor and major update times for that region.
@dataclass
class LastUpdate:
    index: int # The index of the region in update.
    real_time: float # The UNIX timestamp at which the region updated.
    minor: float # The predicted timestamp at which the region would update during minor update.
    major: float # The predicted timestamp at which the region would update during major update.

# Listen for region updates, dispatch them to TriggerManager, keep track of the last registered region update, and trigger self-termination after update's over.
class UpdateListener(commands.Cog):
    def __init__(self, bot: commands.Bot, exit_delay: typing.Optional[int]):
        self.bot = bot
        self.last_update: typing.Optional[LastUpdate] = None

        database: Database = self.bot.get_cog('Database')
        cursor = database.everblaze_db.cursor()

        self.region_count = util.count_regions(cursor)
        cursor.close()

        self.exit_delay = exit_delay

    # Format a region update happening given a trigger that has just updated.
    def format_update_log(self, trigger: typing.Dict) -> str:
        if "message" in trigger.keys():
            return trigger["message"]
        
        if "target" not in trigger.keys():
            return f"{trigger["api_name"]} updated!"
        
        return f"{trigger["target"]} will update in {trigger["delay"]}s ({trigger["api_name"]} updated)!"
    
    # Generate region update messages to send to a given channel. They will all be collected and executed simultaneously using asyncio.gather()
    def update_region(self, api_name: str, last_update: LastUpdate, channel_id: int, ping_role: int, guild: discord.Guild, targets: util.TriggerList):
        already_updated = targets.remove_all_updated_triggers(last_update.index)
        channel = guild.get_channel(channel_id)
        role = guild.get_role(ping_role)

        messages = []

        for r in already_updated:
            messages.append((channel, f"{r["api_name"]} has already updated!"))

        target = targets.query_trigger(api_name)

        target_lock: TargetLock = self.bot.get_cog('TargetLock')

        if target is not None:
            targets.remove_trigger(api_name)
            target_lock.unlock(guild.id, target)
            messages.append((channel, f"{role.mention} {self.format_update_log(target)}"))

        return messages

    @commands.Cog.listener()
    async def on_region_update(self, event: typing.Tuple[str, int]):
        (region, timestamp) = event
        
        database: Database = self.bot.get_cog('Database')
        data = database.fetch_region_data(region)

        if data is None:
            return None
        
        self.last_update = LastUpdate(data["update_index"], float(timestamp), data["seconds_minor"], data["seconds_major"])
        
        messages = []

        guilds: GuildManager = self.bot.get_cog('GuildManager')
        triggers: TriggerManager = self.bot.get_cog('TriggerManager')
        
        for channel_id, targets in triggers.trigger_map.items():
            channel = guilds.channels[channel_id]
            guild = self.bot.get_guild(channel.guild_id)

            messages += self.update_region(region, self.last_update, channel_id, channel.ping_role, guild, targets)

        coroutines = [channel.send(message) for (channel, message) in messages]
        await asyncio.gather(*coroutines)

        if data["update_index"] == (self.region_count-1):
            self.bot.dispatch("update_end")

    @commands.Cog.listener()
    async def on_update_end(self):
        # Wipe all triggers
        triggers: TriggerManager = self.bot.get_cog('TriggerManager')
        triggers.trigger_map = {}

        if self.exit_delay is not None:
            print(f"[everblaze] starting exit timer... terminating in {self.exit_delay} seconds")

            await asyncio.sleep(self.exit_delay)

            print(f"[everblaze] exiting now")

            sys.exit(0)

    @app_commands.command(description="Show the most recent region update.")
    async def lastupdate(self, interaction: discord.Interaction):
        if self.last_update is None:
            await interaction.response.send_message(f"Not in update/last update not recorded.")
            return

        database: Database = self.bot.get_cog('Database')
        cursor = database.everblaze_db.cursor()
        region = util.fetch_region_data_with_index(cursor, self.last_update.index)
        cursor.close()

        await interaction.response.send_message(f"Last update: {region["canon_name"]}")