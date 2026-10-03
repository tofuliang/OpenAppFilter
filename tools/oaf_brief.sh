#!/bin/sh
# OAF brief: periodically summarize newly captured domains + new feature rules.
# Appends a readable brief to /tmp/pcap/brief.log and pushes to WeChat (qywx)
# when there is anything new. Usage: sh /tmp/oaf_brief.sh        (one round)
#                                    sh /tmp/oaf_brief.sh loop   (every 30min)
DRAFT=/tmp/pcap/features_draft.txt
RULES=/tmp/pcap/features_rules.txt
LOG=/tmp/pcap/brief.log
PREV_D=/tmp/pcap/.brief_draft_prev
PREV_R=/tmp/pcap/.brief_rules_prev
T=/tmp/pcap/.brief_tmp.$$

rotate_log() {
  # brief.log 每轮写入前检查：超过 100KB 只保留末尾 50KB
  [ -f "$LOG" ] || return 0
  sz=$(wc -c < "$LOG")
  [ "$sz" -gt 102400 ] || return 0
  tail -c 51200 "$LOG" > "$LOG.rot.$$" && mv "$LOG.rot.$$" "$LOG"
}

push_qywx() {
  rotate_log
  # $1 = markdown content
  cid=$(uci -q get wechatpush.config.corpid)
  [ -n "$cid" ] || { echo "$(date "+%F %T") push_skip:no_corpid" >> "$LOG"; return 1; }
  sec=$(uci -q get wechatpush.config.corpsecret)
  uid=$(uci -q get wechatpush.config.userid)
  aid=$(uci -q get wechatpush.config.agentid)
  [ -n "$uid" ] || { echo "$(date "+%F %T") push_skip:no_userid" >> "$LOG"; return 1; }
  [ -n "$aid" ] || { echo "$(date "+%F %T") push_skip:no_agentid" >> "$LOG"; return 1; }
  tok=$(curl -s --connect-timeout 10 --max-time 20 \
    "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=${cid}&corpsecret=${sec}" \
    | jq -r '.access_token // empty')
  if [ -z "$tok" ]; then
    echo "$(date "+%F %T") push_fail:gettoken" >> "$LOG"
    return 1
  fi
  # markdown hard limit 4096B: keep head
  c=$(printf '%s' "$1" | head -c 3800)
  body=$(jq -n --arg u "$uid" --arg a "$aid" --arg c "$c" \
    '{touser:$u, msgtype:"markdown", agentid:($a|tonumber), markdown:{content:$c}}')
  resp=$(curl -s --connect-timeout 10 --max-time 20 -X POST \
    -H "Content-Type: application/json" -d "$body" \
    "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=${tok}")
  echo "$(date "+%F %T") push_resp: $resp" >> "$LOG"
}

run_once() {
  rotate_log
  [ -f /tmp/pcap/STOP_FLAG ] && return 0
  [ -f "$DRAFT" ] || return 0
  mkdir -p /tmp/pcap

  LC_ALL=C sort "$DRAFT" > "$T.d" 2>/dev/null
  [ -f "$RULES" ] && sed 's/^[0-9][0-9]*~//' "$RULES" | LC_ALL=C sort > "$T.r" || : > "$T.r"

  if [ ! -f "$PREV_D" ] || [ ! -f "$PREV_R" ]; then
    cp "$T.d" "$PREV_D"; cp "$T.r" "$PREV_R"
    echo "$(date "+%F %T") brief_init draft=$(grep -c . "$T.d") rules=$(grep -c . "$T.r")" >> "$LOG"
    rm -f "$T".*
    return 0
  fi

  awk 'NR==FNR{p[$0]=1;next}!($0 in p)' "$PREV_D" "$T.d" > "$T.dn"
  awk 'NR==FNR{p[$0]=1;next}!($0 in p)' "$PREV_R" "$T.r" > "$T.rn"
  # keep only domain-looking entries (drop http| hex blobs etc.)
  sed 's/^[a-z][a-z]*|//' "$T.dn" | grep -Ei '\.[a-z]{2,}$' | grep -Ei '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$' | LC_ALL=C sort -u > "$T.dom" || : > "$T.dom"
  nd=$(grep -c . "$T.dom"); nr=$(grep -c . "$T.rn")
  dt=$(grep -c . "$T.d"); rt=$(grep -c '^[0-9]' "$RULES" 2>/dev/null); [ -z "$rt" ] && rt=0
  ts=$(date "+%F %T")

  if [ "$nd" -eq 0 ] && [ "$nr" -eq 0 ]; then
    echo "$ts no_new draft=$dt rules=$rt" >> "$LOG"
    # still refresh prev (draft may gain filtered-out junk only)
    cp "$T.d" "$PREV_D"; cp "$T.r" "$PREV_R"
    rm -f "$T".*
    return 0
  fi

  {
    echo "== $ts new_domains=$nd new_rules=$nr draft=$dt rules=$rt =="
    if [ "$nd" -gt 0 ]; then
      echo "-- new domains --"
      cat "$T.dom"
    fi
    if [ "$nr" -gt 0 ]; then
      echo "-- new rules --"
      awk 'NR==FNR{n[$0]=1;next}{c=$0;sub(/^[0-9]+~/,"",c);if(c in n)print}' "$T.rn" "$RULES"
    fi
  } >> "$LOG"

  # push brief when there is news
  md=$( { echo "#### OAF 简报"
    echo "新域名 **$nd** 条 · 新特征 **$nr** 条（累计 draft=$dt rules=$rt）"
    if [ "$nd" -gt 0 ]; then
      echo ""
      echo "**新抓到的域名：**"
      head -n 15 "$T.dom" | sed 's/^/> /'
      [ "$nd" -gt 15 ] && echo "> …等 $nd 条，详见 brief.log"
    fi
    if [ "$nr" -gt 0 ]; then
      echo ""
      echo "**新特征：**"
      awk 'NR==FNR{n[$0]=1;next}{c=$0;sub(/^[0-9]+~/,"",c);if(c in n){sub(/:.*$/,"",$0);print "> "$0}}' "$T.rn" "$RULES" | head -n 10
      [ "$nr" -gt 10 ] && echo "> …等 $nr 条"
    fi
  } )
  push_qywx "$md"

  cp "$T.d" "$PREV_D"; cp "$T.r" "$PREV_R"
  rm -f "$T".*
}

if [ "$1" = "loop" ]; then
  while true; do
    run_once
    sleep 1800
  done
else
  run_once
fi
