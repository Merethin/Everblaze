from discord.ext import commands
from discord import app_commands
from .guilds import GuildManager
from .triggers import TriggerManager, compose_trigger
from .update import UpdateListener
from .db import Database
from .blacklist import BlacklistManager
from .lock import TargetLock
import discord, typing
import utility as util

class RegionView(discord.ui.View):
    interaction: discord.Interaction | None = None

    def __init__(self, user: discord.User | discord.Member, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        # We set the user who invoked the command as the user who can interact with the view
        self.user = user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "You cannot interact with this view.", ephemeral=True
            )
            return False
        # update the interaction attribute when a valid interaction is received
        self.interaction = interaction
        return True

# Implementation of the /snipe and /select commands, which find triggers for either one target or many.
class RegionFinder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(description="Find a trigger for a selected target.")
    async def snipe(self, interaction: discord.Interaction, target: str, update: str, ideal_delay: int, early_tolerance: int, late_tolerance: int, message: typing.Optional[str]):
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')
        triggers: TriggerManager = self.bot.get_cog('TriggerManager')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        minor = util.is_minor(update)

        region_data = database.fetch_region_data(util.format_nation_or_region(target))
        if region_data is None:
            await interaction.response.send_message(f"{target} does not exist!", ephemeral=guilds.should_be_ephemeral(interaction))
            return
        
        trigger_time = 0
        if minor:
            trigger_time = region_data["seconds_minor"] - ideal_delay
        else:
            trigger_time = region_data["seconds_major"] - ideal_delay

        cursor = database.everblaze_db.cursor()

        trigger = util.find_region_updating_at_time(cursor, trigger_time, minor, early_tolerance, late_tolerance)
        if trigger is None:
            cursor.close()
            await interaction.response.send_message(f"No trigger for {target} found in the specified time range!", ephemeral=guilds.should_be_ephemeral(interaction))
            return

        delay = 0
        if minor:
            delay = region_data["seconds_minor"] - trigger["seconds_minor"]
        else:
            delay = region_data["seconds_major"] - trigger["seconds_major"]

        targets = triggers.get_trigger_list(interaction)

        targets.add_trigger(compose_trigger(trigger["api_name"], target=util.format_nation_or_region(target), delay=delay, message=message))
        targets.sort_triggers(cursor)

        cursor.close()

        await interaction.response.send_message(f"Set trigger {trigger["api_name"]} for {target} (delay: {delay}s)", ephemeral=guilds.should_be_ephemeral(interaction))

    @app_commands.command(description="Find and select targets with no password and an executive delegate.")
    async def select(self, interaction: discord.Interaction, update: str, point_endos: int, min_switch_time: int, ideal_delay: int, early_tolerance: int, late_tolerance: int, message: typing.Optional[str], confirm: bool = True):
        guilds: GuildManager = self.bot.get_cog('GuildManager')
        database: Database = self.bot.get_cog('Database')
        triggers: TriggerManager = self.bot.get_cog('TriggerManager')
        blacklist: BlacklistManager = self.bot.get_cog('BlacklistManager')
        update_listener: UpdateListener = self.bot.get_cog('UpdateListener')
        target_lock: TargetLock = self.bot.get_cog('TargetLock')

        if not await guilds.check_channel_setup_role(interaction):
            return
        
        await interaction.response.send_message(f"Got it! Selecting targets for {update}...", ephemeral=guilds.should_be_ephemeral(interaction))

        cursor = database.everblaze_db.cursor()
        
        minor = util.is_minor(update)

        guild = guilds[interaction.guild.id]

        last_update = update_listener.last_update

        start = -1
        if last_update is not None:
            start = last_update.index

        raidable_regions = util.find_raidable_regions(cursor, point_endos, start)

        last_switch_time = -999

        if last_update is not None:
            if minor:
                last_switch_time = last_update.minor
            else:
                last_switch_time = last_update.major

        for region in raidable_regions:
            last_update = update_listener.last_update

            if last_update is not None:
                if(region["update_index"] <= last_update.index):
                    continue

            update_time = 0
            if minor:
                update_time = region["seconds_minor"]
            else:
                update_time = region["seconds_major"]

            if (update_time - last_switch_time) < min_switch_time:
                continue

            if blacklist.check_blacklist(guild, region):
                continue

            target = region["api_name"]
            trigger_time = update_time - ideal_delay

            if target_lock.is_locked(interaction.guild.id, compose_trigger("", target=target)):
                continue

            trigger = util.find_region_updating_at_time(cursor, trigger_time, minor, early_tolerance, late_tolerance)
            if trigger is None:
                continue

            delay = 0
            if minor:
                delay = region["seconds_minor"] - trigger["seconds_minor"]
            else:
                delay = region["seconds_major"] - trigger["seconds_major"]

            targets = triggers.get_trigger_list(interaction)
            should_finish = False

            if not confirm:
                targets.add_trigger(compose_trigger(trigger["api_name"], target=util.format_nation_or_region(target), delay=delay, message=message))
                targets.sort_triggers(cursor)

                target_lock.lock(interaction.guild.id, compose_trigger("", target=target))

                last_switch_time = update_time
                continue

            view = RegionView(interaction.user)
            accept_button = discord.ui.Button(label="Accept Target", style=discord.ButtonStyle.green)
            skip_button = discord.ui.Button(label="Find Another", style=discord.ButtonStyle.red)
            end_button = discord.ui.Button(label="Finish", style=discord.ButtonStyle.gray)

            async def accept_callback(interaction: discord.Interaction):
                nonlocal last_switch_time

                if target_lock.is_locked(interaction.guild.id, compose_trigger("", target=target)):
                    await interaction.response.send_message(f"The target {target} has already been selected in a different channel, finding a new one instead.", ephemeral=guilds.should_be_ephemeral(interaction))
                    view.stop()
                    return

                targets.add_trigger(compose_trigger(trigger["api_name"], target=util.format_nation_or_region(target), delay=delay, message=message))
                targets.sort_triggers(cursor)

                target_lock.lock(interaction.guild.id, compose_trigger("", target=target))

                last_switch_time = update_time

                await interaction.response.send_message(f"Set trigger {trigger["api_name"]} for target {target} (delay: {delay}s)", ephemeral=guilds.should_be_ephemeral(interaction))

                view.stop()
            
            async def skip_callback(interaction: discord.Interaction):
                await interaction.response.send_message(f"Understood, finding a different target...", ephemeral=guilds.should_be_ephemeral(interaction))
                view.stop()

            async def end_callback(interaction: discord.Interaction):
                nonlocal should_finish
                should_finish = True

                await interaction.response.send_message("Stopped looking for targets.", ephemeral=guilds.should_be_ephemeral(interaction))
                view.stop()

            # add the callback to the button
            accept_button.callback = accept_callback
            skip_button.callback = skip_callback
            end_button.callback = end_callback
            view.add_item(accept_button)
            view.add_item(skip_button)
            view.add_item(end_button)

            await interaction.followup.send(f"Target: https://www.nationstates.net/region={target}\nTrigger: {trigger["api_name"]}\nDelay: {delay}s", view=view, ephemeral=guilds.should_be_ephemeral(interaction))

            await view.wait()

            if should_finish:
                return

        await interaction.followup.send(f"No more regions found!", ephemeral=guilds.should_be_ephemeral(interaction))