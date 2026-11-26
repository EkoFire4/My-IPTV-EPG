
import os
import re
import gzip
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# ==========================================
# EPG SOURCES
# Add or remove EPG sources here
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


# ==========================================
# DOWNLOAD FUNCTION
# ==========================================

def download(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()

    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)

    return data


# ==========================================
# RETRIEVE PRIVATE M3U PLAYLIST
# ==========================================

def get_channel_ids():
    m3u_url = os.environ.get("M3U_URL")

    if not m3u_url:
        raise SystemExit("ERROR: M3U_URL secret is missing.")

    print("Downloading private M3U playlist...")

    try:
        playlist = download(m3u_url).decode(
            "utf-8-sig", errors="replace"
        )
    except Exception:
        raise SystemExit(
            "ERROR: Unable to download playlist. "
            "Check your M3U_URL secret."
        ) from None

    channel_ids = set()

    for line in playlist.splitlines():
        if line.startswith("#EXTINF"):
            match = re.search(
                r'tvg-id\s*=\s*"([^"]*)"',
                line,
                re.IGNORECASE
            )

            if match:
                channel_id = match.group(1).strip()

                if channel_id:
                    channel_ids.add(channel_id)

    if not channel_ids:
        raise SystemExit(
            "ERROR: No tvg-id values found in playlist."
        )

    print(f"Found {len(channel_ids)} unique channel IDs.")

    return channel_ids


# ==========================================
# DOWNLOAD AND FILTER EPG SOURCES
# ==========================================

def build_epg(channel_ids):
    channels = {}
    programmes = []
    programme_keys = set()

    matched_ids = set()

    for index, url in enumerate(URLS, start=1):

        print(f"Processing EPG source {index}/{len(URLS)}...")

        try:
            data = download(url)
            source = ET.fromstring(data)

            if source.tag != "tv":
                raise ValueError("Invalid XMLTV document")

            source_matches = set()

            for channel in source.findall("channel"):
                channel_id = channel.get("id")

                if channel_id in channel_ids:
                    source_matches.add(channel_id)

                    if channel_id not in channels:
                        channels[channel_id] = channel

            added = 0

            for programme in source.findall("programme"):
                channel_id = programme.get("channel")

                if channel_id not in source_matches:
                    continue

                key = (
                    channel_id,
                    programme.get("start"),
                    programme.get("stop"),
                )

                if key in programme_keys:
                    continue

                programme_keys.add(key)
                programmes.append(programme)
                added += 1

            matched_ids.update(source_matches)

            print(
                f"Matched {len(source_matches)} channels; "
                f"added {added} programmes."
            )

        except Exception:
            print(
                f"WARNING: EPG source {index} failed. "
                "Continuing with remaining sources."
            )

    if not channels or not programmes:
        raise SystemExit(
            "ERROR: No usable EPG matches found. "
            "Existing EPG has not been replaced."
        )

    root = ET.Element(
        "tv",
        {"generator-info-name": "Light EPG Updater"}
    )

    for channel in channels.values():
        root.append(channel)

    for programme in programmes:
        root.append(programme)

    print(f"Total matched channels: {len(matched_ids)}")
    print(f"Unmatched channels: {len(channel_ids - matched_ids)}")
    print(f"Total programmes: {len(programmes)}")

    return root


# ==========================================
# SAVE COMPRESSED EPG
# ==========================================

def save_epg(root):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    xml_data = ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True
    )

    # Prevent accidental publication of the playlist URL.
    m3u_url = os.environ.get("M3U_URL", "")

    if m3u_url and m3u_url.encode("utf-8") in xml_data:
        raise SystemExit(
            "ERROR: Private playlist URL detected in output."
        )

    temp_file = OUTPUT_FILE.with_suffix(".gz.tmp")

    with gzip.open(temp_file, "wb") as output:
        output.write(xml_data)

    temp_file.replace(OUTPUT_FILE)

    size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)

    print("EPG generated successfully!")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Compressed size: {size_mb:.2f} MB")


# ==========================================
# RUN SCRIPT
# ==========================================

if __name__ == "__main__":
    channel_ids = get_channel_ids()
    epg = build_epg(channel_ids)
    save_epg(epg)
