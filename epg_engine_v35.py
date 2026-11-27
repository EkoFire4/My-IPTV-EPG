
#!/usr/bin/env python3

# ==========================================================
# INTELLIGENT EPG MATCHING ENGINE
# VERSION 3.5
# DEVELOPMENT ONLY
# ==========================================================

import re
import json
from pathlib import Path
from collections import Counter

import epg_engine_v34 as v34

engine = v34.engine

# ==========================================================
# CONFIGURATION
# ==========================================================

engine.VERSION = "3.5"
engine.TEST_MODE = True

engine.MIN_MATCHED_CHANNELS = 618
engine.MIN_PREVIOUS_COVERAGE = 0.90

engine.OUTPUT_FILE = Path(
    "epgs/development-v35.xml.gz"
)

BASELINE_CHANNELS = 618

BASELINE_FILE = Path(
    "v34-diagnostics.json"
)

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

diagnostics = Counter()
records = {}
playlist_changes = []
source_changes = []

previous_normalise = engine.normalise_name
previous_read_playlist = engine.read_playlist
previous_load_sources = engine.load_epg_sources
previous_match = engine.match_channel

original_save = v34.original_save


# ==========================================================
# EXPANDED REGIONAL ALIASES
# ==========================================================

ADDITIONAL_ALIASES = {

    "ca": {
        "sportssnetone": "sportsnetone",
        "sportsnet1": "sportsnetone",
        "sportsnetont": "sportsnetontario",
        "sportsnetpac": "sportsnetpacific",
        "tvasport": "tvasports",
        "tvasport2": "tvasports2",
    },

    "at": {
        "orfsportplus": "orfsportplus",
        "orfsport": "orfsport",
        **{
            f"skysportsaustria{i}":
                f"skysportaustria{i}"
            for i in range(1, 9)
        },
    },

    "uk": {
        "skysportsmainevent":
            "skysportsmainevent",
        "skysportmainevent":
            "skysportsmainevent",
        "skysportsprem":
            "skysportspremierleague",
        "skysportsepl":
            "skysportspremierleague",
        "skysportsformulaone":
            "skysportsformula1",
        "tntsportsultimate":
            "tntsportsultimate",
        "premiersport1":
            "premiersports1",
        "premiersport2":
            "premiersports2",
    },

    "de": {
        "sportdigitalfussball":
            "sportdigitalfussball",
        "sportdigitalfootball":
            "sportdigitalfussball",
        "skysportformel1":
            "skysportformel1",
        "skysportformula1":
            "skysportformel1",
    },

    "us": {
        "foxsport1": "foxsports1",
        "foxsport2": "foxsports2",
        "espnnews": "espnews",
        "cbssn": "cbssportsnetwork",
        "cbssportsnet": "cbssportsnetwork",
        "nflnet": "nflnetwork",
    },

    "nl": {
        "ziggosport1": "ziggosport",
        "espn1": "espn",
    },

    "cz": {
        "ceskatelevizesport": "ctsport",
    },

    "br": {
        "bandsport": "bandsports",
    },

    "qa": {
        **{
            f"alkasssports{i}": f"alkass{i}"
            for i in range(1, 9)
        },
    },
}

for region, aliases in ADDITIONAL_ALIASES.items():

    engine.REGIONAL_ALIASES.setdefault(
        region, {}
    ).update(aliases)


# ==========================================================
# SAFE DIAGNOSTIC TEXT
# ==========================================================

def safe(value):

    value = str(value or "")

    value = re.sub(
        r"https?://[^\s]+",
        "[URL REMOVED]",
        value,
        flags=re.I
    )

    value = re.sub(
        r"\b(?:[0-9a-f]{2}:){5}"
        r"[0-9a-f]{2}\b",
        "[MAC REMOVED]",
        value,
        flags=re.I
    )

    value = re.sub(
        r"\b(?:bearer|token|password|"
        r"authorization|cookie)"
        r"\s*[:= ]\s*\S+",
        "[CREDENTIAL REMOVED]",
        value,
        flags=re.I
    )

    return value


# ==========================================================
# DECORATIVE CATEGORY DETECTION
# ==========================================================

def is_category_heading(names):

    names = list(names)

    if not names:
        return False

    # Require decorative markers in every
    # available name before excluding an entry.

    return all(
        name.count("☰") >= 4
        for name in names
    )


# ==========================================================
# ADVANCED EVENT FEED DETECTION
# ==========================================================

def is_extra_event_feed(names):

    for name in names:

        value = engine.clean_text(name)

        patterns = [

            r"\bpsf\s*\d+\s*[:|]",

            r"\blive\s+football\s*\d+\b",

            r"\btod\s+bein\s+event\s*\d+\b",

            r"\bsportsnet\s+world\s+extra"
            r"\s*\d+\b",

            r"\bf1\s*tv\s*pro\b",

            r"\bmatch\s*time\b",

            r"\b\d{1,2}:\d{2}\s+.+"
            r"\s+(?:vs\.?|versus|v)\s+",

            r"\b(?:event|fixture|feed)"
            r"\s*[-:]?\s*\d+\b",
        ]

        if any(
            re.search(pattern, value)
            for pattern in patterns
        ):

            return True

    return False


# ==========================================================
# IMPROVED NAME NORMALISATION
# ==========================================================

def normalise_name(value, region=""):

    value = engine.clean_text(value)

    # Canadian compound country/language prefix.

    if region == "ca":

        value = re.sub(
            r"^\s*ca\s+(?:fr|en)"
            r"\s*[:|]\s*",
            "",
            value
        )

        value = re.sub(
            r"\bsportssnet\b",
            "sportsnet",
            value
        )

    # Arabic-language prefix.
    # Only strip when the channel is not
    # classified as Argentina.

    if region != "ar":

        value = re.sub(
            r"^\s*ar\s*[:|]\s*",
            "",
            value
        )

    # Remove recording and technical labels.

    value = re.sub(
        r"[⏺●🔴⏹]+",
        " ",
        value
    )

    value = re.sub(
        r"\b(?:rec|recording|dolby|"
        r"hdf|raw|hevc|avc|hdr10|hdr)\b",
        " ",
        value
    )

    value = re.sub(
        r"\b(?:25|30|50|60)\s*fps\b",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return previous_normalise(
        value,
        region
    )


engine.normalise_name = normalise_name


# ==========================================================
# BROADCASTER REGION DATABASE
# ==========================================================

def broadcaster_region(names):

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
            r"\bsky[\s._-]*sport"
            r"[\s._-]*austria\b",
            "at",
            "sky_austria"
        ),

        (
            r"\borf[\s._-]*sport"
            r"[\s._-]*(?:plus|\+)",
            "at",
            "orf_sport"
        ),

        (
            r"\bziggo[\s._-]*sport",
            "nl",
            "ziggo"
        ),

        (
            r"\bsportsnet[\s._-]*"
            r"(?:ontario|pacific|west|east|"
            r"world|one|360)\b",
            "ca",
            "sportsnet"
        ),

        (
            r"\btva[\s._-]*sports?\b",
            "ca",
            "tva_sports"
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
            r"\bct[\s._-]*sport\b",
            "cz",
            "ct_sport"
        ),

        (
            r"\bnovasports?[\s._-]*"
            r"(?:prime|start|news)\b",
            "gr",
            "novasports"
        ),
    ]

    matches = []

    for pattern, region, reason in rules:

        if re.search(pattern, value):

            matches.append(
                (region, reason)
            )

    regions = {
        region
        for region, reason in matches
    }

    if len(regions) == 1:

        return matches[0]

    return "", ""


# ==========================================================
# ARABIC LANGUAGE IDENTIFICATION
# ==========================================================

def has_arabic_prefix(names):

    for name in names:

        value = engine.clean_text(name)

        if re.search(
            r"^\s*ar\s*[:|]",
            value
        ):

            return True

        if re.search(
            r"\[\s*ar\s*\]|\(\s*ar\s*\)",
            value
        ):

            return True

    return False


def has_argentina_label(names):

    for name in names:

        value = engine.clean_text(name)

        if re.search(
            r"\b(?:argentina|arg)\b",
            value
        ):

            return True

    return False


def is_arabic_broadcaster(names):

    value = engine.clean_text(
        " ".join(sorted(names))
    )

    return bool(
        re.search(
            r"\b(?:bein|tod|mbc|ssc|"
            r"alkass|al[\s._-]*kass|"
            r"abu[\s._-]*dhabi|"
            r"dubai|oman[\s._-]*sport|"
            r"kuwait[\s._-]*sport)\b",
            value
        )
    )


# ==========================================================
# REBUILD MATCHING KEYS
# ==========================================================

def rebuild_keys(entry, source=False):

    region = entry.get("region", "")

    names = set(
        entry.get("names", [])
    )

    if source:

        source_id = str(
            entry.get("id", "")
        )

        if source_id and not source_id.isdigit():

            names.add(source_id)

    keys = set()

    for name in names:

        key = normalise_name(
            name,
            region
        )

        if key:

            keys.add(key)

    entry["keys"] = keys


# ==========================================================
# RECORD REGION CHANGES
# ==========================================================

def record_region_change(
    channel,
    old_region,
    new_region,
    reason
):

    if old_region == new_region:
        return

    playlist_changes.append({

        "channel_id": str(
            channel["id"]
        ),

        "name": safe(
            sorted(channel["names"])[0]
        ),

        "old_region":
            old_region or "unknown",

        "new_region":
            new_region or "unknown",

        "reason": reason,
    })

    diagnostics[
        "playlist_region_corrected"
    ] += 1

    diagnostics[
        f"playlist_{reason}"
    ] += 1


# ==========================================================
# PLAYLIST CLASSIFICATION
# ==========================================================

def read_playlist():

    channels = previous_read_playlist()

    print(
        "\n===== V3.5 PLAYLIST CLASSIFICATION ====="
    )

    for channel_id, channel in channels.items():

        names = channel["names"]

        channel["heading"] = (
            is_category_heading(names)
        )

        if channel["heading"]:

            diagnostics[
                "category_headings"
            ] += 1

            continue

        if (
            not channel.get("event", False)
            and is_extra_event_feed(names)
        ):

            channel["event"] = True

            diagnostics[
                "additional_event_feeds"
            ] += 1

        old_region = channel.get(
            "region", ""
        )

        # Preserve unresolved explicit conflicts.

        if channel.get(
            "ambiguous_region", False
        ):

            diagnostics[
                "region_conflicts_preserved"
            ] += 1

            continue

        cleaned_names = [
            engine.clean_text(name)
            for name in names
        ]

        # Resolve CA FR and CA EN prefixes.

        if any(
            re.search(
                r"^\s*ca\s+(?:fr|en)"
                r"\s*[:|]",
                name
            )
            for name in cleaned_names
        ):

            if old_region in ("", "ca"):

                channel["region"] = "ca"

                record_region_change(
                    channel,
                    old_region,
                    "ca",
                    "canadian_compound_prefix"
                )

        region, reason = broadcaster_region(
            names
        )

        current_region = channel.get(
            "region", ""
        )

        # AR can denote Arabic, not Argentina.

        arabic_identity = (
            has_arabic_prefix(names)
            and is_arabic_broadcaster(names)
            and not has_argentina_label(names)
        )

        if (
            current_region == "ar"
            and arabic_identity
        ):

            # Assign a country only where
            # broadcaster identity supports it.

            channel["region"] = region or ""

            channel["language_hint"] = "ar"

            record_region_change(
                channel,
                current_region,
                channel["region"],
                "arabic_not_argentina"
            )

        elif region and not current_region:

            channel["region"] = region

            record_region_change(
                channel,
                current_region,
                region,
                reason
            )

        rebuild_keys(channel)

    print(
        f"Category headings: "
        f"{diagnostics['category_headings']}"
    )

    print(
        f"Additional event feeds: "
        f"{diagnostics['additional_event_feeds']}"
    )

    print(
        f"Playlist region corrections: "
        f"{len(playlist_changes)}"
    )

    for item in playlist_changes[:40]:

        print(
            f"{item['name']}: "
            f"{item['old_region']} -> "
            f"{item['new_region']}"
        )

    return channels


engine.read_playlist = read_playlist


# ==========================================================
# EPG SOURCE REGION CORRECTIONS
# ==========================================================

def load_epg_sources(*args, **kwargs):

    entries = previous_load_sources(
        *args,
        **kwargs
    )

    print(
        "\n===== V3.5 SOURCE CORRECTIONS ====="
    )

    for entry in entries:

        names = set(
            entry.get("names", [])
        )

        source_id = str(
            entry.get("id", "")
        )

        names.add(source_id)

        old_region = entry.get(
            "region", ""
        )

        region, reason = broadcaster_region(
            names
        )

        # Austrian broadcasters can appear
        # in the German EPG source.

        if (
            region == "at"
            and reason in (
                "sky_austria",
                "orf_sport"
            )
            and old_region in ("de", "", "at")
        ):

            entry["region"] = "at"

        # Preserve the successful Al Kass fix.

        elif (
            region == "qa"
            and reason == "alkass"
            and old_region in ("ar", "", "qa")
        ):

            entry["region"] = "qa"

        # Fill unknown regions only where
        # broadcaster recognition is specific.

        elif region and not old_region:

            entry["region"] = region

        new_region = entry.get(
            "region", ""
        )

        if old_region != new_region:

            source_changes.append({

                "epg_id": safe(source_id),

                "old_region":
                    old_region or "unknown",

                "new_region":
                    new_region or "unknown",

                "reason": reason,
            })

            diagnostics[
                "source_region_corrected"
            ] += 1

            print(
                f"{safe(source_id)}: "
                f"{old_region or 'unknown'} "
                f"-> {new_region}"
            )

        rebuild_keys(
            entry,
            source=True
        )

    print(
        f"Additional source corrections: "
        f"{len(source_changes)}"
    )

    return entries


engine.load_epg_sources = load_epg_sources


# ==========================================================
# SAFE MATCHING AND FULL DIAGNOSTICS
# ==========================================================

def match_channel(
    channel,
    indexes,
    mappings
):

    channel_id = str(
        channel["id"]
    )

    record = {

        "channel_id": channel_id,

        "name": safe(
            sorted(channel["names"])[0]
        ),

        "region":
            channel.get("region") or "unknown",

        "event": bool(
            channel.get("event", False)
        ),

        "heading": bool(
            channel.get("heading", False)
        ),

        "language_hint":
            channel.get("language_hint", ""),

        "normalised_names": sorted(
            channel.get("keys", [])
        ),
    }

    # Decorative headings are not stations.
    # Keep them in diagnostics but do not
    # assign a programme schedule.

    if record["heading"]:

        record.update({

            "status": "excluded",

            "method": "category_heading",

            "reason": "category_heading",

            "candidates": [],
        })

        records[channel_id] = record

        diagnostics[
            "excluded_category_heading"
        ] += 1

        return None, "category_heading", []

    # Retain the conservative V3.4 matcher.

    result, method, candidates = previous_match(
        channel,
        indexes,
        mappings
    )

    record["method"] = method

    if result:

        record.update({

            "status": "matched",

            "epg_id": safe(
                result["id"]
            ),

            "source": safe(
                result["source"]
            ),
        })

        diagnostics["matched"] += 1

    else:

        record.update({

            "status": "unmatched",

            "reason": method,

            "candidates": [
                safe(candidate)
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
# REGRESSION COMPARISON
# ==========================================================

def compare_baseline():

    print(
        "\n===== V3.5 REGRESSION ANALYSIS ====="
    )

    if not BASELINE_FILE.exists():

        print(
            "V3.4 baseline report not found."
        )

        print(
            "Individual regression analysis skipped."
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
            f"Baseline error: "
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

        if (
            old_matches[channel_id].get("epg_id")
            != new_matches[channel_id].get("epg_id")
        )
    ]

    print(f"Previous matches: {len(old_matches)}")
    print(f"Current matches: {len(new_matches)}")
    print(f"New matches: {len(gained)}")
    print(f"Lost matches: {len(lost)}")
    print(f"Retained matches: {len(retained)}")
    print(f"Changed mappings: {len(changed)}")

    if lost or changed:

        print(
            "REVIEW REQUIRED: "
            "Previous mappings were lost or changed."
        )

    else:

        print(
            "No lost or changed EPG identifiers."
        )

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
# FINAL DEVELOPMENT REPORT
# ==========================================================

def save_epg(root):

    matched = len(
        root.findall("channel")
    )

    programmes = len(
        root.findall("programme")
    )

    all_records = list(
        records.values()
    )

    matched_records = [

        item for item in all_records

        if item["status"] == "matched"
    ]

    unmatched_records = [

        item for item in all_records

        if item["status"] == "unmatched"
    ]

    excluded_records = [

        item for item in all_records

        if item["status"] == "excluded"
    ]

    eligible_records = [

        item for item in all_records

        if item["status"] != "excluded"
    ]

    regular_records = [

        item for item in eligible_records

        if not item["event"]
    ]

    event_records = [

        item for item in eligible_records

        if item["event"]
    ]

    matched_regular = sum(

        item["status"] == "matched"

        for item in regular_records
    )

    matched_events = sum(

        item["status"] == "matched"

        for item in event_records
    )

    total = len(all_records)

    eligible = len(eligible_records)

    regular = len(regular_records)

    events = len(event_records)

    headings = len(excluded_records)

    raw_coverage = (
        matched / total * 100
        if total else 0
    )

    adjusted_coverage = (
        matched / eligible * 100
        if eligible else 0
    )

    regular_coverage = (
        matched_regular / regular * 100
        if regular else 0
    )

    distinct_identities = len({

        item.get("epg_id")

        for item in matched_records
    })

    comparison = compare_baseline()

    print(
        "\n===== V3.5 DEVELOPMENT RESULTS ====="
    )

    print(
        f"V3.4 baseline: {BASELINE_CHANNELS}"
    )

    print(
        f"V3.5 matched channels: {matched}"
    )

    print(
        f"Net improvement: "
        f"{matched - BASELINE_CHANNELS:+d}"
    )

    print(
        f"Distinct EPG identifiers: "
        f"{distinct_identities}"
    )

    print(
        f"Programme listings: {programmes}"
    )

    print(
        f"Detailed channel records: {total}"
    )

    print(
        f"Excluded category headings: {headings}"
    )

    print(
        f"Eligible playlist channels: {eligible}"
    )

    print(
        f"Regular channels: {regular}"
    )

    print(
        f"Event feeds: {events}"
    )

    print(
        f"Matched regular channels: "
        f"{matched_regular}"
    )

    print(
        f"Matched event feeds: {matched_events}"
    )

    print(
        f"Raw coverage: {raw_coverage:.2f}%"
    )

    print(
        f"Adjusted coverage: "
        f"{adjusted_coverage:.2f}%"
    )

    print(
        f"Regular channel coverage: "
        f"{regular_coverage:.2f}%"
    )

    for key, value in sorted(
        diagnostics.items()
    ):

        print(f"{key}: {value}")

    report = {

        "version": "3.5",

        "test_mode": True,

        "baseline_channels":
            BASELINE_CHANNELS,

        "matched_channels": matched,

        "net_improvement":
            matched - BASELINE_CHANNELS,

        "distinct_epg_identifiers":
            distinct_identities,

        "programmes": programmes,

        "total_playlist_entries": total,

        "excluded_headings": headings,

        "eligible_channels": eligible,

        "regular_channels": regular,

        "event_feeds": events,

        "matched_regular_channels":
            matched_regular,

        "matched_event_feeds":
            matched_events,

        "raw_coverage":
            round(raw_coverage, 2),

        "adjusted_coverage":
            round(adjusted_coverage, 2),

        "regular_coverage":
            round(regular_coverage, 2),

        "diagnostics":
            dict(diagnostics),

        "playlist_changes":
            playlist_changes,

        "source_changes":
            source_changes,

        "comparison":
            comparison,

        "match_records":
            all_records,
    }

    report_file = (
        REPORT_DIR / "v35-diagnostics.json"
    )

    report_file.write_text(

        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),

        encoding="utf-8"
    )

    # Reuse the working V3.4 CSV exporter.

    v34.write_csv(
        "v35-matched-channels.csv",
        matched_records
    )

    v34.write_csv(
        "v35-unmatched-channels.csv",
        unmatched_records
    )

    v34.write_csv(
        "v35-excluded-headings.csv",
        excluded_records
    )

    v34.write_csv(
        "v35-event-feeds.csv",
        event_records
    )

    print(
        "\n===== V3.5 REPORTS GENERATED ====="
    )

    print("reports/v35-diagnostics.json")
    print("reports/v35-matched-channels.csv")
    print("reports/v35-unmatched-channels.csv")
    print("reports/v35-excluded-headings.csv")
    print("reports/v35-event-feeds.csv")

    # Production protection.
    # Never publish from development.

    engine.TEST_MODE = True

    original_save(root)

    print(
        "\nPRODUCTION EPG NOT MODIFIED."
    )


engine.save_epg = save_epg


# ==========================================================
# START VERSION 3.5
# ==========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("VERSION 3.5 INTELLIGENT EPG MATCHING")
    print("DEVELOPMENT MODE")
    print("PRODUCTION PROTECTION ENABLED")
    print("=" * 60)

    engine.main()
