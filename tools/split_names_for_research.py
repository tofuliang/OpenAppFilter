#!/usr/bin/env python3
"""Split domain-like rule names: MY_KNOWN vs agent chunks."""
import os
import re
TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
F = f"{TMP}/features_rules_final_new.txt"
DOMAIN_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

# my confident knowledge pass: id -> friendly name
MY_KNOWN = {
    20244: "一点资讯",      # go2yd.com
    20234: "盒马",          # hemaos.com
    20235: "盒马",          # hemashare.cn
    20279: "欧可林",        # oclean.com
    20422: "乐播投屏",      # hpplay.com.cn
    20434: "中国电信118114", # 118114.net
    20124: "哔哩哔哩",      # bilibilihelper.com
    20497: "苹果服务",      # mzstatic.com
    20477: "Fastly",      # fastly-edge.com
    20452: "微软AppCenter", # appcenter.ms
    20484: "Iconfont",     # iconfont.cn
    20485: "Imgcook",      # imgcook.com
    20284: "grep.app",     # grep.app (product name itself)
    20311: "柏林工业大学",  # tu-berlin.de
    20127: "Barnes & Noble",# bn.com (name charset: no #~:;,[] — & ok)
    20348: "Naver",        # xn--ngstr-lra8j = 네이버 (verify via decode)
}

dom = []
for line in open(F, encoding="utf-8"):
    if line.startswith("#") or not line.strip(): continue
    rid_s, rest = line.rstrip("\n").split("~", 1)
    name = rest.split(":[", 1)[0]
    if DOMAIN_NAME.match(name):
        dom.append((int(rid_s), name))

unknown = [(r, n) for r, n in dom if r not in MY_KNOWN]
print(f"domain-named {len(dom)}, my_known {len(dom)-len(unknown)}, unknown {len(unknown)}")
n = len(unknown)
# 3 chunks, contiguous
import math
size = math.ceil(n / 3)
for c in range(3):
    part = unknown[c*size:(c+1)*size]
    with open(f"{TMP}/name_chunk{c+1}.txt", "w") as f:
        for r, nm in part:
            f.write(f"{r} {nm}\n")
    print(f"chunk{c+1}: {len(part)}")
