import sseclient, re, json, time, requests, typing, argparse, zmq, pidfile, sys

UPDATE_REGEX = re.compile(r"%%([a-z0-9_]+)%% updated\.")

def connect_sse(url: str, headers: typing.Dict) -> sseclient.SSEClient:
    try:
        return sseclient.SSEClient(url, headers=headers)
    except requests.HTTPError as e:
        if e.response.status_code == 429: # API rate limit
            retry_after = int(e.response.headers["Retry-After"])
            time.sleep(retry_after)
            return connect_sse(url, headers)
        else:
            raise e

def main():
    parser = argparse.ArgumentParser(prog="everblaze-server", description="Everblaze triggering server")
    parser.add_argument("nation", help="The main nation of the player using this script")
    args = parser.parse_args()

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://localhost:6432")

    is_cancelled = False

    print(f'Starting Everblaze server using nation {args.nation}')

    # Server-sent events API endpoint. Will return update and other admin events for every region in the world. Then we filter.
    url = 'https://www.nationstates.net/api/admin/'
    headers = {'Accept': 'text/event-stream', 'User-Agent': f"Everblaze (server) by Merethin, used by {args.nation}"}

    client = connect_sse(url, headers)

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
            match = UPDATE_REGEX.match(happening)
            if match is not None:
                region_name = match.groups()[0]

                print(f"log: {region_name} updated!")

                # Everyone listening will get an update event delivered straight to their socket!
                socket.send_string(region_name)

if __name__ == "__main__":
    try:
        with pidfile.PIDFile():
            main()
    except pidfile.AlreadyRunningError:
        print('Another Everblaze server is already running.')
        sys.exit(0)