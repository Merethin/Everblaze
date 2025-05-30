from discord.ext import commands

# Make sure only one channel at a time is setting a specific target in a guild
class TargetLock(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock_map: dict[int, set] = {}

    def get_lock_map_for_guild(self, guild_id: int) -> set:
        if guild_id not in self.lock_map.keys():
            self.lock_map[guild_id] = set()
        return self.lock_map[guild_id]

    def lock(self, guild_id: int, trigger: dict) -> bool:
        if "target" not in trigger.keys():
            return True
        
        map = self.get_lock_map_for_guild(guild_id)
        if trigger["target"] in map:
            return False
        
        map.add(trigger["target"])
        return True
    
    def is_locked(self, guild_id: int, trigger: dict) -> bool:
        if "target" not in trigger.keys():
            return False
        
        map = self.get_lock_map_for_guild(guild_id)
        if trigger["target"] in map:
            return True
        return False

    def unlock(self, guild_id: int, trigger: dict) -> None:
        if "target" not in trigger.keys():
            return
        
        map = self.get_lock_map_for_guild(guild_id)
        map.discard(trigger["target"])

    def unlocklist(self, guild_id: int, triggers: list[dict]) -> None:
        for trigger in triggers:
            self.unlock(guild_id, trigger)

    def unlockall(self) -> None:
        self.lock_map = {}