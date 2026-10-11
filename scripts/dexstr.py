#!/usr/bin/env python3
"""Extract printable strings from all classes*.dex inside the APK and grep them."""
import sys, zipfile, re, os

APK = "/home/jcleng/work/mywork/revert_amap/.work/target.apk"
CACHE = "/home/jcleng/work/mywork/revert_amap/.work/dexstrings.txt"

def build():
    z = zipfile.ZipFile(APK)
    names = sorted(n for n in z.namelist() if re.fullmatch(r"classes\d*\.dex", n))
    with open(CACHE, "w", encoding="utf-8", errors="replace") as out:
        for n in names:
            data = z.read(n)
            for m in re.finditer(rb"[\x20-\x7e]{6,200}", data):
                out.write(m.group().decode("ascii") + "\n")
    return names

if __name__ == "__main__":
    if not os.path.exists(CACHE) or "--rebuild" in sys.argv:
        print("building from", build(), file=sys.stderr)
    pat = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    rx = re.compile(pat, re.I) if pat else None
    seen = set()
    for line in open(CACHE, encoding="utf-8", errors="replace"):
        s = line.rstrip("\n")
        if rx and rx.search(s) and s not in seen:
            seen.add(s)
            print(s)
