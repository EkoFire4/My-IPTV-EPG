
#!/usr/bin/env python3

# ==========================================================
# INTELLIGENT SPORTS EPG ENGINE
# Version 3.2 - Advanced Regional Matching
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
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit


# ==========================================================
# CONFIGURATION
# ==========================================================

VERSION = "3.2"

M3U_URL = os.environ.get("M3U_URL", "").strip()

OUTPUT_FILE = Path("epgs/light-epg.xml.gz")
MAPPING_FILE = Path("channel_mapping.json")

TEST_MODE = False

MIN_MATCHED_CHANNELS = 400
MIN_PREVIOUS_COVERAGE = 0.90

DOWNLOAD_TIMEOUT = 60

NOW = datetime.now(timezone.utc)
EARLIEST = NOW - timedelta(hours=12)

BASE = "https://epgshare01.online/epgshare01/"


# ==========================================================
# EPG SOURCES
# ==========================================================

KNOWN_SOURCES = [
    "UK1", "IE1", "US2", "US_LOCALS1",
    "CA2", "AU1", "NZ1", "DE1",
    "ES1", "FR1", "PT1", "IT1",
    "NL1", "PL1", "MY1", "SG1",
    "HK1", "IN1", "BEIN1",
    "DIRECTVSPORTS1", "SPORTKLUB1",
    "PEACOCK1", "AR1", "TR1",
    "MX1", "FI1", "BR1", "AT1",
    "SE1", "DK1", "NO1", "CH1",
    "ZA1", "NG1",
]

EXTRA_REGIONS = {
    "GR", "RO", "RS", "CZ", "HR",
    "BE", "PK", "HU", "ID", "PH",
    "AE", "SA", "QA", "EG", "TH",
    "JP", "KR", "CL", "CO", "PE",
}

EXTRA_SOURCE_NAMES = {
    "BEIN",
    "SPORTKLUB",
    "DIRECTVSPORTS",
    "DAZN",
}

PLUTO_URL = (
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
    "cz": ["cz", "cze", "czech republic"],
    "hu": ["hu", "hungary"],
    "hr": ["hr", "cro", "croatia"],
    "rs": ["rs", "srb", "serbia"],
    "ae": ["ae", "uae"],
    "sa": ["sa", "ksa", "saudi arabia"],
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
# GLOBAL ALIASES
# ==========================================================

GLOBAL_ALIASES = {
    "tntsportsone": "tntsports1",
    "tntsportstwo": "tntsports2",
    "tntsportsthree": "tntsports3",
    "tntsportsfour": "tntsports4",
    "tntsportsfive": "tntsports5",

    "eurosportone": "eurosport1",
    "eurosporttwo": "eurosport2",

    "premiersportsone": "premiersports1",
    "premiersportstwo": "premiersports2",

    "bbc1": "bbcone",
    "bbc2": "bbctwo",
    "bbc3": "bbcthree",
    "bbc4": "bbcfour",
    "itvone": "itv1",
}

for number in range(1, 11):

    GLOBAL_ALIASES[f"bein{number}"] = (
        f"beinsports{number}"
    )

    GLOBAL_ALIASES[f"tntsport{number}"] = (
        f"tntsports{number}"
    )


# ==========================================================
# REGION-SPECIFIC ALIASES
# ==========================================================

REGIONAL_ALIASES = {

    "uk": {
        "skysportsmain": "skysportsmainevent",
        "skysportspremier": "skysportspremierleague",
        "skysportsepl": "skysportspremierleague",
        "skysportsf1": "skysportsformula1",
        "skysportsformulaone": "skysportsformula1",
    },

    "us": {
        "fs1": "foxsports1",
        "fs2": "foxsports2",
        "foxsportsone": "foxsports1",
        "foxsportstwo": "foxsports2",
        "espnu": "espnu",
        "espnone": "espn",
        "espntwo": "espn2",
        "espn1": "espn",
    },

    "ar": {
        "espnsports": "espn",
        "espn1": "espn",
        "foxsportsone": "foxsports1",
        "foxsportstwo": "foxsports2",
        "foxsportsthree": "foxsports3",
        "directvsports": "dsports",
        "directvsports2": "dsports2",
        "directvsportsplus": "dsportsplus",
    },

    "au": {
        "foxsports501": "foxsports501",
        "foxsports502": "foxsports502",
        "foxsports503": "foxsports503",
        "foxsports504": "foxsports504",
        "foxsports505": "foxsports505",
        "foxsports506": "foxsports506",
        "foxsports507": "foxsports507",
    },

    "ae": {
        "dubaisport1": "dubaisports1",
        "dubaisport2": "dubaisports2",
        "dubaisport3": "dubaisports3",
        "adsports1": "abudhabisports1",
        "adsports2": "abudhabisports2",
        "adsportpremium1": "abudhabisportspremium1",
        "adsportpremium2": "abudhabisportspremium2",
        "adsportspremium1": "abudhabisportspremium1",
        "adsportspremium2": "abudhabisportspremium2",
    },

    "br": {
        "bandsport": "bandsports",
    },

    "ca": {
        "sportsnetont": "sportsnetontario",
        "sportsnetpac": "sportsnetpacific",
    },

    "pt": {
        "sporttvone": "sporttv1",
        "sporttvtwo": "sporttv2",
    },
}

for region in ("de", "at"):

    REGIONAL_ALIASES.setdefault(region, {})

    for number in range(1, 11):

        REGIONAL_ALIASES[region][
            f"skysports{number}"
        ] = f"skysport{number}"


# ==========================================================
# DOWNLOAD
# ==========================================================

def download(url):

    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("Unsupported URL scheme")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Mozilla/5.0 EPG/{VERSION}",
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
# AUTOMATIC SOURCE DISCOVERY
# ==========================================================

def discover_sources():

    sources = set(KNOWN_SOURCES)

    print("\nDiscovering additional EPG sources...")

    try:

        page = download(BASE).decode(
            "utf-8",
            errors="replace"
        )

        available = set(
            re.findall(
                r"epg_ripper_([A-Z0-9_]+)\.xml\.gz",
                page
            )
        )

        for name in available:

            match = re.match(
                r"^([A-Z]{2})(?:\d|_)",
                name
            )

            if match:

                country = match.group(1)

                if country in EXTRA_REGIONS:
                    sources.add(name)

            if any(
                name.startswith(prefix)
                for prefix in EXTRA_SOURCE_NAMES
            ):

                sources.add(name)

        # Exclude generic placeholder schedules.
        sources.discard("DUMMY_CHANNELS")

        print(
            f"Discovered source files: {len(available)}"
        )

    except Exception as error:

        print(
            "Source discovery unavailable: "
            f"{type(error).__name__}"
        )

        print("Using known working sources.")

    urls = [
        BASE + f"epg_ripper_{name}.xml.gz"
        for name in sorted(sources)
    ]

    urls.append(PLUTO_URL)

    print(f"Configured EPG sources: {len(urls)}")

    return urls


# ==========================================================
# TEXT NORMALISATION
# ==========================================================

def clean_text(value):

    value = html.unescape(str(value or ""))

    value = unicodedata.normalize("NFKD", value)

    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    value = value.casefold().strip()

    return re.sub(r"[┃│┆¦｜]", "|", value)


def safe_text(value):

    return re.sub(
        r"https?://[^\s]+",
        "[URL REMOVED]",
        str(value or "")
    )


def region_candidates(value):

    value = clean_text(value)

    found = set()

    patterns = [
        rf"[\[(]\s*({REGION_PATTERN})\s*[\])]",

        rf"^\s*({REGION_PATTERN})"
        rf"\s*[:|._\-]+\s*",

        rf"[._|]\s*({REGION_PATTERN})"
        rf"(?:\d+)?$",
    ]

    for pattern in patterns:

        for match in re.finditer(pattern, value):

            found.add(
                REGIONS[match.group(1)]
            )

    return found


def get_region(value):

    regions = region_candidates(value)

    if len(regions) == 1:
        return next(iter(regions))

    return ""


def normalise_id(value):

    return re.sub(
        r"[^a-z0-9]",
        "",
        clean_text(value)
    )


def normalise_name(value, region=""):

    value = clean_text(value).strip(" |")

    # Remove known category prefixes.
    value = re.sub(
        r"^(?:ucl|uel|uecl|epl|uefa|fifa|"
        r"sports|sport|football|soccer|f1 tv)"
        r"\s*\|\s*",
        "",
        value
    )

    # Remove explicit country prefix.
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

    # Remove EPG country suffixes.
    # Example: ESPN.HD.us2
    value = re.sub(
        rf"[._|]\s*(?:{REGION_PATTERN})"
        rf"(?:\d+)?$",
        "",
        value
    )

    # Remove video resolution and codec labels.
    value = re.sub(
        r"\b(?:uhd|fhd|hd|sd|4k|8k|"
        r"1080p|720p|2160p|hevc|"
        r"h265|h264|50fps|60fps)\b",
        "",
        value
    )

    # Preserve timeshift and plus channels.
    value = value.replace("+", " plus ")

    value = re.sub(
        r"[^a-z0-9]",
        "",
        value
    )

    value = GLOBAL_ALIASES.get(
        value,
        value
    )

    value = REGIONAL_ALIASES.get(
        region,
        {}
    ).get(value, value)

    return value


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

    name = clean_text(name)

    # Do not classify Sky Sports Main Event
    # as a temporary event feed.
    if re.search(r"main[\s._-]*event", name):
        return False

    patterns = [
        r"\bevent[\s._-]*\d+",
        r"\bppv\b",
        r"\bmatch[\s._-]*\d+",
        r"\bfeed[\s._-]*\d+",
        r"\bfixture[\s._-]*\d+",
        r"\bred[\s._-]*button\b",
        r"\bf1[\s._-]*tv[\s._-]*pro\b",
        r"\bonboard\b",
        r"\bdriver[\s._-]*cam\b",
        r"\bparamount\s*\+\s*\d+",
    ]

    return any(
        re.search(pattern, name)
        for pattern in patterns
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

    if programme.get("stop") and stop is None:
        return False

    if stop is not None:

        if stop <= start:
            return False

        return stop >= EARLIEST

    return start >= EARLIEST


def programme_is_current_or_future(programme):

    start = parse_timestamp(
        programme.get("start")
    )

    stop = parse_timestamp(
        programme.get("stop")
    )

    if start is None:
        return False

    return (
        stop > NOW
        if stop is not None
        else start >= NOW
    )


# ==========================================================
# READ PLAYLIST
# ==========================================================

def read_playlist():

    if not M3U_URL:

        raise RuntimeError(
            "M3U_URL GitHub secret is missing."
        )

    print("\nDownloading M3U playlist...")

    content = download(M3U_URL).decode(
        "utf-8-sig",
        errors="replace"
    )

    if not content.lstrip().startswith("#EXTM3U"):
        raise RuntimeError("Invalid M3U playlist.")

    channels = {}
    conflicts = set()
    region_conflicts = []

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

        if not channel_id or "://" in channel_id:
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

        detected_regions = set()

        for name in names:

            detected_regions.update(
                region_candidates(name)
            )

        detected_regions.update(
            region_candidates(channel_id)
        )

        if len(detected_regions) > 1:

            region_conflicts.append(
                sorted(names)[0]
            )

            region = ""
            ambiguous_region = True

        elif detected_regions:

            region = next(
                iter(detected_regions)
            )

            ambiguous_region = False

        else:

            region = get_region(group)
            ambiguous_region = False

        keys = {
            normalise_name(name, region)
            for name in names
            if normalise_name(name, region)
        }

        if not keys:
            continue

        event = any(
            is_event_channel(name)
            for name in names
        )

        if channel_id in channels:

            existing = channels[channel_id]

            region_mismatch = (
                existing["region"]
                and region
                and existing["region"] != region
            )

            if (
                region_mismatch
                or not keys.intersection(
                    existing["keys"]
                )
            ):

                conflicts.add(channel_id)
                channels.pop(channel_id, None)
                continue

            existing["names"].update(names)
            existing["keys"].update(keys)

            existing["event"] |= event

            existing["ambiguous_region"] |= (
                ambiguous_region
            )

        else:

            channels[channel_id] = {
                "id": channel_id,
                "names": names,
                "keys": keys,
                "region": region,
                "event": event,
                "ambiguous_region":
                    ambiguous_region,
            }

    print(
        f"Found {len(channels)} usable channel IDs."
    )

    print(
        f"Conflicting IDs skipped: {len(conflicts)}"
    )

    print(
        f"Conflicting region labels: "
        f"{len(region_conflicts)}"
    )

    print(
        f"Dedicated event feeds: "
        f"{sum(c['event'] for c in channels.values())}"
    )

    print("\n===== REGION CONFLICT SAMPLES =====")

    for name in region_conflicts[:15]:
        print(safe_text(name))

    print("\n===== PLAYLIST REGIONS =====")

    regions = Counter(
        c["region"] or "unknown"
        for c in channels.values()
    )

    for region, count in regions.most_common():
        print(f"{region}: {count}")

    return channels


# ==========================================================
# LOAD EPG SOURCES
# ==========================================================

def load_epg_sources(urls):

    entries = []

    successful = 0
    failed = []
    expired = 0

    for index, url in enumerate(urls, 1):

        filename = urlsplit(url).path.split("/")[-1]

        print(
            f"\nSource {index}/{len(urls)}: "
            f"{filename}"
        )

        try:

            root = ET.fromstring(
                download(url)
            )

            if root.tag != "tv":
                raise ValueError("Invalid XMLTV")

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

                if not programme.findtext("title"):
                    continue

                programmes[channel_id].append(
                    programme
                )

            count = 0
            default_region = source_region(url)

            for channel in root.findall("channel"):

                channel_id = channel.get("id", "")

                schedule = programmes.get(
                    channel_id,
                    []
                )

                if not schedule:
                    continue

                if not any(
                    programme_is_current_or_future(p)
                    for p in schedule
                ):

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

                detected = region_candidates(
                    channel_id
                )

                if not detected:

                    for name in names:

                        detected.update(
                            region_candidates(name)
                        )

                if len(detected) > 1:
                    continue

                region = (
                    next(iter(detected))
                    if detected
                    else default_region
                )

                keys = {
                    normalise_name(name, region)
                    for name in names
                    if normalise_name(name, region)
                }

                if not keys:
                    continue

                entries.append({
                    "id": channel_id,
                    "names": names,
                    "keys": keys,
                    "region": region,
                    "source": filename,
                    "programmes": schedule,
                    "event": any(
                        is_event_channel(name)
                        for name in names
                    ),
                })

                count += 1

            successful += 1

            print(f"Loaded {count} usable EPG entries.")

        except Exception as error:

            failed.append(filename)

            print(
                "Source unavailable: "
                f"{type(error).__name__}"
            )

    print("\n===== SOURCE RESULTS =====")

    print(f"Successful sources: {successful}")
    print(f"Failed sources: {len(failed)}")
    print(f"Total EPG entries: {len(entries)}")

    print(
        f"Expired/invalid programmes removed: "
        f"{expired}"
    )

    if failed:

        print("\nUnavailable sources:")

        for filename in failed:
            print(filename)

    if not entries:
        raise RuntimeError("No usable EPG data.")

    return entries


# ==========================================================
# MATCHING INDEXES
# ==========================================================

def build_indexes(entries):

    names = defaultdict(list)
    exact_ids = defaultdict(list)
    normalised_ids = defaultdict(list)

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

    return {
        "names": names,
        "exact_ids": exact_ids,
        "normalised_ids": normalised_ids,
    }


# ==========================================================
# MANUAL MAPPINGS
# ==========================================================

def load_mappings():

    if not MAPPING_FILE.exists():

        print("No manual mapping file found.")
        return {}

    try:

        data = json.loads(
            MAPPING_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return {}

        print(f"Loaded {len(data)} manual mappings.")

        return data

    except Exception:

        print("Could not read manual mappings.")
        return {}


# ==========================================================
# DUPLICATE SOURCE RESOLUTION
# ==========================================================

def schedule_signature(entry):

    signature = set()

    for programme in entry["programmes"]:

        start = parse_timestamp(
            programme.get("start")
        )

        title = clean_text(
            programme.findtext("title", "")
        )

        if start and title:

            signature.add(
                (start, title)
            )

    return signature


def schedules_agree(first, second):

    a = schedule_signature(first)
    b = schedule_signature(second)

    if not a or not b:
        return False

    a_times = {start for start, title in a}
    b_times = {start for start, title in b}

    common_times = a_times & b_times

    if len(common_times) < 3:
        return False

    agreed = {
        start
        for start, title in a & b
    }

    return len(agreed) / len(common_times) >= 0.90


def choose_match(candidates, channel):

    region = channel["region"]

    unique = {}

    for entry in candidates:

        if region and entry["region"] != region:
            continue

        if channel["event"] != entry["event"]:
            continue

        identity = (
            entry["source"],
            entry["id"],
        )

        unique[identity] = entry

    candidates = list(unique.values())

    if not candidates:
        return None, "no_compatible_candidate"

    if len(candidates) == 1:
        return candidates[0], "single"

    regions = {
        entry["region"]
        for entry in candidates
    }

    if len(regions) != 1:
        return None, "region_ambiguity"

    ranked = sorted(
        candidates,
        key=lambda entry: (
            len(entry["programmes"]),
            entry["source"],
            entry["id"]
        ),
        reverse=True
    )

    best = ranked[0]

    # Accept duplicate schedules only when
    # their programme listings substantially agree.
    if all(
        schedules_agree(best, other)
        for other in ranked[1:]
    ):

        return best, "duplicate_resolved"

    return None, "schedule_ambiguity"


# ==========================================================
# CHANNEL MATCHING
# ==========================================================

def match_channel(channel, indexes, mappings):

    channel_id = channel["id"]
    region = channel["region"]

    if channel["ambiguous_region"]:
        return None, "region_conflict", []

    # Manually verified mapping.
    mapping = mappings.get(channel_id)

    if isinstance(mapping, dict):

        expected_name = mapping.get("name", "")
        epg_id = mapping.get("epg_id", "")

        if (
            expected_name
            and epg_id
            and normalise_name(
                expected_name,
                region
            ) in channel["keys"]
        ):

            candidates = indexes[
                "exact_ids"
            ].get(epg_id.casefold(), [])

            result, reason = choose_match(
                candidates,
                channel
            )

            if result:
                return result, "manual", []

    # Exact non-numeric ID.
    if not channel_id.isdigit():

        candidates = indexes[
            "exact_ids"
        ].get(channel_id.casefold(), [])

        result, reason = choose_match(
            candidates,
            channel
        )

        if result:
            return result, "exact", []

        candidates = indexes[
            "normalised_ids"
        ].get(
            normalise_id(channel_id),
            []
        )

        result, reason = choose_match(
            candidates,
            channel
        )

        if result:
            return result, "normalised", []

    # Exact normalised name.
    candidates = []

    for key in channel["keys"]:

        candidates.extend(
            indexes["names"].get(key, [])
        )

    result, reason = choose_match(
        candidates,
        channel
    )

    if result:

        method = (
            "duplicate_resolved"
            if reason == "duplicate_resolved"
            else "name"
        )

        return result, method, []

    candidate_ids = sorted({
        f"{entry['id']} [{entry['region'] or '?'}]"
        for entry in candidates
    })

    # No fuzzy guessing in this version.
    return None, reason, candidate_ids[:5]


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

    if not start:
        return None

    if not programme_is_fresh(programme):
        return None

    result = ET.Element(
        "programme",
        {
            "start": start.strftime(
                "%Y%m%d%H%M%S +0000"
            ),
            "channel": channel_id,
        }
    )

    if stop:

        result.set(
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
            result,
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

    if not result.findtext("title"):
        return None

    return result


# ==========================================================
# GENERATE XMLTV
# ==========================================================

def generate_epg(channels, entries):

    indexes = build_indexes(entries)
    mappings = load_mappings()

    root = ET.Element(
        "tv",
        {
            "generator-info-name":
                f"Intelligent Sports EPG V{VERSION}"
        }
    )

    stats = Counter()
    regional_totals = Counter()
    regional_matches = Counter()

    unmatched = defaultdict(list)
    matched_samples = defaultdict(list)
    rejected = defaultdict(list)

    all_programmes = []
    distinct_epg = set()

    print("\nMatching IPTV channels...")

    for channel_id, channel in channels.items():

        region = channel["region"] or "unknown"
        name = sorted(channel["names"])[0]

        regional_totals[region] += 1

        entry, method, candidates = match_channel(
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

            if candidates:

                rejected[region].append(
                    (name, method, candidates)
                )

            continue

        valid_programmes = []
        seen = set()

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

        element = ET.SubElement(
            root,
            "channel",
            {"id": channel_id}
        )

        for display_name in sorted(
            channel["names"]
        ):

            node = ET.SubElement(
                element,
                "display-name"
            )

            node.text = safe_text(display_name)

        all_programmes.extend(valid_programmes)

        stats["matched"] += 1
        stats[method] += 1

        regional_matches[region] += 1

        if channel["event"]:
            stats["matched_events"] += 1

        distinct_epg.add(
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
    # REGIONAL RESULTS
    # ------------------------------------------------------

    print("\n===== REGIONAL MATCHING RESULTS =====")

    for region, total in regional_totals.most_common():

        matched = regional_matches[region]

        print(
            f"{region.upper()}: "
            f"{matched}/{total} matched "
            f"({matched / total * 100:.2f}%)"
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
    # UNMATCHED SAMPLES
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

        # Avoid reporting five resolution variants
        # of the same station.
        displayed = set()

        for name in unique_names:

            key = normalise_name(
                name,
                region
            )

            if key in displayed:
                continue

            displayed.add(key)

            print(safe_text(name))

            if len(displayed) >= 10:
                break

    # ------------------------------------------------------
    # REJECTED CANDIDATES
    # ------------------------------------------------------

    print("\n===== REJECTED MATCH CANDIDATES =====")

    for region, samples in sorted(
        rejected.items()
    ):

        print(f"\n[{region.upper()}]")

        for name, reason, candidates in samples[:5]:

            print(
                f"{safe_text(name)} | {reason}"
            )

            for candidate in candidates:

                print(
                    f"  Candidate: "
                    f"{safe_text(candidate)}"
                )

    # ------------------------------------------------------
    # FINAL STATISTICS
    # ------------------------------------------------------

    total = len(channels)
    matched = stats["matched"]

    events = sum(
        c["event"]
        for c in channels.values()
    )

    regular_total = total - events

    regular_matched = (
        matched - stats["matched_events"]
    )

    rate = (
        matched / total * 100
        if total else 0
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
        f"Channel name matches: "
        f"{stats['name']}"
    )

    print(
        f"Duplicate source matches resolved: "
        f"{stats['duplicate_resolved']}"
    )

    print(f"Total matched channels: {matched}")

    print(
        f"Distinct EPG identities: "
        f"{len(distinct_epg)}"
    )

    print(f"Unmatched channels: {total - matched}")
    print(f"Total event feeds: {events}")

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

    print(
        f"Regular channel match rate: "
        f"{regular_rate:.2f}%"
    )

    print("======================================")

    return root


# ==========================================================
# PUBLICATION QUALITY PROTECTION
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

    programme_count = len(
        root.findall("programme")
    )

    quality_ok = (
        new_count >= MIN_MATCHED_CHANNELS
        and new_count >= (
            old_count * MIN_PREVIOUS_COVERAGE
        )
        and programme_count > 0
    )

    print("\n===== QUALITY CHECK =====")

    print(f"Previous EPG channels: {old_count}")
    print(f"New EPG channels: {new_count}")
    print(f"Programme listings: {programme_count}")

    print(
        f"Quality check: "
        f"{'PASSED' if quality_ok else 'FAILED'}"
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
        print("Existing EPG preserved.")
        print("Test completed.")

        return

    if not quality_ok:

        raise RuntimeError(
            "Quality check failed. "
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
    print(f"INTELLIGENT SPORTS EPG ENGINE V{VERSION}")
    print("=" * 50)

    print(f"Test mode: {TEST_MODE}")

    channels = read_playlist()

    if not channels:
        raise RuntimeError("No usable IPTV channels.")

    urls = discover_sources()

    entries = load_epg_sources(urls)

    root = generate_epg(
        channels,
        entries
    )

    save_epg(root)


if __name__ == "__main__":
    main()
