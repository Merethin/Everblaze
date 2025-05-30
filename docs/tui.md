# Everblaze (TUI version) Documentation

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

## Command reference

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
