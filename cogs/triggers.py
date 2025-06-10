from discord.ext import commands
from discord import app_commands
import utility as util
import discord, typing
from .guilds import GuildManager
from .db import Database
from .lock import TargetLock
from pagination import Pagination

# Compose a trigger dictionary with an arbitrary number of keyword arguments.
def compose_trigger(api_name: str, target: typing.Optional[str] = None, delay: typing.Optional[int] = None, message: typing.Optional[str] = None) -> dict:
    trigger = {
        "api_name": api_name
    }

    if target is not None:
        trigger["target"] = target

    if delay is not None:
        trigger["delay"] = delay

    if message is not None:
        trigger["message"] = message

    return trigger

# Format a number of seconds, with fractional parts, as a string "HH:MM:SS.XX"
def format_time(timestamp: float) -> str:
    seconds = int(timestamp)
    fractional = timestamp - seconds
    minutes = seconds // 60
    seconds = seconds % 60
    hours = minutes // 60
    minutes = minutes % 60
    return "{:02d}:{:02d}:{:02d}.{:02d}".format(hours, minutes, seconds, int(fractional*100))

# Manage per-channel triggers, add them, remove them, react to them.
class TriggerManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.trigger_map: dict[int, util.TriggerList] = {}
    
    def get_trigger_list_from_id(self, channel_id: int):
        if channel_id not in self.trigger_map.keys():
            self.trigger_map[channel_id] = util.TriggerList()

        return self.trigger_map[channel_id]
    
    def get_trigger_list(self, interaction: discord.Interaction):
        return self.get_trigger_list_from_id(interaction.channel.id)
    
    def remove_channel(self, channel_id: int):
        if channel_id in self.trigger_map.keys():
            del self.trigger_map[channel_id]
    
    # Format a string with trigger data, including the link, triggers and predicted update times.
    def display_trigger(self, trigger: typing.Dict) -> str:
        database: Database = self.bot.get_cog('Database')

        cursor = database.everblaze_db.cursor()
        data = util.fetch_region_data_from_db(cursor, trigger["api_name"])
        cursor.close()

        if data is None:
            return ""

        message_shown = ""
        if "message" in trigger.keys():
            message_shown = f" - message: \"{trigger["message"]}\""

        if "target" not in trigger.keys():
            return f"[{trigger["api_name"]}](https://www.nationstates.net/region={trigger["api_name"]}) - {format_time(data["seconds_minor"])} minor, {format_time(data["seconds_major"])} major{message_shown}"
        
        return f"[{trigger["target"]}](https://www.nationstates.net/region={trigger["target"]}) ({data["canon_name"]};%.2fs) - {format_time(data["seconds_minor"])} minor, {format_time(data["seconds_major"])} major{message_shown}" % trigger["delay"]
    
    # Format a string with a link to a trigger.
    def display_trigger_simple(self, trigger: typing.Dict) -> str:
        if "target" not in trigger.keys():
            return f"trigger: [{trigger["api_name"]}](https://www.nationstates.net/region={trigger["api_name"]})"
        
        return f"target: [{trigger["target"]}](https://www.nationstates.net/region={trigger["target"]})"

    @app_commands.command(description="Add a new trigger.")
    async def add(self, interaction: discord.Interaction, trigger: str, message: typing.Optional[str]):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        database: Database = self.bot.get_cog('Database')
        cursor = database.everblaze_db.cursor()
        
        targets = self.get_trigger_list(interaction)
        
        targets.add_trigger(compose_trigger(util.format_nation_or_region(trigger), message=message))
        targets.sort_triggers(cursor)
        cursor.close()

        await interaction.response.send_message(f"Added trigger {trigger}.", ephemeral=guilds.should_be_ephemeral(interaction))

    @app_commands.command(description="Add a new target and associated trigger.")
    async def add_target(self, interaction: discord.Interaction, target: str, trigger: str, delay: int, message: typing.Optional[str]):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        database: Database = self.bot.get_cog('Database')
        cursor = database.everblaze_db.cursor()
        
        targets = self.get_trigger_list(interaction)

        targets.add_trigger(compose_trigger(util.format_nation_or_region(trigger), target=util.format_nation_or_region(target), delay=delay, message=message))
        targets.sort_triggers(cursor)
        cursor.close()

        await interaction.response.send_message(f"Added target {target} with trigger {trigger}.", ephemeral=guilds.should_be_ephemeral(interaction))

    @app_commands.command(description="Reset all triggers in this channel.")
    async def clear(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        triggers = self.get_trigger_list(interaction).triggers

        target_lock: TargetLock = self.bot.get_cog('TargetLock')
        target_lock.unlocklist(interaction.guild.id, triggers)

        del self.trigger_map[interaction.channel.id]

        await interaction.response.send_message(f"Successfully reset all triggers in this channel.", ephemeral=guilds.should_be_ephemeral(interaction))

    @app_commands.command(description="Remove a trigger.")
    async def remove(self, interaction: discord.Interaction, trigger: str):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        targets = self.get_trigger_list(interaction)
        
        t = targets.remove_trigger(util.format_nation_or_region(trigger))
        if t is None:
            await interaction.response.send_message(f"No such trigger {trigger}. Check that you have run /remove with the trigger name and not the target name.", ephemeral=guilds.should_be_ephemeral(interaction))
            return
        
        target_lock: TargetLock = self.bot.get_cog('TargetLock')
        target_lock.unlock(interaction.guild.id, t)

        await interaction.response.send_message(f"Removed trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=guilds.should_be_ephemeral(interaction))

    @app_commands.command(description="List active triggers.")
    async def triggers(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        targets = self.get_trigger_list(interaction)

        if(len(targets.triggers) == 0):
            await interaction.response.send_message(f"No triggers set!", ephemeral=guilds.should_be_ephemeral(interaction))
            return

        ELEMENTS_PER_PAGE = 10

        if(len(targets.triggers) > ELEMENTS_PER_PAGE):
            local_targets = targets.triggers[:] # Local copy in case the original one is modified while the user is scrolling

            async def get_page(page: int):
                emb = discord.Embed(title="Trigger List", description="")
                offset = (page-1) * ELEMENTS_PER_PAGE
                for region in local_targets[offset:offset+ELEMENTS_PER_PAGE]:
                    emb.description += f"{self.display_trigger(region)}\n"
                n = Pagination.compute_total_pages(len(local_targets), ELEMENTS_PER_PAGE)
                emb.set_footer(text=f"Page {page} of {n}")
                return emb, n

            await Pagination(interaction, get_page).navigate()
            return

        list = "\n".join([self.display_trigger(t) for t in targets.triggers])
        await interaction.response.send_message(list, ephemeral=guilds.should_be_ephemeral(interaction))

    @app_commands.command(description="Display the next region to update in the trigger list.")
    async def next(self, interaction: discord.Interaction, visible: bool = True):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        targets = self.get_trigger_list(interaction)

        if(len(targets.triggers) == 0):
            await interaction.response.send_message(f"No triggers set!", ephemeral=guilds.should_be_ephemeral(interaction))
            return
        
        await interaction.response.send_message(f"Next {self.display_trigger_simple(targets.triggers[0])}", ephemeral=(self.should_be_ephemeral(interaction) and not visible))

    @app_commands.command(description="Skip the next region to update in the trigger list.")
    async def skip(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        targets = self.get_trigger_list(interaction)

        if(len(targets.triggers) == 0):
            await interaction.response.send_message(f"No triggers set!", ephemeral=guilds.should_be_ephemeral(interaction))
            return
        
        name = targets.triggers[0]["api_name"]
        trigger = targets.remove_trigger(name)

        target_lock: TargetLock = self.bot.get_cog('TargetLock')
        target_lock.unlock(interaction.guild.id, trigger)
        
        await interaction.response.send_message(f"Removed {self.display_trigger_simple(trigger)}")