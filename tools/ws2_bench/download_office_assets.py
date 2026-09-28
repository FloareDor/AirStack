#!/usr/bin/env python3
"""Download the public Isaac 4.5 Office asset subtree for a WS2 run."""
import argparse
import os
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

BUCKET = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
PREFIX = "Assets/Isaac/4.5/Isaac/Environments/Office/"
STRIP = "Assets/Isaac/4.5/"
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def request(url):
    context = ssl._create_unverified_context()
    return urllib.request.urlopen(url, context=context).read()


def objects():
    token = None
    while True:
        query = {"list-type": "2", "prefix": PREFIX}
        if token:
            query["continuation-token"] = token
        root = ET.fromstring(request(BUCKET + "/?" + urllib.parse.urlencode(query)))
        for node in root.findall("s3:Contents", NS):
            key = node.findtext("s3:Key", namespaces=NS)
            size = int(node.findtext("s3:Size", namespaces=NS))
            if key and not key.endswith("/") and "/.thumbs/" not in key:
                yield key, size
        token = root.findtext("s3:NextContinuationToken", namespaces=NS)
        if not token:
            return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", default="/tmp/ws2_assets/Isaac/4.5")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    entries = list(objects())
    total = sum(size for _, size in entries)
    print(f"Office subtree: {len(entries)} files, {total / 1024 / 1024:.1f} MiB")
    if args.dry_run:
        return
    def download(item):
        index, (key, size) = item
        relative = key.removeprefix(STRIP)
        target = os.path.join(args.destination, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target) and os.path.getsize(target) == size:
            return
        print(f"[{index}/{len(entries)}] {relative}", flush=True)
        with open(target, "wb") as output:
            output.write(request(BUCKET + "/" + urllib.parse.quote(key)))
    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(download, enumerate(entries, 1)))


if __name__ == "__main__":
    main()
