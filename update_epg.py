
#!/usr/bin/env python3

# ==========================================================
# SPORTS-OPTIMISED IPTV EPG ENGINE
# Version 3.0
# ==========================================================

import os
import re
import gzip
import copy
import html
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.parse import urlsplit


# ==========================================================
# CONFIGURATION
# ==========================================================

M3U_URL = os.environ.get("M3U_URL", "").strip()

OUTPUT_FILE = Path("epgs/light-epg.xml.gz")

# True = test without replacing existing EPG.
# False = publish the updated EPG.
TEST_MODE = True

ENABLE_FUZZY = True
FUZZY_THRESHOLD = 0.94
FUZZY_MARGIN = 0.05

MIN_MATCHED_CHANNELS = 75
MIN_PREVIOUS_COVERAGE = 0.90

DOWNLOAD_TIMEOUT = 120


# ==========================================================
# EPG SOURCES
# ==========================================================

BASE = "https://epgshare01.online/epgshare01/"

SOURCE_FILES = [
    # UK and Ireland
    "UK1",
    "IE1",

    # USA and Canada
    "US2",
    "US_LOCALS1",
    "CA2",

    # Australia and New Zealand
    "AU1",
    "NZ1",

    # Europe
    "DE1",
    "ES1",
    "FR1",
    "PT1",
    "IT1",
    "NL1",
    "PL1",

    # Asia
    "MY1",
    "SG1",
    "HK1",
    "IN1",

    # Additional sports sources
    "BEIN1",
    "DIRECTVSPORTS1",
    "SPORTKLUB1",
    "PEACOCK1",
]

EPG_URLS = [
    BASE + f"epg_ripper_{name}.xml.gz"
    for name in SOURCE_FILES
]

EPG_URLS.append(
    "https://raw.githubusercontent.com/"
    "matthuisman/i.mjh.nz/refs/heads/master/"
    "PlutoTV/all.xml"
)


# ==========================================================
# COUNTRY RECOGNITION
# ==========================================================

REGIONS = {
    "uk": "uk",
    "gb": "uk",
    "united kingdom": "uk",
    "england": "uk",
    "britain": "uk",

    "us": "us",
    "usa": "us",
    "united states": "us",
    "america": "us",

    "ca": "ca",
    "canada": "ca",

    "au": "au",
    "aus": "au",
    "australia": "au",

    "nz": "nz",
    "new zealand": "nz",

    "ie": "ie",
    "ireland": "ie",

    "de": "de",
    "ger": "de",
    "germany": "de",

    "es": "es",
    "spain": "es",

    "fr": "fr",
    "france": "fr",

    "pt": "pt",
    "portugal": "pt",

    "it": "it",
    "italy": "it",

    "nl": "nl",
    "netherlands": "nl",

    "pl": "pl",
    "poland": "pl",

    "my": "my",
    "malaysia": "my",

    "sg": "sg",
    "singapore": "sg",

    "hk": "hk",
    "hong kong": "hk",

    "in": "in",
    "india": "in",

    "ng": "ng",
    "nigeria": "ng",

    "za": "za",
    "south africa": "za",

    "tr": "tr",
    "turkey": "tr",

    "br": "br",
    "brazil": "br",

    "mx": "mx",
    "mexico": "mx",

    "ar": "ar",
    "argentina": "ar",

    "be": "be",
    "belgium": "be",

    "ch": "ch",
    "switzerland": "ch",

    "at": "at",
    "austria": "at",

    "se": "se",
    "sweden": "se",

    "no": "no",
    "norway": "no",

    "dk": "dk",
    "denmark": "dk",

    "fi": "fi",
    "finland": "fi",
}

REGION_PATTERN = "|".join(
    re.escape(x)
    for x in sorted(REGIONS, key=len, reverse=True)
)


# ==========================================================
# SPORTS CHANNEL ALIASES
# ==========================================================

ALIASES = {
    "skysportsmain": "skysportsmainevent",
    "skysportsmainevent": "skysportsmainevent",

    "skysportspremier": "skysportspremierleague",
    "skysportsepl": "skysportspremierleague",

    "skysportsf1": "skysportsformula1",
    "skysportsformulaone": "skysportsformula1",

    "skysportsnews": "skysportsnews",
    "skysportsfootball": "skysportsfootball",

    "foxsportsone": "foxsports1",
    "foxsportstwo": "foxsports2",
    "fs1": "foxsports1",
    "fs2": "foxsports2",

    "espnone": "espn1",
    "espntwo": "espn2",

    "bein1": "beinsports1",
    "bein2": "beinsports2",
    "bein3": "beinsports3",
    "bein4": "beinsports4",
    "bein5": "beinsports5",

    "eurosportone": "eurosport1",
    "eurosporttwo": "eurosport2",

    "premiersportsone": "premiersports1",
    "premiersportstwo": "premiersports2",

    "tntsportsone": "tntsports1",
    "tntsportstwo": "tntsports2",
    "tntsportsthree": "tntsports3",
    "tntsportsfour": "tntsports4",

    "sportsnetont": "sportsnetontario",
    "sportsnetpac": "sportsnetpacific",

    "bbc1": "bbcone",
    "bbc2": "bbctwo",
    "itvone": "itv1",
}


# ==========================================================
# DOWNLOAD FUNCTIONS
# ==========================================================

def download(url):

    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("Unsupported URL scheme")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 IPTV-EPG/3.0",
            "Accept": "*/*",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=DOWNLOAD_TIMEOUT
    ) as response:

        data = response.read()

    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)

    return data


# ==========================================================
# TEXT CLEANING
# ==========================================================

def clean_text(value):

    value = html.unescape(str(value or ""))

    value = unicodedata.normalize("NFKD", value)

    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )

    value = value.casefold().strip()

    value = re.sub(r"[┃│┆¦｜]", "|", value)

    return value


def safe_text(value):

    value = str(value or "")

    value = re.sub(
        r"https?://[^\s]+",
        "[URL REMOVED]",
        value
    )

    return value


def get_region(value):

    value = clean_text(value)

    # Bracketed country labels.
    match = re.search(
        rf"[\[(]\s*({REGION_PATTERN})\s*[\])]",
        value
    )

    if match:
        return REGIONS[match.group(1)]

    # Country prefix.
    match = re.match(
        rf"^[\s|]*({REGION_PATTERN})"
        rf"[\s:|._\-]+",
        value
    )

    if match:
        return REGIONS[match.group(1)]

    # Country suffix.
    match = re.search(
        rf"[\s:|._\-]+({REGION_PATTERN})$",
        value
    )

    if match:
        return REGIONS[match.group(1)]

    return ""


def normalise_id(value):

    return re.sub(
        r"[^a-z0-9]",
        "",
        clean_text(value)
    )


def normalise_name(value):

    value = clean_text(value)

    # Remove leading separators.
    value = value.strip(" |")

    # Remove known competition/category prefixes.
    value = re.sub(
        r"^(?:ucl|uel|uecl|epl|uefa|fifa)"
        r"\s*\|\s*",
        "",
        value
    )

    # Remove country prefixes.
    value = re.sub(
        rf"^[\[\(\s|]*(?:{REGION_PATTERN})"
        rf"[\]\):|._\-\s]+",
        "",
        value
    )

    # Remove bracketed country labels.
    value = re.sub(
        rf"[\[(]\s*(?:{REGION_PATTERN})"
        rf"\s*[\])]",
        "",
        value
    )

    # Remove video quality labels.
    value = re.sub(
        r"\b(?:uhd|fhd|hd|sd|4k|8k|"
        r"1080p|720p|2160p|hevc|"
        r"h265|h264|50fps|60fps)\b",
        "",
        value
    )

    value = value.strip()

    # Remove country suffixes.
    value = re.sub(
        rf"[\s._|\-]+(?:{REGION_PATTERN})$",
        "",
        value
    )

    # Preserve plus and timeshift channels.
    value = value.replace("+", " plus ")

    value = re.sub(
        r"[^a-z0-9]",
        "",
        value
    )

    return ALIASES.get(value, value)


def compatible_regions(first, second):

    if first and second:
        return first == second

    return True


def source_region(url):

    match = re.search(
        r"epg_ripper_([A-Z]{2})(?:\d|_)",
        url
    )

    if match:
        return REGIONS.get(
            match.group(1).lower(),
            ""
        )

    return ""


def is_event_channel(name):

    return bool(
        re.search(
            r"event\d*|"
            r"ppv\d*|"
            r"match\d+|"
            r"feed\d+|"
            r"fixture\d+",
            name
        )
    )


# ==========================================================
# READ IPTV PLAYLIST
# ==========================================================

def read_playlist():

    if not M3U_URL:
        raise RuntimeError(
            "M3U_URL GitHub secret is missing."
        )

    print("Downloading private M3U playlist...")

    content = download(M3U_URL).decode(
        "utf-8-sig",
        errors="replace"
    )

    if not content.lstrip().startswith("#EXTM3U"):
        raise RuntimeError(
            "Downloaded file is not an M3U playlist."
        )

    channels = {}
    conflicts = set()

    for line in content.splitlines():

        if not line.startswith("#EXTINF"):
            continue

        attrs = dict(
            re.findall(
                r'([\w-]+)="([^"]*)"',
                line
            )
        )

        channel_id = attrs.get(
            "tvg-id", ""
        ).strip()

        if not channel_id:
            continue

        if "://" in channel_id:
            continue

        if channel_id in conflicts:
            continue

        # Locate the display-name comma outside quotes.
        display_name = ""
        inside_quotes = False

        for index, char in enumerate(line):

            if char == '"':
                inside_quotes = not inside_quotes

            elif char == "," and not inside_quotes:
                display_name = line[index + 1:].strip()
                break

        tvg_name = attrs.get(
            "tvg-name", ""
        ).strip()

        names = {
            html.unescape(name)
            for name in (tvg_name, display_name)
            if name
        }

        if not names:
            continue

        region = (
            get_region(channel_id)
            or get_region(tvg_name)
            or get_region(display_name)
        )

        keys = {
            normalise_name(name)
            for name in names
            if normalise_name(name)
        }

        if channel_id in channels:

            existing = channels[channel_id]

            old_keys = {
                normalise_name(name)
                for name in existing["names"]
            }

            if (
                not compatible_regions(
                    existing["region"],
                    region
                )
                or not keys.intersection(old_keys)
            ):

                conflicts.add(channel_id)
                channels.pop(channel_id, None)
                continue

            existing["names"].update(names)

            if not existing["region"]:
                existing["region"] = region

        else:

            channels[channel_id] = {
                "id": channel_id,
                "names": names,
                "region": region,
            }

    print(
        f"Found {len(channels)} usable channel IDs."
    )

    print(
        f"Conflicting IDs skipped: {len(conflicts)}"
    )

    region_counts = defaultdict(int)

    for channel in channels.values():
        region_counts[
            channel["region"] or "unknown"
        ] += 1

    print("\n===== PLAYLIST REGIONS =====")

    for region, count in sorted(
        region_counts.items(),
        key=lambda item: -item[1]
    ):
        print(f"{region}: {count}")

    return channels


# ==========================================================
# LOAD EPG SOURCES
# ==========================================================

def load_epg_sources():

    entries = []
    successful = 0
    failed = 0

    for index, url in enumerate(EPG_URLS, 1):

        print(
            f"\nProcessing EPG source "
            f"{index}/{len(EPG_URLS)}..."
        )

        print(
            f"Source: {urlsplit(url).path.split('/')[-1]}"
        )

        try:

            data = download(url)
            root = ET.fromstring(data)

            if root.tag != "tv":
                raise ValueError("Not an XMLTV file")

            programmes = defaultdict(list)

            for programme in root.findall("programme"):

                channel_id = programme.get(
                    "channel", ""
                )

                if channel_id:
                    programmes[channel_id].append(
                        programme
                    )

            count = 0
            default_region = source_region(url)

            for channel in root.findall("channel"):

                channel_id = channel.get("id", "")

                if not channel_id:
                    continue

                if channel_id not in programmes:
                    continue

                names = {
                    node.text.strip()
                    for node in channel.findall(
                        "display-name"
                    )
                    if node.text and node.text.strip()
                }

                if not channel_id.isdigit():
                    names.add(channel_id)

                if not names:
                    continue

                region = get_region(channel_id)

                if not region:

                    detected = {
                        get_region(name)
                        for name in names
                        if get_region(name)
                    }

                    if len(detected) == 1:
                        region = detected.pop()

                region = region or default_region

                entries.append({
                    "id": channel_id,
                    "names": names,
                    "region": region,
                    "programmes": programmes[channel_id],
                })

                count += 1

            successful += 1

            print(
                f"Loaded {count} channels "
                f"with programmes."
            )

        except Exception as error:

            failed += 1

            # Do not print raw exceptions or credentials.
            print(
                f"Source unavailable: "
                f"{type(error).__name__}"
            )

    print("\n===== SOURCE RESULTS =====")
    print(f"Successful sources: {successful}")
    print(f"Failed sources: {failed}")
    print(f"Total EPG entries: {len(entries)}")

    if not entries:
        raise RuntimeError(
            "No usable EPG sources were downloaded."
        )

    return entries


# ==========================================================
# BUILD MATCHING INDEXES
# ==========================================================

def build_indexes(entries):

    exact_ids = defaultdict(list)
    normalised_ids = defaultdict(list)
    names = defaultdict(list)
    regional_names = defaultdict(set)

    for entry in entries:

        channel_id = entry["id"]

        # Numeric IDs are not globally unique.
        if not channel_id.isdigit():

            exact_ids[
                channel_id.casefold()
            ].append(entry)

            normalised_ids[
                normalise_id(channel_id)
            ].append(entry)

        for name in entry["names"]:

            key = normalise_name(name)

            if not key:
                continue

            names[key].append(entry)

            if entry["region"]:

                regional_names[
                    entry["region"]
                ].add(key)

    return {
        "exact_ids": exact_ids,
        "normalised_ids": normalised_ids,
        "names": names,
        "regional_names": regional_names,
    }


# ==========================================================
# SELECT BEST MATCH
# ==========================================================

def choose_match(candidates, region):

    candidates = [
        entry for entry in candidates
        if compatible_regions(
            region,
            entry["region"]
        )
    ]

    if not candidates:
        return None

    if region:

        same_region = [
            entry for entry in candidates
            if entry["region"] == region
        ]

        if same_region:
            candidates = same_region

    identities = {
        (
            entry["id"].casefold(),
            entry["region"]
        )
        for entry in candidates
    }

    # Avoid ambiguous channel matches.
    if len(identities) != 1:
        return None

    return max(
        candidates,
        key=lambda entry: len(
            entry["programmes"]
        )
    )


# ==========================================================
# MATCH IPTV CHANNELS
# ==========================================================

def match_channel(channel, indexes):

    channel_id = channel["id"]
    region = channel["region"]

    # Stage 1: Exact ID matching.
    if not channel_id.isdigit():

        result = choose_match(
            indexes["exact_ids"].get(
                channel_id.casefold(),
                []
            ),
            region
        )

        if result:
            return result, "exact"

        # Stage 2: Normalised ID matching.
        result = choose_match(
            indexes["normalised_ids"].get(
                normalise_id(channel_id),
                []
            ),
            region
        )

        if result:
            return result, "normalised"

    keys = {
        normalise_name(name)
        for name in channel["names"]
        if normalise_name(name)
    }

    # Stage 3: Channel names and aliases.
    candidates = []

    for key in keys:

        candidates.extend(
            indexes["names"].get(key, [])
        )

    result = choose_match(
        candidates,
        region
    )

    if result:
        return result, "name"

    # Stage 4: Conservative fuzzy matching.
    if not ENABLE_FUZZY or not region:
        return None, None

    regional_keys = indexes[
        "regional_names"
    ].get(region, set())

    scores = {}

    for key in keys:

        if len(key) < 6:
            continue

        # Do not guess dedicated event feeds.
        if is_event_channel(key):
            continue

        key_numbers = re.findall(r"\d+", key)

        for candidate in regional_keys:

            if is_event_channel(candidate):
                continue

            if abs(len(key) - len(candidate)) > 3:
                continue

            if key_numbers != re.findall(
                r"\d+", candidate
            ):
                continue

            if ("plus" in key) != (
                "plus" in candidate
            ):
                continue

            score = SequenceMatcher(
                None,
                key,
                candidate
            ).ratio()

            if score >= FUZZY_THRESHOLD:

                scores[candidate] = max(
                    score,
                    scores.get(candidate, 0)
                )

    if not scores:
        return None, None

    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], item[0])
    )

    best_key, best_score = ranked[0]

    if len(ranked) > 1:

        second_score = ranked[1][1]

        if best_score - second_score < FUZZY_MARGIN:
            return None, None

    result = choose_match(
        indexes["names"].get(best_key, []),
        region
    )

    if result:
        return result, "fuzzy"

    return None, None


# ==========================================================
# CLEAN PROGRAMME DATA
# ==========================================================

ALLOWED_TAGS = {
    "title",
    "sub-title",
    "desc",
    "category",
    "date",
    "episode-num",
    "language",
    "country",
    "length",
}

ALLOWED_ATTRIBUTES = {
    "lang",
    "system",
    "units",
}


def clean_programme(programme, channel_id):

    start = programme.get("start", "")
    stop = programme.get("stop", "")

    timestamp_pattern = (
        r"\d{14}(?:\s*[+-]\d{4})?"
    )

    if not re.fullmatch(
        timestamp_pattern, start
    ):
        return None

    if stop and not re.fullmatch(
        timestamp_pattern, stop
    ):
        return None

    new_programme = ET.Element(
        "programme",
        {
            "start": start,
            "channel": channel_id,
        }
    )

    if stop:
        new_programme.set("stop", stop)

    for child in programme:

        if child.tag not in ALLOWED_TAGS:
            continue

        if not child.text:
            continue

        new_child = ET.SubElement(
            new_programme,
            child.tag
        )

        new_child.text = safe_text(child.text)

        for key, value in child.attrib.items():

            if (
                key in ALLOWED_ATTRIBUTES
                and re.fullmatch(
                    r"[\w.\- ]{1,40}",
                    value
                )
            ):

                new_child.set(key, value)

    if new_programme.find("title") is None:
        return None

    return new_programme


# ==========================================================
# GENERATE XMLTV EPG
# ==========================================================

def generate_epg(channels, entries):

    print("\nBuilding matching indexes...")

    indexes = build_indexes(entries)

    root = ET.Element(
        "tv",
        {
            "generator-info-name":
                "Sports Optimised EPG V3.0"
        }
    )

    stats = defaultdict(int)
    all_programmes = []
    unmatched_samples = []
    matched_samples = []

    print("Matching IPTV channels...")

    for channel_id, channel in channels.items():

        entry, method = match_channel(
            channel,
            indexes
        )

        if not entry:

            stats["unmatched"] += 1

            if len(unmatched_samples) < 30:

                unmatched_samples.append(
                    (
                        sorted(channel["names"])[0],
                        channel["region"]
                    )
                )

            continue

        seen = set()
        valid_programmes = []

        for programme in entry["programmes"]:

            cleaned = clean_programme(
                programme,
                channel_id
            )

            if cleaned is None:
                continue

            key = (
                cleaned.get("start", ""),
                cleaned.get("stop", "")
            )

            if key in seen:
                continue

            seen.add(key)
            valid_programmes.append(cleaned)

        if not valid_programmes:

            stats["unmatched"] += 1
            continue

        channel_element = ET.SubElement(
            root,
            "channel",
            {"id": channel_id}
        )

        for name in sorted(channel["names"]):

            display = ET.SubElement(
                channel_element,
                "display-name"
            )

            display.text = safe_text(name)

        all_programmes.extend(valid_programmes)

        stats[method] += 1
        stats["matched"] += 1

        if len(matched_samples) < 20:

            matched_samples.append(
                (
                    sorted(channel["names"])[0],
                    entry["id"],
                    method
                )
            )

    for programme in all_programmes:
        root.append(programme)

    total = len(channels)
    matched = stats["matched"]

    rate = (
        matched / total * 100
        if total else 0
    )

    print("\n===== MATCHED CHANNEL SAMPLES =====")

    for name, epg_id, method in matched_samples:

        print(
            f"{safe_text(name)} -> "
            f"{safe_text(epg_id)} "
            f"({method})"
        )

    print("\n===== UNMATCHED CHANNEL SAMPLES =====")

    for name, region in unmatched_samples:

        print(
            f"{safe_text(name)} | "
            f"Region: {region or 'unknown'}"
        )

    print("\n========== MATCHING RESULTS ==========")

    print(f"Total channel IDs: {total}")
    print(f"Exact ID matches: {stats['exact']}")

    print(
        f"Normalised ID matches: "
        f"{stats['normalised']}"
    )

    print(
        f"Channel name matches: "
        f"{stats['name']}"
    )

    print(
        f"Fuzzy name matches: "
        f"{stats['fuzzy']}"
    )

    print(f"Total matched channels: {matched}")
    print(f"Unmatched channels: {total - matched}")
    print(f"Total programmes: {len(all_programmes)}")
    print(f"Match rate: {rate:.2f}%")

    print("======================================")

    return root


# ==========================================================
# EXISTING EPG QUALITY PROTECTION
# ==========================================================

def previous_channel_count():

    if not OUTPUT_FILE.exists():
        return 0

    try:

        with gzip.open(
            OUTPUT_FILE, "rb"
        ) as file:

            root = ET.parse(file).getroot()

        return len(root.findall("channel"))

    except Exception:

        print(
            "Could not read existing EPG."
        )

        return 0


def save_epg(root):

    new_count = len(
        root.findall("channel")
    )

    old_count = previous_channel_count()

    print("\n===== QUALITY CHECK =====")
    print(f"Previous EPG channels: {old_count}")
    print(f"New EPG channels: {new_count}")

    if new_count < MIN_MATCHED_CHANNELS:

        raise RuntimeError(
            "New EPG is below minimum coverage. "
            "Existing EPG preserved."
        )

    if old_count:

        minimum = (
            old_count * MIN_PREVIOUS_COVERAGE
        )

        if new_count < minimum:

            raise RuntimeError(
                "EPG coverage dropped significantly. "
                "Existing EPG preserved."
            )

    xml_data = ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True
    )

    if M3U_URL.encode() in xml_data:

        raise RuntimeError(
            "Privacy check failed."
        )

    if TEST_MODE:

        print(
            "\nTEST MODE ENABLED."
        )

        print(
            "Test completed successfully."
        )

        print(
            "Existing EPG preserved."
        )

        return

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    compressed = gzip.compress(
        xml_data,
        compresslevel=9,
        mtime=0
    )

    temp_file = OUTPUT_FILE.with_suffix(
        ".gz.tmp"
    )

    temp_file.write_bytes(compressed)

    temp_file.replace(OUTPUT_FILE)

    print("\n===== EPG SAVED =====")

    print(f"File: {OUTPUT_FILE}")

    print(
        f"Compressed size: "
        f"{len(compressed) / 1024:.2f} KB"
    )

    print("EPG update completed successfully.")


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 50)
    print("SPORTS-OPTIMISED EPG ENGINE V3.0")
    print("=" * 50)

    print(f"Test mode: {TEST_MODE}")
    print(f"Configured EPG sources: {len(EPG_URLS)}")

    channels = read_playlist()

    if not channels:

        raise RuntimeError(
            "No usable IPTV channels found."
        )

    entries = load_epg_sources()

    root = generate_epg(
        channels,
        entries
    )

    save_epg(root)


if __name__ == "__main__":
    main()
