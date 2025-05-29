# tui.py - Interactive terminal triggering tool
# Authored by Merethin, licensed under the BSD-2-Clause license.

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog
from textual import on, work
from textual.message import Message
import re, argparse, sqlite3, typing, sys, sans, asyncio
import utility as util

# Global variables.
targets = util.TriggerList() # The list of targets to watch for updates (can be modified at runtime).
cursor: typing.Optional[sqlite3.Cursor] = None # Database cursor

# Input field to run commands.
# Currently, these are the four supported commands:
#   add region_name - adds a region to the trigger list
#   remove region_name - manually removes a region from the trigger list, without waiting for it to update
#   snipe target;update;delay;early_tolerance;late_tolerance - finds a trigger for a specified region
#   clear - clears the log
class CommandInput(Input):
    class AddTarget(Message):
        """Add a target to the trigger list (user-triggered)."""

        def __init__(self, target: str) -> None:
            self.target = target
            super().__init__()

    class SnipeTarget(Message):
        """Add a target to the trigger list (user-triggered), with a corresponding trigger <delay> seconds before."""

        def __init__(self, target: str, update: str, delay: int, early_tolerance: int, late_tolerance: int) -> None:
            self.target = target
            self.update = update
            self.delay = delay
            self.early_tolerance = early_tolerance
            self.late_tolerance = late_tolerance
            super().__init__()

    class RemoveTarget(Message):
        """Remove a target from the trigger list (user-triggered)."""

        def __init__(self, target: str) -> None:
            self.target = target
            super().__init__()

    def on_mount(self) -> None:
        self.placeholder = "Operation to execute..."
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.split(" ", 1)

        if command[0] == "add" or command[0] == "+":
            self.app.post_message(self.AddTarget(util.format_nation_or_region(command[1])))
        if command[0] == "snipe":
            match = re.match(r"([a-zA-Z0-9_\- ]+);(minor|major);([0-9]+)(s|m);([0-9]+);([0-9]+)", command[1])
            if match is not None:
                groups = match.groups()
                region_name = groups[0]
                update = groups[1]
                delay = int(groups[2])
                seconds_or_minutes = groups[3]
                if seconds_or_minutes == "m":
                    delay *= 60
                early_tolerance = groups[4]
                late_tolerance = groups[5]
                self.app.post_message(self.SnipeTarget(util.format_nation_or_region(region_name), update, delay, int(early_tolerance), int(late_tolerance)))
            else:
                self.app.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog("\u2e30 Invalid command formatting (should be snipe <RegionName>;major|minor;<delay>s|m;<early>;<late>)."))
        elif command[0] == "remove" or command[0] == "-":
            self.app.post_message(self.RemoveTarget(util.format_nation_or_region(command[1])))
        elif command[0] == "clear":
            self.app.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.ClearLog())
        else:
            pass

        self.clear()

# Output log widget.
# Also hosts the Everblaze client worker, who listens to the server for update events.
class OutputLog(RichLog):
    class WriteLog(Message):
        """Write a message to the log."""

        def __init__(self, message: str) -> None:
            self.message = message
            super().__init__()
    
    class ClearLog(Message):
        """Clear the log."""

        def __init__(self) -> None:
            super().__init__()

    class Bell(Message):
        """Trigger the terminal bell."""

        def __init__(self) -> None:
            super().__init__()

    class RemoveTarget(Message):
        """Remove a target from the target list after it has updated."""

        def __init__(self, target: str) -> None:
            self.target = target
            super().__init__()

    def on_mount(self) -> None:
        self.styles.border = ("round", "blue")
        self.border_title = "Output Log"
        self.styles.width = "3fr"
        self.auto_scroll = True
        self.worker = self.update_listener() # Launch the client

        loop = asyncio.get_event_loop()
        loop.set_task_factory(asyncio.eager_task_factory)
        
        if len(targets) != 0:
            self.post_message(self.WriteLog("\u2e30 Ready! Waiting for targets."))
        else:
            self.post_message(self.WriteLog("\u2e30 No triggers set!"))

    # fixme: How can we render rich text here??
    @on(WriteLog)
    def on_write_log(self, event: WriteLog):
        self.write(event.message)
        event.stop()

    @on(Bell)
    def on_bell(self, event: Bell):
        self.app.bell()
        event.stop()

    @on(ClearLog)
    def on_clear_log(self, event: ClearLog):
        self.clear()
        event.stop()

    # Update client/listener worker.
    @work(name="update")
    async def update_listener(self):
        client = sans.AsyncClient()
        async for event in sans.serversent_events(client, "admin"):
            happening = event["str"]

            # The happening line is formatted like this: "%%region_name%% updated." We want to know if the happening matches this, 
            # and if so, retrieve the region name.
            match = util.EVENTS["update"].match(happening)
            if match is not None:
                region_name = match.groups()[0]

                print(f"log: {region_name} updated!")

                self.app.post_message(TriggerApp.RegionUpdate(region_name))

def display_trigger(trigger: typing.Dict) -> str:
    if "target" not in trigger.keys():
        return trigger["api_name"]
    
    return f"{trigger["target"]} ({trigger["api_name"]};{trigger["delay"]}s)"

def format_update_log(trigger: typing.Dict) -> str:
    if "target" not in trigger.keys():
        return f"\u2e30 {trigger["api_name"]} updated!"
    
    return f"\u2e30 {trigger["target"]} will update in {trigger["delay"]}s ({trigger["api_name"]} updated)!"

# Trigger list widget
# Renders a list of all active triggers (the global "targets" variable)
class TriggerList(Static):
    class RefreshTriggerList(Message):
        """Refresh the trigger list widget."""

        def __init__(self) -> None:
            super().__init__()

    def on_mount(self) -> None:
        self.styles.border = ("round", "blue")
        self.border_title = "Trigger List"
        self.styles.width = "2fr"
        self.styles.height = "100%"

    def render(self) -> str:
        global targets

        if(len(targets) == 0):
            return "No triggers set."
        return "\n".join([display_trigger(t) for t in targets.triggers])
    
    @on(RefreshTriggerList)
    def on_refresh_trigger_list(self, event: RefreshTriggerList) -> None:
        self.refresh()
        event.stop()

class TriggerApp(App):
    cursor: typing.Optional[sqlite3.Cursor]

    class RegionUpdate(Message):
        """Transmitted when a region has updated."""

        def __init__(self, region: str) -> None:
            self.region = region

            super().__init__()

    def compose(self) -> ComposeResult:
        global cursor
        self.title = "Everblaze"

        self.cursor = cursor

        yield Header()
        yield Vertical(
            CommandInput(id="command"),
            Horizontal(
                OutputLog(id="output"),
                TriggerList(id="triggers"),
            ),
        )
        yield Footer()
    
    @on(CommandInput.AddTarget)
    def on_add_target(self, event: CommandInput.AddTarget) -> None:
        global targets

        assert self.cursor

        targets.add_trigger({
            "api_name": event.target
        })
        targets.sort_triggers(self.cursor)

        self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())
        self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog("\u2e30 Triggers edited, reloading."))

    # This one is called by a command, and therefore produces a "Triggers edited" happening in the output log.
    @on(CommandInput.RemoveTarget)
    def on_remove_target(self, event: CommandInput.RemoveTarget) -> None:
        global targets
        targets.remove_trigger(event.target)

        self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())
        self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog("\u2e30 Triggers edited, reloading."))

    # This one is called when a region updates, and therefore does not produce a "Triggers edited" happening in the output log
    # Region updates already generate their own "region updated" happening anyway
    @on(OutputLog.RemoveTarget)
    def on_remove_target_after_update(self, event: OutputLog.RemoveTarget) -> None:
        global targets
        targets.remove_trigger(event.target)

        self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())

    @on(RegionUpdate)
    def on_region_update(self, event: RegionUpdate) -> None:
        global targets

        assert self.cursor

        data = util.fetch_region_data_from_db(self.cursor, event.region)

        if data is None:
            return None

        already_updated = targets.remove_all_updated_triggers(data["update_index"])
        for trigger in already_updated:
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog(f"\u2e30 {trigger["api_name"]} has already updated!"))
            self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())

        target = targets.query_trigger(event.region)

        if target is not None:
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog(format_update_log(target)))
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.Bell())
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.RemoveTarget(event.region))

    @on(CommandInput.SnipeTarget)
    def on_snipe_target(self, event: CommandInput.SnipeTarget) -> None:
        global targets

        assert self.cursor

        minor = util.is_minor(event.update)

        region_data = util.fetch_region_data_from_db(self.cursor, event.target)
        if region_data is None:
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog(f"\u2e30 The region {event.target} does not exist!"))
            return
        
        target_time = 0
        if minor:
            target_time = region_data["seconds_minor"] - event.delay
        else:
            target_time = region_data["seconds_major"] - event.delay

        trigger = util.find_region_updating_at_time(self.cursor, target_time, minor, event.early_tolerance, event.late_tolerance)
        if trigger is None:
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog(f"\u2e30 No trigger found in the specified time range!"))
            return

        delay = 0
        if minor:
            delay = region_data["seconds_minor"] - trigger["seconds_minor"]
        else:
            delay = region_data["seconds_major"] - trigger["seconds_major"]

        targets.add_trigger({
            "target": event.target,
            "api_name": trigger["api_name"],
            "delay": delay,
        })
        targets.sort_triggers(self.cursor)

        self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())
        self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog("\u2e30 Triggers edited, reloading."))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="everblaze-tui", description="Versatile triggering tool for NationStates R/D")
    parser.add_argument("-n", "--nation-name", default="")
    parser.add_argument("-r", '--regenerate-db', action='store_true')

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-t", "--triglist", default="")
    group.add_argument("--raidfile", default="")
    args = parser.parse_args()

    nation_name = ""

    if len(args.nation_name) != 0:
        nation_name = args.nation_name
    else:
        nation_name = input("Please enter your main nation name: ")

    user_agent = f"Everblaze (TUI) by Merethin, used by {nation_name}"
    sans.set_agent(user_agent)

    if not util.check_if_nation_exists(nation_name):
        print(f"The nation {nation_name} does not exist. Try again.")
        sys.exit(1)

    util.bootstrap(args.regenerate_db)

    con = sqlite3.connect("regions.db")
    cursor = con.cursor()

    if len(args.triglist) != 0:
        with open(args.triglist, "r") as trigger_file:
            targets.add_triggers([{"api_name": util.format_nation_or_region(line.rstrip())} for line in trigger_file.readlines()])
            targets.sort_triggers(cursor)
    elif len(args.raidfile) != 0:
        with open(args.raidfile, "r") as raidfile:
            for line in raidfile.readlines():
                match = re.match(r"([a-zA-Z0-9_\- ]+) \(([a-zA-Z0-9_\- ]+);([0-9]+)s\)", line.rstrip())
                if match is not None:
                    groups = match.groups()
                    target = groups[0]
                    trigger = groups[1]
                    delay = int(groups[2])
                    targets.add_trigger({
                        "target": target,
                        "api_name": trigger,
                        "delay": delay,
                    })
            targets.sort_triggers(cursor)

    app = TriggerApp()

    app.run()
