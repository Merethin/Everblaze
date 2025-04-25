from dotenv import dotenv_values
import discord, sqlite3, argparse, threading, json, asyncio
from discord import app_commands
from discord.ext import commands, tasks
import utility as util

# Global variables.
guilds = {} # All discord servers the bot is in, with their own specific configuration and trigger lists.
everblaze_cursor = None # Everblaze region database cursor
bot_con = None # Connection to the bot database
bot_cursor = None # Bot database cursor
nation_name = "" # The main nation of the player using this script

is_cancelled = False

settings = dotenv_values(".env")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='%', intents=intents)

@bot.event
async def on_ready():
    global nation_name
    print(f'Everblaze: logged in as {bot.user}')

    for guild in bot.guilds:
        bot_cursor.execute("SELECT * FROM guilds WHERE guild_id = ?", [guild.id])
        data = bot_cursor.fetchone()

        if data is not None:
            guilds[guild.id] = {}
            guilds[guild.id]["setup_role"] = data[1]
            guilds[guild.id]["ping_role"] = data[2]
            guilds[guild.id]["channel"] = data[3]
            guilds[guild.id]["triggers"] = util.TriggerList()

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")
        
    print(f"Everblaze has the following guild data: {guilds}")

    url = 'https://www.nationstates.net/api/admin/'
    headers = {'Accept': 'text/event-stream', 'User-Agent': f"Everblaze (Discord bot) by Merethin, used by {nation_name}"}

    client = util.connect_sse(url, headers)

    print(f"Connected to {url}.")
    print(f"User Agent: '{headers["User-Agent"]}'")

    while not is_cancelled:
        region = await asyncio.to_thread(sse_listener, client)
        bot.dispatch("region_update", region)

async def check_command_permissions(interaction: discord.Interaction) -> bool:
    if interaction.guild.id not in guilds.keys():
        await interaction.response.send_message("This server is not configured. Tell the owner to run /config first.", ephemeral=True)
        return False
    guild = guilds[interaction.guild.id]
    if "setup_role" not in guild.keys():
        await interaction.response.send_message("This server is not configured. Tell the owner to run /config first.", ephemeral=True)
        return False
    if interaction.user.get_role(guild["setup_role"]) is None:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return False

    return True

@commands.is_owner()
@bot.tree.command(description="Configure the bot.")
async def config(interaction: discord.Interaction, setup_role: discord.Role, ping_role: discord.Role, channel: discord.TextChannel):
    data = (interaction.guild.id, setup_role.id, ping_role.id, channel.id)
    bot_cursor.execute("INSERT OR REPLACE INTO guilds VALUES (?, ?, ?, ?)", data)
    bot_con.commit()

    if interaction.guild.id not in guilds.keys():
        guilds[interaction.guild.id] = {}

    guilds[interaction.guild.id]["setup_role"] = setup_role.id
    guilds[interaction.guild.id]["ping_role"] = ping_role.id
    guilds[interaction.guild.id]["channel"] = channel.id

    if "triggers" not in guilds[interaction.guild.id].keys():
        guilds[interaction.guild.id]["triggers"] = util.TriggerList()

    print(f"Server configuration updated for guild {interaction.guild.name}: Setup Role {setup_role.name}, Ping Role {ping_role.name}, Channel {channel.name}")

    await interaction.response.send_message("Server configuration updated!", ephemeral=True)

def display_trigger(trigger) -> str:
    if "target" not in trigger.keys():
        return trigger["api_name"]
    
    return f"{trigger["target"]} ({trigger["api_name"]};{trigger["delay"]}s)"

def format_update_log(trigger) -> str:
    if "target" not in trigger.keys():
        return f"{trigger["api_name"]} updated!"
    
    return f"{trigger["target"]} will update in {trigger["delay"]}s ({trigger["api_name"]} updated)!"

@bot.tree.command(description="Add a new trigger.")
async def add(interaction: discord.Interaction, trigger: str):
    if not await check_command_permissions(interaction):
        return
    
    targets = guilds[interaction.guild.id]["triggers"]
    
    targets.add_trigger({
        "api_name": util.format_nation_or_region(trigger)
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Added trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=True)

@bot.tree.command(description="Add a new target and associated trigger.")
async def add_target(interaction: discord.Interaction, target: str, trigger: str, delay: int):
    if not await check_command_permissions(interaction):
        return
    
    targets = guilds[interaction.guild.id]["triggers"]
    
    targets.add_trigger({
        "api_name": util.format_nation_or_region(trigger),
        "target": util.format_nation_or_region(target),
        "delay": delay,
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Added target {target} with trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=True)
    
@bot.tree.command(description="Remove a trigger.")
async def remove(interaction: discord.Interaction, trigger: str):
    if not await check_command_permissions(interaction):
        return
    
    targets = guilds[interaction.guild.id]["triggers"]
    
    targets.remove_trigger(util.format_nation_or_region(trigger))

    await interaction.response.send_message(f"Removed trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=True)

@bot.tree.command(description="List active triggers.")
async def triggers(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    targets = guilds[interaction.guild.id]["triggers"]

    if(len(targets.triggers) == 0):
        await interaction.response.send_message(f"No triggers set!", ephemeral=True)

    list = "\n".join([display_trigger(t) for t in targets.triggers])
    await interaction.response.send_message(list, ephemeral=True)
    
@bot.tree.command(description="Find a trigger for a selected target.")
async def snipe(interaction: discord.Interaction, target: str, update: str, ideal_delay: int, early_tolerance: int, late_tolerance: int):
    if not await check_command_permissions(interaction):
        return
    
    minor = update == "minor"

    region_data = util.fetch_region_data_from_db(everblaze_cursor, util.format_nation_or_region(target))
    if region_data is None:
        await interaction.response.send_message(f"{target} does not exist!", ephemeral=True)
        return
    
    target_time = 0
    if minor:
        target_time = region_data["seconds_minor"] - ideal_delay
    else:
        target_time = region_data["seconds_major"] - ideal_delay

    trigger = util.find_region_updating_at_time(everblaze_cursor, target_time, minor, early_tolerance, late_tolerance)
    if trigger is None:
        await interaction.response.send_message(f"No trigger for {target} found in the specified time range!", ephemeral=True)
        return

    delay = 0
    if minor:
        delay = region_data["seconds_minor"] - trigger["seconds_minor"]
    else:
        delay = region_data["seconds_major"] - trigger["seconds_major"]

    targets = guilds[interaction.guild.id]["triggers"]

    targets.add_trigger({
        "target": util.format_nation_or_region(target),
        "api_name": trigger["api_name"],
        "delay": delay,
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Set trigger {trigger["api_name"]} for {target} (delay: {delay}s)", ephemeral=True)

@bot.event
async def on_region_update(region: str):
    data = util.fetch_region_data_from_db(everblaze_cursor, region)

    if data is None:
        return None
    
    for id, guild in guilds.items():
        guild = bot.get_guild(id)

        targets = guild["triggers"]

        already_updated = targets.remove_all_updated_triggers(data["update_index"])
        channel = guild.get_channel(guild["channel"])
        role = guild.get_role(guild["ping_role"])

        for r in already_updated:
            channel.send(f"{r["api_name"]} has already updated!")

        target = targets.query_trigger(region)

        if target is not None:
            channel.send(f"{role.mention} {format_update_log(target["api_name"])}")
            targets.remove_trigger(target)

def sse_listener(client) -> None:
    for event in client:
        # We only notice this after a heartbeat arrives from the connection.
        if is_cancelled:
            print("Cancelled thread, closing connection")
            return
        
        if event.data: # If the event has no data it's a heartbeat. We do want to receive heartbeats however so that we can check for cancellation above.
            data = json.loads(event.data)
            happening = data["str"]

            # The happening line is formatted like this: "%%region_name%% updated." We want to know if the happening matches this, 
            # and if so, retrieve the region name.
            match = util.UPDATE_REGEX.match(happening)
            if match is not None:
                region_name = match.groups()[0]

                print(f"log: {region_name} updated!")

                return region_name

def main():
    global everblaze_cursor, bot_con, bot_cursor, is_cancelled, nation_name
    parser = argparse.ArgumentParser(prog="everblaze-bot", description="Everblaze Discord bot for NationStates R/D")
    parser.add_argument("-n", "--nation-name", default="")
    parser.add_argument("-r", '--regenerate-db', action='store_true')
    args = parser.parse_args()

    if len(args.nation_name) != 0:
        nation_name = args.nation_name
    else:
        nation_name = input("Please enter your main nation name: ")

    util.bootstrap(nation_name, args.regenerate_db)

    everblaze_con = sqlite3.connect("regions.db")
    everblaze_cursor = everblaze_con.cursor()

    bot_con = sqlite3.connect("bot.db")
    bot_cursor = bot_con.cursor()

    table_list = bot_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='guilds'; ").fetchall()

    if table_list == []:
        # Guild list doesn't exist, create it
        bot_cursor.execute("CREATE TABLE guilds(guild_id, setup_role_id, ping_role_id, channel_id)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_guild_id ON guilds (guild_id);")
        bot_con.commit()

    bot.run(settings["TOKEN"])

    is_cancelled = True

if __name__ == "__main__":
    main()