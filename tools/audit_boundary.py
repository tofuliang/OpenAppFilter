#!/usr/bin/env python3
"""Audit all host rules for mid-label substring-catch risk.

Corpus = draft observed hosts + raw rules hosts + official rule hosts.
For each rule host pattern p, find corpus host d where p occurs in d
BUT NOT at label boundary (i.e. preceded by a non-dot char) -> catches d wrongly.
"""
import re, collections, sys
import os

TMP = os.environ.get("OAF_TMP", "/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode")

def hosts_of(field):
    # hosts field is comma separated in our rules; official uses plain tokens
    out = []
    for t in field.split(","):
        t = t.strip().lower()
        if t:
            out.append(t)
    return out

def parse_rule_hosts(line):
    """return list of host patterns from a rule line `id~name:[proto;..;hosts;..,..]`"""
    line = line.strip()
    if not line or line.startswith("#"):
        return []
    m = re.match(r'^(\d+)~([^:]+):\[(.*)\]\s*$', line)
    if not m:
        return []
    body = m.group(3)
    hosts = []
    # split into comma-separated features, but hosts field is 4th ;-field inside brackets
    # features are comma-separated groups of proto;sport;dport;host;req;dict;search;ignore
    # careful: some fields may contain commas (dict uses |, search uses |). Official: dict/search use |.
    for feat in body.split(","):
        parts = feat.split(";")
        if len(parts) >= 4 and parts[3].strip():
            hosts.extend(hosts_of(parts[3]))
    return hosts

def parse_draft_hosts(line):
    """return list of hosts from a draft line `kind|host`"""
    line = line.strip()
    if not line or line.startswith("#") or "|" not in line:
        return []
    h = line.split("|", 1)[1].strip().lower()
    return [h] if h else []

def load_rules(path):
    pats = []
    with open(path) as f:
        for line in f:
            for h in parse_rule_hosts(line):
                pats.append(h)
    return pats

def load_corpus():
    corpus = set()
    # draft observed hosts (features_draft.txt) - kind|host lines, not rule format
    for fn in ["features_draft.txt", "features_rules.txt", "feature_official.txt", "oaf_raw_rules.txt"]:
        try:
            with open(f"{TMP}/{fn}") as f:
                for line in f:
                    parse = parse_draft_hosts if fn == "features_draft.txt" else parse_rule_hosts
                    for h in parse(line):
                        corpus.add(h)
        except FileNotFoundError:
            pass
    # also raw host dump if exists (urlcheck dir)
    return corpus

def mid_label_occurrences(p, d):
    """yield positions where p occurs in d NOT at label boundary"""
    res = []
    start = 0
    while True:
        i = d.find(p, start)
        if i < 0:
            break
        if i > 0 and d[i-1] != ".":
            res.append(i)
        start = i + 1
    return res

def main():
    rules_path = sys.argv[1] if len(sys.argv) > 1 else f"{TMP}/features_rules_final_new.txt"
    corpus = load_corpus()
    rules = load_rules(rules_path)
    print(f"rules: {len(rules)} host patterns, corpus: {len(corpus)} hosts")

    hits = []
    for p in sorted(set(rules)):
        for d in corpus:
            if p == d:
                continue
            occ = mid_label_occurrences(p, d)
            if occ:
                hits.append((p, d, occ))

    # group by pattern
    by_pat = collections.defaultdict(list)
    for p, d, occ in hits:
        by_pat[p].append((d, occ))

    print(f"\nMID-LABEL CATCH: {len(by_pat)} patterns catch {len(hits)} corpus hosts wrongly")
    for p in sorted(by_pat, key=lambda x: -len(by_pat[x])):
        ex = by_pat[p][:6]
        exs = ", ".join(f"{d}@{o}" for d, o in ex)
        print(f"  {p:35s} x{len(by_pat[p]):3d}  e.g. {exs}")

    # Also: prefix-tail (p at boundary but d continues beyond p -> different registrable)
    print("\n--- TAIL-OVERREACH (p matches d but d has more labels after p) ---")
    tail = []
    for p in sorted(set(rules)):
        for d in corpus:
            if d == p or not d.startswith(p):
                continue
            if len(d) > len(p) and d[len(p)] == ".":
                tail.append((p, d))
    for p, d in tail[:40]:
        print(f"  {p:35s} -> {d}")
    print(f"  total tail-overreach pairs: {len(tail)}")

if __name__ == "__main__":
    main()
