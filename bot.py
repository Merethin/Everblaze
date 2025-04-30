# bot.py - Versatile Discord bot for R/D triggering and tag raiding
# Authored by Merethin, licensed under the BSD-2-Clause license.
# The only API calls made by this file are imported from db.py and utility.py, through bootstrap() and check_if_nation_exists().

from dotenv import dotenv_values
import discord, sqlite3, argparse, json, asyncio, typing, re, time, math, sys, sseclient, threading
from discord.ext import commands
import utility as util
from pagination import Pagination
from dataclasses import dataclass

# Stores information about a region update event, specifically the last one that happened.
# It stores the update index of the region, the UNIX timestamp of when it updated, and the previously predicted minor and major update times for that region.
@dataclass
class LastUpdate:
    index: int # The index of the region in update.
    time: float # The UNIX timestamp at which the region updated.
    minor: int # The predicted timestamp at which the region would update during minor update.
    major: int # The predicted timestamp at which the region would update during major update.

# Stores settings and triggers for a specific channel in a guild.
@dataclass
class TriggerChannel:
    setup_role: int # Role to add, remove, and view triggers.
    ping_role: int # Role to ping when triggers update.
    invisible: bool # Whether configuration messages should be ephemeral.
    triggers: util.TriggerList # The trigger list for this channel.
    session: typing.Optional[typing.Awaitable[None]] = None # Currently running tag session, stored as an async coroutine.

# Stores settings, update data and global targets for a guild.
@dataclass
class Guild:
    setup_role: int # Role to set up trigger settings.
    mutually_exclusive_targets: set # Targets shared across channels, so that one team doesn't inadvertently interfere with the other.
    last_update: typing.Optional[LastUpdate] # Last update information.
    channels: dict[int, TriggerChannel] # Configured channels.
    ongoing_tags: int = 0 # Ongoing tag sessions.

# Global variables.
guilds: dict[int, Guild] = {} # All discord servers the bot is in, with their own specific configuration and trigger lists.
everblaze_cursor: typing.Optional[sqlite3.Cursor] = None # Everblaze region database cursor
bot_con: typing.Optional[sqlite3.Connection] = None # Connection to the bot database
bot_cursor: typing.Optional[sqlite3.Cursor] = None # Bot database cursor
nation_name: str = "" # The main nation of the player using this script

# Config loaded from .env, in order to access the Discord token.
settings: dict[str, str | None] = dotenv_values(".env")

intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Used to cancel the SSE thread.
sse_cancel_event = threading.Event()

bot = commands.Bot(command_prefix='%', intents=intents)

@bot.event
async def on_ready():
    global nation_name
    print(f'Everblaze: logged in as {bot.user}')

    assert bot_cursor

    # Load guild data from the database
    for guild in bot.guilds:
        bot_cursor.execute("SELECT * FROM guilds WHERE guild_id = ?", [guild.id])
        data = bot_cursor.fetchone()

        if data is not None:
            guilds[guild.id] = Guild(data[1], set(), None, {})

    bot_cursor.execute("SELECT * FROM channels")
    data = bot_cursor.fetchall()

    # Load channel data from the database
    for channel in data:
        if channel[0] in guilds.keys():
            guilds[channel[0]].channels[channel[1]] = TriggerChannel(channel[1], channel[2], channel[3], util.TriggerList())

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    url = 'https://www.nationstates.net/api/admin+endo+member/'
    headers = {'Accept': 'text/event-stream', 'User-Agent': f"Everblaze (Discord bot) by Merethin, used by {nation_name}"}

    # Connect to the SSE feed for: update events, endorsement events, and WA resignation events.
    client = util.connect_sse(url, headers)

    print(f"Connected to {url}.")
    print(f"User Agent: '{headers["User-Agent"]}'")

    while True:
        # Listen to SSE events on loop.
        response = await asyncio.to_thread(sse_listener, client, sse_cancel_event)
        if response is None:
            return
        (event, data) = response
        bot.dispatch(event, data)

# Check if a command follows the following requirements:
# 1. The guild it was run in has been configured.
# 2. The channel it was run in has been configured.
# 3. The author of the command has the Setup Role for the channel it's being used in.
async def check_command_permissions(interaction: discord.Interaction) -> bool:
    if interaction.guild.id not in guilds.keys():
        await interaction.response.send_message("This server is not configured. Tell the owner to run /config first.", ephemeral=True)
        return False
    
    guild = guilds[interaction.guild.id]
    if interaction.channel.id not in guild.channels.keys():
        await interaction.response.send_message("This channel is not configured. Tell a person with the appropriate role to run /addch first.", ephemeral=True)
        return False
    
    channel = guild.channels[interaction.channel.id]
    if interaction.user.get_role(channel.setup_role) is None:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return False

    return True

# Get the channel properties to edit from a command.
# Assumes check_command_permissions() has been run before,
# so the channel properties should exist no matter what.
def get_channel_to_edit(interaction: discord.Interaction) -> TriggerChannel:
    guild = guilds[interaction.guild.id]

    if interaction.channel.id in guild.channels.keys():
        return guild.channels[interaction.channel.id]
    
    typing.assert_never("No channel to edit after running check_command_permissions!")

# Whether a response to a command should be ephemeral, depending on the channel settings.
def should_be_ephemeral(interaction: discord.Interaction) -> bool:
    return bool(get_channel_to_edit(interaction).invisible)

# Get the trigger list for a channel.
def get_trigger_list(channel: TriggerChannel) -> util.TriggerList:
    return channel.triggers

# Format a number of seconds as a string "HH:MM:SS"
def format_time(seconds: int) -> str:
    minutes = seconds // 60
    seconds = seconds % 60
    hours = minutes // 60
    minutes = minutes % 60
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)

@bot.tree.command(description="Configure the bot.")
async def config(interaction: discord.Interaction, setup_role: discord.Role):
    if interaction.user.id != interaction.guild.owner.id:
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    
    assert bot_cursor
    assert bot_con
    
    data = (interaction.guild.id, setup_role.id)
    bot_cursor.execute("INSERT OR REPLACE INTO guilds VALUES (?, ?)", data)
    bot_con.commit()

    if interaction.guild.id not in guilds.keys():
        guilds[interaction.guild.id] = Guild(setup_role.id, set(), None, {})
    else:
        guilds[interaction.guild.id].setup_role = setup_role.id
        guilds[interaction.guild.id].last_update = None

    print(f"Server configuration updated for guild {interaction.guild.name}: Setup Role {setup_role.name}")

    await interaction.response.send_message("Server configuration updated!", ephemeral=True)

@bot.tree.command(description="Add a separate setup role, ping role and target list to a channel.")
async def addch(interaction: discord.Interaction, setup_role: discord.Role, ping_role: discord.Role, invisible: bool):
    if interaction.user.get_role(guilds[interaction.guild.id].setup_role) is None:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return
    
    assert bot_cursor
    assert bot_con
    
    data = (interaction.guild.id, interaction.channel.id, setup_role.id, ping_role.id, invisible)
    bot_cursor.execute("INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?)", data)
    bot_con.commit()

    guild = guilds[interaction.guild.id]

    if interaction.channel.id not in guild.channels.keys():
        guild.channels[interaction.channel.id] = TriggerChannel(setup_role.id, ping_role.id, invisible, util.TriggerList())
    else:
        guild.channels[interaction.channel.id].setup_role = setup_role.id
        guild.channels[interaction.channel.id].ping_role = ping_role.id
        guild.channels[interaction.channel.id].invisible = invisible

    print(f"Server configuration updated for guild {interaction.guild.name}, channel {interaction.channel.name}: Setup Role {setup_role.name}, Ping Role {ping_role.name}, Invisible {invisible}")

    await interaction.response.send_message("Channel configuration updated!", ephemeral=True)

@bot.tree.command(description="Remove the separate ping role and target list from a channel.")
async def remch(interaction: discord.Interaction):
    if interaction.user.get_role(guilds[interaction.guild.id].setup_role) is None:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return
    
    if interaction.channel.id not in guilds[interaction.guild.id].channels.keys():
        await interaction.response.send_message("This channel has no channel-specific configuration to remove!", ephemeral=True)
        return
    
    assert bot_cursor
    assert bot_con
    
    bot_cursor.execute("DELETE FROM channels WHERE guild_id = ? AND channel_id = ?", [interaction.guild.id, interaction.channel.id])
    bot_con.commit()

    guild = guilds[interaction.guild.id]

    triggers = get_trigger_list(guild.channels[interaction.channel.id]).triggers
    for trigger in triggers:
        if "target" in trigger.keys():
            guild.mutually_exclusive_targets.discard(trigger["target"])

    del guild.channels[interaction.channel.id]

    await interaction.response.send_message("Channel configuration removed!", ephemeral=True)

# Format a string with trigger data, including the link, triggers and predicted update times.
def display_trigger(trigger: typing.Dict) -> str:
    assert everblaze_cursor
    data = util.fetch_region_data_from_db(everblaze_cursor, trigger["api_name"])

    if data is None:
        return ""

    if "target" not in trigger.keys():
        return f"https://www.nationstates.net/region={trigger["api_name"]} - {format_time(data["seconds_minor"])} minor, {format_time(data["seconds_major"])} major"
    
    return f"https://www.nationstates.net/region={trigger["target"]} ({data["canon_name"]};{trigger["delay"]}s) - {format_time(data["seconds_minor"])} minor, {format_time(data["seconds_major"])} major"

# Format a string with a link to a trigger.
def display_trigger_simple(trigger: typing.Dict) -> str:
    if "target" not in trigger.keys():
        return f"trigger: https://www.nationstates.net/region={trigger["api_name"]}"
    
    return f"target: https://www.nationstates.net/region={trigger["target"]}"

# Format a region update happening given a trigger that has just updated.
def format_update_log(trigger: typing.Dict) -> str:
    if "target" not in trigger.keys():
        return f"{trigger["api_name"]} updated!"
    
    return f"{trigger["target"]} will update in {trigger["delay"]}s ({trigger["api_name"]} updated)!"

@bot.tree.command(description="Add a new trigger.")
async def add(interaction: discord.Interaction, trigger: str):
    if not await check_command_permissions(interaction):
        return
    
    assert everblaze_cursor
    
    targets = get_trigger_list(get_channel_to_edit(interaction))
    
    targets.add_trigger({
        "api_name": util.format_nation_or_region(trigger)
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Added trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Add a new target and associated trigger.")
async def add_target(interaction: discord.Interaction, target: str, trigger: str, delay: int):
    if not await check_command_permissions(interaction):
        return
    
    assert everblaze_cursor
    
    targets = get_trigger_list(get_channel_to_edit(interaction))
    
    targets.add_trigger({
        "api_name": util.format_nation_or_region(trigger),
        "target": util.format_nation_or_region(target),
        "delay": delay,
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Added target {target} with trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Reset all triggers and update information.")
async def reset(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    if guilds[interaction.guild.id].ongoing_tags > 0:
        await interaction.response.send_message(f"Can't do that, there are tag sessions running. Use /clear instead.", ephemeral=should_be_ephemeral(interaction))
        return

    guilds[interaction.guild.id].mutually_exclusive_targets = set()

    for channel in guilds[interaction.guild.id].channels.values():
        channel.triggers.triggers = []

    guilds[interaction.guild.id].last_update = None

    await interaction.response.send_message(f"Successfully reset all triggers (including channel-specific ones) and update information.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Reset all triggers in this channel.")
async def clear(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    triggers = get_trigger_list(get_channel_to_edit(interaction)).triggers

    for trigger in triggers:
        if "target" in trigger.keys():
            guilds[interaction.guild.id].mutually_exclusive_targets.discard(trigger["target"])

    get_trigger_list(get_channel_to_edit(interaction)).triggers = []

    await interaction.response.send_message(f"Successfully reset all triggers in this channel.", ephemeral=should_be_ephemeral(interaction))
    
@bot.tree.command(description="Remove a trigger.")
async def remove(interaction: discord.Interaction, trigger: str):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_channel_to_edit(interaction))
    
    t = targets.remove_trigger(util.format_nation_or_region(trigger))
    if t is None:
        await interaction.response.send_message(f"No such trigger {trigger}. Check that you have run /remove with the trigger name and not the target name.", ephemeral=should_be_ephemeral(interaction))
        return
    
    if "target" in t.keys():
        guilds[interaction.guild.id].mutually_exclusive_targets.discard(t["target"])

    await interaction.response.send_message(f"Removed trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="List active triggers.")
async def triggers(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_channel_to_edit(interaction))

    if(len(targets.triggers) == 0):
        await interaction.response.send_message(f"No triggers set!", ephemeral=should_be_ephemeral(interaction))
        return

    ELEMENTS_PER_PAGE = 10

    if(len(targets.triggers) > ELEMENTS_PER_PAGE):
        local_targets = targets.triggers[:] # Local copy in case the original one is modified while the user is scrolling

        async def get_page(page: int):
            emb = discord.Embed(title="Trigger List", description="")
            offset = (page-1) * ELEMENTS_PER_PAGE
            for region in local_targets[offset:offset+ELEMENTS_PER_PAGE]:
                emb.description += f"{display_trigger(region)}\n"
            n = Pagination.compute_total_pages(len(local_targets), ELEMENTS_PER_PAGE)
            emb.set_footer(text=f"Page {page} of {n}")
            return emb, n

        await Pagination(interaction, get_page).navigate()
        return

    list = "\n".join([display_trigger(t) for t in targets.triggers])
    await interaction.response.send_message(list, ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Display the next region to update.")
async def next(interaction: discord.Interaction, visible: bool = True):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_channel_to_edit(interaction))

    if(len(targets.triggers) == 0):
        await interaction.response.send_message(f"No triggers set!", ephemeral=should_be_ephemeral(interaction))
        return
    
    await interaction.response.send_message(f"Next {display_trigger_simple(targets.triggers[0])}", ephemeral=(should_be_ephemeral(interaction) and not visible))

@bot.tree.command(description="Skip the next region to update.")
async def skip(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_channel_to_edit(interaction))

    if(len(targets.triggers) == 0):
        await interaction.response.send_message(f"No triggers set!", ephemeral=should_be_ephemeral(interaction))
        return
    
    name = targets.triggers[0]["api_name"]
    trigger = targets.remove_trigger(name)

    assert trigger # The case where the trigger list is empty is already handled above.

    if "target" in trigger.keys():
        guilds[interaction.guild.id].mutually_exclusive_targets.discard(trigger["target"])
    
    await interaction.response.send_message(f"Removed {display_trigger_simple(trigger)}")
    
@bot.tree.command(description="Find a trigger for a selected target.")
async def snipe(interaction: discord.Interaction, target: str, update: str, ideal_delay: int, early_tolerance: int, late_tolerance: int):
    if not await check_command_permissions(interaction):
        return
    
    assert everblaze_cursor
    
    minor = util.is_minor(update)

    region_data = util.fetch_region_data_from_db(everblaze_cursor, util.format_nation_or_region(target))
    if region_data is None:
        await interaction.response.send_message(f"{target} does not exist!", ephemeral=should_be_ephemeral(interaction))
        return
    
    trigger_time = 0
    if minor:
        trigger_time = region_data["seconds_minor"] - ideal_delay
    else:
        trigger_time = region_data["seconds_major"] - ideal_delay

    trigger = util.find_region_updating_at_time(everblaze_cursor, trigger_time, minor, early_tolerance, late_tolerance)
    if trigger is None:
        await interaction.response.send_message(f"No trigger for {target} found in the specified time range!", ephemeral=should_be_ephemeral(interaction))
        return

    delay = 0
    if minor:
        delay = region_data["seconds_minor"] - trigger["seconds_minor"]
    else:
        delay = region_data["seconds_major"] - trigger["seconds_major"]

    targets = get_trigger_list(get_channel_to_edit(interaction))

    targets.add_trigger({
        "target": util.format_nation_or_region(target),
        "api_name": trigger["api_name"],
        "delay": delay,
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Set trigger {trigger["api_name"]} for {target} (delay: {delay}s)", ephemeral=should_be_ephemeral(interaction))

class BaseRegionView(discord.ui.View):
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

@bot.tree.command(description="Find and select targets with no password and an executive delegate.")
async def select(interaction: discord.Interaction, update: str, point_endos: int, min_switch_time: int, ideal_delay: int, early_tolerance: int, late_tolerance: int, confirm: bool = True):
    if not await check_command_permissions(interaction):
        return
    
    await interaction.response.send_message(f"Got it! Selecting targets for {update}...", ephemeral=should_be_ephemeral(interaction))

    assert everblaze_cursor
    
    minor = util.is_minor(update)

    last_update = guilds[interaction.guild.id].last_update

    start = -1
    if last_update is not None:
        start = last_update.index

    raidable_regions = util.find_raidable_regions(everblaze_cursor, point_endos, start)

    last_switch_time = -999

    if last_update is not None:
        if minor:
            last_switch_time = last_update.minor
        else:
            last_switch_time = last_update.major

    for region in raidable_regions:
        last_update = guilds[interaction.guild.id].last_update

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

        target = region["api_name"]
        trigger_time = update_time - ideal_delay

        # Skip if selected in a different channel
        if target in guilds[interaction.guild.id].mutually_exclusive_targets:
            continue

        trigger = util.find_region_updating_at_time(everblaze_cursor, trigger_time, minor, early_tolerance, late_tolerance)
        if trigger is None:
            continue

        delay = 0
        if minor:
            delay = region["seconds_minor"] - trigger["seconds_minor"]
        else:
            delay = region["seconds_major"] - trigger["seconds_major"]

        targets = get_trigger_list(get_channel_to_edit(interaction))
        should_finish = False

        if not confirm:
            targets.add_trigger({
                "api_name": trigger["api_name"],
                "target": target,
                "delay": delay,
            })
            targets.sort_triggers(everblaze_cursor)

            guilds[interaction.guild.id].mutually_exclusive_targets.add(target)

            last_switch_time = update_time
            continue

        view = BaseRegionView(interaction.user)
        accept_button = discord.ui.Button(label="Accept Target", style=discord.ButtonStyle.green)
        skip_button = discord.ui.Button(label="Find Another", style=discord.ButtonStyle.red)
        end_button = discord.ui.Button(label="Finish", style=discord.ButtonStyle.gray)

        async def accept_callback(interaction: discord.Interaction):
            nonlocal last_switch_time

            if target in guilds[interaction.guild.id].mutually_exclusive_targets:
                await interaction.response.send_message(f"The target {target} has already been selected in a different channel, finding a new one instead.", ephemeral=should_be_ephemeral(interaction))
                view.stop()
                return

            targets.add_trigger({
                "api_name": trigger["api_name"],
                "target": target,
                "delay": delay,
            })
            targets.sort_triggers(everblaze_cursor)

            guilds[interaction.guild.id].mutually_exclusive_targets.add(target)

            last_switch_time = update_time

            await interaction.response.send_message(f"Set trigger {trigger["api_name"]} for target {target} (delay: {delay}s)", ephemeral=should_be_ephemeral(interaction))

            view.stop()
        
        async def skip_callback(interaction: discord.Interaction):
            await interaction.response.send_message(f"Understood, finding a different target...", ephemeral=should_be_ephemeral(interaction))
            view.stop()

        async def end_callback(interaction: discord.Interaction):
            nonlocal should_finish
            should_finish = True

            await interaction.response.send_message("Stopped looking for targets.", ephemeral=should_be_ephemeral(interaction))
            view.stop()

        # add the callback to the button
        accept_button.callback = accept_callback
        skip_button.callback = skip_callback
        end_button.callback = end_callback
        view.add_item(accept_button)
        view.add_item(skip_button)
        view.add_item(end_button)

        await interaction.followup.send(f"Target: https://www.nationstates.net/region={target}\nTrigger: {trigger["api_name"]}\nDelay: {delay}s", view=view, ephemeral=should_be_ephemeral(interaction))

        await view.wait()

        if should_finish:
            return

    await interaction.followup.send(f"No more regions found!", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Start a tag run session.")
async def tag(interaction: discord.Interaction, update: str, point_endos: int, switch_time: int, min_delay: int) -> None:
    if not await check_command_permissions(interaction):
        return
    
    if guilds[interaction.guild.id].channels[interaction.channel.id].session is not None:
        await interaction.response.send_message(f"There is already a tag session ongoing in this channel!", ephemeral=True)
        return
    
    session = run_tag_session(interaction, update, point_endos, switch_time, min_delay)
    guilds[interaction.guild.id].channels[interaction.channel.id].session = session
    await session

async def run_tag_session(interaction: discord.Interaction, update: str, point_endos: int, switch_time: int, min_delay: int) -> None:
    global ongoing_tags
    
    if guilds[interaction.guild.id].last_update is None:
        await interaction.response.send_message(f"Waiting for {update} to start...")
        await bot.wait_for(
            "region_update",
            timeout=None,
        )
        await interaction.followup.send(f"Started tag run for {update}. Please post the point and start endorsing.")
    else:
        await interaction.response.send_message(f"Started tag run for {update}. Please post the point and start endorsing.")

    assert everblaze_cursor

    minor = util.is_minor(update)

    nation = ""

    guilds[interaction.guild.id].ongoing_tags += 1

    wfe_blacklist: set[str] = set()
    embassy_blacklist: set[str] = set()

    while True:
        op = await bot.wait_for(
            "message",
            check=lambda x: x.channel.id == interaction.channel.id
            and (x.content.lower().startswith("t")
            or x.content.lower() == "quit"
            or x.content.lower() == "miss"
            or x.content.lower().startswith("endos")
            or x.content.lower().startswith("delay")
            or x.content.lower().startswith("switch")
            or x.content.lower().startswith("blwfe")
            or x.content.lower().startswith("wlwfe")
            or x.content.lower().startswith("blemb")
            or x.content.lower().startswith("wlemb")),
            timeout=None,
        )

        endos = 0

        if op.content.lower().startswith("t"):
            # Point provided. Fetch nation name
            match = re.match(r"t[\s]+http[s]?://(?:fast|www)\.nationstates\.net/nation=([a-zA-Z0-9_ ]+)", op.content.lower())
            if match is not None:
                nation = util.format_nation_or_region(match.groups()[0])
            else:
                continue
        elif op.content.lower() == "miss":
            # Don't wait for all nations to endorse the point, it's already endorsed
            endos = point_endos + 1
        else:
            if op.content.lower() == "quit":
                await interaction.followup.send(f"Quitting the tag session.")
                guilds[interaction.guild.id].ongoing_tags -= 1
                guilds[interaction.guild.id].channels[interaction.channel.id].session = None
                return
            elif op.content.lower().startswith("endos"):
                match = re.match(r"endos[\s]+([0-9]+)", op.content.lower())
                if match is not None:
                    point_endos = int(match.groups()[0])
                    await interaction.followup.send(f"Point endos changed to {point_endos}.")
            elif op.content.lower().startswith("delay"):
                match = re.match(r"delay[\s]+([0-9]+)", op.content.lower())
                if match is not None:
                    min_delay = int(match.groups()[0])
                    await interaction.followup.send(f"Minimum delay changed to {min_delay}s")
            elif op.content.lower().startswith("switch"):
                match = re.match(r"switch[\s]+([0-9]+)", op.content.lower())
                if match is not None:
                    switch_time = int(match.groups()[0])
                    await interaction.followup.send(f"Switch time changed to {switch_time}s")
            elif op.content.lower().startswith("blwfe"):
                match = re.match(r"blwfe[\s]+([0-9a-z_ ]+)", op.content.lower())
                if match is not None:
                    text = match.groups()[0]
                    wfe_blacklist.add(embassy)
                    await interaction.followup.send(f"Added \"{text}\" to the WFE blacklist")
            elif op.content.lower().startswith("wlwfe"):
                match = re.match(r"wlwfe[\s]+([0-9a-z_ ]+)", op.content.lower())
                if match is not None:
                    text = match.groups()[0]
                    wfe_blacklist.discard(embassy)
                    await interaction.followup.send(f"Removed \"{text}\" from the WFE blacklist, if it was there")
            elif op.content.lower().startswith("blemb"):
                match = re.match(r"blemb[\s]+([0-9a-z_ ]+)", op.content.lower())
                if match is not None:
                    embassy = util.format_nation_or_region(match.groups()[0])
                    embassy_blacklist.add(embassy)
                    await interaction.followup.send(f"Added {embassy} to the embassy blacklist")
            elif op.content.lower().startswith("wlemb"):
                match = re.match(r"wlemb[\s]+([0-9a-z_ ]+)", op.content.lower())
                if match is not None:
                    embassy = util.format_nation_or_region(match.groups()[0])
                    embassy_blacklist.discard(embassy)
                    await interaction.followup.send(f"Removed {embassy} to the embassy blacklist, if it was there")
            continue

        message: typing.Optional[discord.WebhookMessage] = None
        if endos < point_endos:
            message = await interaction.followup.send(f"Waiting for everyone to endorse {nation} before posting target... ({endos}/{point_endos})")

        def match(data: typing.Tuple[str, str]) -> bool:
            nonlocal nation
            (_, target) = data
            return target == nation
        
        while endos < point_endos:
            (event, _) = await bot.wait_for(
                "wa",
                check=match,
                timeout=None,
            )
            if event == "endo":
                endos += 1
                if message is not None:
                    await message.edit(content=f"Waiting for everyone to endorse {nation} before posting target... ({endos}/{point_endos})")
            elif event == "unendo":
                await interaction.followup.send(f"{nation} has been unendorsed, canceling. Waiting for another command.")
                break
            elif event == "resign":
                await interaction.followup.send(f"{nation} has resigned from the WA, canceling. Waiting for another command.")
                break
        else:
            last_update = guilds[interaction.guild.id].last_update
            assert last_update

            start = last_update.index

            raidable_regions = util.find_raidable_regions(everblaze_cursor, point_endos, start)

            last_update_time = 0
            if minor:
                last_update_time = last_update.minor
            else:
                last_update_time = last_update.major

            time_since_last_update = time.time() - last_update.time
            target_update_time = math.ceil(last_update_time + time_since_last_update + switch_time + min_delay)

            search_start_time = time.time()

            for region in raidable_regions:
                last_update = guilds[interaction.guild.id].last_update
                assert last_update

                if(region["update_index"] <= last_update.index):
                    continue

                update_time: int = 0
                if minor:
                    update_time = region["seconds_minor"]
                else:
                    update_time = region["seconds_major"]

                embassies: list[str] = region["embassies"].split(",")
                for embassy in embassy_blacklist:
                    if embassy in embassies:
                        continue

                wfe: str = region["wfe"]
                for entry in wfe_blacklist:
                    if entry in wfe.lower():
                        continue

                # Large region is probably updating. Let's wait until it ends and then find a more reliable trigger/target.
                while (update_time - target_update_time) > 2 or time_since_last_update > 1.5:
                    await asyncio.sleep(0.3) # Wait for a bit longer before finding a target.

                    last_update = guilds[interaction.guild.id].last_update
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

                if target in guilds[interaction.guild.id].mutually_exclusive_targets:
                    continue

                guilds[interaction.guild.id].mutually_exclusive_targets.add(target)

                search_time = time.time() - search_start_time
                remaining_time = switch_time - search_time

                gap_delay = (update_time - target_update_time)

                if remaining_time > 0:
                    await asyncio.sleep(remaining_time)

                try:
                    embed = discord.Embed()
                    text = "%" * 400
                    embed.description = f"[{text}](https://fast.nationstates.net/region={target})"
                    embed.set_footer(text=f"Move to target: {target}, estimated delay: {gap_delay + min_delay}s")
                    await interaction.followup.send(embed=embed)
                except Exception:
                    await interaction.followup.send(f"An error occurred, please try again.")
                    break
                break
            else:
                await interaction.followup.send(f"No more regions found, update is over! Quitting tag session.")
                guilds[interaction.guild.id].ongoing_tags -= 1
                guilds[interaction.guild.id].channels[interaction.channel.id].session = None
                return

def update_region(api_name: str, last_update: LastUpdate, channel_id: int, ping_role: int, guild: discord.Guild, targets: util.TriggerList):
    already_updated = targets.remove_all_updated_triggers(last_update.index)
    channel = guild.get_channel(channel_id)
    role = guild.get_role(ping_role)

    messages = []

    for r in already_updated:
        messages.append((channel, f"{r["api_name"]} has already updated!"))

    target = targets.query_trigger(api_name)

    if target is not None:
        targets.remove_trigger(api_name)
        if "target" in target.keys():
            guilds[guild.id].mutually_exclusive_targets.discard(target["target"])
        messages.append((channel, f"{role.mention} {format_update_log(target)}"))

    return messages

@bot.event
async def on_region_update(event: typing.Tuple[str, int]):
    assert everblaze_cursor

    (region, timestamp) = event

    data = util.fetch_region_data_from_db(everblaze_cursor, region)

    if data is None:
        return None
    
    messages = []
    
    for id, server in guilds.items():
        guild = bot.get_guild(id)

        server.last_update = LastUpdate(data["update_index"], float(timestamp), data["seconds_minor"], data["seconds_major"])

        for id, channel in server.channels.items():
            channel_targets = get_trigger_list(channel)
            messages += update_region(region, server.last_update, id, channel.ping_role, guild, channel_targets)

    coroutines = [channel.send(message) for (channel, message) in messages]
    await asyncio.gather(*coroutines)

ENDO_REGEX = re.compile(r"@@([a-z0-9_]+)@@ endorsed @@([a-z0-9_]+)@@")
UNENDO_REGEX = re.compile(r"@@([a-z0-9_]+)@@ withdrew its endorsement from @@([a-z0-9_]+)@@")
RESIGN_REGEX = re.compile(r"@@([a-z0-9_]+)@@ resigned from the World Assembly")

def sse_listener(client: sseclient.SSEClient, cancel_event: threading.Event) -> typing.Optional[typing.Tuple[str, typing.Tuple[str, int] | typing.Tuple[str, str]]]:
    for event in client:
        # We only notice this after a heartbeat arrives from the connection.
        if cancel_event.is_set():
            print("Cancelled thread, closing connection")
            return None
        
        if event.data: # If the event has no data it's a heartbeat. We do want to receive heartbeats however so that we can check for cancellation above.
            data = json.loads(event.data)
            happening = data["str"]

            # The update happening line is formatted like this: "%%region_name%% updated." We want to know if the happening matches this, 
            # and if so, retrieve the region name.
            match = util.UPDATE_REGEX.match(happening)
            if match is not None:
                region_name = match.groups()[0]

                print(f"log: {region_name} updated!")

                time = data["time"]
                assert type(time) == int
                return ("region_update", (region_name, time))
            
            # The endorsement happening line is formatted like this: "@@endorser@@ endorsed @@endorsed@@" We want to know if the happening matches this, 
            # and if so, retrieve the endorsed nation's name.
            match = ENDO_REGEX.match(happening)
            if match is not None:
                target = match.groups()[1]

                print(f"log: {target} was endorsed!")

                return ("wa", ("endo", target))
            
            # The unendorsement happening line is formatted like this: "@@endorser@@ withdrew its endorsement from @@endorsed@@" 
            # We want to know if the happening matches this, and if so, retrieve the unendorsed nation's name.
            match = UNENDO_REGEX.match(happening)
            if match is not None:
                target = match.groups()[1]

                print(f"log: {target} was unendorsed!")

                return ("wa", ("unendo", target))
            
            # The WA resignation happening line is formatted like this: "@@nation@@ resigned from the World Assembly" 
            # We want to know if the happening matches this, and if so, retrieve the nation's name.
            match = RESIGN_REGEX.match(happening)
            if match is not None:
                target = match.groups()[0]

                print(f"log: {target} resigned from the WA!")

                return ("wa", ("resign", target))
            
    return None # SSE feed aborted/disconnected for some reason

def main() -> None:
    global everblaze_cursor, bot_con, bot_cursor, is_cancelled, nation_name
    parser = argparse.ArgumentParser(prog="everblaze-bot", description="Everblaze Discord bot for NationStates R/D")
    parser.add_argument("-n", "--nation-name", default="")
    parser.add_argument("-r", '--regenerate-db', action='store_true')
    args = parser.parse_args()

    if len(args.nation_name) != 0:
        nation_name = args.nation_name
    else:
        nation_name = input("Please enter your main nation name: ")

    if not util.check_if_nation_exists(nation_name):
        print(f"The nation {nation_name} does not exist. Try again.")
        sys.exit(1)

    util.bootstrap(nation_name, args.regenerate_db)

    everblaze_con = sqlite3.connect("regions.db")
    everblaze_cursor = everblaze_con.cursor()

    bot_con = sqlite3.connect("bot.db")
    bot_cursor = bot_con.cursor()

    table_list = bot_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='guilds'; ").fetchall()

    if table_list == []:
        # Guild list doesn't exist, create it
        bot_cursor.execute("CREATE TABLE guilds(guild_id, setup_role_id)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_guild_id ON guilds (guild_id);")
        bot_con.commit()

    channel_list = bot_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'; ").fetchall()

    if channel_list == []:
        # Channel list doesn't exist, create it
        bot_cursor.execute("CREATE TABLE channels(guild_id, channel_id, setup_role_id, ping_role_id, invisible)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_channel_id ON channels (channel_id);")
        bot_con.commit()

    bot.run(settings["TOKEN"])

    print("Closing SSE thread...")
    sse_cancel_event.set()

if __name__ == "__main__":
    main()