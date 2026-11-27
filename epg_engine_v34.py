
#!/usr/bin/env python3

# ==========================================================
# ADVANCED SPORTS EPG MATCHING ENGINE
# VERSION 3.4
# DEVELOPMENT ONLY
# ==========================================================

import re
import json
import csv
from pathlib import Path
from collections import Counter

import epg_engine_v33 as v33

engine = v33.engine

# ==========================================================
# CONFIGURATION
# ==========================================================

engine.VERSION = "3.4"
engine.TEST_MODE = True

engine.MIN_MATCHED_CHANNELS = 596
engine.MIN_PREVIOUS_COVERAGE = 0.90

engine.OUTPUT_FILE = Path(
    "epgs/development-v34.xml.gz"
)

REPORT_DIR = Path("reports")

BASELINE_FILE = Path(
    "v33-diagnostics.json"
)

BASELINE_CHANNELS = 596

REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

diagnostics = Counter()
records = {}
source_corrections = []

# Preserve working V3.3 functions.

previous_normalise = engine.normalise_name
previous_read_playlist = engine.read_playlist
previous_load_sources = engine.load_epg_sources
previous_match = engine.match_channel

# Use the original V3.2 save function.
# Avoid generating an additional V3.3 report.

original_save = v33.original_save_epg


# ==========================================================
# EXPANDED REGIONAL ALIASES
# ==========================================================

ADDITIONAL_ALIASES = {

    "uk": {
        "skysportfootball": "skysportsfootball",
        "skysportcricket": "skysportscricket",
        "skysportgolf": "skysportsgolf",
        "skysporttennis": "skysportstennis",
        "skysportf1": "skysportsformula1",
        "skysportsf1": "skysportsformula1",
        "skysportmix": "skysportsmix",
        "skysportnews": "skysportsnews",
        "tntsport1": "tntsports1",
        "tntsport2": "tntsports2",
        "tntsport3": "tntsports3",
        "tntsport4": "tntsports4",
    },

    "de": {
        "skysportf1": "skysportformel1",
        "skysportsf1": "skysportformel1",
        "skysportformula1": "skysportformel1",
        "sportdigitalfootball":
            "sportdigitalfussball",
        "sportdigitalfussball":
            "sportdigitalfussball",
    },

    "nl": {
        "ziggosport1": "ziggosport",
        "espn1": "espn",
    },

    "us": {
        "foxsports1": "foxsports1",
        "foxsports2": "foxsports2",
        "fs1": "foxsports1",
        "fs2": "foxsports2",
        "espnnews": "espnews",
        "cbssn": "cbssportsnetwork",
        "cbssportsnet": "cbssportsnetwork",
        "nbatv": "nbatv",
        "nflnetwork": "nflnetwork",
        "mlbnetwork": "mlbnetwork",
    },

    "au": {
        "foxsportsnews": "foxsportsnews",
        "foxsports501": "foxsports501",
        "foxsports502": "foxsports502",
        "foxsports503": "foxsports503",
        "foxsports504": "foxsports504",
        "foxsports505": "foxsports505",
        "foxsports506": "foxsports506",
        "foxsports507": "foxsports507",
    },

    "gr": {
        "novasportnews": "novasportsnews",
        "novasportprime": "novasportsprime",
        "novasportstart": "novasportsstart",
        "novasportpremierleague":
            "novasportspremierleague",
    },

    "tr": {
        "beinsportshaber": "beinsportshaber",
        "beinsporthaber": "beinsportshaber",
        "aspor": "aspor",
        "trtspor": "trtspor",
    },

    "qa": {
        "alkasssports1": "alkass1",
        "alkasssports2": "alkass2",
        "alkasssports3": "alkass3",
        "alkasssports4": "alkass4",
        "alkasssports5": "alkass5",
    },

    "ca": {
        "sportsnetont": "sportsnetontario",
        "sportsnetpac": "sportsnetpacific",
    },

    "br": {
        "bandsport": "bandsports",
    },

    "es": {
        "movistarlaliga": "mlaliga",
        "movistarlaligatv": "mlaligatv",
    },

    "it": {
        "skysportsuno": "skysportuno",
        "skysports24": "skysport24",
    },
}

for region, aliases in ADDITIONAL_ALIASES.items():

    engine.REGIONAL_ALIASES.setdefault(
        region, {}
    ).update(aliases)


# ==========================================================
# ADVANCED TECHNICAL LABEL CLEANING
# ==========================================================

def clean_technical_labels(value):

    value = engine.clean_text(value)

    # Remove recording indicators.

    value = re.sub(
        r"[⏺●🔴⏹▶]+",
        " ",
        value
    )

    value = re.sub(
        r"\b(?:rec|recording)\b",
        " ",
        value
    )

    # Remove audio format descriptions.

    value = re.sub(
        r"\b(?:dolby|ddp|aac|ac3|eac3)"
        r"(?:\s*\d(?:\.\d)?)?\b",
        " ",
        value
    )

    # Remove video encoding and quality labels.

    value = re.sub(
        r"\b(?:raw|hdf|fhd|uhd|hd|sd|"
        r"hevc|avc|hdr10|hdr|"
        r"4k|8k|1080i|1080p|"
        r"720p|2160p|"
        r"25fps|30fps|50fps|60fps|"
        r"h[.\s]?264|h[.\s]?265)\b",
        " ",
        value
    )

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def normalise_name(value, region=""):

    value = clean_technical_labels(value)

    # Al Kass EPG identifiers can contain
    # AR.bein as a source designation.

    if region == "qa":

        value = re.sub(
            r"^\s*ar\s*\|\s*",
            "",
            value
        )

        value = re.sub(
            r"[_ .-]+ar[_.-]+bein$",
            "",
            value
        )

    return previous_normalise(
        value,
        region
    )


engine.normalise_name = normalise_name


# ==========================================================
# BROADCASTER-SPECIFIC REGION RECOGNITION
# ==========================================================

def identify_broadcaster(names):

    value = engine.clean_text(
        " ".join(sorted(names))
    )

    rules = [

        (
            r"\b(?:al[\s._-]*kass|alkass)"
            r"(?=[\s._-]|\d|$)",
            "qa",
            "alkass"
        ),

        (
            r"\bziggo[\s._-]*sport",
            "nl",
            "ziggo"
        ),

        (
            r"\b(?:ct|čt)[\s._-]*sport\b",
            "cz",
            "ct_sport"
        ),

        (
            r"\bsky[\s._-]*sport"
            r"[\s._-]*austria\b",
            "at",
            "sky_austria"
        ),

        (
            r"\bsportsnet[\s._-]*"
            r"(?:ontario|pacific|west|east)\b",
            "ca",
            "sportsnet"
        ),

        (
            r"\babu[\s._-]*dhabi"
            r"[\s._-]*sports?\b",
            "ae",
            "abu_dhabi"
        ),

        (
            r"\bdubai[\s._-]*sports?\b",
            "ae",
            "dubai_sports"
        ),

        (
            r"\bastro[\s._-]*arena\b",
            "my",
            "astro_arena"
        ),

        (
            r"\btrt[\s._-]*spor\b",
            "tr",
            "trt_spor"
        ),

        (
            r"\bnovasports?[\s._-]*"
            r"(?:prime|start|news)\b",
            "gr",
            "novasports"
        ),
    ]

    for pattern, region, reason in rules:

        if re.search(pattern, value):

            return region, reason

    return "", ""


# ==========================================================
# REBUILD NORMALISED CHANNEL KEYS
# ==========================================================

def rebuild_keys(entry):

    region = entry.get("region", "")

    names = set(
        entry.get("names", [])
    )

    source_id = entry.get("id", "")

    if source_id and not source_id.isdigit():

        names.add(source_id)

    entry["keys"] = {
        normalise_name(name, region)
        for name in names
        if normalise_name(name, region)
    }


# ==========================================================
# IMPROVED PLAYLIST RECOGNITION
# ==========================================================

def read_playlist():

    channels = previous_read_playlist()

    print(
        "\n===== V3.4 PLAYLIST CORRECTIONS ====="
    )

    for channel_id, channel in channels.items():

        old_region = channel.get("region", "")

        region, reason = identify_broadcaster(
            channel["names"]
        )

        # Infer a region only when there is
        # no existing region or conflict.

        if (
            region
            and not old_region
            and not channel.get(
                "ambiguous_region", False
            )
        ):

            channel["region"] = region

            diagnostics[
                "playlist_region_inferred"
            ] += 1

            diagnostics[
                f"playlist_{reason}"
            ] += 1

            print(
                f"{engine.safe_text(sorted(channel['names'])[0])}"
                f" -> {region}"
            )

        rebuild_keys(channel)

    print(
        "\n===== V3.4 PLAYLIST REGIONS ====="
    )

    regions = Counter(
        channel.get("region") or "unknown"
        for channel in channels.values()
    )

    for region, count in regions.most_common():

        print(f"{region}: {count}")

    return channels


engine.read_playlist = read_playlist


# ==========================================================
# CORRECT EPG SOURCE REGIONS
# ==========================================================

def load_epg_sources(*args, **kwargs):

    entries = previous_load_sources(
        *args,
        **kwargs
    )

    print(
        "\n===== V3.4 SOURCE CORRECTIONS ====="
    )

    for entry in entries:

        names = set(
            entry.get("names", [])
        )

        names.add(
            entry.get("id", "")
        )

        old_region = entry.get("region", "")

        region, reason = identify_broadcaster(
            names
        )

        # Correct Al Kass source metadata.
        # AR in these identifiers is not
        # necessarily an Argentine region.

        if (
            reason == "alkass"
            and old_region in ("", "ar", "qa")
        ):

            entry["region"] = "qa"

        # Other broadcaster-specific rules
        # only fill missing source regions.

        elif region and not old_region:

            entry["region"] = region

        new_region = entry.get("region", "")

        if new_region != old_region:

            diagnostics[
                "source_region_corrected"
            ] += 1

            source_corrections.append({
                "epg_id": engine.safe_text(
                    entry["id"]
                ),
                "old_region":
                    old_region or "unknown",
                "new_region": new_region,
                "reason": reason,
            })

            print(
                f"{engine.safe_text(entry['id'])}: "
                f"{old_region or 'unknown'} "
                f"-> {new_region}"
            )

        rebuild_keys(entry)

    print(
        f"Source region corrections: "
        f"{len(source_corrections)}"
    )

    return entries


engine.load_epg_sources = load_epg_sources


# ==========================================================
# COMPLETE MATCH DIAGNOSTICS
# ==========================================================

def match_channel(channel, indexes, mappings):

    result, method, candidates = previous_match(
        channel,
        indexes,
        mappings
    )

    channel_id = str(channel["id"])

    record = {
        "channel_id": channel_id,
        "name": engine.safe_text(
            sorted(channel["names"])[0]
        ),
        "region":
            channel.get("region") or "unknown",
        "event": bool(
            channel.get("event", False)
        ),
        "method": method,
        "normalised_names": sorted(
            channel.get("keys", [])
        ),
    }

    if result:

        record.update({
            "status": "matched",
            "epg_id": engine.safe_text(
                result["id"]
            ),
            "source": result["source"],
        })

        diagnostics["matched"] += 1

    else:

        record.update({
            "status": "unmatched",
            "reason": method,
            "candidates": [
                engine.safe_text(str(candidate))
                for candidate in candidates
            ],
        })

        diagnostics[
            f"unmatched_{method}"
        ] += 1

    records[channel_id] = record

    return result, method, candidates


engine.match_channel = match_channel


# ==========================================================
# PREVIOUS VERSION COMPARISON
# ==========================================================

def compare_previous_version():

    if not BASELINE_FILE.exists():

        print(
            "V3.3 baseline report not found."
        )

        print(
            "Channel-by-channel comparison skipped."
        )

        return {
            "available": False
        }

    try:

        baseline = json.loads(
            BASELINE_FILE.read_text(
                encoding="utf-8"
            )
        )

        old_matches = {
            str(item["channel_id"]): item
            for item in baseline["match_records"]
            if item["status"] == "matched"
        }

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError
    ) as error:

        print(
            f"Unable to read baseline: "
            f"{type(error).__name__}"
        )

        return {
            "available": False
        }

    new_matches = {
        channel_id: item
        for channel_id, item in records.items()
        if item["status"] == "matched"
    }

    gained = sorted(
        new_matches.keys() - old_matches.keys()
    )

    lost = sorted(
        old_matches.keys() - new_matches.keys()
    )

    retained = sorted(
        old_matches.keys() & new_matches.keys()
    )

    changed = [
        channel_id
        for channel_id in retained
        if old_matches[channel_id].get("epg_id")
        != new_matches[channel_id].get("epg_id")
        or old_matches[channel_id].get("name")
        != new_matches[channel_id].get("name")
    ]

    print(
        "\n===== V3.4 REGRESSION ANALYSIS ====="
    )

    print(f"New matches: {len(gained)}")
    print(f"Lost matches: {len(lost)}")
    print(f"Retained matches: {len(retained)}")
    print(f"Changed mappings: {len(changed)}")

    return {
        "available": True,
        "gained": [
            new_matches[item]
            for item in gained
        ],
        "lost": [
            old_matches[item]
            for item in lost
        ],
        "changed": [
            {
                "previous": old_matches[item],
                "current": new_matches[item],
            }
            for item in changed
        ],
        "retained_count": len(retained),
    }


# ==========================================================
# CSV REPORT GENERATION
# ==========================================================

def write_csv(filename, rows):

    fields = [
        "channel_id",
        "name",
        "region",
        "event",
        "status",
        "method",
        "epg_id",
        "source",
        "reason",
        "normalised_names",
        "candidates",
    ]

    with (REPORT_DIR / filename).open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()

        for row in rows:

            clean_row = dict(row)

            for field in (
                "candidates",
                "normalised_names"
            ):

                clean_row[field] = " | ".join(
                    row.get(field, [])
                )

            # Protect spreadsheet applications
            # against formula-like text.

            for key, value in clean_row.items():

                if isinstance(value, str):

                    if value.startswith(
                        ("=", "+", "-", "@")
                    ):

                        clean_row[key] = "'" + value

            writer.writerow(clean_row)


# ==========================================================
# FINAL DEVELOPMENT REPORT
# ==========================================================

def save_epg(root):

    matched = len(
        root.findall("channel")
    )

    programmes = len(
        root.findall("programme")
    )

    matched_records = [
        item
        for item in records.values()
        if item["status"] == "matched"
    ]

    unmatched_records = [
        item
        for item in records.values()
        if item["status"] == "unmatched"
    ]

    distinct_identities = len({
        (
            item.get("source"),
            item.get("epg_id")
        )
        for item in matched_records
    })

    comparison = compare_previous_version()

    print(
        "\n===== V3.4 DEVELOPMENT RESULTS ====="
    )

    print(
        f"V3.3 baseline: {BASELINE_CHANNELS}"
    )

    print(
        f"V3.4 matched channels: {matched}"
    )

    print(
        f"Net improvement: "
        f"{matched - BASELINE_CHANNELS:+d}"
    )

    print(
        f"Distinct EPG identities: "
        f"{distinct_identities}"
    )

    print(
        f"Programme listings: {programmes}"
    )

    print(
        f"Detailed channel records: "
        f"{len(records)}"
    )

    for key, value in sorted(
        diagnostics.items()
    ):

        print(f"{key}: {value}")

    report = {
        "version": "3.4",
        "test_mode": True,
        "baseline_channels":
            BASELINE_CHANNELS,
        "matched_channels": matched,
        "net_improvement":
            matched - BASELINE_CHANNELS,
        "distinct_epg_identities":
            distinct_identities,
        "programmes": programmes,
        "diagnostics": dict(diagnostics),
        "source_corrections":
            source_corrections,
        "comparison": comparison,
        "match_records":
            list(records.values()),
    }

    report_file = (
        REPORT_DIR / "v34-diagnostics.json"
    )

    report_file.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    write_csv(
        "v34-matched-channels.csv",
        matched_records
    )

    write_csv(
        "v34-unmatched-channels.csv",
        unmatched_records
    )

    print(
        "\n===== V3.4 REPORTS GENERATED ====="
    )

    print("reports/v34-diagnostics.json")
    print("reports/v34-matched-channels.csv")
    print("reports/v34-unmatched-channels.csv")

    # Production protection.
    # Never publish from this script.

    engine.TEST_MODE = True

    original_save(root)

    print(
        "\nPRODUCTION EPG NOT MODIFIED."
    )


engine.save_epg = save_epg


# ==========================================================
# START VERSION 3.4
# ==========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("VERSION 3.4 ADVANCED EPG MATCHING ENGINE")
    print("DEVELOPMENT MODE")
    print("PRODUCTION PROTECTION ENABLED")
    print("=" * 60)

    engine.main()

