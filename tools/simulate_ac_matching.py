#!/usr/bin/env python3
"""Simulate the engine match pipeline on a bare-domain corpus.

Pipeline modeled (fwx_main.c):
  step 1 AC  : dot patterns; earliest END index wins, longest pattern at
               the same end index (output_list before fail chain).
  step 2/3 rx: caret patterns via re.fullmatch (equivalent to K&R regex for
               our ^h[*]*$ / ^<h..>last*$ / ^label\\..*$ forms).
Buckets:
  EXACT     d == base            (regex apex hit, or dot match ending at len)
  SUFFIX    d endswith '.'+base  (label-boundary suffix -- correct)
  LEFT-MID  match starts inside a label (the bug class; MUST be 0)
  TAIL      match ends before end of d (more labels after)
  UNCLASS   no winner (+ whether a correct rule exists)
"""
import re
import sys
import os

TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")
OUT = os.path.join(TMP, "features_rules_final_new.txt")

RULE_LINE = re.compile(r"^(\d+)~(.+?):\[(.*)\]$")
CORPUS_OK = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
IP_OK = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.-]*\.[a-z0-9.-]+")

# Known, accepted label-boundary exceptions (same owner, correct final label).
LEFT_MID_XC = {"zenvideo.qq.com"}   # plain 'video.qq.com' mid-label; zenvideo 是腾讯视频转码域
# official loose substring patterns (douyin, -dy-, zhaopin, liveplay, ...):
# LEFT-MID hits by these are intended official AC behavior -> bucket LOOSE
from official_gap_data import OFFICIAL_LOOSE
LOOSE_PAT = set(OFFICIAL_LOOSE)


def features_of(body):
    for chunk in body.split(","):
        f = chunk.split(";")
        # accept 4-8 field styles (our 8f, official 6f verbatim, odd 7f)
        if 4 <= len(f) <= 8 and f[3]:
            yield f[3]


def load_rules(path):
    ac, rx, bases, names = [], [], {}, {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = RULE_LINE.match(line)
        if not m:
            continue
        rid, name, body = int(m.group(1)), m.group(2), m.group(3)
        names[rid] = name
        bs = set()
        for p in features_of(body):
            if p.startswith("^"):
                rx.append((rid, p))
            else:
                ac.append((rid, p))
                bs.add(p[1:] if p.startswith(".") else p)
        bases[rid] = bs
    return ac, rx, bases, names


def load_corpus(ac, extra_files):
    hosts = set()
    # rules' own base domains (every host has a dot-feature)
    for _rid, p in ac:
        if p.startswith("."):
            hosts.add(p[1:])
    for fn in extra_files:
        if not os.path.exists(fn):
            print(f"  (missing corpus file: {fn})")
            continue
        for line in open(fn, encoding="utf-8"):
            if line.startswith("#"):
                continue
            for tok in TOKEN_RE.findall(line.lower()):
                tok = tok.rstrip(".")
                if "." not in tok or IP_OK.match(tok) or not CORPUS_OK.match(tok):
                    continue
                hosts.add(tok)
    return sorted(hosts)


def match_ac(d, ac):
    best_end, best = None, []
    for rid, p in ac:
        i = d.find(p)
        if i < 0:
            continue
        fe = i + len(p)
        if best_end is None or fe < best_end:
            best_end, best = fe, [(rid, p, i)]
        elif fe == best_end:
            best.append((rid, p, i))
    if best_end is None:
        return None
    best.sort(key=lambda t: -len(t[1]))
    rid, p, i = best[0]
    return ("ac", rid, p, i, best_end)


def match_rx(d, rx):
    for rid, p in rx:
        if re.fullmatch(p, d):
            return ("rx", rid, p)
    return None


def classify(d, hit, bases):
    step, rid, p = hit[0], hit[1], hit[2]
    if step == "ac":
        base = p[1:] if p.startswith(".") else p
        i, fe = hit[3], hit[4]
        left_ok = p.startswith(".") or i == 0 or d[i - 1] == "."
        if not left_ok:
            return ("LEFT-MID", rid, base, i, fe)
        if fe < len(d):
            return ("TAIL", rid, base, i, fe)
        if d == base:
            return ("EXACT", rid, base, i, fe)
        return ("SUFFIX", rid, base, i, fe)
    # regex
    if p.endswith(r"\..*$"):
        lab = p[1:-5].replace("\\.", ".")
        return ("EXACT", rid, lab + ".*", None, None)
    body = p[1:-1]
    if body.endswith("[*]*"):
        base = body[:-4].replace("\\.", ".")
    elif body.endswith("*"):
        base = body[:-1].replace("\\.", ".")
    else:
        return ("RX-ODD", rid, p, None, None)
    if d == base:
        return ("EXACT", rid, base, None, None)
    return ("RX-NEAR", rid, f"{base} (matched {d})", None, None)


def correct_rule_exists(d, bases):
    for rid, bs in bases.items():
        for b in bs:
            if d == b or d.endswith("." + b):
                return rid
    return None


def main():
    rules_path = sys.argv[1] if len(sys.argv) > 1 else OUT
    ac, rx, bases, names = load_rules(rules_path)
    print(f"rules: ac={len(ac)} rx={len(rx)}")
    corpus = load_corpus(ac, [os.path.join(TMP, f) for f in (
        "features_draft.txt", "features_rules.txt",
        "feature_official.txt", "oaf_raw_rules.txt",
    )])
    print(f"corpus: {len(corpus)} bare domains")
    if len(ac) < 800 or len(corpus) < 3000:
        print(f"corpus/AC suspiciously small: ac={len(ac)} words={len(corpus)} — refusing to report PASS", file=sys.stderr)
        sys.exit(1)

    buckets = {}
    for d in corpus:
        hit = match_ac(d, ac)
        if hit is None:
            h = match_rx(d, rx)
            if h is None:
                rid = correct_rule_exists(d, bases)
                entry = (d, rid, names.get(rid) if rid else None)
                buckets.setdefault("UNCLASS", []).append(entry)
                continue
            hit = (h[0], h[1], h[2], None, None)
        cat, rid, base, i, fe = classify(d, hit, bases)
        if cat == "LEFT-MID" and d in LEFT_MID_XC:   # known same-owner, correct label
            cat = "LEFT-MID-XC"
        elif cat == "LEFT-MID" and hit[2] in LOOSE_PAT:
            # catching pattern is an official loose substring: official intends
            # mid-label AC matching for it (e.g. idouyinvod.com <- 'douyin')
            cat = "LOOSE"
        buckets.setdefault(cat, []).append((d, rid, base, i, fe))

    order = ["EXACT", "SUFFIX", "TAIL", "LEFT-MID", "LEFT-MID-XC", "LOOSE", "RX-NEAR", "RX-ODD", "UNCLASS"]
    print("\n=== summary ===")
    for cat in order:
        if cat in buckets:
            print(f"  {cat:8} {len(buckets[cat])}")

    if buckets.get("LEFT-MID"):
        print("\n=== LEFT-MID (bug class, must be 0) ===")
        for d, rid, base, i, fe in buckets["LEFT-MID"]:
            print(f"  {d} -> {rid}:{names.get(rid)} via '{base}' [{i}:{fe}]")

    if buckets.get("LOOSE"):
        print("\n=== LOOSE (official loose substring, accepted - not a failure) ===")
        for d, rid, base, i, fe in buckets["LOOSE"]:
            print(f"  {d} -> {rid}:{names.get(rid)} via '{base}' [{i}:{fe}]")

    if buckets.get("TAIL"):
        print("\n=== TAIL (label-boundary left, more labels right) ===")
        for d, rid, base, i, fe in buckets["TAIL"]:
            print(f"  {d} -> {rid}:{names.get(rid)} via '.{base}' [{i}:{fe}]")

    if buckets.get("RX-NEAR") or buckets.get("RX-ODD"):
        print("\n=== regex oddities ===")
        for cat in ("RX-NEAR", "RX-ODD"):
            for e in buckets.get(cat, []):
                print(f"  {cat} {e}")

    if buckets.get("UNCLASS"):
        print("\n=== UNCLASSIFIED ===")
        for d, rid, name in buckets["UNCLASS"]:
            note = f"correct rule exists: {rid}:{name}" if rid else "no rule"
            print(f"  {d}  ({note})")

    lm = len(buckets.get("LEFT-MID", []))
    print(f"\nLEFT-MID count: {lm} (baseline old sim: 23 misclassified)")
    print("RESULT:", "PASS" if lm == 0 else "FAIL")
    sys.exit(0 if lm == 0 else 1)  # non-zero on FAIL (pipeline fail-fast)


if __name__ == "__main__":
    main()
