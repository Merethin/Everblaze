# Everblaze

Everblaze is a triggering tool for the NationStates R/D game, using the new server-sent events API.

Features:
- Interactive terminal user interface
- Triggers can be set from a file
- Triggers can also be added or removed at runtime
- Lower overhead than tools that poll the API

# Setup

It is highly recommended, but not mandatory, to use a Python virtual environment to use this tool.

```
$ python -m venv venv
```

On Linux, the virtual environment can be entered with
```
$ source venv/bin/activate
```
and left with:
```
$ deactivate
```

Once that's done, install the required packages with `pip`:
```
pip install -r requirements.txt
```

# Running

Use the `-t` flag to provide a trigger file and the `-n` flag to specify your main nation (so that the API knows who's using the tool).
If you do not provide the `-n` flag, the program will prompt you to enter your main nation.

Example:
```
python tui.py -t trigger_list.txt -n Merethin
```

Instead of the `-t` flag, one can use the `--raidfile` flag to provide a list of targets and associated triggers (note that this is not currently compatible with the raidfiles format used by programs like QuickDraw and zoomies, which is a feature planned for the future.)

Example:
```
python tui.py --raidfile raidfile.txt -n Merethin
```

The first time you run the program, it will generate a region database from the daily data dumps, which will slow down startup.

It is recommended to run the program with the `-r` flag (which regenerates the database) every so often to keep the database up to date. It is not required though, especially if you're running it mid-update.

# Trigger list format

The trigger list should be a newline-separated list of region names.
The region names can have any capitalization and use either spaces or underscores.

Example:
```
the south pacific
The North Pacific
The_Plains_Of_Perdition
warzone_trinidad
```

# Raidfile format

The raidfile list should be a newline-separated list of lines following this format: `<target> (<trigger>;<delay>s)`.
The region names can have any capitalization and use either spaces or underscores.

Example:
```
the south pacific (suspicious;4s)
The North Pacific (lazarus;12s)
The_Plains_Of_Perdition (artificial_solar_system;7s)
warzone_trinidad (Warzone Asia;10s)
```
_Note: the triggers shown above are made up for illustration purposes and do not actually update as shown._

## Command bar

The command bar can be used to change the trigger list at runtime.

The `add` command will add a region to the trigger list.
```
add <Region Name>
```

The `remove` command will remove a region from the trigger list.
```
remove <Region Name>
```

A plus and minus sign can be used as aliases for the add and remove commands:
 
```
+ <Region Name>
- <Region Name 2>
```

The `clear` command will clear the output log.
```
clear
```

The `snipe` command will find a trigger region that updates X seconds before the target region, and add it to the trigger list.
```
snipe <Region Name>;<major|minor>;<delay>m|s;<early_tolerance>;<late_tolerance>
```

Parameters:

`Region Name`: The target to find a trigger for.

`major|minor`: Either "major" or "minor", depending on the update the trigger will be used for.

`delay`: The amount of time before the target that the trigger should update at. Can be provided in minutes (example: `5m`) or in seconds: (example: `12s`).

Tolerance parameters:

If no region is found to update exactly `delay` time before the target, how much earlier or later can we search for a trigger?

`early_tolerance`: How many seconds earlier a trigger can be. Set this to 0 if you want the trigger to be exactly at `delay` seconds before the target.

`late_tolerance`: How many seconds later a trigger can be. Set this to 0 if you want the trigger to be exactly at `delay` seconds before the target.

Example:
```
snipe Suspicious;minor;6s;1;1
```

This will find a trigger that updates 6 seconds before Suspicious at minor, ideally. If it can't find one, it'll try to find a trigger that updates 7s earlier (early tolerance of 1 second) or 5s earlier (late tolerance of 1 second). The trigger will then be added to the list, along with the delay that was picked in the end.


## Exiting the app

Press Ctrl+Q to quit.

## Discord bot hosting

The discord bot can be found in `bot.py`. To self-host it yourself (alternatively: ask me and I'll consider giving your server access to my own self-hosted version), go to https://discord.com/developers/applications, create a new application, go to the "Bot" section and copy its token.

Create a file called `.env` and paste the token like this:
```
TOKEN = "<TOKEN>"```

Still on the "Bot" tab, enable "Message Content Intent".

To invite the bot to a server, go to the "Installation" tab, copy the discord provided Install Link, and go to the Oauth2 tab.

Paste the install link into "Redirects" and configure the permissions in the following way.

"OAuth2 URL Generator":
Check "messages.read", "bot" and "applications.commands".
Select the previously pasted install link in "Select Redirect URL."

"Bot Permissions":
Check "Send Messages", "Embed Links", "Mention Everyone", and "Use Slash Commands".

After this, you can copy the "generated URL" given to you by Discord. This is the install link for your bot. Paste it in your browser, select a server, and you're done. Now run the bot.

```
python bot.py -n <NATION_NAME> -r
```

## Discord bot commands

When added to any server, the server owner must run the following command first, in any channel:

```/config @Setup Role @Ping Role #channel```

@Setup Role: everyone who has this role will be able to add, remove, and view triggers in this server.

@Ping Role: everyone who has this role will be pinged when a trigger updates.

#channel: When a trigger updates, the message will be sent in this channel.

Apart from that, the bot commands are almost identical to the TUI commands, except for one addition:

```/add_target <target> <trigger> <delay>```

This command is to import targets from tools like QuickDraw manually, as the Discord bot does not support importing trigger lists/raidfiles.

Given a QuickDraw line like this:
```
2) https://www.nationstates.net/region=flevoland (0:1:48)
	a) https://www.nationstates.net/template-overall=none/region=manama (6s)
```

The command should be:
```/add_target flevoland manama 6```

The delay is **not** checked. Whenever the trigger region updates, Everblaze will send out a ping saying the target region is about to update. If the delay is wrongly set, that's your problem.

To find suitable triggers for a target, use the `/snipe` command instead.

Triggers can be viewed by anyone with the `@Setup Role` at any time by running the `/triggers` command.

## Contact

If you have any questions about this tool, contact me using one of the following:

NationStates telegrams: https://nationstates.net/nation=merethin

Discord: @ns_merethin

## Disclaimer
This program is provided as-is with no guarantees of legality or compliance with the NationStates API rules. While I have tried my best to comply with them, it is the responsibility of every user to understand and insure the scripts they run are legal. You assume all risks.
