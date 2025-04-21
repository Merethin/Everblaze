from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog
from textual import on, work
from textual.message import Message
from textual.worker import get_current_worker
import zmq, re, argparse, sqlite3, typing
import utility as util

# Global variables.
targets = util.TriggerList() # The list of targets to watch for updates (can be modified at runtime).

# Input field to run commands.
# Currently, these are the three supported commands:
#   add region_name - adds a region to the trigger list
#   remove region_name - manually removes a region from the trigger list, without waiting for it to update
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

        if command[0] == "add":
            self.app.post_message(self.AddTarget(util.format_nation_or_region(command[1])))
        if command[0] == "snipe":
            match = re.match("([a-zA-Z0-9_ ]+);(minor|major);([0-9]+)(s|m);([0-9]+);([0-9]+)", command[1])
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
        elif command[0] == "remove":
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
    @work(thread=True)
    def update_listener(self) -> None:
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect("tcp://localhost:6432")
        socket.setsockopt(zmq.SUBSCRIBE, b'')

        self.post_message(OutputLog.WriteLog(f"\u2e30 Connected to tcp://localhost:6432"))

        while True:
            # We only notice this after a heartbeat arrives from the connection.
            # Unfortunate, but checking manually is the only way to cancel a thread apparently.
            # UNIX signals were too unreliable and thread-unsafe, huh? Quite the inconvenience.
            if get_current_worker().is_cancelled:
                print("Cancelled thread, closing connection")
                return
            
            region = socket.recv_string()

            self.post_message(OutputLog.WriteLog(f"\u2e30 feed: {region} updated."))

            self.app.post_message(TriggerApp.RegionUpdate(region))

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
    class RegionUpdate(Message):
        """Transmitted when a region has updated."""

        def __init__(self, region: str) -> None:
            self.region = region

            super().__init__()

    def compose(self) -> ComposeResult:
        self.title = "Everblaze"

        self.con = sqlite3.connect("regions.db")
        self.cursor = self.con.cursor()

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

        data = util.fetch_region_data_from_db(self.cursor, event.region)

        already_updated = targets.remove_all_updated_triggers(data["update_index"])
        for trigger in already_updated:
            self.post_message(OutputLog.WriteLog(f"\u2e30 {trigger["api_name"]} has already updated!"))

        target = targets.query_trigger(event.region)

        if target is not None:
            self.post_message(OutputLog.WriteLog(format_update_log(target)))
            self.post_message(OutputLog.Bell())
            self.post_message(OutputLog.RemoveTarget(event.region))

    @on(CommandInput.SnipeTarget)
    def on_snipe_target(self, event: CommandInput.SnipeTarget) -> None:
        global targets

        minor = event.update == "minor"

        region_data = util.fetch_region_data_from_db(self.cursor, event.target)
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
    parser.add_argument("-t", "--triglist", default="")
    parser.add_argument("-n", "--nation-name", default="")
    args = parser.parse_args()

    nation = ""
    if len(args.nation_name) != 0:
        nation = args.nation_name
    else:
        nation = input("Please enter your main nation name: ")

    util.bootstrap(nation, False) # FIXME: Add command line parameter for regenerate_db

    app = TriggerApp()

    if len(args.triglist) != 0:
        with open(args.triglist, "r") as trigger_file:
            targets.add_triggers([util.format_nation_or_region(line.rstrip()) for line in trigger_file.readlines()])
            targets.sort_triggers(app.cursor)

    app.run()
    app.get_widget_by_id("output", expect_type=OutputLog).worker.cancel()
