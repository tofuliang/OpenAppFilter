#!/usr/bin/env python3
"""Scan corpus for mid-label / tail-early FPs of candidate PLAIN sub-service patterns."""
import re
import os
TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
PAT = ["weixin.qq.com", "wx.qq.com", "video.qq.com", "v.qq.com",
       "map.qq.com", "map.baidu.com", "pan.baidu.com", "gemini.google.com"]
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+")

def is_ip(s):
    p = s.split(".")
    return len(p) == 4 and all(x.isdigit() and int(x) < 256 for x in p)

corpus = set()
# draft: kind|host
for line in open(f"{TMP}/features_draft.txt", encoding="utf-8"):
    if "|" not in line: continue
    kind, d = line.rstrip("\n").split("|", 1)
    d = d.lower().rstrip(".")
    if d and HOST_RE.match(d) and not is_ip(d): corpus.add(d)
# raw + official + final: token scan
for fn in ("features_rules.txt", "feature_official.txt", "features_rules_final.txt"):
    for line in open(f"{TMP}/{fn}", encoding="utf-8"):
        if line.startswith("#"): continue
        for t in TOKEN_RE.findall(line.lower()):
            t = t.rstrip(".")
            if t and "." in t and HOST_RE.match(t) and not is_ip(t): corpus.add(t)
# rules' own bases
for line in open(f"{TMP}/features_rules_final_new.txt", encoding="utf-8"):
    if line.startswith("#") or not line.strip(): continue
    body = line.split(":[", 1)[1].rstrip("]\n")
    for ch in body.split(","):
        f = ch.split(";")
        if len(f) == 8 and f[3].startswith("."):
            corpus.add(f[3][1:])

print(f"corpus {len(corpus)}")
for p in PAT:
    mid, tail = [], []
    for d in sorted(corpus):
        i = d.find(p)
        if i < 0: continue
        if i > 0 and d[i-1] != ".":
            mid.append(d)                       # mid-label FP
        elif i + len(p) < len(d):
            tail.append(d)                      # tail-early
    print(f"{p:<22} mid={len(mid)} tail={len(tail)}")
    for d in mid: print(f"   MID   {d}")
    for d in tail: print(f"   tail  {d}")
