from discord.ext import commands
from discord import app_commands
from .db import Database
from .lock import TargetLock
from dataclasses import dataclass
import discord

# Stores settings for a specific channel in a guild.
@dataclass
class Channel:
    guild_id: int # Guild ID the channel is inside of.
    setup_role: int # Role to add, remove, and view triggers.
    ping_role: int # Role to ping when triggers update.
    invisible: bool # Whether configuration messages should be ephemeral.
    tag: bool # Whether the channel is used for tagging.

# Stores settings for a guild.
@dataclass
class Guild:
    setup_role: int # Role to set up trigger settings.
    embassy_blacklist: set[str] # Embassies to avoid targeting.
    wfe_blacklist: set[str] # WFE words/phrases to avoid targeting.

# Auxiliary function to split a string, removing empty strings, and making it into a set for convenience ^^
def split_string_into_set(string: str, delim: str) -> set:
    return set([s for s in string.split(delim) if s.strip() != ''])

# Manages bot-wide guild and channel settings and keeps them synced with the database.
class GuildManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.guilds: dict[int, Guild] = {}
        self.channels: dict[int, Channel] = {}
        self.load_from_database()

    # Loads guild and channel data from the database on startup.
    def load_from_database(self) -> None:
        database: Database = self.bot.get_cog('Database')
        cursor = database.bot_db.cursor()

        # Load guild data from the database
        cursor.execute("SELECT * FROM guilds")
        data = cursor.fetchall()

        # Guild database format: guild_id, setup_role_id, embassy_blacklist (delimited by semicolons), wfe_blacklist (delimited by semicolons)
        for guild in data:
            self.guilds[guild[0]] = Guild(guild[1], split_string_into_set(guild[2], ';'), split_string_into_set(guild[3], ';'))

        # Load channel data from the database
        cursor.execute("SELECT * FROM channels")
        data = cursor.fetchall()

        # Channel database format: channel_id, guild_id, setup_role_id, ping_role_id, invisible
        for channel in data:
            self.channels[channel[0]] = Channel(channel[1], channel[2], channel[3], channel[4], channel[5])

        cursor.close()

    # Syncs settings for a guild to the database.
    def sync_guild(self, id: int, guild: Guild) -> None:
        database: Database = self.bot.get_cog('Database')
        cursor = database.bot_db.cursor()

        embassy_blacklist = ";".join(guild.embassy_blacklist)
        wfe_blacklist = ";".join(guild.wfe_blacklist)
    
        data = (id, guild.setup_role, embassy_blacklist, wfe_blacklist)
        cursor.execute("INSERT OR REPLACE INTO guilds VALUES (?, ?, ?, ?)", data)
        database.bot_db.commit()

        cursor.close()

    # Syncs settings for a channel to the database.
    def sync_channel(self, id: int, channel: Channel) -> None:
        database: Database = self.bot.get_cog('Database')
        cursor = database.bot_db.cursor()

        data = (id, channel.guild_id, channel.setup_role, channel.ping_role, channel.invisible, channel.tag)
        cursor.execute("INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?, ?)", data)
        database.bot_db.commit()

        cursor.close()

    # Whether a response to a command should be ephemeral, depending on the channel settings.
    def should_be_ephemeral(self, interaction: discord.Interaction) -> bool:
        return bool(self.channels[interaction.channel.id].invisible)
    
    # Query a guild by guild id.
    def get_guild(self, id: int) -> Guild:
        return self.guilds[id]
    
    # Query a channel by channel id.
    def get_channel(self, id: int) -> Channel:
        return self.channels[id]

    # Checks whether a user can manage the server before running a command.
    async def check_manage_server(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Only a member with the 'Manage Server' permission can use this command.", ephemeral=True)
            return False
        return True
    
    # Checks whether the current guild is configured.
    async def check_config(self, interaction: discord.Interaction) -> bool:
        if interaction.guild.id not in self.guilds.keys():
            await interaction.response.send_message("This server is not configured. Tell the owner to run /config first.", ephemeral=True)
            return False
        return True
    
    # Checks whether a user has the setup role for a guild (and whether the guild is configured) before running a command.
    async def check_guild_setup_role(self, interaction: discord.Interaction) -> bool:
        if not await self.check_config(interaction):
            return False
        
        if interaction.user.get_role(self.guilds[interaction.guild.id].setup_role) is None:
            await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
            return False
        
        return True
    
    # Checks whether a user has the setup role for a channel (and whether the guild/channel are configured) before running a command.
    async def check_channel_setup_role(self, interaction: discord.Interaction) -> bool:
        if not await self.check_config(interaction):
            return False
        
        if interaction.channel.id not in self.channels.keys():
            await interaction.response.send_message("This channel is not configured. Tell a person with the appropriate role to run /addch first.", ephemeral=True)
            return False
    
        channel = self.channels[interaction.channel.id]
        if interaction.user.get_role(channel.setup_role) is None:
            await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
            return False
        
        return True

    @app_commands.command(description="Configure the bot.")
    async def config(self, interaction: discord.Interaction, setup_role: discord.Role):
        if not await self.check_manage_server(interaction):
            return
        
        guild = Guild(setup_role.id, set(), set())
        if interaction.guild.id in self.guilds.keys():
            guild = self.guilds[interaction.guild.id]
        
        self.sync_guild(interaction.guild.id, guild)
        self.guilds[interaction.guild.id] = guild

        print(f"Server configuration updated for guild {interaction.guild.name}: Setup Role {setup_role.name}")

        await interaction.response.send_message("Server configuration updated!", ephemeral=True)

    @app_commands.command(description="Add a separate setup role and ping role to a channel.")
    async def addch(self, interaction: discord.Interaction, setup_role: discord.Role, ping_role: discord.Role, invisible: bool, tag: bool):
        if not await self.check_guild_setup_role(interaction):
            return
        
        channel = Channel(interaction.guild.id, setup_role.id, ping_role.id, invisible, tag)

        self.sync_channel(interaction.channel.id, channel)
        self.channels[interaction.channel.id] = channel

        print(f"Server configuration updated for guild {interaction.guild.name}, channel {interaction.channel.name}: Setup Role {setup_role.name}, Ping Role {ping_role.name}, Invisible {invisible}, Tag {tag}")

        await interaction.response.send_message("Channel configuration updated!", ephemeral=True)

    @app_commands.command(description="Remove the separate ping role and target list from this channel.")
    async def remch(self, interaction: discord.Interaction):
        if not await self.check_guild_setup_role(interaction):
            return
        
        if interaction.channel.id not in self.channels.keys():
            await interaction.response.send_message("This channel has no channel-specific configuration to remove!", ephemeral=True)
            return
        
        database: Database = self.bot.get_cog('Database')
        cursor = database.bot_db.cursor()
        
        cursor.execute("DELETE FROM channels WHERE channel_id = ?", [interaction.channel.id])
        database.bot_db.commit()
        cursor.close()

        del self.channels[interaction.channel.id]

        triggers = self.bot.get_cog('TriggerManager') # avoid circular imports here
        target_lock: TargetLock = self.bot.get_cog('TargetLock')

        target_lock.unlocklist(interaction.guild.id, triggers.trigger_map[interaction.channel.id].triggers)
        del triggers.trigger_map[interaction.channel.id]

        await interaction.response.send_message("Channel configuration removed!", ephemeral=True)