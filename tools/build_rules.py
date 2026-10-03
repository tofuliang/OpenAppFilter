#!/usr/bin/env python3
"""Build features_rules_final_new.txt = final(432) + raw/draft-derived rules
 official library gaps (official_gap_data: adopted ids, HOST_ADDS, NEW_APPS),
rendered: every host -> '.host' AC pattern + exact-apex regex feature
(plain single feature for sub-service / TLD-less hosts), one host per feature
(kernel comma-split safe); official verbatim features pass through as-is;
output written with official-style #version/#class headers."""
import os, re, collections, sys

TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
OUT = f"{TMP}/features_rules_final_new.txt"

PSL2 = {"com.cn","net.cn","org.cn","edu.cn","gov.cn","ac.cn","mil.cn",
        "co.jp","com.tw","com.hk","co.uk","org.uk"}
PSL_BARE = PSL2 | {"cn","com","net","org","gov","edu","mil","int","io","co","cc","tv","me","top","xyz","info","biz"}
MULTITENANT = {"cloudfront.net","github.io","pages.dev","workers.dev","netlify.app","vercel.app",
               "herokuapp.com","azurewebsites.net","aliyuncs.com","myqcloud.com"}
KNOWN_FRAG = {"a-inc.com","eepseek.com","idu.com","ili.com","iplus.com","iyun.com","ll.com",
              "ng.com","ox.com","pilot.com","shu.cn","un.com","ba-inc.com","ilibili.com"}
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# non-PSL final labels official uses as if they were TLDs (TLD-less truncations
# like music.163 / xssh.qq must stay plain-substring; NEVER add non-TLD words
# (qq, nie, netease, fp, vivo, ixigua, koudaibaobao, kugou, proxima, 163, 126)
EXTRA_TLD = {'bz','dev','app','ms','im','de','vip','mobi','tech','audio','media','hk','cloud','ai','arpa','ly','fm','gg','sh','studio','page','site','online','store','zone','today','team','world','center','icu','pro','ltd','group','wiki','chat','fun','run','work','mail','email','xin','press','fund','money','pay'}
TLD_ALL = PSL_BARE | EXTRA_TLD

# data bug: id 20312 友盟 host truncated to umeng.co -> real domain umeng.com
HOST_FIX = {"umeng.co": "umeng.com"}

# multi-tenant CDN/platform: unify tenant-specific hosts to the base domain
# (cloudfront dist-ids are random hashes; rule intent is the platform itself)
UNIFY_SUFFIX = ("cloudfront.net",)

def canon(h):
    h = HOST_FIX.get(h, h)
    for b in UNIFY_SUFFIX:
        if h == b or h.endswith("." + b):
            return b
    return h

def esc(h):
    return h.replace(".", r"\.")

def apex_rx(h):
    r"""Exact-apex regex (engine needs ^ * $ to detect regex hosts).
    Form 1: suffix [*]* (LIST of literal star, starred) -> zero reps cannot
    shorten the match, exact only. Form 2 (long hosts, host_url[31] budget):
    star the final char -> matches host + host-minus-final-char (harmless for
    long names). Form 3 (oversized hosts): ^label\..* anchor on the first
    label -> matches the bare distribution domain + its subdomains (label is
    a random dist-id, so precision is effectively exact). None = impossible."""
    e = esc(h)
    if len(e) + 6 <= 31:
        return "^" + e + "[*]*$"
    if len(e) + 3 <= 31:
        return "^" + e[:-1] + e[-1] + "*$"
    lab = h.split(".")[0]
    p3 = "^" + esc(lab) + r"\..*$"
    if len(p3) <= 31:
        return p3
    return None

# registrable -> assigned name (only confident mappings; others keep domain as name)
NAME_MAP = {
  "realsee-cdn.cn":"如视","realsee.com":"如视",
  "bytetos.com":"字节跳动","bytescm.com":"字节跳动","bytegoofy.com":"字节跳动",
  "bytefae.com":"字节跳动","bytesfield.com":"字节跳动","byteurl.cn":"字节跳动","ttwebview.com":"字节跳动",
  "myhuaweicloud.cn":"华为云","dbankcloud.com":"华为云","dbankcloud.cn":"华为云",
  "eastmoney.com":"东方财富","dfcfw.com":"东方财富",
  "weixinbridge.com":"微信",
  "sm.cn":"神马搜索","yisou.com":"神马搜索",
  "uc.cn":"UC浏览器","open-uc.cn":"UC浏览器",
  "fqnovelstatic.com":"番茄小说",
  "icbc.com.cn":"工商银行",
  "abchina.com.cn":"农业银行","abchina.com":"农业银行",
  "pingan.com":"平安","pingan.com.cn":"平安",
  "cmbchina.com":"招商银行",
  "tsinghua.edu.cn":"清华大学",
  "jiaoyimao.com":"交易猫",
  "jiyoujia.com":"极有家",
  "maizuo6.com":"卖座",
  "shuqireader.com":"书旗小说",
  "yunos.com":"YunOS",
  "taopiaopiao.cn":"淘票票",
  "9game.cn":"九游",
  "jikeiot.cloud":"极氪",
  "geetest.com":"极验",
  "qianwen.com":"通义千问",
  "dewu.com":"得物",
  "ucloud.cn":"UCloud",
  "umengcloud.com":"友盟","umindex.com":"友盟","umtrack.com":"友盟","um0.cn":"友盟",
  "aligenie.com":"天猫精灵",
  "alihealth.cn":"阿里健康",
  "alimama.com":"阿里妈妈",
  "alibabagroup.com":"阿里巴巴","aliunicorn.com":"阿里巴巴","aliwork.com":"阿里巴巴",
  "cainiao-inc.com":"菜鸟",
  "dingtalkcloud.com":"钉钉","dingtalkapps.com":"钉钉",
  "xiaoaiassist.com":"小爱",
  "amapauto.com":"高德",
  "ksyungslb.com":"金山云CDN",
  "cnzz.com":"CNZZ",
  "heytap.com":"OPPO","heytap.net":"OPPO","heytap.com.cn":"OPPO",
  "heytapcloud.cn":"OPPO","heytapcloud.com":"OPPO","heytapcloud.net":"OPPO",
  "heytapcs.com":"OPPO","heytapmobile.com":"OPPO","heytapimage.com":"OPPO","opposhop.cn":"OPPO",
  "youku.com":"优酷",
  "gtimg.com":"腾讯CDN","gtimg.cn":"腾讯CDN",
  "cmpassport.com":"中国移动认证",
  "aiclk.com":"快手广告",
  "qtaeixd.com":"阿里防爬",
}

# official library gap data (generated by gen_official_gap_data.py — do not hand-edit)
from official_gap_data import (ID_MAP, CLASS_MAP, CLASS_NAMES, CLASS_KEYS,
                            NEW_APPS, HOST_ADDS, OFFICIAL_LOOSE)
LOOSE = set(OFFICIAL_LOOSE)   # official loose substring hosts: skip domain checks

CLASS_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 14]
CLASS_KW = [("游戏",2),("视频",3),("直播",3),("影视",3),("短剧",3),
            ("购物",4),("超市",4),("商城",4),("拼购",4),
            ("音乐",5),("听书",5),("电台",5),
            ("招聘",6),("直聘",6),
            ("网盘",7),("下载",7),("云盘",7),
            ("银行",14),("支付",14),("金融",14),("证券",14),
            ("聊天",1),("社交",1),("社区",1),("论坛",1),
            ("工具",11),("输入法",11),("浏览器",11),("加速器",11),
            ("新闻",8),("门户",8),("百科",8),("资讯",8)]

def guess_class(name):
    for kw, c in CLASS_KW:
        if kw in name:
            return c
    return 10

def parse(path):
    rules = []
    for ln, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line: continue
        rid, rest = line.split("~", 1)
        name, body = rest.split(":[", 1)
        fields = body.rstrip("]").split(";")
        hosts = [h for h in fields[3].split(",") if h]
        rules.append([int(rid), name, fields, hosts, []])   # 5-elem: verb=[]
    return rules

def registrable(d):
    parts = d.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in PSL2:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return d

final = parse(f"{TMP}/features_rules_final.txt")
raw = parse(f"{TMP}/features_rules.txt")

# ---- append sub-service hosts (归属修正): 微信的 qq.com 子域此前被误算为腾讯QQ ----
HOST_APPEND = {20238: ["weixin.qq.com", "wx.qq.com"]}
for r in final:
    for h in HOST_APPEND.get(r[0], []):
        if h not in r[3]:
            r[3].append(h)
final_hosts = [h for r in final for h in r[3]]
fh_set = set(final_hosts)

dns = collections.Counter(); sni = collections.Counter()
draft_hosts = set()
for line in open(f"{TMP}/features_draft.txt", encoding="utf-8"):
    line = line.strip()
    if "|" not in line: continue
    kind, d = line.split("|", 1)
    if not d: continue
    d = d.lower()
    if not HOST_RE.match(d): continue   # drop draft junk: hex hashes, [2408, rl=, ku9 ...
    draft_hosts.add(d)
    (dns if kind == "dns" else sni)[d] += 1

known = draft_hosts | set(raw_hosts := [h for r in raw for h in r[3]]) | fh_set

def covered(h):   return any(f and f in h for f in fh_set)
def subset(h):    return any(h and h in f for f in fh_set)

# ---- NEW raw hosts ----
new_orig = {}   # registrable -> set(original hosts)
for r in raw:
    for h in r[3]:
        if covered(h) or subset(h): continue
        new_orig.setdefault(registrable(h.lower() if h.isupper() else h), set()).add(h)

# ---- draft-only registrables (in draft, family not covered by final or NEW) ----
extra = collections.defaultdict(set)
new_regs = set(new_orig)
for d in draft_hosts:
    if covered(d) or subset(d): continue
    reg = registrable(d)
    if reg in new_regs: continue
    if reg in KNOWN_FRAG: continue
    if any(reg in f or f in reg for f in fh_set): continue
    if any(reg in x or x in reg for x in new_regs): continue
    extra[reg].add(d)
for reg, hs in extra.items():
    new_orig.setdefault(reg, set()).update(hs)

print(f"raw-derived registrables: {len([1 for r in new_orig if r not in extra])}  draft-only adds: {len(extra)}")
if extra:
    for reg in sorted(extra):
        ev = [f"{d}[{dns[d]}/{sni[d]}]" for d in sorted(extra[reg])[:4]]
        print(f"  DRAFT-ONLY {reg}: {' '.join(ev)}")

# ---- filters on original hosts ----
drop_orig = set(); chain_hits = []; frag_hits = []
for reg, hs in new_orig.items():
    for h in hs:
        hl = h.lower()
        # chain: known domain embedded with >=2 labels tail after it
        for d in known:
            if d and d != hl and d in hl:
                p = hl.find(d); tail = hl[p+len(d):]
                if tail.startswith(".") and len([x for x in tail.split(".") if x]) >= 2:
                    chain_hits.append((hl, d)); drop_orig.add(h); break
        if h in drop_orig: continue
        # fragment: proper substring of a DNS-proven domain, itself dns=0
        if dns[hl] == 0:
            for d in draft_hosts:
                if d != hl and hl in d and dns[d] > 0:
                    frag_hits.append((hl, d)); drop_orig.add(h); break

print(f"chain-dropped: {chain_hits or '-'}")
print(f"frag-dropped: {frag_hits or '-'}")

# ---- fold to registrable (lowercase), drop empty/frag ----
folded = {}
for reg, hs in new_orig.items():
    keep = [h for h in hs if h not in drop_orig]
    if not keep: continue
    rl = reg.lower()
    if rl in KNOWN_FRAG: continue
    if rl in PSL_BARE: print(f"!! PSL parent {rl} skipped"); continue
    if rl in MULTITENANT:
        folded[rl] = {h.lower() for h in keep}   # keep specific hosts
    else:
        folded[rl] = {rl}
print(f"folded registrables: {len(folded)}  bare hosts: {sum(len(v) for v in folded.values())}")

# ---- assign name, merge by name ----
byname = collections.defaultdict(set)
for reg, hs in folded.items():
    byname[NAME_MAP.get(reg, reg)].update(hs)

# ---- P1: family match to final (registrable equality) ----
final_regs = {registrable(h) for h in final_hosts}
p1 = []
for name in list(byname):
    if name in final_regs:   # host name equals a final family reg
        p1.append(name)
print(f"P1 family appends: {len(p1) or '-'} {p1 if p1 else ''}")

# ---- within-rule dedupe: drop X if Y⊂X exists in same rule ----
def dedupe(hosts):
    out = set(hosts)
    for x in list(out):
        if any(y != x and y in x for y in out):
            out.discard(x)
    return out

# ---- manual sub-service rules (独立 APP，Tier1+Tier2 已确认) ----
MANUAL = [
    (20546, "腾讯视频", ["video.qq.com", "v.qq.com"]),
    (20547, "腾讯地图", ["map.qq.com"]),
    (20548, "百度地图", ["map.baidu.com"]),
    (20549, "百度网盘", ["pan.baidu.com"]),
    (20550, "Gemini",  ["gemini.google.com"]),
]
reserved = {rid for rid, _, _ in MANUAL}   # auto id 分配跳过 MANUAL 固定 id

new_rules = []
nid = 20433
for name in sorted(byname, key=lambda n: (byname[n] and sorted(byname[n])[0])):
    while nid in reserved:
        nid += 1   # 新增 registrable 会使 auto id 后移，撞 MANUAL 固定 id 前跳过
    hs = dedupe(byname[name])
    new_rules.append([nid, name, ["tcp", "", "", ",".join(sorted(hs)), "", "", "", ""], sorted(hs), []])
    nid += 1

for rid, name, hs in MANUAL:
    new_rules.append([rid, name, ["tcp", "", "", ",".join(hs), "", "", "", ""], hs, []])
new_rules.sort(key=lambda r: r[0])

# ---- transform: one host per feature; plain single feature for sub-service
#      hosts (bare apex) AND TLD-less official truncations (music.163 ..),
#      else '.host' AC pattern + exact-apex regex; verbs appended verbatim ----
def render_rule(rid, name, fl, hosts, verb=()):
    proto, sport, dport = fl[0], fl[1], fl[2]
    req, dic, sea, ign = fl[4], fl[5], fl[6], fl[7]
    feats = []
    seen = set()
    for h in hosts:
        h = canon(h)
        if h in seen: continue
        seen.add(h)
        if use_plain(h):   # plain: 子服务宿主匹配裸域顶点 + TLD-less 官方截断（点形式匹配不到 apex）
            feats.append(f"{proto};{sport};{dport};{h};{req};{dic};{sea};{ign}")
            continue
        feats.append(f"{proto};{sport};{dport};.{h};{req};{dic};{sea};{ign}")
        rx = apex_rx(h)
        if rx:
            feats.append(f"{proto};{sport};{dport};{rx};{req};{dic};{sea};{ign}")
        else:
            APEX_SKIPPED.append(h)
    feats.extend(verb)   # official verbatim features byte-identical
    return f"{rid}~{name}:[{','.join(feats)}]"

all_src = final + new_rules

# ---- rename domain-like labels -> researched friendly names ----
# (auto-range: domain-keyed — 自动 id 随新增 registrable 漂移，不能做键；id<20433 源规则 id 稳定)
# 改名时机与旧版 id 覆盖一致：赋 id 之后、同名合并之前，保证基线 id 消耗/空洞不变)
from name_overrides import NAME_OVERRIDE, NAME_AUTO_OVERRIDE   # generated by gen_name_overrides.py
for rec in all_src:
    if rec[0] in NAME_OVERRIDE:
        rec[1] = NAME_OVERRIDE[rec[0]]
    elif rec[0] >= 20433 and rec[3]:
        reg = registrable(rec[3][0])
        if reg in NAME_AUTO_OVERRIDE:
            rec[1] = NAME_AUTO_OVERRIDE[reg]

# ---- merge same-name rules: keep lowest id, union hosts+verbs (fields must match) ----
groups = {}
for rec in all_src:
    groups.setdefault(rec[1], []).append(rec)
merged = []
n_mgroup = 0
for name, recs in groups.items():
    if len(recs) == 1:
        merged.append(recs[0])
        continue
    recs.sort(key=lambda r: r[0])
    if len({tuple(r[2][:3] + r[2][4:]) for r in recs}) > 1:   # fl[3] is the hosts string itself
        merged.extend(recs)   # feature fields differ -> keep separate
        print(f"NOTE not merged (field mismatch): {name} ids {[r[0] for r in recs]}")
        continue
    hosts = []; verb = []
    for r in recs:
        for h in r[3]:
            if h not in hosts: hosts.append(h)
        for v in r[4]:
            if v not in verb: verb.append(v)
    merged.append([recs[0][0], name, recs[0][2], hosts, verb])
    n_mgroup += 1
n_before = len(all_src)
all_src = sorted(merged, key=lambda r: r[0])
print(f"merged {n_mgroup} same-name groups: rules {n_before} -> {len(all_src)}")

# ---- HOST_ADDS: official extra domains/verbs onto existing rules ----
names_present = {r[1] for r in all_src}
n_hadd = 0
for name, (doms, verbs) in HOST_ADDS.items():
    if name not in names_present:
        print(f"NOTE HOST_ADDS name missing: {name}")
        continue
    rec = next(r for r in all_src if r[1] == name)
    for d in doms:
        if d not in rec[3]: rec[3].append(d)
    for v in verbs:
        if v not in rec[4]: rec[4].append(v)
    n_hadd += 1
print(f"HOST_ADDS applied: {n_hadd}/{len(HOST_ADDS)}")

# ---- ID_MAP adoption: official appid for our same-name rules (no id collision:
#      official <=14027, ours >=20001; skip + NOTE if adoption would duplicate) ----
used_ids = {r[0] for r in all_src}
adopted = []
for rec in all_src:
    oid = ID_MAP.get(rec[1])
    if oid is None or rec[0] == oid: continue
    if oid in used_ids:
        print(f"NOTE id adoption skipped (dup id {oid}): {rec[1]} keeps {rec[0]}")
        continue
    used_ids.add(oid)
    adopted.append((oid, rec[1]))
    rec[0] = oid
print(f"adopted {len(adopted)} official ids: "
      + ", ".join(f"{i}~{n}" for i, n in adopted[:5]) + (" ..." if len(adopted) > 5 else ""))

# ---- append NEW_APPS (official-only apps we lack) ----
for rid, name, cls_off, doms, verbs in NEW_APPS:
    all_src.append([rid, name, ["tcp", "", "", "", "", "", "", ""], list(doms), list(verbs)])
all_src = sorted(all_src, key=lambda r: r[0])
print(f"NEW_APPS appended: {len(NEW_APPS)}  total rules: {len(all_src)}")

# ---- data bug fix: official file swaps the 1905电影 / 豆瓣电影 hosts ----
FIX1905 = {"1905电影": ["1905.com"], "豆瓣电影": ["movie.douban.com"]}
for rec in all_src:
    if rec[1] in FIX1905 and rec[3] != FIX1905[rec[1]]:
        print(f"NOTE 1905/豆瓣 host swap fix: {rec[1]} {rec[3]} -> {FIX1905[rec[1]]}")
        rec[3] = FIX1905[rec[1]][:]

# ---- fold proper sub-domains onto their apex inside the same rule (parent's
#      '.apex' dot feature already matches them; form-aware redundancy flags them) ----
for rec in all_src:
    hs = rec[3]
    keep = [h for h in hs if not any(h != o and h.endswith("." + o) for o in hs)]
    if len(keep) != len(hs):
        print(f"NOTE folded sub-hosts {rec[1]}: {[h for h in hs if h not in keep]}")
        rec[3] = keep

# ---- class assignment (stored per rec so split chunks inherit it) ----
n_kw = 0
for rec in all_src:
    c = CLASS_MAP.get(rec[1])
    if c is None:
        c = guess_class(rec[1]); n_kw += 1
    rec.append(c)
print(f"class assigned: CLASS_MAP hits={sum(1 for r in all_src if r[1] in CLASS_MAP)}  keyword={n_kw}")

all_bases = {canon(h) for _, _, _, hs, _vb, _c in all_src for h in hs}

def is_sub(h):   # 另一条规则的基域是 h 的真后缀 → 子服务（如 video.qq.com 在 qq.com 规则下）
    b = canon(h)
    return any(b != o and b.endswith("." + o) for o in all_bases)

def use_plain(h):   # plain emission: sub-service apex OR TLD-less official truncation
    b = canon(h)
    return is_sub(b) or b.split(".")[-1] not in TLD_ALL

APEX_SKIPPED = []
# ---- split rules whose rendered line >= 800B (kernel MAX_FEATURE_LINE_LEN) ----
# items = hosts + verbatim features (cost of verb = len(string)); chunks carry
# their subset of both; first chunk keeps rid, later chunks get next_id.
LINE_LIMIT = 800
next_id = max(r[0] for r in all_src) + 1
n_split = 0
split_out = []
for rid, name, fl, hs, vb, cls in all_src:
    if len(render_rule(rid, name, fl, hs, vb)) < LINE_LIMIT:
        split_out.append([rid, name, fl, hs, vb, cls])
        continue
    base = len(f"{rid}~{name}:[]")
    base_c = max(base, len(f"{next_id}~{name}:[]"))   # chunk ids may gain a digit
    seen = set(); items = []
    for h in hs:          # canon-dedup like render does (expect counts unique)
        c = canon(h)
        if c in seen: continue
        seen.add(c); items.append(("h", c))
    for v in vb:
        items.append(("v", v))
    costs = [(k, x, len(render_rule(rid, name, fl, [x])) - base if k == "h" else len(x))
             for k, x in items]
    total = sum(c for _, _, c in costs)
    k = 1
    while True:
        # balanced contiguous partition into k parts
        target = total / k
        parts, acc, acc_cost, cuts = [], [], 0.0, k - 1
        for i, item in enumerate(costs):
            acc.append(item)
            acc_cost += item[2]
            if cuts > 0 and acc_cost >= target and len(costs) - (i + 1) >= cuts:
                parts.append(acc)
                acc, acc_cost, cuts = [], 0.0, cuts - 1
        if acc:
            parts.append(acc)
        # line_len = base + sum(costs) + (len-1) commas
        if all(base_c + sum(c for _, _, c in p) + (len(p) - 1) < LINE_LIMIT for p in parts):
            break
        k += 1
        if k > len(costs):
            break   # single-item parts; unfixable if still >= limit
    ids = [rid] + [next_id + j for j in range(len(parts) - 1)]
    next_id += len(parts) - 1
    for pid, p in zip(ids, parts):
        ch = [x for kk, x, _ in p if kk == "h"]
        cv = [x for kk, x, _ in p if kk == "v"]
        split_out.append([pid, name, fl, ch, cv, cls])
    if len(parts) > 1:
        n_split += 1
        print(f"NOTE split >={LINE_LIMIT}B: {name} -> ids {ids} parts "
              f"{[(sum(1 for kk, _, _ in q if kk == 'h'), sum(1 for kk, _, _ in q if kk == 'v')) for q in parts]}")
if n_split:
    print(f"split {n_split} oversized rules -> {len(split_out)} lines")
all_src = sorted(split_out, key=lambda r: r[0])

# ---- write official-style: 4 headers + #class sections, rules sorted by id ----
lines_out = []
with open(OUT, "w", encoding="utf-8") as f:
    f.write("#version 26.09.29\n#format v4.0\n#type 0\n#free 1\n")
    for c in CLASS_ORDER:
        f.write(f"#class {CLASS_KEYS[c]} {c} {CLASS_NAMES[c]}\n")
        for rid, name, fl, hs, vb, cls in sorted((r for r in all_src if r[5] == c),
                                                 key=lambda r: r[0]):
            ln = render_rule(rid, name, fl, hs, vb)
            f.write(ln + "\n")
            lines_out.append(ln)
print(f"new rules: {len(new_rules)} ids 20433-{max(r[0] for r in new_rules)}  total lines: {len(lines_out)}")
dist = collections.Counter(r[5] for r in all_src)
print("class distribution: " + "  ".join(f"{CLASS_KEYS[c]}={dist[c]}" for c in CLASS_ORDER))

# ---- validation on transformed output (round-trip from OUT, '#' lines skipped) ----
errs = []
raw_out = open(OUT, encoding="utf-8").read().splitlines()
check_lines = [l for l in raw_out if not l.startswith("#")]
if check_lines != lines_out: errs.append("write round-trip mismatch")
if raw_out[:4] != ["#version 26.09.29", "#format v4.0", "#type 0", "#free 1"]:
    errs.append(f"header mismatch: {raw_out[:4]}")
class_seen = {l.split()[1] for l in raw_out if l.startswith("#class ")}
missing_cls = [CLASS_KEYS[c] for c in CLASS_ORDER if CLASS_KEYS[c] not in class_seen]
if missing_cls: errs.append(f"missing #class sections: {missing_cls}")

LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

def parse_pat(p):
    r"""-> ('exact', base) | ('prefix', first-label) | None
    exact: '.h' dot form or ^h[*]*$ / ^<h-minus-last>last*$ apex regex.
    prefix: form3 ^label\..*$ -> mid ends with \\ + .* star."""
    if p.startswith("."):
        b = p[1:]
        return ("exact", b) if b and not b.startswith(".") else None
    if p.startswith("^") and p.endswith("$"):
        mid = p[1:-1]
        if mid.endswith("[*]*"): esc_b = mid[:-4]
        elif mid.endswith(r"\..*"):
            return ("prefix", mid[:-4].replace("\\.", "."))
        elif mid.endswith("*"): esc_b = mid[:-1]
        else: return None
        if not esc_b or "\\" in esc_b.replace(r"\.", ""): return None
        return ("exact", esc_b.replace("\\.", "."))
    if p and p[0] not in ".^":   # plain sub-service / TLD-less pattern
        return ("exact", p)
    return None

seen_ids = {}; bases_by_rule = {}; rule_chunks = {}; nfeat = 0
for line in check_lines:
    rid_s, rest = line.split("~", 1)
    rid = int(rid_s)
    name, body = rest.split(":[", 1)
    body = body.rstrip("]")
    if rid in seen_ids: errs.append(f"dup id {rid}")
    seen_ids[rid] = 1
    if not (1 <= rid < 20900): errs.append(f"id range {rid} {name}")
    if not (1 <= len(name.encode()) <= 63): errs.append(f"name len {rid} {name}")
    if re.search(r"[#~:;,\[\]]", name): errs.append(f"name charset {rid} {name}")
    if len(line.encode()) >= 800: errs.append(f"line len {rid} {len(line.encode())}")
    blist = []; plist = []; loose_l = []; nch = 0
    for chunk in body.split(","):
        nfeat += 1; nch += 1
        f = chunk.split(";")
        if not (4 <= len(f) <= 8):
            errs.append(f"bad chunk nfields={len(f)} {rid} {name}: {chunk[:60]}")
            continue
        if f[0] not in ("tcp", "udp"): errs.append(f"bad proto {rid} {f[0]}")
        p = f[3]
        if not p:
            # hostless chunk = payload-only feature; legal iff dport/request/dict/...
            if not any(f[i] for i in (2, 4, 5, 6, 7) if i < len(f)):
                errs.append(f"hostless chunk without payload {rid} {name}: {chunk[:60]}")
            continue
        if p in LOOSE:
            loose_l.append(p)   # official loose substring: skip domain/PSL/IP checks
            continue
        if len(p) > 31: errs.append(f"host_url>31 {rid} {p}")
        parsed = parse_pat(p)
        if parsed is None: errs.append(f"pattern form {rid} {p}"); continue
        kind, val = parsed
        if kind == "exact":
            if IP_RE.match(val): errs.append(f"bare IP {rid} {val}")
            if val in PSL_BARE: errs.append(f"PSL parent {rid} {val}")
            if not HOST_RE.match(val): errs.append(f"host charset {rid} {val}")
            blist.append(val)
        else:
            if not LABEL_RE.match(val): errs.append(f"prefix label {rid} {val}")
            plist.append(val)
    bases_by_rule[rid] = (name, sorted(set(blist)), sorted(set(plist)), sorted(set(loose_l)))
    rule_chunks[rid] = nch
    for y in set(blist):
        # form-aware: actual AC text p(b)=b(plain/sub) or '.'+b(dot); y adds nothing if p(x) in p(y)
        # (loose patterns are never in blist: only identical loose dups would be
        #  flagged and identicals are skipped by x != y — official keeps both)
        if any(x != y and (px := (x if use_plain(x) else "." + x)) in (py := (y if use_plain(y) else "." + y))
               for x in blist): errs.append(f"within-rule redundant {rid} {name}: {y}")

# ---- cross-rule prefix-steal on actual AC forms (dot for domains, text for loose) ----
# pairs: (rid, pattern, is_loose)
SAME_OWNER_STEAL = {("vivo.com", "vivo.com.cn")}   # same vendor, unavoidable
pairs = []
for rid, (_, bl, _pl, lol) in bases_by_rule.items():
    for b in bl: pairs.append((rid, b, False))
    for l in lol: pairs.append((rid, l, True))
for i, (r1, a, la) in enumerate(pairs):
    for r2, b, lb in pairs[i+1:]:
        if r1 == r2: continue
        da = a if la else "." + a
        db = b if lb else "." + b
        if da == db:
            # official keeps same-owner duplicates across rules (wan.baidu.com,
            # 58.com): identical patterns are attribution-ambiguous, not steals
            print(f"NOTE equal-host across rules {r1}/{r2}: {a}")
            continue
        # known same-owner pair: our 'vivo' (vivo.com) vs official 'vivo官网'
        # (vivo.com.cn). '.vivo.com' matches www.vivo.com.cn at an earlier AC
        # end — unavoidable given both official datasets; same vendor, so the
        # engine resolution is acceptable (analogous to sim LEFT_MID_XC).
        if da in db and not db.endswith(da):
            m = f"prefix-steal {r1}:{a} steals {r2}:{b}"
            if la or lb: print(f"NOTE loose-steal {m}")
            elif (a, b) in SAME_OWNER_STEAL: print(f"NOTE same-owner steal {m}")
            else: errs.append(m)
        elif db in da and not da.endswith(db):
            m = f"prefix-steal {r2}:{b} steals {r1}:{a}"
            if la or lb: print(f"NOTE loose-steal {m}")
            elif (b, a) in SAME_OWNER_STEAL: print(f"NOTE same-owner steal {m}")
            else: errs.append(m)

# pattern-aware steal: actual AC text (plain for sub/TLD-less, dot otherwise,
# raw text for loose) matching inside another base before its end -> earliest-end
# wins for that host (bypasses the dot-boundary protection above)
raw_p = {p: (p if (lo or use_plain(p)) else "." + p) for _, p, lo in pairs}
for i, (r1, a, la) in enumerate(pairs):
    for r2, b, lb in pairs[i+1:]:
        if r1 == r2: continue
        if raw_p[a] in b[:-1]:
            m = f"raw-steal {r1}:{a} inside {r2}:{b}"
            if la or lb: print(f"NOTE loose-steal {m} (official intended substring)")
            else: errs.append(m)
        if raw_p[b] in a[:-1]:
            m = f"raw-steal {r2}:{b} inside {r1}:{a}"
            if la or lb: print(f"NOTE loose-steal {m} (official intended substring)")
            else: errs.append(m)

# form3 prefix: no other rule's exact host may sit under label." ""
for rid, (_, _bl, pl, _lo) in bases_by_rule.items():
    for lab in pl:
        for rid2, (_n2, bl2, _p2, _l2) in bases_by_rule.items():
            if rid2 == rid: continue
            for b2 in bl2:
                if b2.startswith(lab + "."):
                    errs.append(f"prefix-overlap {rid}: ^{lab}\\. matches {rid2}:{b2}")

# ---- source -> output consistency: per-rule expected chunk count + name ----
def nfeat_of(hs, vb):
    seen = set(); n = 0
    for h in hs:
        c = canon(h)
        if c in seen: continue
        seen.add(c)
        n += 1 if use_plain(c) else (2 if apex_rx(c) else 1)
    return n + len(vb)

src = {}
for rid, name, fl, hs, vb, cls in all_src:
    if not hs and not vb:
        errs.append(f"empty rule (no hosts, no verb) {rid} {name}")
    src[rid] = (name, nfeat_of(hs, vb), sorted({canon(h) for h in hs}), list(vb))
if len(check_lines) != len(all_src): errs.append("line count mismatch")
for rid, (sname, exp, shs, svb) in src.items():
    if rid not in bases_by_rule: errs.append(f"missing {rid}"); continue
    on, oe, op, oloose = bases_by_rule[rid]
    if on != sname: errs.append(f"name changed {rid}")
    if rule_chunks.get(rid) != exp:
        errs.append(f"chunk count {rid} {sname}: {rule_chunks.get(rid)} != {exp}")
    if oe != shs: errs.append(f"hosts changed {rid}: {oe} != {shs}")
    exp_loose = sorted({v.split(";")[3] for v in svb
                        if (ff := v.split(";"))[3] and ff[3] in LOOSE})
    if oloose != exp_loose:
        errs.append(f"loose hosts changed {rid}: {oloose} != {exp_loose}")
    exp_p = sorted({h.split(".")[0] for h in shs
                    if not use_plain(h) and (ax := apex_rx(h)) and ax.endswith(r"\..*$")})
    if op != exp_p: errs.append(f"apex-prefix mismatch {rid}: {op} != {exp_p}")
expect = sum(e for _, e, _, _ in src.values())
if nfeat != expect: errs.append(f"features {nfeat} != expect {expect}")

import hashlib
old_md5 = hashlib.md5(open(f"{TMP}/features_rules_final.txt", "rb").read()).hexdigest()[:12]
new_md5 = hashlib.md5(open(OUT, "rb").read()).hexdigest()
print(f"features written: {nfeat} (expect {expect})")
if APEX_SKIPPED: print(f"apex-regex skipped (host>31): {APEX_SKIPPED}")
print(f"md5 old={old_md5} new={new_md5}")
print(f"VALIDATION: {'OK' if not errs else str(len(errs))+' errors'}")
for e in errs[:40]: print("  ERR", e)
if errs:
    print("!!! OUTPUT INVALID — DO NOT PACK !!!", file=sys.stderr)
out_rids = {int(l.split("~", 1)[0]) for l in check_lines}
print("\nNEW RULES:")
for rec in new_rules:   # recs grew a class slot via all_src aliases
    if rec[0] not in out_rids: continue   # merged-away orphan not in written OUT
    rid, name, fields, hs, vb = rec[:5]
    print(f"  {rid}~{name}  hosts={','.join(hs)}" + (f"  verb={len(vb)}" if vb else ""))
sys.exit(1 if errs else 0)  # non-zero on validation errors (pipeline fail-fast)
