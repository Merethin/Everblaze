# utility.py - Utility functions for the entire Everblaze suite of tools
# Authored by Merethin, licensed under the BSD-2-Clause license.
# This file makes 1 (one) API call (in check_if_nation_exists()) - to check if a user's nation exists.
# Additional API calls are imported from db.py, and used in bootstrap().

import threading, time, typing, sqlite3, os, sseclient, re, requests, db

next_api_hit: float = 0 # Next time we can hit the API (in UNIX time). Starts at 0, so we can use it immediately the first time.
next_api_hit_lock = threading.Lock()

# Call this before making any API request to NationStates. It will make sure all requests are 
# at least {delay} seconds apart, even if the requests are spread between multiple threads.
def ensure_api_rate_limit(delay: float):
    global next_api_hit
    global next_api_hit_lock

    while True:
        next_api_hit_time: float = 0
        current_time: float = 0

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

# Convert a row from a database query to a dictionary with well-known keys.
def format_database_data(data) -> typing.Dict:
    output = {}
    # Database row layout: (canon_name, api_name, update_index, seconds_major, seconds_minor, delendos, executive, password, wfe, embassies)
    output["canon_name"] = data[0]
    output["api_name"] = data[1]
    output["update_index"] = data[2]
    output["seconds_major"] = data[3]
    output["seconds_minor"] = data[4]
    output["delendos"] = data[5]
    output["executive"] = data[6]
    output["password"] = data[7]
    output["wfe"] = data[8]
    output["embassies"] = data[9]

    return output

# Fetch data for a region from the local database.
# The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
def fetch_region_data_from_db(cursor: sqlite3.Cursor, region: str) -> typing.Dict | None:
    cursor.execute("SELECT * FROM regions WHERE api_name = ?", [region])
    data = cursor.fetchone()

    if data is None:
        return None

    return format_database_data(data)

# Fetch data for a region from the local database, using its update index.
# The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
def fetch_region_data_with_index(cursor: sqlite3.Cursor, index: int) -> typing.Dict | None:
    cursor.execute("SELECT * FROM regions WHERE update_index = ?", [index])
    data = cursor.fetchone()

    if data is None:
        return None

    return format_database_data(data)

# Find a region updating at the specified delay from the start of update (approximately) in the local database.
# If minor is set to true, will use minor update times. Otherwise, will use major update times.
# If early_tolerance is nonzero, it is the number of seconds before <delay> that a region is permitted to update at in order to be returned, if there is no exact match.
# If late_tolerance is nonzero, it is the number of seconds after <delay> that a region is permitted to update at in order to be returned, if there is no exact match.
def find_region_updating_at_time(cursor: sqlite3.Cursor, delay: int, minor: bool, early_tolerance: int, late_tolerance: int) -> typing.Dict | None:
    if minor:
        cursor.execute("SELECT * FROM regions WHERE seconds_minor = ?", [delay])
    else:
        cursor.execute("SELECT * FROM regions WHERE seconds_major = ?", [delay])

    data = cursor.fetchone()
    if data is None:
        # If there is no exact match, check for surrounding times
        if early_tolerance != 0 or late_tolerance != 0:
            start = delay - early_tolerance
            end = delay + late_tolerance

            for time in range(start, end + 1):
                if time == delay:
                    continue

                # FIXME: optimize this so that the result is the closest it can be to the ideal delay?
                result = find_region_updating_at_time(cursor, time, minor, 0, 0)
                if result is not None:
                    return result
                
        return None
    
    return format_database_data(data)

# Return a list of all regions that have less endorsements than a point nation and have an executive delegacy.
def find_raidable_regions(cursor: sqlite3.Cursor, point_endos: int, start: int = -1) -> typing.List[typing.Dict]:
    cursor.execute("SELECT * FROM regions WHERE executive = 1 AND password = 0 AND delendos < ? AND update_index > ?", [point_endos, start])
    data = cursor.fetchall()

    output = []
    for region in data:
        output.append(format_database_data(region))

    return output

# Returns the number of regions in the database.
def count_regions(cursor: sqlite3.Cursor) -> int:
    cursor.execute("SELECT count(update_index) FROM regions")
    return int(cursor.fetchone()[0])

# Fetch the update index for a region from the local database.
# The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
def fetch_update_index(cursor: sqlite3.Cursor, region: str) -> int | None:
    data = fetch_region_data_from_db(cursor, region)
    if data is None:
        return None
    return data["update_index"]

# Fetch the canonical name (how it's displayed on NationStates) for a region from the local database.
# The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
def fetch_canon_name(cursor: sqlite3.Cursor, region: str) -> str | None:
    data = fetch_region_data_from_db(cursor, region)
    if data is None:
        return None
    return data["canon_name"]

# List of triggers, with arbitrary additional values.
class TriggerList:
    def __init__(self) -> None:
        self.triggers: list[dict] = []

    def __len__(self) -> int:
        return len(self.triggers)

    # Add a new trigger to the list.
    # The trigger must be a dictionary with the "api_name" value set to the trigger region's name
    # with lowercase letters and underscores (as output by format_nation_or_region()).
    # This dictionary may contain any additional values.
    def add_trigger(self, target: typing.Dict) -> None:
        if self.query_trigger(target["api_name"]) is None:
            self.triggers.append(target)

    # Add several new triggers to the list.
    # Each trigger must be a dictionary with the "api_name" value set to the trigger region's name
    # with lowercase letters and underscores (as output by format_nation_or_region()).
    # This dictionary may contain any additional values.
    def add_triggers(self, targets: typing.List[typing.Dict]) -> None:
        for target in targets:
            self.add_trigger(target)

    # Sort the triggers by update order, in ascending order. (First updating trigger goes first, last updating trigger goes last).
    # If the triggers have "update_index" values they will be used, otherwise they will be queried from the database.
    def sort_triggers(self, cursor: sqlite3.Cursor) -> None:
        for trigger in self.triggers:
            if "update_index" not in trigger.keys():
                region_data = fetch_region_data_from_db(cursor, trigger["api_name"])
                assert region_data
                trigger["update_index"] = region_data["update_index"]

        self.triggers.sort(key=lambda x: x["update_index"])

    # Find the trigger object with any associated data for the corresponding region.
    # If the region is not in the trigger list, None will be returned.
    # The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
    def query_trigger(self, api_name: str) -> typing.Dict | None:
        for trigger in self.triggers:
            if trigger["api_name"] == api_name:
                return trigger
            
        return None
    
    # Remove a region from the trigger list, if present, and return it.
    # The region's name must be formatted with lowercase letters and underscores (as output by format_nation_or_region()).
    def remove_trigger(self, api_name: str) -> typing.Optional[typing.Dict]:
        value = None

        for trigger in self.triggers:
            if trigger["api_name"] == api_name:
                value = trigger

        if value is not None:
            self.triggers.remove(value)

        return value

    # Remove all regions with a lower update index than provided from the trigger list, and return them.
    def remove_all_updated_triggers(self, update_index: int) -> typing.List[typing.Dict]:
        already_updated = []

        for trigger in self.triggers:
            if trigger["update_index"] < update_index:
                already_updated.append(trigger)

        for trigger in already_updated:
            self.triggers.remove(trigger)

        return already_updated

# If needed, generate the region database.
# If regenerate_db is set to True, it will always be generated. 
# Otherwise, it will only be generated if there isn't already one.
def bootstrap(nation: str, regenerate_db: bool):
    if(regenerate_db or not os.path.exists("regions.db")):
        db.generate_database(nation)

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
        
def check_if_nation_exists(nation: str) -> bool:
    url = f"https://www.nationstates.net/cgi-bin/api.cgi?nation={format_nation_or_region(nation)}&q=name"
    headers = {'User-Agent': f"Everblaze by Merethin, used by {nation}"}

    ensure_api_rate_limit(0.7)
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return True
    elif response.status_code == 404:
        return False
    else:
        # Should never happen unless something's wrong with your connection to NS, in which case, it will throw an error as we can't connect to NS anyway.
        typing.assert_never(response.status_code)

# If update is "minor" with any capitalization, returns minor. Anything else is assumed to be major.
def is_minor(update: str) -> bool:
    return update.lower() == "minor"