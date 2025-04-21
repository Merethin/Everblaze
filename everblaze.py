from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Input, RichLog
from textual import on, work
from textual.message import Message
from textual.worker import get_current_worker
import sseclient, json, typing, re, argparse
import utility as util

# Global variables.
nation_name = "" # The nation using this tool.
targets = [] # The list of targets to watch for updates (can be modified at runtime).

UPDATE_REGEX = re.compile(r"%%([a-z0-9_]+)%% updated\.")

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
        elif command[0] == "remove":
            self.app.post_message(self.RemoveTarget(util.format_nation_or_region(command[1])))
        elif command[0] == "clear":
            self.app.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.ClearLog())
        else:
            pass

        self.clear()

# Output log widget.
# Also hosts the SSE client/listener worker.
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

    class RelaunchSSE(Message):
        """Relaunch the server-sent event listener."""

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
        self.worker = None

        self.post_message(self.RelaunchSSE()) # More like launch instead of relaunch here

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

    # SSE client/listener worker.
    @work(exclusive=True, thread=True)
    def sse_task(self, target_list: typing.List) -> None:
        if(len(target_list) == 0):
            self.post_message(self.WriteLog("\u2e30 No triggers set!"))
            return
        
        # Server-sent events API endpoint. A URL like "https://www.nationstates.net/api/admin/region:the_north_pacific+region:lazarus"
        # will only return happenings that match both of the following criteria:
        #   1. the happening is part of the "Admin" shard
        #   2. the happening was generated in The North Pacific or Lazarus
        url = f'https://www.nationstates.net/api/admin/{"+".join([f"region:{region}" for region in target_list])}'
        headers = {'Accept': 'text/event-stream', 'User-Agent': f"Everblaze by Merethin, used by {nation_name}"}

        # I think initial SSE requests need to comply with the API rate limit?
        # Not sure, but if there's any doubt, it's better to comply with the rate limit.
        util.ensure_api_rate_limit(0.7)
        messages = sseclient.SSEClient(url, headers=headers)

        for event in messages:
            # We only notice this after a heartbeat arrives from the connection.
            # Unfortunate, but checking manually is the only way to cancel a thread apparently.
            # UNIX signals were too unreliable and thread-unsafe, huh? Quite the inconvenience.
            if get_current_worker().is_cancelled:
                print("Cancelled thread, closing connection")
                return
            
            if event.data: # If the event has no data it's a heartbeat. We do want to receive heartbeats however so that we can check for cancellation above.
                data = json.loads(event.data)
                happening = data["str"]

                # The happening line is formatted like this: "%%region_name%% updated." We want to know if the happening matches this, 
                # and if so, retrieve the region name.
                match = UPDATE_REGEX.match(happening)
                if match is not None:
                    region_name = match.groups()[0]

                    self.post_message(self.WriteLog(f"\u2e30 {region_name} updated!"))
                    self.post_message(self.Bell())
                    self.post_message(self.RemoveTarget(region_name))


    @on(RelaunchSSE)
    def on_relaunch_sse(self, event: RelaunchSSE) -> None:
        if(self.worker):
            self.worker.cancel() # Cancel the current client, who has an outdated target list

        self.worker = self.sse_task(targets[:]) # Restart the SSE client with the new target list
        event.stop()

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
        return "\n".join(targets)
    
    @on(RefreshTriggerList)
    def on_refresh_trigger_list(self, event: RefreshTriggerList) -> None:
        self.refresh()
        event.stop()

class TriggerApp(App):
    def compose(self) -> ComposeResult:
        self.title = "Everblaze"

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
        if event.target not in targets:
            targets.append(event.target)

            self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.RelaunchSSE())
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog("\u2e30 Triggers edited, reloading."))

    # This one is called by a command, and therefore produces a "Triggers edited" happening in the output log.
    @on(CommandInput.RemoveTarget)
    def on_remove_target(self, event: CommandInput.RemoveTarget) -> None:
        global targets
        if event.target in targets:
            targets.remove(event.target)

            self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.RelaunchSSE())
            self.get_widget_by_id("output", expect_type=OutputLog).post_message(OutputLog.WriteLog("\u2e30 Triggers edited, reloading."))

    # This one is called by the SSE thread when a region updates, and therefore does not produce a "Triggers edited" happening in the output log
    # The SSE thread already generates its own "region updated" happening anyway
    @on(OutputLog.RemoveTarget)
    def on_remove_target_after_update(self, event: OutputLog.RemoveTarget) -> None:
        global targets
        if event.target in targets:
            targets.remove(event.target)

            self.get_widget_by_id("triggers", expect_type=TriggerList).post_message(TriggerList.RefreshTriggerList())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="trigger tool", description="Versatile triggering tool for NationStates R/D")
    parser.add_argument("-t", "--triglist", default="")
    parser.add_argument("-n", "--nation-name", default="")
    args = parser.parse_args()

    if len(args.triglist) != 0:
        with open(args.triglist, "r") as trigger_file:
            targets = [util.format_nation_or_region(line.rstrip()) for line in trigger_file.readlines()]

    if len(args.nation_name) != 0:
        nation_name = args.nation_name
    else:
        nation_name = input("Please enter your main nation name: ") # Can't hit the API without a main nation name
    
    app = TriggerApp()
    app.run()
