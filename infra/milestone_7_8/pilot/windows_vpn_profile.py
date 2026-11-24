"""Read back this run's Azure VPN Client entry from the Windows application phonebook."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.pilot_cleanup import file_hash, read


def profile_fields(xml):
    root = ET.fromstring(xml)
    def texts(path):
        return sorted(node.text or "" for node in root.findall(path))
    aad = "{*}clientauth/{*}aad/"
    config = "{*}clientconfig/"
    return {
        "name": root.findtext("{*}name"),
        "audience": texts(aad + "{*}audience"), "tenant": texts(aad + "{*}tenant"),
        "issuer": texts(aad + "{*}issuer"), "servers": texts("{*}serverlist//{*}fqdn"),
        "dns": texts(config + "{*}dnsservers/{*}dnsserver"),
        "suffixes": texts(config + "{*}dnssuffixes/{*}dnssuffix"),
        "routes": sorted((node.findtext("{*}destination"), node.findtext("{*}mask"))
                         for node in root.findall(config + "{*}includeroutes/{*}route")),
    }


def verify(phonebook, profile, *, absent=False):
    expected = profile_fields(profile)
    if not all(expected.values()):
        raise CampaignError("verified native VPN profile is incomplete")
    if len(phonebook) > 16_000_000:
        raise CampaignError("unexpected VPN phonebook size")
    codec = "utf-16" if phonebook.startswith((b"\xff\xfe", b"\xfe\xff")) else (
        "utf-16-le" if phonebook[:80].count(b"\0") > 15 else "utf-8-sig")
    sections = re.split(r"(?m)^\[([^]\r\n]+)\][ \t]*\r?\n", phonebook.decode(codec))
    if phonebook and len(sections) == 1:
        raise CampaignError("Windows VPN phonebook has no readable sections")
    entries = [body for name, body in zip(sections[1::2], sections[2::2], strict=True)
               if name.casefold() == expected["name"].casefold()]
    if len(entries) != (0 if absent else 1):
        raise CampaignError("Windows VPN Client contains an unexpected number of entries for the staging profile")
    if entries:
        blob = bytes.fromhex("".join(line.partition("=")[2].strip() for line in entries[0].splitlines()
                                     if line.startswith("ThirdPartyProfileInfo=")))
        documents = re.findall(r"<AzVpnProfile\b.*?</AzVpnProfile>", blob.decode("utf-16-le", errors="replace"),
                               re.I | re.S)
        if len(documents) != 1:
            raise CampaignError("one installed Azure VPN profile document required")
        observed = profile_fields(documents[0])
        different = [key for key in expected if observed[key] != expected[key]]
        if different:
            raise CampaignError("installed VPN profile differs in " + ", ".join(different))
    return {"installedEntries": len(entries), "profileSha256": hashlib.sha256(profile).hexdigest(),
            "atUtc": datetime.now(UTC).isoformat()}


def observe(package, *, absent=False):
    run = package.parent / ("run-" + file_hash(package / "review-package.json")[:8])
    vpn = (run / "vpn").resolve()
    ready = read(vpn / "profile-ready.json")
    source = (vpn / ready["relativeProfile"]).resolve()
    if source.parent != vpn or not ready["azureGatewayVerified"] or file_hash(source) != ready["profileSha256"]:
        raise CampaignError("VPN profile does not match the native gateway receipt")
    phonebook = Path(os.environ["LOCALAPPDATA"]) / "Packages/Microsoft.AzureVpn_8wekyb3d8bbwe/LocalState/rasphone.pbk"
    try:
        data = phonebook.read_bytes()
    except FileNotFoundError:
        data = b""
    return verify(data, source.read_bytes(), absent=absent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--absent", action="store_true")
    arguments = parser.parse_args()
    print(observe(arguments.package, absent=arguments.absent))
