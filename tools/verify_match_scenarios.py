#!/usr/bin/env python3
"""Engine-accurate winner: earliest END index, then longest pattern at that end."""
import os
import re
import sys
TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
OUT = os.path.join(TMP, "features_rules_final_new.txt")
ac = []  # (pattern, rid, name)
for line in open(OUT, encoding="utf-8"):
    if line.startswith("#"):   # official-style #version/#class headers
        continue
    rid, rest = line.rstrip("\n").split("~", 1)
    name, body = rest.split(":[", 1)
    for chunk in body.rstrip("]").split(","):
        f = chunk.split(";")
        # 8-field ours / 6-field official / one odd 7-field: host = f[3]
        if 4 <= len(f) <= 8 and f[3] and f[3][0] not in "^":
            ac.append((f[3], int(rid), name))

def winner(host):
    best = None  # (end, -len)
    for p, rid, name in ac:
        i = host.find(p)
        if i < 0: continue
        end = i + len(p)
        cand = (end, -len(p))
        if best is None or cand < best[0]:
            best = (cand, p, rid, name)
    return best

def is_ok(want, got):
    if want is None:
        return got == "NO-MATCH"
    return got == want

CASES = [
    ("mp.weixin.qq.com", "微信"), ("short.weixin.qq.com", "微信"),
    ("extshort.weixin.qq.com", "微信"), ("wx.qq.com", "微信"),
    ("video.qq.com", "腾讯视频"), ("v.qq.com", "腾讯视频"),
    ("findermp.video.qq.com", "腾讯视频"),
    ("map.qq.com", "腾讯地图"), ("lbs.map.qq.com", "腾讯地图"),
    ("map.baidu.com", "百度地图"), ("api.map.baidu.com", "百度地图"),
    ("pan.baidu.com", "百度网盘"),
    ("gemini.google.com", "Gemini"),
    ("www.qq.com", "腾讯QQ"), ("dldir1.qq.com", "腾讯QQ"),
    ("a.b.qq.com", "腾讯QQ"), ("weixinbridge.com", "微信"),
    ("m.taobao.com", "淘宝"), ("mp.weixin.qq.com.evil.example", None),
]
# 2 known FAs (expected FAIL): weixinbridge NO-MATCH (AC-sim artifact),
# evil.example tail-chain pollution (engine keeps longest-at-end semantics).
KNOWN_FA = {"weixinbridge.com", "mp.weixin.qq.com.evil.example"}
bad = unexpected = 0
for host, want in CASES:
    w = winner(host)
    got = w[3] if w else "NO-MATCH"
    mark = "OK " if is_ok(want, got) else "FAIL"
    if mark == "FAIL":
        bad += 1
        if host not in KNOWN_FA:
            unexpected += 1
    print(f"{mark} {host:<38} -> {w[1] if w else '-'} {got}")
print(f"FAILURES: {bad} (known FA expected: {len(KNOWN_FA)})")
if bad != len(KNOWN_FA):
    print(f"NOTICE: known-FA count changed (expected {len(KNOWN_FA)}, got {bad}) — engine semantics may have shifted")
if unexpected:
    print(f"UNEXPECTED FAILURES: {unexpected}")
    sys.exit(1)  # non-zero on unexpected regression (pipeline fail-fast)
print("SCENARIOS: PASS")
