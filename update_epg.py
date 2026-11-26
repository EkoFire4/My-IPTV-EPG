
#!/usr/bin/env python3

# ==========================================================
# INTELLIGENT SPORTS EPG ENGINE
# Version 3.1
# ==========================================================

import os
import re
import gzip
import html
import json
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

from pathlib import Path
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit


# ==========================================================
# CONFIGURATION
# ==========================================================

M3U_URL = os.environ.get("M3U_URL", "").strip()

OUTPUT_FILE = Path("epgs/light-epg.xml.gz")
MAPPING_FILE = Path("channel_mapping.json")

TEST_MODE = True

ENABLE_FUZZY = True
FUZZY_THRESHOLD = 0.95
FUZZY_MARGIN = 0.05

MIN_MATCHED_CHANNELS = 75
MIN_PREVIOUS_COVERAGE = 0.90

DOWNLOAD_TIMEOUT = 60

NOW = datetime.now(timezone.utc)
EARLIEST = NOW - timedelta(hours=12)


# ==========================================================
# EPG SOURCES
# ==========================================================

BASE = "https://epgshare01.online/epgshare01/"

SOURCE_FILES = [
    # Existing working sources
    "UK1",
    "IE1",
    "US2",
    "US_LOCALS1",
    "CA2",
    "AU1",
    "NZ1",
    "DE1",
    "ES1",
    "FR1",
    "PT1",
    "IT1",
    "NL1",
    "PL1",
    "MY1",
    "SG1",
    "HK1",
    "IN1",
    "BEIN1",
    "DIRECTVSPORTS1",
    "SPORTKLUB1",
    "PEACOCK1",

    # Additional international sources
    "AR1",
    "TR1",
    "BE1",
    "MX1",
    "FI1",
    "BR1",
    "AT1",
    "SE1",
    "DK1",
    "NO1",
    "CH1",
    "ZA1",
    "NG1",
    "DUMMY_CHANNELS",
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

COUNTRIES = {
    "uk": ["uk", "gb", "united kingdom",
           "england", "britain"],
    "us": ["us", "usa", "united states"],
    "ca": ["ca", "can", "canada"],
    "au": ["au", "aus", "australia"],
    "nz": ["nz", "new zealand"],
    "ie": ["ie", "irl", "ireland"],
    "de": ["de", "ger", "germany", "deutschland"],
    "es": ["es", "esp", "spain", "espana"],
    "fr": ["fr", "fra", "france"],
    "pt": ["pt", "por", "portugal"],
    "it": ["it", "ita", "italy", "italia"],
    "nl": ["nl", "ned", "netherlands", "holland"],
    "pl": ["pl", "pol", "poland", "polska"],
    "my": ["my", "malaysia"],
    "sg": ["sg", "singapore"],
    "hk": ["hk", "hong kong"],
    "in": ["in", "india"],
    "ng": ["ng", "nigeria"],
    "za": ["za", "south africa"],
    "tr": ["tr", "tur", "turkey", "turkiye"],
    "br": ["br", "bra", "brazil", "brasil"],
    "mx": ["mx", "mex", "mexico"],
    "ar": ["ar", "arg", "argentina"],
    "be": ["be", "bel", "belgium"],
    "ch": ["ch", "switzerland"],
    "at": ["at", "aut", "austria"],
    "se": ["se", "swe", "sweden"],
    "no": ["no", "nor", "norway"],
    "dk": ["dk", "den", "denmark"],
    "fi": ["fi", "fin", "finland"],
    "gr": ["gr", "gre", "greece"],
    "ro": ["ro", "romania"],
    "cz": ["cz", "czech republic"],
    "hu": ["hu", "hungary"],
    "hr": ["hr", "croatia"],
    "rs": ["rs", "serbia"],
    "ae": ["ae", "uae"],
    "sa": ["sa", "saudi arabia"],
    "qa": ["qa", "qatar"],
    "eg": ["eg", "egypt"],
    "pk": ["pk", "pakistan"],
    "id": ["id", "indonesia"],
    "th": ["th", "thailand"],
    "ph": ["ph", "philippines"],
    "jp": ["jp", "japan"],
    "kr": ["kr", "south korea"],
    "cl": ["cl", "chile"],
    "co": ["co", "colombia"],
    "pe": ["pe", "peru"],
}

REGIONS = {
    alias: region
    for region, aliases in COUNTRIES.items()
    for alias in aliases
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
    "skysportspremier": "skysportspremierleague",
    "skysportsepl": "skysportspremierleague",
    "skysportsf1": "skysportsformula1",
    "skysportsformulaone": "skysportsformula1",

    "foxsportsone": "foxsports1",
    "foxsportstwo": "foxsports2",
    "fs1": "foxsports1",
    "fs2": "foxsports2",

    "espnone": "espn1",
    "espntwo": "espn2",

    "eurosportone": "eurosport1",
    "eurosporttwo": "eurosport2",

    "premiersportsone": "premiersports1",
    "premiersportstwo": "premiersports2",

    "tntsportsone": "tntsports1",
    "tntsportstwo": "tntsports2",
    "tntsportsthree": "tntsports3",
    "tntsportfour": "tntsports4",
    "tntsportfive": "tntsports5",

    "sportsnetont": "sportsnetontario",
    "sportsnetpac": "sportsnetpacific",

    "bbc1": "bbcone",
    "bbc2": "bbctwo",
    "bbc3": "bbcthree",
    "bbc4": "bbcfour",
    "itvone": "itv1",

    "sporttvone": "sporttv1",
    "sporttvtwo": "sporttv2",

    "ziggosportselect": "ziggosportselect",
}

for number in range(1, 11):

    ALIASES[f"bein{number}"] = (
        f"beinsports{number}"
    )

    ALIASES[f"tntsport{number}"] = (
        f"tntsports{number}"
    )

    ALIASES[f"skysport{number}"] = (
        f"skysports{number}"
    )


# ==========================================================
# DOWNLOAD
# ==========================================================

def download(url):

    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("Unsupported URL scheme")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 EPG-Engine/3.1",
            "Accept": "*/*",
        }
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
# TEXT NORMALISATION
# ==========================================================

def clean_text(value):

    value = html.unescape(str(value or ""))

    value = unicodedata.normalize("NFKD", value)

    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )

    value = value.casefold().strip()

    return re.sub(r"[┃│┆¦｜]", "|", value)


def safe_text(value):

    return re.sub(
        r"https?://[^\s]+",
        "[URL REMOVED]",
        str(value or "")
    )


def get_region(value):

    value = clean_text(value)

    patterns = [
        rf"[\[(]\s*({REGION_PATTERN})\s*[\])]",

        rf"^\s*({REGION_PATTERN})"
        rf"\s*[:|._\-]+\s*",

        rf"[._|]\s*({REGION_PATTERN})$",
    ]

    for pattern in patterns:

        match = re.search(pattern, value)

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

    value = value.strip(" |")

    # Remove known category prefixes.
    value = re.sub(
        r"^(?:ucl|uel|uecl|epl|uefa|fifa|"
        r"sports|sport|football|soccer)"
        r"\s*\|\s*",
        "",
        value
    )

    # Remove explicit country prefixes.
    value = re.sub(
        rf"^\s*(?:{REGION_PATTERN})"
        rf"\s*[:|._\-]+\s*",
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

    # Remove country suffixes from EPG IDs.
    value = re.sub(
        rf"[._|]\s*(?:{REGION_PATTERN})$",
        "",
        value
    )

    # Remove encoding and resolution labels.
    value = re.sub(
        r"\b(?:uhd|fhd|hd|sd|4k|8k|"
        r"1080p|720p|2160p|hevc|"
        r"h265|h264|50fps|60fps)\b",
        "",
        value
    )

    value = value.replace("+", " plus ")

    value = re.sub(
        r"[^a-z0-9]",
        "",
        value
    )

    return ALIASES.get(value, value)


def compatible_regions(first, second):

    return not first or not second or first == second


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
            r"event\d*|ppv\d*|match\d+|"
            r"feed\d+|fixture\d+|"
            r"redbutton\d*",
            name
        )
    )


# ==========================================================
# PROGRAMME FRESHNESS
# ==========================================================

def parse_timestamp(value):

    value = str(value or "").strip()

    for pattern in (
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M%S%z",
        "%Y%m%d%H%M%S",
    ):

        try:

            result = datetime.strptime(
                value,
                pattern
            )

            if result.tzinfo is None:
                result = result.replace(
                    tzinfo=timezone.utc
                )

            return result.astimezone(
                timezone.utc
            )

        except ValueError:
            continue

    return None


def programme_is_fresh(programme):

    start = parse_timestamp(
        programme.get("start")
    )

    stop = parse_timestamp(
        programme.get("stop")
    )

    if start is None:
        return False

    if stop is not None:

        if stop <= start:
            return False

        return stop >= EARLIEST

    return start >= EARLIEST


# ==========================================================
# READ IPTV PLAYLIST
# ==========================================================

def read_playlist():

    if not M3U_URL:
        raise RuntimeError(
            "M3U_URL GitHub secret is missing."
        )

    print("Downloading M3U playlist...")

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

        display_name = ""
        inside_quotes = False

        for index, char in enumerate(line):

            if char == '"':
                inside_quotes = not inside_quotes

            elif char == "," and not inside_quotes:

                display_name = line[
                    index + 1:
                ].strip()

                break

        tvg_name = attrs.get(
            "tvg-name", ""
        ).strip()

        group = attrs.get(
            "group-title", ""
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
            or get_region(group)
        )

        keys = {
            normalise_name(name)
            for name in names
            if normalise_name(name)
        }

        if not keys:
            continue

        event = any(
            is_event_channel(key)
            for key in keys
        )

        if channel_id in channels:

            existing = channels[channel_id]

            if (
                not compatible_regions(
                    existing["region"],
                    region
                )
                or not keys.intersection(
                    existing["keys"]
                )
            ):

                conflicts.add(channel_id)
                channels.pop(channel_id, None)
                continue

            existing["names"].update(names)
            existing["keys"].update(keys)

            existing["region"] = (
                existing["region"] or region
            )

            existing["event"] = (
                existing["event"] or event
            )

        else:

            channels[channel_id] = {
                "id": channel_id,
                "names": names,
                "keys": keys,
                "region": region,
                "event": event,
            }

    print(
        f"Found {len(channels)} usable channel IDs."
    )

    print(
        f"Conflicting IDs skipped: {len(conflicts)}"
    )

    event_count = sum(
        channel["event"]
        for channel in channels.values()
    )

    print(f"Dedicated event feeds: {event_count}")

    print("\n===== PLAYLIST REGIONS =====")

    regions = Counter(
        channel["region"] or "unknown"
        for channel in channels.values()
    )

    for region, count in regions.most_common():
        print(f"{region}: {count}")

    return channels


# ==========================================================
# LOAD EPG SOURCES
# ==========================================================

def load_epg_sources():

    entries = []
    successful = 0
    failed = 0
    expired = 0
    failed_sources = []

    for index, url in enumerate(EPG_URLS, 1):

        filename = urlsplit(url).path.split("/")[-1]

        print(
            f"\nProcessing EPG source "
            f"{index}/{len(EPG_URLS)}..."
        )

        print(f"Source: {filename}")

        try:

            data = download(url)
            root = ET.fromstring(data)

            if root.tag != "tv":
                raise ValueError("Not XMLTV")

            programmes = defaultdict(list)

            for programme in root.findall("programme"):

                channel_id = programme.get(
                    "channel", ""
                )

                if not channel_id:
                    continue

                if not programme_is_fresh(programme):

                    expired += 1
                    continue

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

                keys = {
                    normalise_name(name)
                    for name in names
                    if normalise_name(name)
                }

                if not keys:
                    continue

                entries.append({
                    "id": channel_id,
                    "names": names,
                    "keys": keys,
                    "region": region,
                    "source": filename,
                    "programmes": programmes[channel_id],
                })

                count += 1

            successful += 1

            print(
                f"Loaded {count} channels "
                f"with recent or future programmes."
            )

        except Exception as error:

            failed += 1
            failed_sources.append(filename)

            print(
                f"Source unavailable: "
                f"{type(error).__name__}"
            )

    print("\n===== SOURCE RESULTS =====")
    print(f"Successful sources: {successful}")
    print(f"Failed sources: {failed}")
    print(f"Total EPG entries: {len(entries)}")
    print(f"Expired/invalid programmes removed: {expired}")

    if failed_sources:

        print("\nUnavailable source files:")

        for filename in failed_sources:
            print(filename)

    if not entries:
        raise RuntimeError("No usable EPG data.")

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

        if not channel_id.isdigit():

            exact_ids[
                channel_id.casefold()
            ].append(entry)

            normalised_ids[
                normalise_id(channel_id)
            ].append(entry)

        for key in entry["keys"]:

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
# OPTIONAL VERIFIED CHANNEL MAPPINGS
# ==========================================================

def load_verified_mappings():

    if not MAPPING_FILE.exists():

        print("No manual channel mapping file found.")
        return {}

    try:

        mappings = json.loads(
            MAPPING_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(mappings, dict):
            raise ValueError("Invalid mapping format")

        print(
            f"Loaded {len(mappings)} manual mappings."
        )

        return mappings

    except Exception:

        print("Manual mapping file could not be read.")
        return {}


# ==========================================================
# SELECT BEST MATCH
# ==========================================================

def choose_match(candidates, region):

    candidates = [
        entry
        for entry in candidates
        if compatible_regions(
            region,
            entry["region"]
        )
    ]

    if not candidates:
        return None

    if region:

        same_region = [
            entry
            for entry in candidates
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

    # Reject ambiguous matches.
    if len(identities) != 1:
        return None

    return max(
        candidates,
        key=lambda entry: len(
            entry["programmes"]
        )
    )


# ==========================================================
# MATCH CHANNELS
# ==========================================================

def match_channel(channel, indexes, mappings):

    channel_id = channel["id"]
    region = channel["region"]
    keys = channel["keys"]

    # Stage 1: Manually verified mapping.
    mapping = mappings.get(channel_id)

    if isinstance(mapping, dict):

        mapped_id = mapping.get("epg_id", "")
        expected_name = mapping.get("name", "")

        if (
            mapped_id
            and expected_name
            and normalise_name(expected_name) in keys
        ):

            result = choose_match(
                indexes["exact_ids"].get(
                    mapped_id.casefold(),
                    []
                ),
                region
            )

            if result:
                return result, "manual"

    # Stage 2: Exact non-numeric ID.
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

        # Stage 3: Normalised ID.
        result = choose_match(
            indexes["normalised_ids"].get(
                normalise_id(channel_id),
                []
            ),
            region
        )

        if result:
            return result, "normalised"

    # Stage 4: Exact normalised channel names.
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

    # Never guess an event feed.
    if channel["event"]:
        return None, None

    # Stage 5: Conservative fuzzy matching.
    if not ENABLE_FUZZY or not region:
        return None, None

    regional_keys = indexes[
        "regional_names"
    ].get(region, set())

    scores = {}

    for key in keys:

        if len(key) < 6:
            continue

        numbers = re.findall(r"\d+", key)

        for candidate in regional_keys:

            if is_event_channel(candidate):
                continue

            if abs(len(key) - len(candidate)) > 3:
                continue

            if numbers != re.findall(
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

        if best_score - ranked[1][1] < FUZZY_MARGIN:
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

    start = parse_timestamp(
        programme.get("start")
    )

    stop = parse_timestamp(
        programme.get("stop")
    )

    if start is None:
        return None

    if not programme_is_fresh(programme):
        return None

    new_programme = ET.Element(
        "programme",
        {
            "start": start.strftime(
                "%Y%m%d%H%M%S +0000"
            ),
            "channel": channel_id,
        }
    )

    if stop:

        new_programme.set(
            "stop",
            stop.strftime(
                "%Y%m%d%H%M%S +0000"
            )
        )

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
# GENERATE XMLTV
# ==========================================================

def generate_epg(channels, entries):

    print("\nBuilding matching indexes...")

    indexes = build_indexes(entries)
    mappings = load_verified_mappings()

    root = ET.Element(
        "tv",
        {
            "generator-info-name":
                "Intelligent Sports EPG V3.1"
        }
    )

    stats = Counter()

    regional_totals = Counter()
    regional_matches = Counter()

    unmatched = defaultdict(list)
    matched_samples = defaultdict(list)

    all_programmes = []
    unique_epg_channels = set()

    print("Matching IPTV channels...")

    for channel_id, channel in channels.items():

        region = channel["region"] or "unknown"

        regional_totals[region] += 1

        name = sorted(channel["names"])[0]

        entry, method = match_channel(
            channel,
            indexes,
            mappings
        )

        if not entry:

            stats["unmatched"] += 1

            if channel["event"]:

                stats["unmatched_events"] += 1

            else:

                stats["unmatched_regular"] += 1

                unmatched[region].append(name)

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

            if channel["event"]:
                stats["unmatched_events"] += 1
            else:
                stats["unmatched_regular"] += 1
                unmatched[region].append(name)

            continue

        channel_element = ET.SubElement(
            root,
            "channel",
            {"id": channel_id}
        )

        for display_name in sorted(
            channel["names"]
        ):

            display = ET.SubElement(
                channel_element,
                "display-name"
            )

            display.text = safe_text(display_name)

        all_programmes.extend(valid_programmes)

        stats["matched"] += 1
        stats[method] += 1

        regional_matches[region] += 1

        if channel["event"]:
            stats["matched_events"] += 1

        unique_epg_channels.add(
            (
                entry["id"].casefold(),
                entry["region"]
            )
        )

        if len(matched_samples[region]) < 3:

            matched_samples[region].append(
                (
                    name,
                    entry["id"],
                    method
                )
            )

    for programme in all_programmes:
        root.append(programme)

    # ------------------------------------------------------
    # REGIONAL REPORT
    # ------------------------------------------------------

    print("\n===== REGIONAL MATCHING RESULTS =====")

    for region, total in regional_totals.most_common():

        matched = regional_matches[region]

        rate = matched / total * 100

        print(
            f"{region.upper()}: "
            f"{matched}/{total} matched "
            f"({rate:.2f}%)"
        )

    # ------------------------------------------------------
    # MATCHED SAMPLES
    # ------------------------------------------------------

    print("\n===== MATCHED CHANNEL SAMPLES =====")

    for region, samples in sorted(
        matched_samples.items()
    ):

        print(f"\n[{region.upper()}]")

        for name, epg_id, method in samples:

            print(
                f"{safe_text(name)} -> "
                f"{safe_text(epg_id)} "
                f"({method})"
            )

    # ------------------------------------------------------
    # UNMATCHED REGULAR CHANNELS
    # ------------------------------------------------------

    print(
        "\n===== UNMATCHED REGULAR CHANNEL SAMPLES ====="
    )

    for region, samples in sorted(
        unmatched.items()
    ):

        print(
            f"\n[{region.upper()}] "
            f"{len(samples)} unmatched"
        )

        unique_names = list(
            dict.fromkeys(samples)
        )

        for name in unique_names[:5]:

            print(safe_text(name))

    # ------------------------------------------------------
    # FINAL STATISTICS
    # ------------------------------------------------------

    total = len(channels)
    matched = stats["matched"]

    rate = matched / total * 100 if total else 0

    total_events = sum(
        channel["event"]
        for channel in channels.values()
    )

    regular_total = total - total_events

    regular_matched = (
        matched - stats["matched_events"]
    )

    regular_rate = (
        regular_matched / regular_total * 100
        if regular_total else 0
    )

    print("\n========== MATCHING RESULTS ==========")

    print(f"Total channel IDs: {total}")
    print(f"Manual matches: {stats['manual']}")
    print(f"Exact ID matches: {stats['exact']}")

    print(
        f"Normalised ID matches: "
        f"{stats['normalised']}"
    )

    print(
        f"Channel name matches: {stats['name']}"
    )

    print(
        f"Fuzzy name matches: {stats['fuzzy']}"
    )

    print(f"Total matched channels: {matched}")

    print(
        f"Distinct EPG channel identities: "
        f"{len(unique_epg_channels)}"
    )

    print(f"Unmatched channels: {total - matched}")

    print(f"Total event feeds: {total_events}")

    print(
        f"Matched event feeds: "
        f"{stats['matched_events']}"
    )

    print(
        f"Unmatched event feeds: "
        f"{stats['unmatched_events']}"
    )

    print(
        f"Unmatched regular channels: "
        f"{stats['unmatched_regular']}"
    )

    print(f"Total programmes: {len(all_programmes)}")
    print(f"Match rate: {rate:.2f}%")
    print(f"Regular channel match rate: {regular_rate:.2f}%")

    print("======================================")

    return root


# ==========================================================
# QUALITY PROTECTION
# ==========================================================

def previous_channel_count():

    if not OUTPUT_FILE.exists():
        return 0

    with gzip.open(OUTPUT_FILE, "rb") as file:

        root = ET.parse(file).getroot()

    return len(root.findall("channel"))


def save_epg(root):

    new_count = len(root.findall("channel"))
    old_count = previous_channel_count()

    print("\n===== QUALITY CHECK =====")
    print(f"Previous EPG channels: {old_count}")
    print(f"New EPG channels: {new_count}")

    quality_ok = (
        new_count >= MIN_MATCHED_CHANNELS
        and new_count >= (
            old_count * MIN_PREVIOUS_COVERAGE
        )
    )

    xml_data = ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True
    )

    if M3U_URL.encode() in xml_data:
        raise RuntimeError("Privacy check failed.")

    if TEST_MODE:

        print("\nTEST MODE ENABLED.")

        print(
            f"Quality check: "
            f"{'PASSED' if quality_ok else 'FAILED'}"
        )

        print("Existing EPG preserved.")
        print("Test completed.")

        return

    if not quality_ok:

        raise RuntimeError(
            "Coverage quality check failed. "
            "Existing EPG preserved."
        )

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
    print("INTELLIGENT SPORTS EPG ENGINE V3.1")
    print("=" * 50)

    print(f"Test mode: {TEST_MODE}")

    print(
        f"Configured EPG sources: {len(EPG_URLS)}"
    )

    channels = read_playlist()

    if not channels:
        raise RuntimeError("No usable IPTV channels.")

    entries = load_epg_sources()

    root = generate_epg(
        channels,
        entries
    )

    save_epg(root)


if __name__ == "__main__":
    main()
