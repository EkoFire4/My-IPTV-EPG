
#!/usr/bin/env python3

# ==========================================================
# INTELLIGENT SPORTS EPG ENGINE
# VERSION 3.3 - ADVANCED CHANNEL RECOGNITION
# ==========================================================

import re
import json
from pathlib import Path
from collections import Counter

import epg_engine_v32 as engine


# ==========================================================
# DEVELOPMENT CONFIGURATION
# ==========================================================

engine.VERSION = "3.3"
engine.TEST_MODE = True

engine.MIN_MATCHED_CHANNELS = 554
engine.MIN_PREVIOUS_COVERAGE = 0.90

engine.OUTPUT_FILE = Path(
    "epgs/development-epg.xml.gz"
)

REPORT_FILE = Path(
    "reports/v33-diagnostics.json"
)

# Preserve original V3.2 functions.

original_normalise = engine.normalise_name
original_read_playlist = engine.read_playlist
original_match_channel = engine.match_channel
original_save_epg = engine.save_epg

diagnostics = Counter()
match_records = []
region_changes = []


# ==========================================================
# EXPANDED REGIONAL ALIASES
# ==========================================================

ADDITIONAL_ALIASES = {

    "uk": {
        "skysportsfootball": "skysportsfootball",
        "skysportmainevent": "skysportsmainevent",
        "skysportpremierleague":
            "skysportspremierleague",
        "skysportsformula1": "skysportsformula1",
        "tntsportsultimate": "tntsportsultimate",
        "premiersport1": "premiersports1",
        "premiersport2": "premiersports2",
    },

    "ie": {
        "premiersport1": "premiersports1",
        "premiersport2": "premiersports2",
    },

    "de": {
        "sportdigitalfootball":
            "sportdigitalfussball",
        "skysportbundesliga1":
            "skysportbundesliga1",
        "skysportsnews":
            "skysportnews",
    },

    "us": {
        "foxsports1": "foxsports1",
        "foxsports2": "foxsports2",
        "cbssportsnet": "cbssportsnetwork",
        "cbssn": "cbssportsnetwork",
        "nbcsn": "nbcsportsnetwork",
        "espnnews": "espnews",
    },

    "nl": {
        "espn1": "espn",
        "ziggosport1": "ziggosport",
    },

    "fr": {
        "rmcsportone": "rmcsport1",
        "rmcsporttwo": "rmcsport2",
        "bein1": "beinsports1",
        "bein2": "beinsports2",
        "bein3": "beinsports3",
    },

    "ae": {
        "adsport1": "abudhabisports1",
        "adsport2": "abudhabisports2",
        "adsports1": "abudhabisports1",
        "adsports2": "abudhabisports2",
    },

    "cz": {
        "ceskatelevizesport": "ctsport",
    },

    "gr": {
        "novasport1": "novasports1",
        "novasport2": "novasports2",
        "novasport3": "novasports3",
        "novasport4": "novasports4",
    },

    "ar": {
        "espnsports": "espn",
        "espn1": "espn",
    },
}

for region, aliases in ADDITIONAL_ALIASES.items():

    engine.REGIONAL_ALIASES.setdefault(
        region, {}
    ).update(aliases)


# ==========================================================
# ADVANCED NAME NORMALISATION
# ==========================================================

def normalise_name(value, region=""):

    value = engine.clean_text(value)

    # Remove technical stream labels.

    value = re.sub(
        r"\b(?:raw|hevc|avc|hdr10|hdr|"
        r"1080i|1080p|720p|2160p|"
        r"25fps|30fps|50fps|60fps|"
        r"h[.\s]?264|h[.\s]?265)\b",
        "",
        value
    )

    # Remove Arabic grouping prefix only
    # when the station identity supports it.

    if re.search(
        r"\b(?:al[\s._-]*kass|"
        r"alkass)\b",
        value
    ):

        value = re.sub(
            r"^\s*ar\s*\|\s*",
            "",
            value
        )

    return original_normalise(
        value,
        region
    )


engine.normalise_name = normalise_name


# ==========================================================
# EXPLICIT COUNTRY SUFFIX RECOGNITION
# ==========================================================

def explicit_suffix_regions(names):

    regions = set()

    for name in names:

        value = engine.clean_text(name)

        matches = re.findall(
            rf"[\[(]\s*"
            rf"({engine.REGION_PATTERN})"
            rf"\s*[\])]",
            value
        )

        for match in matches:

            regions.add(
                engine.REGIONS[match]
            )

    return regions


def prefix_regions(names):

    regions = set()

    for name in names:

        value = engine.clean_text(name)

        match = re.match(
            rf"^\s*({engine.REGION_PATTERN})"
            rf"\s*[:|._\-]+",
            value
        )

        if match:

            regions.add(
                engine.REGIONS[match.group(1)]
            )

    return regions


# ==========================================================
# CHANNEL-SPECIFIC REGIONAL RECOGNITION
# ==========================================================

def identify_special_region(channel):

    names = " ".join(
        sorted(channel["names"])
    )

    value = engine.clean_text(names)

    # Al Kass is a Qatari broadcaster.
    # Do not treat AR as Argentina here.

    if re.search(
        r"\b(?:al[\s._-]*kass|alkass)\b",
        value
    ):

        return "qa", "alkass_identity"

    if re.search(
        r"\bsky\s+sport\s+austria\b",
        value
    ):

        return "at", "austrian_identity"

    if re.search(
        r"\babu\s+dhabi\s+sports?\b",
        value
    ):

        return "ae", "uae_identity"

    if re.search(
        r"\bdubai\s+sports?\b",
        value
    ):

        return "ae", "uae_identity"

    if re.search(
        r"\bsportsnet\s+"
        r"(?:ontario|pacific|"
        r"west|east)\b",
        value
    ):

        return "ca", "canadian_identity"

    return "", ""


# ==========================================================
# IMPROVED PLAYLIST REGION DETECTION
# ==========================================================

def read_playlist():

    channels = original_read_playlist()

    print(
        "\n===== V3.3 REGION CORRECTIONS ====="
    )

    for channel_id, channel in channels.items():

        old_region = channel["region"]
        new_region = old_region

        reason = ""

        suffixes = explicit_suffix_regions(
            channel["names"]
        )

        prefixes = prefix_regions(
            channel["names"]
        )

        special_region, special_reason = (
            identify_special_region(channel)
        )

        # Multiple conflicting explicit suffixes
        # require manual verification.

        if len(suffixes) > 1:

            diagnostics[
                "unresolved_suffix_conflicts"
            ] += 1

            continue

        # Known broadcaster identity.

        if special_region:

            if (
                suffixes
                and special_region not in suffixes
            ):

                diagnostics[
                    "identity_suffix_conflicts"
                ] += 1

                continue

            new_region = special_region
            reason = special_reason

        # Explicit suffix takes priority only
        # for recognised channel families.

        elif len(suffixes) == 1:

            suffix = next(iter(suffixes))

            names = engine.clean_text(
                " ".join(
                    sorted(channel["names"])
                )
            )

            supported_family = re.search(
                r"\b(?:premier\s+sports?|"
                r"dazn)\b",
                names
            )

            if (
                channel["ambiguous_region"]
                and supported_family
            ):

                new_region = suffix
                reason = "explicit_country_suffix"

            elif not channel["ambiguous_region"]:

                new_region = suffix
                reason = "explicit_country_suffix"

        elif (
            not old_region
            and not channel["ambiguous_region"]
            and len(prefixes) == 1
        ):

            new_region = next(iter(prefixes))
            reason = "country_prefix"

        if not reason:
            continue

        channel["region"] = new_region

        channel["ambiguous_region"] = False

        channel["keys"] = {
            normalise_name(name, new_region)
            for name in channel["names"]
            if normalise_name(name, new_region)
        }

        if new_region != old_region:

            diagnostics[
                "region_corrections"
            ] += 1

            diagnostics[reason] += 1

            region_changes.append({
                "channel_id": channel_id,
                "name": engine.safe_text(
                    sorted(channel["names"])[0]
                ),
                "old_region":
                    old_region or "unknown",
                "new_region": new_region,
                "reason": reason,
            })

    for item in region_changes[:30]:

        print(
            f"{item['name']} | "
            f"{item['old_region']} -> "
            f"{item['new_region']} | "
            f"{item['reason']}"
        )

    print(
        f"\nRegion corrections: "
        f"{len(region_changes)}"
    )

    print(
        "\n===== V3.3 UPDATED REGIONS ====="
    )

    regions = Counter(
        channel["region"] or "unknown"
        for channel in channels.values()
    )

    for region, count in regions.most_common():

        print(f"{region}: {count}")

    return channels


engine.read_playlist = read_playlist


# ==========================================================
# SAFER UNKNOWN-REGION MATCHING
# ==========================================================

def match_channel(channel, indexes, mappings):

    region = channel["region"]

    if channel["ambiguous_region"]:

        diagnostics[
            "unresolved_region_conflicts"
        ] += 1

        return None, "region_conflict", []

    # Avoid assigning a regional broadcast
    # schedule to a channel with no reliable
    # region unless manually verified.

    if not region:

        mapping = mappings.get(
            channel["id"]
        )

        if not isinstance(mapping, dict):

            diagnostics[
                "unknown_region_held"
            ] += 1

            return (
                None,
                "unknown_region_requires_review",
                []
            )

        if not (
            mapping.get("name")
            and mapping.get("epg_id")
        ):

            return (
                None,
                "invalid_manual_mapping",
                []
            )

    result, method, candidates = (
        original_match_channel(
            channel,
            indexes,
            mappings
        )
    )

    # Unknown-region channels must actually
    # succeed through the manual mapping.

    if not region and method != "manual":

        result = None
        method = "unknown_region_requires_review"

    name = engine.safe_text(
        sorted(channel["names"])[0]
    )

    if result:

        diagnostics[
            "accepted_matches"
        ] += 1

        diagnostics[
            f"match_{method}"
        ] += 1

        match_records.append({
            "channel_id": channel["id"],
            "name": name,
            "region": region or "unknown",
            "epg_id": engine.safe_text(
                result["id"]
            ),
            "source": result["source"],
            "method": method,
            "status": "matched",
        })

    else:

        diagnostics[
            f"rejected_{method}"
        ] += 1

        match_records.append({
            "channel_id": channel["id"],
            "name": name,
            "region": region or "unknown",
            "reason": method,
            "candidates": [
                engine.safe_text(candidate)
                for candidate in candidates
            ],
            "status": "unmatched",
        })

    return result, method, candidates


engine.match_channel = match_channel


# ==========================================================
# DEVELOPMENT REPORT
# ==========================================================

def save_epg(root):

    matched = len(
        root.findall("channel")
    )

    programmes = len(
        root.findall("programme")
    )

    baseline = 554

    print(
        "\n===== V3.3 DEVELOPMENT RESULTS ====="
    )

    print(
        f"V3.2 baseline: {baseline}"
    )

    print(
        f"V3.3 matched channels: {matched}"
    )

    print(
        f"Net channel improvement: "
        f"{matched - baseline:+d}"
    )

    print(
        f"Programme listings: {programmes}"
    )

    for key, value in sorted(
        diagnostics.items()
    ):

        print(f"{key}: {value}")

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    report = {
        "version": "3.3",
        "test_mode": True,
        "baseline_channels": baseline,
        "matched_channels": matched,
        "net_improvement": matched - baseline,
        "programmes": programmes,
        "diagnostics": dict(diagnostics),
        "region_changes": region_changes,
        "match_records": match_records,
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print(
        f"\nDevelopment report: {REPORT_FILE}"
    )

    # Force test mode regardless of the
    # configuration in the original engine.

    engine.TEST_MODE = True

    original_save_epg(root)

    print(
        "\nPRODUCTION EPG NOT MODIFIED."
    )


engine.save_epg = save_epg


# ==========================================================
# START VERSION 3.3
# ==========================================================

if __name__ == "__main__":

    print("=" * 55)
    print("VERSION 3.3 DEVELOPMENT ENGINE")
    print("PRODUCTION PROTECTION ENABLED")
    print("=" * 55)

    engine.main()

