# Everblaze Discord Bot Documentation

Follow [this link](selfhost.md) to find out how to self-host the Everblaze bot. Otherwise, contact me and we'll see if I can give your server access (this will be evaluated on a case-by-case basis).

When added to any server, the server owner must run the following command first, in any channel:

```/config @Setup Role @Ping Role #channel invisible```

`@Setup Role`: everyone who has this role will be able to add, remove, and view triggers in this server.

`@Ping Role`: everyone who has this role will be pinged when a trigger updates.

`#channel`: When a trigger updates, a message notifying everyone who has `@Ping Role` will be sent in this channel.

`invisible`: If True, replies from Everblaze should only be visible to the person who ran the command, or if False, they will be visible to everyone in the channel where the command was ran.

If replies are visible, anyone in the channel where Everblaze commands are used (doesn't have to be the same as `#channel` above) will be able to see which triggers you set (which may compromise some operations ahead of time). Consider setting the `invisible` parameter based on your particular server's situation and where you plan to run Everblaze commands - you can always change it later by re-running `/config`.

## Command reference

```/add <trigger>```

Add a region to the trigger list.

A message/ping will be sent when the region updates. If you want a message to be sent at a delay before the region updates, you're looking for `/snipe` instead.

```/addch <ping_role> <invisible>```

Add or edit channel-specific configuration to a channel.

When a channel has channel-specific configuration, it will have its own trigger list, and commands run in that channel will edit that channel's trigger list, instead of the server's global trigger list.

When triggers in the channel-specific trigger list update, `<ping_role>` will be pinged in this channel, instead of the `@Ping Role` specified in `/config`, and instead of the `#channel` specified in `/config`.

Running `/select` in this channel will skip over targets set in other channels (**only** those that have also been set with `/select`, not ones added manually via `/snipe` or `/add_target`), and running `/select` in other channels will skip over targets set in this channel (with the same caveat).

`invisible`: If True, replies from Everblaze in this channel should only be visible to the person who ran the command, or if False, they will be visible to everyone in the channel.

```/remch```

Removes channel-specific configuration and trigger lists and makes all Everblaze commands run in this channel affect the server-wide trigger list instead.

```/add_target <target> <trigger> <delay>```

This command is to import targets from tools like QuickDraw manually, as the Discord bot does not support importing trigger lists/raidfiles.

Given a QuickDraw line like this:
```
1) https://www.nationstates.net/region=flevoland (0:1:48)
	a) https://www.nationstates.net/template-overall=none/region=manama (6s)
```

The command should be:
`/add_target flevoland manama 6`

The delay is **not** checked. Whenever the trigger region updates, Everblaze will send out a ping saying the target region is about to update. If the delay is wrongly set, that's your problem.

To find suitable triggers for a target, use the `/snipe` command instead.

```/next (visible)```

Display a link to the next region set to update from the trigger list.

By default, this command overrides the server-wide `invisible` configuration, as it is intended to be used during tag raids to tell participants which region to prepare to move to next.

If you don't want that, run `/next visible: False` instead. (Note that if your server config is set to `invisible: False`, `visible: False` will not override that, and the message will still be sent to the entire channel).

Triggers can be viewed by anyone with the `@Setup Role` at any time by running the `/triggers` command.

```/remove <trigger>```

Remove a region from the trigger list.

**NOTE: If you have a target with an associated trigger, you must run `/remove` with the TRIGGER NAME, not the target name, or else it will silently fail.**

That is, to remove a trigger like this:

`https://www.nationstates.net/region=suspicious (Region de France;8s) - 00:58:44 minor, 01:44:47 major`

`/remove Suspicious` will not work.
`/remove Region de France` _will_ work.

Triggers are automatically removed when they update.

```/reset```

Clear all triggers and reset internal update data.

Currently, Everblaze stores the last region that has updated in order to support things like starting `/select` mid-update. The official bot should restart and clear this stuff after every update, but in case it doesn't, or you're self-hosting it, you may need to run `/reset` to bring the "last region that has updated" back to the beginning of update, before setting up triggers.

```/select <update> <point_endos> <min_switch_time> <ideal_delay> <early_tolerance> <late_tolerance>```

Arguably the most powerful command in Everblaze. Its functionality is similar to that of QuickDraw, that is, you give it the update to pick triggers for (major or minor), the endorsements you will have on the point, the minimum time to switch between targets, and the desired trigger time, and it will give you unpassworded, executive-delegacy regions to pick from. The targets you pick will automatically be added to the trigger list.

`<update>` must be "major" or "minor". If invalid, defaults to major.
`<point_endos>` should be the number of endorsements you are expecting to have on the point nation.
`<min_switch_time>` should be the minimum time, in seconds, that you want to have to switch between one target and another (resigning, joining, endorsing, opening the target page).
`<ideal_delay>` should be the optimal trigger time in seconds.
`<early_tolerance>`: if Everblaze can't find a trigger `ideal_delay` seconds before a target, how muchb earlier can it go? That is, if your ideal delay is 6 seconds, and your early tolerance is 1 second, Everblaze will try to find 6-second triggers but may give you 7-second triggers if it can't find one.
`<late_tolerance>`: if Everblaze can't find a trigger `ideal_delay` seconds before a target, how much later can it go? That is, if your ideal delay is 6 seconds, and your late tolerance is 1 second, Everblaze will try to find 6-second triggers but may give you 5-second triggers if it can't find one.

When running `/select` correctly, Everblaze will present you with a link to a region. If you want to add that region to your target list, click `Accept Target`. If, for any reason, you don't want to include that region, click `Find Another`. Do this as many times as you want until you have enough, and then click `Finish`. All the triggers and targets you selected will be added to the trigger list.

```/snipe <target> <update> <ideal_delay> <early_tolerance> <late_tolerance>```

Given a specific target region, find a trigger that updates a certain amount of time before it, and add it to the trigger list.

`<target>` should be the region you want to find a trigger for.

All other parameters work the same way as in `/select`:
`<update>` must be "major" or "minor". If invalid, defaults to major.
`<ideal_delay>` should be the optimal trigger time in seconds.
`<early_tolerance>`: if Everblaze can't find a trigger `ideal_delay` seconds before a target, how muchb earlier can it go? That is, if your ideal delay is 6 seconds, and your early tolerance is 1 second, Everblaze will try to find 6-second triggers but may give you 7-second triggers if it can't find one.
`<late_tolerance>`: if Everblaze can't find a trigger `ideal_delay` seconds before a target, how much later can it go? That is, if your ideal delay is 6 seconds, and your late tolerance is 1 second, Everblaze will try to find 6-second triggers but may give you 5-second triggers if it can't find one.

```/triggers```

Display the current trigger list.

There are two different kinds of triggers:

- Individual triggers

Example:
```https://www.nationstates.net/region=kamurocho - 00:57:27 minor, 01:42:05 major```

These triggers do not have any targets associated with them, and Everblaze will only send a message when they update, no prior warnings.
These may be useful for detagging (setting a list of regions, moving to the first, and when Everblaze notifies you of that one updating, run `/next` and prepare the next one) or warnings several minutes before another region updates (prior warnings for an occupation, where you don't want the participants to be aware of the target until a few minutes earlier).

The ping from Everblaze will look like this:
`@Ping Role <trigger> updated!`

Added with the `/add` command.

- Target triggers

Example:
```https://www.nationstates.net/region=kamurocho (The Islay Coast;5s) - 00:57:25 minor, 01:42:00 major```

These triggers have targets associated with them, and a delay. Everblaze will send a message when the trigger updates so that you can move to the target in time.
This is useful for tagging, invasions, liberations, etc.
Unlike individual triggers, the region linked here is the target, not the trigger. Here, Kamurocho is the target, and The Islay Coast the trigger.

The ping from Everblaze will look like this:
`@Ping Role <target> will update in <delay>s (<trigger> updated)!`

Added with `/add_target`, `/select` and `/snipe`.