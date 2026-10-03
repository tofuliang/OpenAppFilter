#!/usr/bin/env python3
"""Generate official_gap_data.py: official gaps vs our ruleset.

Buckets per official rule (dedup by id):
  domain hosts (valid registrable) -> dual-form transform by build_rules
  loose host (single-label/fragment) -> verbatim feature passthrough
  hostless (payload/port) -> verbatim feature passthrough
Outputs:
  ID_MAP     {our_name: official_id}   adoption for names present in BOTH
  CLASS_MAP  {name: class_id}          official-derived app classes
  NEW_APPS   [(id, name, class_id, [domains], [verbatim_feats])]  official-only apps
  HOST_ADDS  {our_name: ([domains], [verbatim_feats])}            uncovered parts for apps we have
  REPORT prints
"""
import os
import re
import sys

TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
HOST_FIX = {"umeng.co": "umeng.com"}
UNIFY_SUFFIX = ("cloudfront.net",)

def canon(h):
    h = HOST_FIX.get(h, h)
    for b in UNIFY_SUFFIX:
        if h == b or h.endswith("." + b):
            return b
    return h

def load_our():
    """our rules: name -> set(bases) ; also full base set"""
    names, bases = {}, set()
    for line in open(f"{TMP}/features_rules_final_new.txt"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, body = line.split(":[", 1)
        rid, name = head.split("~", 1)
        bs = set()
        for ft in body.rstrip("]").split(","):
            fl = ft.split(";")
            if len(fl) < 4:
                continue
            h = fl[3]
            if not h:
                continue
            if h.startswith("^"):
                if h.endswith(r"\..*$"):
                    continue
                m = h[1:-1]
                if m.endswith("[*]*"):
                    m = m[:-4]
                elif m.endswith("*"):
                    m = m[:-1]
                bs.add(canon(m.replace(r"\.", ".")))
            elif h.startswith("."):
                bs.add(canon(h[1:]))
            else:
                bs.add(canon(h))
        names.setdefault(name, set()).update(bs)
        bases |= names[name]
    return names, bases

def load_official():
    rules = {}  # id -> [name, class_id, [feat_text...]]
    cls = None
    clsname = {}
    for line in open(f"{TMP}/feature_official.txt"):
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("#class"):
            p = line.split()
            cls = int(p[2])
            clsname[cls] = p[3]
            continue
        if line.startswith("#"):
            continue
        m = re.match(r"^(\d+)~([^:]+):\[(.*)\]\s*$", line)
        if not m:
            continue
        rid = int(m.group(1))
        name = m.group(2)
        feats = [f.strip() for f in m.group(3).split(",") if f.strip()]
        if rid in rules:
            # same id duplicated lines: union features
            rules[rid][2].extend(f for f in feats if f not in rules[rid][2])
        else:
            rules[rid] = [name, cls, feats]
    return rules, clsname

def covered(p, our_bases):
    for b in our_bases:
        if p == b or p in b or b in p:
            return True
        if p.endswith("." + b) or b.endswith("." + p):
            return True
    return False

def base_of(h):
    """official domain host -> our base (strip www.)"""
    if h.startswith("www."):
        h = h[4:]
    return canon(h)

def main():
    ours_names, our_bases = load_our()
    off, clsname = load_official()
    print(f"official rules {len(off)}, our names {len(ours_names)}, our bases {len(our_bases)}")

    ID_MAP, CLASS_MAP = {}, {}
    NEW_APPS, HOST_ADDS = [], {}
    icon_ids = set()
    for x in open(f"{TMP}/iids.txt"):
        t = x.strip()
        if t.endswith(".png") and t[:-4].isdigit():
            icon_ids.add(int(t[:-4]))

    loose_scan = []  # (id, name, loose_host) for FP audit
    missing_icons = []

    for rid in sorted(off):
        name, cls, feats = off[rid]
        # dedup same-name official rules in same class (keep first id, absorb feats)
        if name in ID_MAP and CLASS_MAP.get(name) == cls:
            first = ID_MAP[name]
            for f in feats:
                if f not in off[first][2]:
                    off[first][2].append(f)
            continue
        domains, verbatim = [], []
        for ft in feats:
            fl = ft.split(";")
            host = fl[3] if len(fl) >= 4 else ""
            if not host:
                verbatim.append(ft)  # keep as-is
            elif HOST_RE.match(host) and not IP_RE.match(host):
                domains.append(base_of(host.lower()))
            else:
                verbatim.append(ft)
                loose_scan.append((rid, name, host.lower()))
        domains = list(dict.fromkeys(domains))  # dedupe preserve order

        existing = name in ours_names
        if name not in ID_MAP:
            ID_MAP[name] = rid
            CLASS_MAP[name] = cls
        if existing:
            miss_dom = [d for d in domains if not covered(d, our_bases)]
            # loose/hostless always appended (payload rules we lack etc.)
            if miss_dom or verbatim:
                prev = HOST_ADDS.get(name, ([], []))
                merged_d = list(prev[0])
                merged_d += [d for d in dict.fromkeys(miss_dom) if d not in merged_d]
                merged_v = list(prev[1]) + [v for v in verbatim if v not in prev[1]]
                HOST_ADDS[name] = (merged_d, merged_v)
        else:
            NEW_APPS.append([rid, name, cls, domains, verbatim])
        if rid not in icon_ids:
            missing_icons.append((rid, name))

    print(f"ID_MAP {len(ID_MAP)}  NEW_APPS {len(NEW_APPS)}  HOST_ADDS {len(HOST_ADDS)}")
    print(f"adopted names missing icons: {missing_icons}")
    tot_d = sum(len(a[3]) for a in NEW_APPS)
    tot_v = sum(len(a[4]) for a in NEW_APPS)
    add_d = sum(len(v[0]) for v in HOST_ADDS.values())
    add_v = sum(len(v[1]) for v in HOST_ADDS.values())
    print(f"NEW: {tot_d} domains + {tot_v} verbatim feats; ADD: {add_d} domains + {add_v} verbatim feats")
    print("\nHOST_ADDS:")
    for n, (d, v) in sorted(HOST_ADDS.items()):
        print(f"  {n}: dom={d} verb={len(v)}")
    print("\nloose hosts (FP audit):")
    for rid, n, h in loose_scan:
        print(f"  {rid} {n} {h}")

    # dedup NEW_APPS by name (first id wins, union domains+verbatim)
    byname = {}
    for rec in NEW_APPS:
        if rec[1] in byname:
            t = byname[rec[1]]
            t[3] = list(dict.fromkeys(t[3] + rec[3]))
            t[4] = list(dict.fromkeys(t[4] + rec[4]))
        else:
            byname[rec[1]] = rec
    NEW_APPS = sorted(byname.values(), key=lambda r: r[0])

    OFFICIAL_LOOSE = sorted({h for _, _, h in loose_scan})
    CLASS_KEYS = {1: "chat", 2: "game", 3: "video", 4: "shopping", 5: "music",
                  6: "employee", 7: "download", 8: "website", 10: "life",
                  11: "tools", 14: "finance"}

    if not NEW_APPS and len(HOST_ADDS) >= 50 and os.environ.get("OAF_ALLOW_EMPTY_GAP") != "1":
        print("ERROR: baseline likely already merged (known signature: NEW_APPS 262→0, HOST_ADDS 18→99); ",
              "re-running gen_official_gap_data against a merged feature file corrupts the gap data — ",
              "set OAF_ALLOW_EMPTY_GAP=1 to override",
              file=sys.stderr)
        sys.exit(1)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "official_gap_data.py")
    with open(out, "w") as f:
        f.write("# generated by gen_official_gap_data.py -- do not edit\n")
        f.write(f"ID_MAP = {ID_MAP!r}\n")
        f.write(f"CLASS_MAP = {CLASS_MAP!r}\n")
        f.write(f"NEW_APPS = {NEW_APPS!r}\n")
        f.write(f"HOST_ADDS = {HOST_ADDS!r}\n")
        f.write(f"CLASS_NAMES = {clsname!r}\n")
        f.write(f"CLASS_KEYS = {CLASS_KEYS!r}\n")
        f.write(f"OFFICIAL_LOOSE = {OFFICIAL_LOOSE!r}\n")
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
