import threading, time

next_api_hit = 0 # Next time we can hit the API (in UNIX time). Starts at 0, so we can use it immediately the first time.
next_api_hit_lock = threading.Lock()

# Call this before making any API request to NationStates. It will make sure all requests are 
# at least {delay} seconds apart, even if the requests are spread between multiple threads.
def ensure_api_rate_limit(delay: float):
    global next_api_hit
    global next_api_hit_lock

    while True:
        next_api_hit_time = 0
        current_time = 0

        with next_api_hit_lock:
            next_api_hit_time = next_api_hit # fetch a copy of the value so that we can use it outside the lock
            current_time = time.time()
            if(next_api_hit_time < current_time):
                next_api_hit = current_time + delay # update the value behind the lock
                print(f"Next API hit: {next_api_hit} seconds UNIX time, currently from {threading.current_thread().name}") # debugging
                return

        time_to_wait = (next_api_hit_time - current_time) + (0.05) # for good measure
        time.sleep(time_to_wait)

# Format a NationStates nation name to be compatible with the API.
def format_nation_or_region(name: str) -> str:
    return name.lower().replace(" ", "_")
