#!/usr/bin/env python3
"""Service-level aggregation under big catch-all rules; flag services that
already have a dedicated rule vs those that would be new candidates."""
import re, collections
import os

TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

rules = []  # (rid, name, exact_bases)
for line in open(f"{TMP}/features_rules_final_new.txt", encoding="utf-8"):
    if line.startswith("#") or not line.strip(): continue
    rid_s, rest = line.rstrip("\n").split("~", 1)
    name, body = rest.split(":[", 1)
    bases = set()
    for chunk in body.rstrip("]").split(","):
        f = chunk.split(";")
        if len(f) != 8: continue
        p = f[3]
        if p.startswith("."): bases.add(p[1:])
    rules.append((int(rid_s), name, bases))

obs = collections.Counter()
for line in open(f"{TMP}/features_draft.txt", encoding="utf-8"):
    line = line.strip()
    if "|" not in line: continue
    d = line.split("|", 1)[1].lower().rstrip(".")
    if d and HOST_RE.match(d) and not IP_RE.match(d): obs[d] += 1
for line in open(f"{TMP}/features_rules.txt", encoding="utf-8"):
    if "~" not in line or ":[" not in line: continue
    body = line.split(":[", 1)[1].rstrip("]\n")
    for chunk in body.split(","):
        f = chunk.split(";")
        if len(f) >= 4 and f[3] and HOST_RE.match(f[3].lower()):
            obs[f[3].lower()] += 1

# all bases in file, to say whether a service bucket already has its own rule
base2rule = {}
for rid, name, bases in rules:
    for b in bases:
        base2rule[b] = (rid, name)

FOCUS = {20031: "qq.com", 20131: "mi.com", 20020: "xiaomi.com", 20032: "baidu.com",
         20024: "taobao.com", 20022: "google.com", 20030: "heytapmobi.com",
         20482: None}  # OPPO multi-base handled below
# find focus rules by name too
def service_of(sub, base):
    # sub = labels before base. service = last-2-labels of sub if >=2 labels else first label
    labs = sub.split(".")
    if len(labs) >= 2:
        return ".".join(labs[-2:]) + "." + base
    return labs[0] + "." + base   # e.g. v.qq.com style single-label sub -> keep first label? no: single label sub -> "v."+base

print("rule | service bucket | obs | already-a-rule?")
for rid, name, bases in rules:
    if rid not in FOCUS and name not in {"腾讯QQ", "小米", "百度", "淘宝", "谷歌", "OPPO", "vivo"}:
        continue
    svc = collections.Counter()
    for d, c in obs.items():
        for b in bases:
            if d.endswith("." + b):
                sub = d[: -(len(b) + 1)]
                labs = sub.split(".")
                key = labs[-1] + "." + b
                svc[key] += c
                break
    if not svc: continue
    print(f"\n=== {rid} {name} ({','.join(sorted(bases))}) ===")
    for s, c in svc.most_common(30):
        hit = ""
        if s in base2rule:
            hit = f"  -> HAS rule {base2rule[s][0]}~{base2rule[s][1]}"
        else:
            # check if some rule base is a suffix of s or vice versa (would still catch)
            for b, (r2, n2) in base2rule.items():
                if s.endswith("." + b) or b.endswith("." + s):
                    hit = f"  -> caught by {r2}~{n2} ('{b}')"
                    break
        print(f"  {s:<45} ×{c}{hit}")
