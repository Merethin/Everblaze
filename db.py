# db.py - Region database generation
# Authored by Merethin, licensed under the BSD-2-Clause license.

import xml.etree.ElementTree as ET
import time, calendar, sqlite3, typing, datetime, gzip, os, sans
import utility as util

# Strip the minutes and seconds from a UNIX timestamp.
# Example: given the following timestamp,
# 1745165862 (Sunday, April 20, 2025 4:17:42 PM)
# the function will return 1745164800 (Sunday, April 20, 2025 4:00:00 PM)
def strip_minutes_and_seconds(timestamp: int) -> int:
    tm = time.gmtime(timestamp)
    return calendar.timegm(tm) - (tm.tm_min*60 + tm.tm_sec)

# Fetch a list of all passworded regions from the NationStates API and return it as a list of API-compatible region names.
def fetch_passworded_regions() -> typing.List[str]:
    query = sans.World("regionsbytag", tags="password")
    root = sans.get(query).xml

    regions = root.find("./REGIONS")

    return [util.format_nation_or_region(r) for r in regions.text.split(',')]

# Fetch a list of all governorless regions from the NationStates API and return it as a list of API-compatible region names.
def fetch_governorless_regions() -> typing.List[str]:
    query = sans.World("regionsbytag", tags="governorless")
    root = sans.get(query).xml

    regions = root.find("./REGIONS")

    return [util.format_nation_or_region(r) for r in regions.text.split(',')]

# Download the daily regional data dump from NationStates and decompress it.
def download_region_data_dump() -> None:
    print("[everblaze] downloading latest regional data dump")

    with sans.stream("GET", sans.RegionsDump()) as r:
        r.raise_for_status()
        with open("regions.xml.gz", 'wb') as f:
            for chunk in r.iter_bytes(chunk_size=8192):
                f.write(chunk)

    print("[everblaze] decompressing latest regional data dump")

    with gzip.open("regions.xml.gz", 'rb') as f:
        file_content = f.read()
        with open("regions.xml", 'wb') as output:
            output.write(file_content)
    
    os.remove("regions.xml.gz")

def get_last_major_data(regions: list[ET.Element]) -> tuple[int, int]:
    first_region = regions[0]
    major_start = int(first_region.find("LASTMAJORUPDATE").text)

    last_region = regions[-1]
    major_end = int(last_region.find("LASTMAJORUPDATE").text)

    return (major_start, major_end - major_start)

def get_last_minor_data(regions: list[ET.Element]) -> tuple[int, int]:
    first_region = regions[0]
    minor_start = int(first_region.find("LASTMINORUPDATE").text)

    last_region = regions[-1]
    minor_end = int(last_region.find("LASTMINORUPDATE").text)

    return (minor_start, minor_end - minor_start)

def format_timestamp(timestamp: int) -> str:
    return datetime.datetime.fromtimestamp(timestamp).strftime("%A %b %d, %H:%M")

# Extract region data from the regions.xml data dump.
def parse_region_data(filename: str) -> typing.List[typing.Tuple]:
    print("[everblaze] parsing latest regional data dump")

    tree = ET.parse(filename)
    root = tree.getroot()

    region_data = []

    regions = root.findall("./REGION")

    (major_start, major_length) = get_last_major_data(regions)
    (minor_start, minor_length) = get_last_minor_data(regions)

    print(f"[everblaze] last major: {format_timestamp(major_start)}, {major_length} seconds long")
    print(f"[everblaze] last minor: {format_timestamp(minor_start)}, {minor_length} seconds long")

    passworded_regions = fetch_passworded_regions()
    governorless_regions = fetch_governorless_regions()

    numnations = 0
    for region in regions:
        numnations += int(region.find("NUMNATIONS").text)

    major_secs_per_nation = major_length / numnations
    minor_secs_per_nation = minor_length / numnations

    print(f"[everblaze] {numnations} total nations, {major_secs_per_nation} seconds per nation (major), {minor_secs_per_nation} seconds per nation (minor)")

    cumulative_nations = 0

    for index, region in enumerate(regions):
        # Core information
        canon_name = region.find("NAME").text
        api_name = util.format_nation_or_region(canon_name)
        update_index = index
        delendos = int(region.find("DELEGATEVOTES").text) - 1 # Delegate Votes = Delegate Endos + 1
        executive = int("X" in region.find("DELEGATEAUTH").text) # 1 for Executive, 0 for Non-Executive
        wfe = region.find("FACTBOOK").text
        if wfe is None:
            wfe = ""

        # Apparently last update isn't accurate enough. Calculate update times based on average update time per nation.
        seconds_major = int(cumulative_nations * major_secs_per_nation)
        seconds_minor = int(cumulative_nations * minor_secs_per_nation)
        cumulative_nations += int(region.find("NUMNATIONS").text)

        # Simple enough
        password = 0
        if api_name in passworded_regions:
            password = 1

        governorless = 0
        if api_name in governorless_regions:
            governorless = 1

        # Oh boy
        embassies = []
        for child in region.find("EMBASSIES"):
            if("type" in child.attrib.keys()):
                if(child.attrib["type"] in ["denied", "rejected"]):
                    # Skipping unwanted embassy
                    continue
                if(child.attrib["type"] in ["requested", "pending", "invited"]):
                    pass # Add it nonetheless. We don't want to retag regions we've already tagged even if the embassy is pending.

            embassies.append(util.format_nation_or_region(child.text))

        # Join it all together
        region_data.append((canon_name, api_name, update_index, seconds_major, seconds_minor, delendos, executive, password, governorless, wfe, ",".join(embassies)))

    return region_data

# Generate the region information database, using the provided nation name to identify itself to NationStates.
def generate_database() -> None:
    print("[everblaze] generating regional database table")

    if os.path.exists("regions.db"):
        os.remove("regions.db")
    con = sqlite3.connect("regions.db")

    cursor = con.cursor()
    cursor.execute("CREATE TABLE regions(canon_name, api_name, update_index, seconds_major, seconds_minor, delendos, executive, password, governorless, wfe, embassies)")

    download_region_data_dump()
    region_data = parse_region_data("regions.xml")

    cursor.executemany("INSERT INTO regions VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", region_data)
    con.commit()