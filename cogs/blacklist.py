from discord.ext import commands
from .guilds import GuildManager, Guild
from discord import app_commands
import discord
import utility as util
from pagination import Pagination

# Embassy and WFE blacklisting commands and checks.
class BlacklistManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def check_blacklist(self, guild: Guild, region: dict) -> bool:
        embassies: list[str] = region["embassies"].split(",")
        for embassy in guild.embassy_blacklist:
            if embassy in embassies:
                return True

        wfe: str = region["wfe"].lower()
        for entry in guild.wfe_blacklist:
            if entry in wfe:
                return True
            
        return False
    
    def check_whitelist(self, guild: Guild, region: dict) -> bool:
        embassies: list[str] = region["embassies"].split(",")
        for embassy in guild.embassy_whitelist:
            if embassy in embassies:
                return True

        wfe: str = region["wfe"].lower()
        for entry in guild.wfe_whitelist:
            if entry in wfe:
                return True
            
        return False
    
    @app_commands.command(description="Add/remove a region to/from the embassy blacklist.")
    async def embassyblacklist(self, interaction: discord.Interaction, region: str, remove: bool):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        region = util.format_nation_or_region(region)
        guild = guilds.get_guild(interaction.guild.id)

        if remove:
            guild.embassy_blacklist.discard(region)
            await interaction.response.send_message(f"Removed {region} from the embassy blacklist.", ephemeral=True)
        else:
            guild.embassy_blacklist.add(region)
            await interaction.response.send_message(f"Added {region} to the embassy blacklist.", ephemeral=True)

        guilds.sync_guild(interaction.guild.id, guild)

    @app_commands.command(description="Add/remove a word or sentence to/from the WFE blacklist.")
    async def wfeblacklist(self, interaction: discord.Interaction, word: str, remove: bool):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        word = word.lower()
        guild = guilds.get_guild(interaction.guild.id)

        if remove:
            guild.wfe_blacklist.discard(word)
            await interaction.response.send_message(f"Removed {word} from the WFE blacklist.", ephemeral=True)
        else:
            guild.wfe_blacklist.add(word)
            await interaction.response.send_message(f"Added {word} to the WFE blacklist.", ephemeral=True)

        guilds.sync_guild(interaction.guild.id, guild)

    @app_commands.command(description="List the current blacklist.")
    async def blacklist(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        guild = guilds.get_guild(interaction.guild.id)

        lines = []
        lines.append("**Embassy Blacklist**")

        for embassy in guild.embassy_blacklist:
            lines.append(f"[{embassy}](https://www.nationstates.net/region={embassy})")
        
        lines.append("")
        lines.append("**WFE Blacklist**")

        for word in guild.wfe_blacklist:
            lines.append(f"'{word}'")

        ELEMENTS_PER_PAGE = 10

        async def get_page(page: int):
            emb = discord.Embed(title="Blacklist", description="")
            offset = (page-1) * ELEMENTS_PER_PAGE
            for line in lines[offset:offset+ELEMENTS_PER_PAGE]:
                emb.description += f"{line}\n"
            n = Pagination.compute_total_pages(len(lines), ELEMENTS_PER_PAGE)
            emb.set_footer(text=f"Page {page} of {n}")
            return emb, n

        await Pagination(interaction, get_page).navigate()
        return

    @app_commands.command(description="Clear the server embassy and WFE blacklists.")
    async def clearblacklist(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        guild = guilds.get_guild(interaction.guild.id)
        guild.embassy_blacklist = set()
        guild.wfe_blacklist = set()

        guilds.sync_guild(interaction.guild.id, guild)

        await interaction.response.send_message(f"Cleared the server blacklist.", ephemeral=True)

    @app_commands.command(description="Add/remove a region to/from the embassy whitelist.")
    async def embassywhitelist(self, interaction: discord.Interaction, region: str, remove: bool):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        region = util.format_nation_or_region(region)
        guild = guilds.get_guild(interaction.guild.id)

        if remove:
            guild.embassy_whitelist.discard(region)
            await interaction.response.send_message(f"Removed {region} from the embassy whitelist.", ephemeral=True)
        else:
            guild.embassy_whitelist.add(region)
            await interaction.response.send_message(f"Added {region} to the embassy whitelist.", ephemeral=True)

        guilds.sync_guild(interaction.guild.id, guild)

    @app_commands.command(description="Add/remove a word or sentence to/from the WFE blacklist.")
    async def wfewhitelist(self, interaction: discord.Interaction, word: str, remove: bool):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        word = word.lower()
        guild = guilds.get_guild(interaction.guild.id)

        if remove:
            guild.wfe_whitelist.discard(word)
            await interaction.response.send_message(f"Removed {word} from the WFE whitelist.", ephemeral=True)
        else:
            guild.wfe_whitelist.add(word)
            await interaction.response.send_message(f"Added {word} to the WFE whitelist.", ephemeral=True)

        guilds.sync_guild(interaction.guild.id, guild)

    @app_commands.command(description="List the current whitelist.")
    async def whitelist(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        guild = guilds.get_guild(interaction.guild.id)

        lines = []
        lines.append("**Embassy Whitelist**")

        for embassy in guild.embassy_whitelist:
            lines.append(f"[{embassy}](https://www.nationstates.net/region={embassy})")
        
        lines.append("")
        lines.append("**WFE Whitelist**")

        for word in guild.wfe_whitelist:
            lines.append(f"'{word}'")

        ELEMENTS_PER_PAGE = 10

        async def get_page(page: int):
            emb = discord.Embed(title="Whitelist", description="")
            offset = (page-1) * ELEMENTS_PER_PAGE
            for line in lines[offset:offset+ELEMENTS_PER_PAGE]:
                emb.description += f"{line}\n"
            n = Pagination.compute_total_pages(len(lines), ELEMENTS_PER_PAGE)
            emb.set_footer(text=f"Page {page} of {n}")
            return emb, n

        await Pagination(interaction, get_page).navigate()
        return

    @app_commands.command(description="Clear the server embassy and WFE whitelists.")
    async def clearwhitelist(self, interaction: discord.Interaction):
        guilds: GuildManager = self.bot.get_cog('GuildManager')

        if not await guilds.check_guild_setup_role(interaction):
            return

        guild = guilds.get_guild(interaction.guild.id)
        guild.embassy_whitelist = set()
        guild.wfe_whitelist = set()

        guilds.sync_guild(interaction.guild.id, guild)

        await interaction.response.send_message(f"Cleared the server whitelist.", ephemeral=True)