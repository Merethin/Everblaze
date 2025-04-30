from dotenv import dotenv_values
import discord, sqlite3, argparse, json, asyncio, typing, re, time, math
from discord.ext import commands
import utility as util
from pagination import Pagination
from dataclasses import dataclass

@dataclass
class LastUpdate:
    index: int
    time: float
    minor: int
    major: int

@dataclass
class TriggerChannel:
    channel: int
    ping_role: int
    invisible: bool
    triggers: util.TriggerList

@dataclass
class Guild:
    setup_role: int
    ping_role: int
    channel: int
    invisible: bool
    triggers: util.TriggerList
    select_targets: set
    last_update: LastUpdate | None
    channels: dict[int, TriggerChannel]

# Global variables.
guilds: dict[int, Guild] = {} # All discord servers the bot is in, with their own specific configuration and trigger lists.
everblaze_cursor: sqlite3.Cursor | None = None # Everblaze region database cursor
bot_con: sqlite3.Connection | None = None # Connection to the bot database
bot_cursor: sqlite3.Cursor | None = None # Bot database cursor
nation_name: str = "" # The main nation of the player using this script

ongoing_tags: int = 0

is_cancelled: bool = False

settings: dict[str, str | None] = dotenv_values(".env")

intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='%', intents=intents)

@bot.event
async def on_ready():
    global nation_name
    print(f'Everblaze: logged in as {bot.user}')

    for guild in bot.guilds:
        bot_cursor.execute("SELECT * FROM guilds WHERE guild_id = ?", [guild.id])
        data = bot_cursor.fetchone()

        if data is not None:
            guilds[guild.id] = Guild(data[1], data[2], data[3], data[4], util.TriggerList(), set(), None, {})

    bot_cursor.execute("SELECT * FROM channels")
    data = bot_cursor.fetchall()

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

    client = util.connect_sse(url, headers)

    print(f"Connected to {url}.")
    print(f"User Agent: '{headers["User-Agent"]}'")

    while not is_cancelled:
        (event, data) = await asyncio.to_thread(sse_listener, client)
        bot.dispatch(event, data)

async def check_command_permissions(interaction: discord.Interaction) -> bool:
    if interaction.guild.id not in guilds.keys():
        await interaction.response.send_message("This server is not configured. Tell the owner to run /config first.", ephemeral=True)
        return False
    guild = guilds[interaction.guild.id]
    if interaction.user.get_role(guild.setup_role) is None:
        await interaction.response.send_message("You are not allowed to use this command!", ephemeral=True)
        return False

    return True

def get_guild_or_channel_to_edit(interaction: discord.Interaction) -> Guild | TriggerChannel:
    guild = guilds[interaction.guild.id]

    if interaction.channel.id in guild.channels.keys():
        return guild.channels[interaction.channel.id]
    
    return guild

def should_be_ephemeral(interaction: discord.Interaction) -> bool:
    return bool(get_guild_or_channel_to_edit(interaction).invisible)

def should_be_ephemeral_guild_wide(interaction: discord.Interaction) -> bool:
    return bool(guilds[interaction.guild.id].invisible)

def get_trigger_list(server: Guild | TriggerChannel) -> util.TriggerList:
    return server.triggers

def format_time(seconds: int) -> str:
    minutes = seconds // 60
    seconds = seconds % 60
    hours = minutes // 60
    minutes = minutes % 60
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)

@bot.tree.command(description="Configure the bot.")
async def config(interaction: discord.Interaction, setup_role: discord.Role, ping_role: discord.Role, channel: discord.TextChannel, invisible: bool):
    if interaction.user.id != interaction.guild.owner.id:
        await interaction.response.send_message("Only the server owner can use this command.", ephemeral=True)
        return
    
    data = (interaction.guild.id, setup_role.id, ping_role.id, channel.id, invisible)
    bot_cursor.execute("INSERT OR REPLACE INTO guilds VALUES (?, ?, ?, ?, ?)", data)
    bot_con.commit()

    if interaction.guild.id not in guilds.keys():
        guilds[interaction.guild.id] = Guild(setup_role.id, ping_role.id, channel.id, invisible, util.TriggerList(), set(), None, {})
    else:
        guilds[interaction.guild.id].setup_role = setup_role.id
        guilds[interaction.guild.id].ping_role = ping_role.id
        guilds[interaction.guild.id].channel = channel.id
        guilds[interaction.guild.id].invisible = invisible
        guilds[interaction.guild.id].last_update = None

    print(f"Server configuration updated for guild {interaction.guild.name}: Setup Role {setup_role.name}, Ping Role {ping_role.name}, Channel {channel.name}, Invisible {invisible}")

    await interaction.response.send_message("Server configuration updated!", ephemeral=True)

@bot.tree.command(description="Add a separate ping role and target list to a channel.")
async def addch(interaction: discord.Interaction, ping_role: discord.Role, invisible: bool):
    if not await check_command_permissions(interaction):
        return
    
    if interaction.channel.id == guilds[interaction.guild.id].channel:
        await interaction.response.send_message("Can't configure this channel because it is already the server's primary channel. Please tell the server owner to change this by running /config.", ephemeral=True)
        return
    
    data = (interaction.guild.id, interaction.channel.id, ping_role.id, invisible)
    bot_cursor.execute("INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?)", data)
    bot_con.commit()

    guild = guilds[interaction.guild.id]

    if interaction.channel.id not in guild.channels.keys():
        guild.channels[interaction.channel.id] = TriggerChannel(interaction.channel.id, ping_role.id, invisible, util.TriggerList())
    else:
        guild.channels[interaction.channel.id].ping_role = ping_role.id
        guild.channels[interaction.channel.id].invisible = invisible

    print(f"Server configuration updated for guild {interaction.guild.name}, channel {interaction.channel.name}: Ping Role {ping_role.name}, Invisible {invisible}")

    await interaction.response.send_message("Channel configuration updated!", ephemeral=should_be_ephemeral_guild_wide(interaction))

@bot.tree.command(description="Remove the separate ping role and target list from a channel.")
async def remch(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    if interaction.channel.id == guilds[interaction.guild.id].channel:
        await interaction.response.send_message("Can't configure this channel because it is already the server's primary channel. Please tell the server owner to change this by running /config.", ephemeral=True)
        return
    
    if interaction.channel.id not in guilds[interaction.guild.id].channels.keys():
        await interaction.response.send_message("This channel has no channel-specific configuration to remove!", ephemeral=True)
        return
    
    bot_cursor.execute("DELETE FROM channels WHERE guild_id = ? AND channel_id = ?", [interaction.guild.id, interaction.channel.id])
    bot_con.commit()

    guild = guilds[interaction.guild.id]

    triggers = get_trigger_list(guild.channels[interaction.channel.id]).triggers
    for trigger in triggers:
        if "target" in trigger.keys():
            guild.select_targets.discard(trigger["target"])

    del guild.channels[interaction.channel.id]

    await interaction.response.send_message("Channel configuration removed!", ephemeral=should_be_ephemeral_guild_wide(interaction))

def display_trigger(trigger) -> str:
    data = util.fetch_region_data_from_db(everblaze_cursor, trigger["api_name"])

    if "target" not in trigger.keys():
        return f"https://www.nationstates.net/region={trigger["api_name"]} - {format_time(data["seconds_minor"])} minor, {format_time(data["seconds_major"])} major"
    
    return f"https://www.nationstates.net/region={trigger["target"]} ({data["canon_name"]};{trigger["delay"]}s) - {format_time(data["seconds_minor"])} minor, {format_time(data["seconds_major"])} major"

def display_trigger_simple(trigger) -> str:
    if "target" not in trigger.keys():
        return f"trigger: https://www.nationstates.net/region={trigger["api_name"]}"
    
    return f"target: https://www.nationstates.net/region={trigger["target"]}"

def format_update_log(trigger) -> str:
    if "target" not in trigger.keys():
        return f"{trigger["api_name"]} updated!"
    
    return f"{trigger["target"]} will update in {trigger["delay"]}s ({trigger["api_name"]} updated)!"

@bot.tree.command(description="Add a new trigger.")
async def add(interaction: discord.Interaction, trigger: str):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))
    
    targets.add_trigger({
        "api_name": util.format_nation_or_region(trigger)
    })
    targets.sort_triggers(everblaze_cursor)

    await interaction.response.send_message(f"Added trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Add a new target and associated trigger.")
async def add_target(interaction: discord.Interaction, target: str, trigger: str, delay: int):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))
    
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
    
    if ongoing_tags > 0:
        await interaction.response.send_message(f"Can't do that, there are tag sessions running. Use /clear instead.", ephemeral=should_be_ephemeral(interaction))
        return
    
    get_trigger_list(guilds[interaction.guild.id]).triggers = []
    guilds[interaction.guild.id].select_targets = set()

    for channel in guilds[interaction.guild.id].channels.values():
        channel.triggers = []

    guilds[interaction.guild.id].last_update = None

    await interaction.response.send_message(f"Successfully reset all triggers (including channel-specific ones) and update information.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="Reset all triggers in this channel.")
async def clear(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    triggers = get_trigger_list(get_guild_or_channel_to_edit(interaction)).triggers

    for trigger in triggers:
        if "target" in trigger.keys():
            guilds[interaction.guild.id].select_targets.discard(trigger["target"])

    get_trigger_list(get_guild_or_channel_to_edit(interaction)).triggers = []

    await interaction.response.send_message(f"Successfully reset all triggers in this channel.", ephemeral=should_be_ephemeral(interaction))
    
@bot.tree.command(description="Remove a trigger.")
async def remove(interaction: discord.Interaction, trigger: str):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))
    
    t = targets.remove_trigger(util.format_nation_or_region(trigger))
    if t is None:
        await interaction.response.send_message(f"No such trigger {trigger}. Check that you have run /remove with the trigger name and not the target name.", ephemeral=should_be_ephemeral(interaction))
        return
    
    if "target" in t.keys():
        guilds[interaction.guild.id].select_targets.discard(t["target"])

    await interaction.response.send_message(f"Removed trigger {trigger}. Run /triggers to see a list of active triggers.", ephemeral=should_be_ephemeral(interaction))

@bot.tree.command(description="List active triggers.")
async def triggers(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))

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
    
    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))

    if(len(targets.triggers) == 0):
        await interaction.response.send_message(f"No triggers set!", ephemeral=should_be_ephemeral(interaction))
        return
    
    await interaction.response.send_message(f"Next {display_trigger_simple(targets.triggers[0])}", ephemeral=(should_be_ephemeral(interaction) and not visible))

@bot.tree.command(description="Skip the next region to update.")
async def skip(interaction: discord.Interaction):
    if not await check_command_permissions(interaction):
        return
    
    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))

    if(len(targets.triggers) == 0):
        await interaction.response.send_message(f"No triggers set!", ephemeral=should_be_ephemeral(interaction))
        return
    
    name = targets.triggers[0]["api_name"]
    trigger = targets.remove_trigger(name)

    if "target" in trigger.keys():
        guilds[interaction.guild.id].select_targets.discard(trigger["target"])
    
    await interaction.response.send_message(f"Removed {display_trigger_simple(trigger)}")
    
@bot.tree.command(description="Find a trigger for a selected target.")
async def snipe(interaction: discord.Interaction, target: str, update: str, ideal_delay: int, early_tolerance: int, late_tolerance: int):
    if not await check_command_permissions(interaction):
        return
    
    minor = update.lower() == "minor"

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

    targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))

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
    
    minor = update.lower() == "minor"

    start = -1
    if guilds[interaction.guild.id].last_update is not None:
        start = guilds[interaction.guild.id].last_update.index

    raidable_regions = util.find_raidable_regions(everblaze_cursor, point_endos, start)

    last_switch_time = -999

    if guilds[interaction.guild.id].last_update is not None:
        if minor:
            last_switch_time = guilds[interaction.guild.id].last_update.minor
        else:
            last_switch_time = guilds[interaction.guild.id].last_update.major

    for region in raidable_regions:
        if guilds[interaction.guild.id].last_update is not None:
            if(region["update_index"] <= guilds[interaction.guild.id].last_update.index):
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

        if target in guilds[interaction.guild.id].select_targets:
            continue

        trigger = util.find_region_updating_at_time(everblaze_cursor, trigger_time, minor, early_tolerance, late_tolerance)
        if trigger is None:
            continue

        delay = 0
        if minor:
            delay = region["seconds_minor"] - trigger["seconds_minor"]
        else:
            delay = region["seconds_major"] - trigger["seconds_major"]

        targets = get_trigger_list(get_guild_or_channel_to_edit(interaction))
        should_finish = False

        if not confirm:
            targets.add_trigger({
                "api_name": trigger["api_name"],
                "target": target,
                "delay": delay,
            })
            targets.sort_triggers(everblaze_cursor)

            guilds[interaction.guild.id].select_targets.add(target)

            last_switch_time = update_time
            continue

        view = BaseRegionView(interaction.user)
        accept_button = discord.ui.Button(label="Accept Target", style=discord.ButtonStyle.green)
        skip_button = discord.ui.Button(label="Find Another", style=discord.ButtonStyle.red)
        end_button = discord.ui.Button(label="Finish", style=discord.ButtonStyle.gray)

        # create a callback for the button
        async def accept_callback(interaction: discord.Interaction):
            nonlocal last_switch_time

            if target in guilds[interaction.guild.id].select_targets:
                await interaction.response.send_message(f"The target {target} has already been selected in a different channel, finding a new one instead.", ephemeral=should_be_ephemeral(interaction))
                view.stop()
                return

            targets.add_trigger({
                "api_name": trigger["api_name"],
                "target": target,
                "delay": delay,
            })
            targets.sort_triggers(everblaze_cursor)

            guilds[interaction.guild.id].select_targets.add(target)

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
async def tag(interaction: discord.Interaction, update: str, point_endos: int, switch_time: int, min_delay: int):
    global ongoing_tags

    if not await check_command_permissions(interaction):
        return
    
    if guilds[interaction.guild.id].last_update is None:
        await interaction.response.send_message(f"Waiting for {update} to start...")
        await bot.wait_for(
            "region_update",
            timeout=None,
        )
        await interaction.followup.send(f"Started tag run for {update}. Please post the point and start endorsing.")
    else:
        await interaction.response.send_message(f"Started tag run for {update}. Please post the point and start endorsing.")

    minor = update.lower() == "minor"

    nation = ""

    ongoing_tags += 1

    while True:
        op = await bot.wait_for(
            "message",
            check=lambda x: x.channel.id == interaction.channel.id
            and (x.content.lower().startswith("t")
            or x.content.lower() == "quit"
            or x.content.lower() == "skip"
            or x.content.lower().startswith("endos")
            or x.content.lower().startswith("delay")
            or x.content.lower().startswith("switch")),
            timeout=None,
        )

        endos = 0

        if op.content.lower().startswith("t"):
            match = re.match(r"t[\s]+http[s]?://(?:fast|www)\.nationstates\.net/nation=([a-zA-Z0-9_ ]+)", op.content.lower())
            if match is not None:
                nation = util.format_nation_or_region(match.groups()[0])
            else:
                continue
        elif op.content.lower() == "skip":
            endos = point_endos + 1
        else:
            if op.content.lower() == "quit":
                await interaction.followup.send(f"Quitting the tag session.")
                ongoing_tags -= 1
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
            continue

        message = None
        if endos < point_endos:
            message = await interaction.followup.send(f"Waiting for everyone to endorse {nation} before posting target... ({endos}/{point_endos})")

        def match(data):
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
                await message.edit(content=f"Waiting for everyone to endorse {nation} before posting target... ({endos}/{point_endos})")
            elif event == "unendo":
                await interaction.followup.send(f"{nation} has been unendorsed, canceling. Waiting for another command.")
                break
            elif event == "resign":
                await interaction.followup.send(f"{nation} has resigned from the WA, canceling. Waiting for another command.")
                break
        else:
            start = guilds[interaction.guild.id].last_update.index

            raidable_regions = util.find_raidable_regions(everblaze_cursor, point_endos, start)

            last_update_time = 0
            if minor:
                last_update_time = guilds[interaction.guild.id].last_update.minor
            else:
                last_update_time = guilds[interaction.guild.id].last_update.major

            time_since_last_update = time.time() - guilds[interaction.guild.id].last_update.time
            target_update_time = math.ceil(last_update_time + time_since_last_update + switch_time + min_delay)

            search_start_time = time.time()

            for region in raidable_regions:
                if(region["update_index"] <= guilds[interaction.guild.id].last_update.index):
                    continue

                update_time = 0
                if minor:
                    update_time = region["seconds_minor"]
                else:
                    update_time = region["seconds_major"]

                if update_time < target_update_time:
                    continue

                target = region["api_name"]

                if target in guilds[interaction.guild.id].select_targets:
                    continue

                guilds[interaction.guild.id].select_targets.add(target)

                print(f"found target region: {target}, sending after switch time's up")

                search_time = time.time() - search_start_time
                remaining_time = switch_time - search_time

                # Account for large gaps in update (caused by big regions updating) by waiting for most of the gap before posting the target.
                gap_delay = (update_time - target_update_time)
                if gap_delay > 4:
                    await interaction.followup.send(f"A large region is updating, the target will take a bit longer (warning: times may be inaccurate).")
                    remaining_time += (gap_delay - 2)
                    gap_delay = 2

                if remaining_time > 0:
                    await asyncio.sleep(remaining_time)

                try:
                    embed = discord.Embed()
                    text = "%" * 350
                    embed.description = f"[{text}](https://fast.nationstates.net/region={target})"
                    embed.set_footer(text=f"Move to target: {target}, estimated delay: {gap_delay + min_delay}s")
                    await interaction.followup.send(embed=embed)
                except Exception:
                    await interaction.followup.send(f"An error occurred, please try again.")
                    break
                break
            else:
                await interaction.followup.send(f"No more regions found, update is over! Quitting tag session.")
                ongoing_tags -= 1
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
            guilds[guild.id].select_targets.discard(target["target"])
        messages.append((channel, f"{role.mention} {format_update_log(target)}"))

    return messages

@bot.event
async def on_region_update(region: str):
    data = util.fetch_region_data_from_db(everblaze_cursor, region)

    if data is None:
        return None
    
    messages = []
    
    for id, server in guilds.items():
        guild = bot.get_guild(id)

        server.last_update = LastUpdate(data["update_index"], time.time(), data["seconds_minor"], data["seconds_major"])

        targets = get_trigger_list(server)
        messages += update_region(region, server.last_update, server.channel, server.ping_role, guild, targets)

        for channel in server.channels.values():
            channel_targets = get_trigger_list(channel)
            messages += update_region(region, server.last_update, channel.channel, channel.ping_role, guild, channel_targets)

    coroutines = [channel.send(message) for (channel, message) in messages]
    await asyncio.gather(*coroutines)

ENDO_REGEX = re.compile(r"@@([a-z0-9_]+)@@ endorsed @@([a-z0-9_]+)@@")
UNENDO_REGEX = re.compile(r"@@([a-z0-9_]+)@@ withdrew its endorsement from @@([a-z0-9_]+)@@")
RESIGN_REGEX = re.compile(r"@@([a-z0-9_]+)@@ resigned from the World Assembly")

def sse_listener(client) -> None:
    for event in client:
        # We only notice this after a heartbeat arrives from the connection.
        if is_cancelled:
            print("Cancelled thread, closing connection")
            return
        
        if event.data: # If the event has no data it's a heartbeat. We do want to receive heartbeats however so that we can check for cancellation above.
            data = json.loads(event.data)
            happening = data["str"]

            # The update happening line is formatted like this: "%%region_name%% updated." We want to know if the happening matches this, 
            # and if so, retrieve the region name.
            match = util.UPDATE_REGEX.match(happening)
            if match is not None:
                region_name = match.groups()[0]

                print(f"log: {region_name} updated!")

                return ("region_update", region_name)
            
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
        bot_cursor.execute("CREATE TABLE guilds(guild_id, setup_role_id, ping_role_id, channel_id, invisible)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_guild_id ON guilds (guild_id);")
        bot_con.commit()

    channel_list = bot_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'; ").fetchall()

    if channel_list == []:
        # Channel list doesn't exist, create it
        bot_cursor.execute("CREATE TABLE channels(guild_id, channel_id, ping_role_id, invisible)")
        bot_cursor.execute("CREATE UNIQUE INDEX idx_channel_id ON channels (channel_id);")
        bot_con.commit()

    bot.run(settings["TOKEN"])

    is_cancelled = True

if __name__ == "__main__":
    main()