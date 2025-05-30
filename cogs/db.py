from discord.ext import commands
import sqlite3
import utility as util

# Global database connections are stored here so everyone can access them.
class Database(commands.Cog):
    def __init__(self, bot: commands.Bot, bot_db: sqlite3.Connection, everblaze_db: sqlite3.Connection):
        self.bot = bot
        self.bot_db = bot_db
        self.everblaze_db = everblaze_db

    # Fetch data for a region from the local database.
    # The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
    # Just a handy wrapper for util.fetch_region_data_from_db().
    def fetch_region_data(self, region: str) -> dict | None:
        cursor = self.everblaze_db.cursor()

        result = util.fetch_region_data_from_db(cursor, region)
        cursor.close()

        return result