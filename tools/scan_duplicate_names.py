#!/usr/bin/env python3
"""Scan final rules: duplicate names + domain-like names."""
import os
import re, collections
TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
F = f"{TMP}/features_rules_final_new.txt"
DOMAIN_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

rules = []
for line in open(F, encoding="utf-8"):
    if line.startswith("#") or not line.strip(): continue
    rid_s, rest = line.rstrip("\n").split("~", 1)
    name, body = rest.split(":[", 1)
    hosts = []
    for ch in body.rstrip("]").split(","):
        f = ch.split(";")
        if len(f) >= 4 and f[3] and f[3][0] != "^":
            hosts.append(f[3])
    rules.append((int(rid_s), name, hosts))

# 1. duplicate names
byname = collections.defaultdict(list)
for rid, name, hs in rules: byname[name].append((rid, hs))
dups = {n: v for n, v in byname.items() if len(v) > 1}
print(f"=== DUP NAMES: {len(dups)} names ===")
for n, v in sorted(dups.items()):
    print(f"  {n}: " + " | ".join(f"{rid}:{len(hs)}h" for rid, hs in v))
    for rid, hs in v:
        print(f"      {rid}: {','.join(hs)}")

# 2. domain-like names
dom = [(rid, name, hs) for rid, name, hs in rules if DOMAIN_NAME.match(name)]
print(f"\n=== DOMAIN-LIKE NAMES: {len(dom)} ===")
for rid, name, hs in dom:
    print(f"  {rid}~{name}: {','.join(hs)}")

print(f"\ntotal rules {len(rules)}, unique names {len(byname)}")
