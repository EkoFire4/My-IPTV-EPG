
import os
import re
import gzip
import copy
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlsplit


# ==========================================
# EPG SOURCES
# ==========================================

URLS = [
    "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_DUMMY_CHANNELS.xml.gz",
    "https://raw.githubusercontent.com/matthuisman/i.mjh.nz/refs/heads/master/PlutoTV/all.xml",
]

OUTPUT_FILE = Path("epgs/light-epg.xml.gz")

FUZZY_THRESHOLD = 0.94
FUZZY_MARGIN = 0.05
ENABLE_FUZZY = True

REGIONS = {
    "uk": "uk",
    "gb": "uk",
    "united kingdom": "uk",
    "us": "us",
    "usa": "us",
    "united states": "us",
    "ca": "ca",
    "canada": "ca",
    "ng": "ng",
    "nigeria": "ng",
    "ie": "ie",
    "ireland": "ie",
    "au": "au",
    "australia": "au",
}

REGION_PATTERN = "|".join(
    sorted(REGIONS, key=len, reverse=True)
)


# ==========================================
# DOWNLOAD FILES
# ==========================================

def download(url):
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("Unsupported URL")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(
        request, timeout=120
    ) as response:
        data = response.read()

    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)

    return data


# ==========================================
# CHANNEL NAME NORMALISATION
# ==========================================

def clean_text(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )
    return value.casefold().strip()


def normalise_id(value):
    return re.sub(
        r"[^a-z0-9]", "", clean_text(value)
    )


def get_region(value):
    value = clean_text(value)

    prefix = re.match(
        rf"^[\[\(\s]*(?:({REGION_PATTERN}))"
        rf"(?:[\]\):|._\-\s]+)",
        value
    )

    if prefix:
        return REGIONS[prefix.group(1)]

    suffix = re.search(
        rf"(?:[\s._|(\-]+)({REGION_PATTERN})[\])]*$",
        value
    )

    if suffix:
        return REGIONS[suffix.group(1)]

    return ""


def normalise_name(value):
    value = clean_text(value)

    # Preserve +1 timeshift channels.
    value = re.sub(
        r"\+\s*(\d+)", r" plus\1 ", value
    )

    # Remove country prefixes and suffixes.
    value = re.sub(
        rf"^[\[\(\s]*(?:{REGION_PATTERN})"
        rf"[\]\):|._\-\s]+",
        "", value
    )

    value = re.sub(
        rf"[\s._|(\-]+(?:{REGION_PATTERN})[\])]*$",
        "", value
    )

    # Remove video quality labels.
    value = re.sub(
        r"\b(?:uhd|fhd|hd|sd|4k|8k|"
        r"1080p|720p|2160p|hevc|h265|h264)\b",
        "", value
    )

    return re.sub(r"[^a-z0-9]", "", value)


def compatible_regions(first, second):
    return not first or not second or first == second


def source_region(url):
    value = url.lower()

    if "ripper_uk" in value:
        return "uk"
    if "ripper_us" in value:
        return "us"
    if "ripper_ca" in value:
        return "ca"
    if "ripper_ng" in value:
        return "ng"

    return ""


# ==========================================
# READ PRIVATE IPTV PLAYLIST
# ==========================================

def read_playlist():
    m3u_url = os.environ.get("M3U_URL", "").strip()

    if not m3u_url:
        raise SystemExit("ERROR: M3U_URL secret is missing.")

    print("Downloading private M3U playlist...")

    try:
        playlist = download(m3u_url).decode(
            "utf-8-sig", errors="replace"
        )
    except Exception:
        raise SystemExit(
            "ERROR: Unable to download playlist."
        ) from None

    channels = {}
    conflicts = set()
    provider_urls = []

    for line in playlist.splitlines():
        line = line.strip()

        if line.startswith("#EXTM3U"):
            matches = re.findall(
                r'(?:x-tvg-url|url-tvg|tvg-url)'
                r'\s*=\s*"([^"]+)"',
                line,
                re.IGNORECASE
            )

            for match in matches:
                for url in match.split(","):
                    url = urljoin(m3u_url, url.strip())

                    if urlsplit(url).scheme in ("http", "https"):
                        provider_urls.append(url)

        if not line.startswith("#EXTINF"):
            continue

        attributes = {
            key.lower(): value
            for key, value in re.findall(
                r'([\w-]+)\s*=\s*"([^"]*)"',
                line
            )
        }

        channel_id = attributes.get("tvg-id", "").strip()
        tvg_name = attributes.get("tvg-name", "").strip()
        display_name = line.rsplit(",", 1)[-1].strip()

        if not channel_id:
            continue

        # Never publish URL-like channel IDs.
        if "://" in channel_id or "?" in channel_id:
            continue

        names = {
            name for name in (tvg_name, display_name)
            if name
        }

        region = (
            get_region(channel_id)
            or get_region(tvg_name)
            or get_region(display_name)
        )

        if channel_id in channels:
            previous = channels[channel_id]

            old_names = {
                normalise_name(n)
                for n in previous["names"]
            }

            new_names = {
                normalise_name(n) for n in names
            }

            if (
                old_names and new_names
                and not old_names.intersection(new_names)
            ):
                conflicts.add(channel_id)

            if not compatible_regions(
                previous["region"], region
            ):
                conflicts.add(channel_id)

            previous["names"].update(names)
            continue

        channels[channel_id] = {
            "id": channel_id,
            "names": names,
            "region": region,
        }

    for channel_id in conflicts:
        channels.pop(channel_id, None)

    if not channels:
        raise SystemExit(
            "ERROR: No usable channel IDs found."
        )

    print(f"Found {len(channels)} usable channel IDs.")
    print(f"Conflicting IDs skipped: {len(conflicts)}")
    print(f"Provider EPG sources detected: {len(provider_urls)}")

    return channels, list(dict.fromkeys(provider_urls))


# ==========================================
# DOWNLOAD AND INDEX EPG SOURCES
# ==========================================

def load_epg_sources(provider_urls):
    sources = list(dict.fromkeys(provider_urls + URLS))
    entries = []

    for index, url in enumerate(sources, start=1):
        print(f"Processing EPG source {index}/{len(sources)}...")

        try:
            root = ET.fromstring(download(url))

            if root.tag != "tv":
                raise ValueError("Invalid XMLTV document")

            programmes = defaultdict(list)

            for programme in root.findall("programme"):
                channel_id = programme.get("channel")

                if channel_id and programme.get("start"):
                    programmes[channel_id].append(programme)

            added = 0

            for channel in root.findall("channel"):
                channel_id = channel.get("id", "")

                if not channel_id or not programmes[channel_id]:
                    continue

                names = {
                    node.text.strip()
                    for node in channel.findall("display-name")
                    if node.text and node.text.strip()
                }

                region = get_region(channel_id)

                if not region:
                    for name in sorted(names):
                        region = get_region(name)
                        if region:
                            break

                region = region or source_region(url)

                entries.append({
                    "id": channel_id,
                    "names": names,
                    "region": region,
                    "provider": url in provider_urls,
                    "programmes": programmes[channel_id],
                })

                added += 1

            print(f"Loaded {added} channels with programmes.")

        except Exception:
            print(
                f"WARNING: EPG source {index} failed. "
                "Continuing..."
            )

    if not entries:
        raise SystemExit("ERROR: No usable EPG sources.")

    return entries


# ==========================================
# BUILD SEARCH INDEXES
# ==========================================

def build_indexes(entries):
    exact = defaultdict(list)
    normalised = defaultdict(list)
    names = defaultdict(list)
    regional_names = defaultdict(set)

    for index, entry in enumerate(entries):
        exact[entry["id"]].append(index)

        key = normalise_id(entry["id"])

        if key and not key.isdigit():
            normalised[key].append(index)

        for name in entry["names"]:
            key = normalise_name(name)

            if not key:
                continue

            names[key].append(index)

            if entry["region"]:
                regional_names[entry["region"]].add(key)

    return exact, normalised, names, regional_names


# ==========================================
# SELECT SAFE MATCHES
# ==========================================

def choose_match(candidates, channel, entries):
    candidates = [
        i for i in set(candidates)
        if compatible_regions(
            channel["region"], entries[i]["region"]
        )
    ]

    if not candidates:
        return None

    if channel["region"]:
        same_region = [
            i for i in candidates
            if entries[i]["region"] == channel["region"]
        ]

        if same_region:
            candidates = same_region

    provider = [
        i for i in candidates
        if entries[i]["provider"]
    ]

    if provider:
        candidates = provider

    identities = {
        (
            entries[i]["id"].casefold(),
            entries[i]["region"]
        )
        for i in candidates
    }

    # Skip ambiguous matches rather than assign
    # an incorrect television schedule.
    if len(identities) != 1:
        return None

    return max(
        candidates,
        key=lambda i: len(entries[i]["programmes"])
    )


def match_channel(channel, entries, indexes):
    exact, normalised, names, regional_names = indexes

    channel_id = channel["id"]

    # Stage 1: Exact ID.
    candidates = exact.get(channel_id, [])

    # Numeric IDs are only trusted from provider EPGs.
    if channel_id.isdigit():
        candidates = [
            i for i in candidates
            if entries[i]["provider"]
        ]

    match = choose_match(candidates, channel, entries)

    if match is not None:
        return match, "Exact ID"

    # Stage 2: Normalised ID.
    match = choose_match(
        normalised.get(normalise_id(channel_id), []),
        channel,
        entries
    )

    if match is not None:
        return match, "Normalised ID"

    # Stage 3: Normalised channel name.
    channel_names = {
        normalise_name(name)
        for name in channel["names"]
        if normalise_name(name)
    }

    candidates = set()

    for name in channel_names:
        candidates.update(names.get(name, []))

    match = choose_match(candidates, channel, entries)

    if match is not None:
        return match, "Channel name"

    # Stage 4: Conservative fuzzy matching.
    # Only compare channels within a known region.
    if not ENABLE_FUZZY or not channel["region"]:
        return None, None

    scores = {}

    for name in channel_names:
        if len(name) < 6:
            continue

        for candidate in regional_names[channel["region"]]:
            if abs(len(name) - len(candidate)) > 3:
                continue

            # Do not confuse channel numbers or +1 variants.
            if re.findall(r"\d+", name) != re.findall(
                r"\d+", candidate
            ):
                continue

            if ("plus" in name) != ("plus" in candidate):
                continue

            score = SequenceMatcher(
                None, name, candidate
            ).ratio()

            scores[candidate] = max(
                scores.get(candidate, 0), score
            )

    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )

    if not ranked or ranked[0][1] < FUZZY_THRESHOLD:
        return None, None

    if (
        len(ranked) > 1
        and ranked[0][1] - ranked[1][1] < FUZZY_MARGIN
    ):
        return None, None

    candidates = [
        i for i in names[ranked[0][0]]
        if entries[i]["region"] == channel["region"]
    ]

    match = choose_match(candidates, channel, entries)

    if match is not None:
        return match, "Fuzzy name"

    return None, None


# ==========================================
# PRIVACY PROTECTION
# ==========================================

def safe_text(value):
    if not value:
        return ""

    # Remove embedded web links from published text.
    return re.sub(
        r'https?://[^\s<>"\']+',
        "[link removed]",
        value,
        flags=re.IGNORECASE
    )


def clean_programme(programme, channel_id):
    result = ET.Element("programme")

    for attribute in ("start", "stop"):
        value = programme.get(attribute)

        if value and re.fullmatch(
            r"\d{8,14}(?:\s[+-]\d{4})?", value
        ):
            result.set(attribute, value)

    if not result.get("start"):
        return None

    result.set("channel", channel_id)

    # Publish only standard programme metadata.
    allowed = {
        "title", "sub-title", "desc", "category",
        "date", "episode-num", "language",
        "country", "length"
    }

    for child in programme:
        if child.tag not in allowed:
            continue

        node = ET.SubElement(result, child.tag)
        node.text = safe_text(child.text)

        for attribute in ("lang", "system", "units"):
            value = child.get(attribute)

            if value and re.fullmatch(
                r"[\w.\-]+", value
            ):
                node.set(attribute, value)

    return result


# ==========================================
# GENERATE MATCHED EPG
# ==========================================

def generate_epg(channels, entries):
    indexes = build_indexes(entries)

    root = ET.Element(
        "tv",
        {"generator-info-name": "Smart EPG Updater"}
    )

    stats = defaultdict(int)
    programme_count = 0
    output_programmes = []

    for channel_id, channel in channels.items():
        match, method = match_channel(
            channel, entries, indexes
        )

        if match is None:
            stats["Unmatched"] += 1
            continue

        entry = entries[match]
        programmes = []
        seen = set()

        for programme in entry["programmes"]:
            key = (
                programme.get("start"),
                programme.get("stop")
            )

            if key in seen:
                continue

            cleaned = clean_programme(
                programme, channel_id
            )

            if cleaned is not None:
                programmes.append(cleaned)
                seen.add(key)

        if not programmes:
            stats["Unmatched"] += 1
            continue

        # Use the ORIGINAL IPTV provider channel ID.
        output_channel = ET.SubElement(
            root, "channel", {"id": channel_id}
        )

        display_name = ET.SubElement(
            output_channel, "display-name"
        )

        display_name.text = safe_text(
            sorted(entry["names"])[0]
            if entry["names"]
            else channel_id
        )

        output_programmes.extend(programmes)

        programme_count += len(programmes)
        stats[method] += 1

    for programme in output_programmes:
        root.append(programme)

    matched = len(channels) - stats["Unmatched"]

    print("\n========== MATCHING RESULTS ==========")
    print(f"Total channel IDs: {len(channels)}")
    print(f"Exact ID matches: {stats['Exact ID']}")
    print(f"Normalised ID matches: {stats['Normalised ID']}")
    print(f"Channel name matches: {stats['Channel name']}")
    print(f"Fuzzy name matches: {stats['Fuzzy name']}")
    print(f"Total matched channels: {matched}")
    print(f"Unmatched channels: {stats['Unmatched']}")
    print(f"Total programmes: {programme_count}")
    print(f"Match rate: {matched / len(channels) * 100:.2f}%")
    print("======================================")

    if not matched or not programme_count:
        raise SystemExit(
            "ERROR: No usable matches. "
            "Existing EPG has not been replaced."
        )

    return root


# ==========================================
# SAVE COMPRESSED EPG
# ==========================================

def save_epg(root):
    OUTPUT_FILE.parent.mkdir(
        parents=True, exist_ok=True
    )

    xml_data = ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True
    )

    private_url = os.environ.get("M3U_URL", "").strip()

    if private_url and private_url.encode() in xml_data:
        raise SystemExit(
            "ERROR: Private URL detected in output."
        )

    temporary = OUTPUT_FILE.with_suffix(".gz.tmp")

    temporary.write_bytes(
        gzip.compress(xml_data, mtime=0)
    )

    temporary.replace(OUTPUT_FILE)

    size = OUTPUT_FILE.stat().st_size / (1024 * 1024)

    print("\nEPG generated successfully!")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Compressed size: {size:.2f} MB")


# ==========================================
# RUN
# ==========================================

if __name__ == "__main__":
    channels, provider_urls = read_playlist()
    entries = load_epg_sources(provider_urls)
    root = generate_epg(channels, entries)
    save_epg(root)
