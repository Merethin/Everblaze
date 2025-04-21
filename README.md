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
python everblaze.py -t trigger_list.txt -n Merethin
```

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

## Command bar

The command bar can be used to change the trigger list at runtime.

The `add` command will add a region to the trigger list.
```
add Region Name
```

The `remove` command will remove a region from the trigger list.
```
remove Region Name
```

A plus and minus sign can be used as aliases for the add and remove commands:

`+ region name`
`- region_name_2`

The `clear` command will clear the output log.
```
clear
```

## Exiting the app

Press Ctrl+Q to quit.

## Contact

If you have any questions about this tool, contact me using one of the following:
- NationStates telegrams: https://nationstates.net/nation=merethin
- Discord: @ns_merethin

## Disclaimer
This program is provided as-is with no guarantees of legality or compliance with the NationStates API rules. While I have tried my best to comply with them, it is the responsibility of every user to understand and insure the scripts they run are legal. You assume all risks.
