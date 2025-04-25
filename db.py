import xml.etree.ElementTree as ET
import time, calendar, sqlite3, typing, requests, gzip, os, argparse, requests
import utility as util

# Strip the minutes and seconds from a UNIX timestamp.
# Example: given the following timestamp,
# 1745165862 (Sunday, April 20, 2025 4:17:42 PM)
# the function will return 1745164800 (Sunday, April 20, 2025 4:00:00 PM)
def strip_minutes_and_seconds(timestamp: int) -> int:
    tm = time.gmtime(timestamp)
    return calendar.timegm(tm) - (tm.tm_min*60 + tm.tm_sec)

def fetch_passworded_regions(nation: str) -> typing.List[str]:
    url = "https://www.nationstates.net/cgi-bin/api.cgi?q=regionsbytag;tags=password"
    headers = {'User-Agent': f"Everblaze by Merethin, used by {nation}"}

    util.ensure_api_rate_limit(0.7)
    with requests.get(url, headers=headers) as r:
        r.raise_for_status()
        with open("passworded.xml", 'wb') as f:
            f.write(r.content)

    tree = ET.parse("passworded.xml")
    root = tree.getroot()

    regions = root.find("./REGIONS")

    os.remove("passworded.xml")

    return [util.format_nation_or_region(r) for r in regions.text.split(',')]

# Download the daily regional data dump from NationStates and decompress it.
def download_region_data_dump(nation: str) -> None:
    url = 'https://www.nationstates.net/pages/regions.xml.gz'
    headers = {'Accept': 'application/gzip', 'User-Agent': f"Everblaze by Merethin, used by {nation}"}

    print(f"Downloading data dump from {url}")
    print(f"Headers = {headers}")

    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        with open("regions.xml.gz", 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    
    with gzip.open("regions.xml.gz", 'rb') as f:
        file_content = f.read()
        with open("regions.xml", 'wb') as output:
            output.write(file_content)
    
    os.remove("regions.xml.gz")

# Extract region data from the regions.xml data dump.
def parse_region_data(nation: str, filename: str) -> typing.List[typing.Tuple]:
    tree = ET.parse(filename)
    root = tree.getroot()

    region_data = []

    regions = root.findall("./REGION")

    first_region = regions[0]
    last_major_start = strip_minutes_and_seconds(int(first_region.find("LASTMAJORUPDATE").text))
    last_minor_start = strip_minutes_and_seconds(int(first_region.find("LASTMINORUPDATE").text))

    passworded_regions = fetch_passworded_regions(nation)

    for index, region in enumerate(regions):
        canon_name = region.find("NAME").text
        api_name = util.format_nation_or_region(canon_name)
        update_index = index
        seconds_major = int(region.find("LASTMAJORUPDATE").text) - last_major_start
        seconds_minor = int(region.find("LASTMINORUPDATE").text) - last_minor_start
        delendos = int(region.find("DELEGATEVOTES").text) - 1 # Delegate Votes = Delegate Endos + 1
        executive = int("X" in region.find("DELEGATEAUTH").text) # 1 for Executive, 0 for Non-Executive
        password = 0
        if api_name in passworded_regions:
            password = 1

        region_data.append((canon_name, api_name, update_index, seconds_major, seconds_minor, delendos, executive, password))

    return region_data

def main():
    parser = argparse.ArgumentParser(prog="everblaze-db", description="Generate a database for use by Everblaze clients")
    parser.add_argument("nation", help="The main nation of the player using this script")
    args = parser.parse_args()

    if os.path.exists("regions.db"):
        os.remove("regions.db")
    con = sqlite3.connect("regions.db")

    cursor = con.cursor()
    cursor.execute("CREATE TABLE regions(canon_name, api_name, update_index, seconds_major, seconds_minor, delendos, executive, password)")

    download_region_data_dump(args.nation)
    region_data = parse_region_data(args.nation,"regions.xml")

    cursor.executemany("INSERT INTO regions VALUES(?, ?, ?, ?, ?, ?, ?, ?)", region_data)
    con.commit()

if __name__ == "__main__":
    main()
