#!/bin/sh
# OAF 规则流水线编排入口（fail-fast：任一步失败立即退出）
# 用法: tools/pipeline.sh [check|build|pack|all|help]
#   check = 构建 + AC 模拟 + 场景回归（文档 §6 三连）
#   build = 仅构建（build_rules → $TMP/features_rules_final_new.txt）
#   pack  = FWXB 打包 + 字节级回读校验（文档 §7）
#   all   = check + pack（默认）
# 数据文件在 $TMP（可用 OAF_TMP 覆盖）；脚本自身在 tools/，任意 cwd 可运行。
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="${OAF_TMP:-/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode}"
RULES="$TMP/features_rules_final_new.txt"
BIN="$TMP/feature.bin.new"
ROUNDTRIP="$TMP/feature_roundtrip.txt"

step() { printf '\n=== %s ===\n' "$*"; }

usage() {
    cat <<EOF
用法: tools/pipeline.sh [build|check|pack|all|help]
  build  构建校验（build_rules.py）
  check  build+simulate+verify 三连
  pack   加密+解密回读+cmp 比对
  all    默认, = check+pack
  help   显示帮助
数据目录默认 ${TMP}（可用 OAF_TMP 覆盖）
EOF
}

do_build() {
    step "build (build_rules.py)"
    python3 "$HERE/build_rules.py"
}

do_check() {
    do_build
    step "simulate AC (simulate_ac_matching.py)"
    python3 "$HERE/simulate_ac_matching.py"
    step "verify scenarios (verify_match_scenarios.py)"
    python3 "$HERE/verify_match_scenarios.py"
}

do_pack() {
    [ -f "$RULES" ] || { echo "missing $RULES (run check/build first)"; exit 1; }
    step "pack FWXB (fwxb_pack.py)"
    python3 "$HERE/fwxb_pack.py" encrypt "$RULES" "$BIN"
    python3 "$HERE/fwxb_pack.py" decrypt "$BIN" "$ROUNDTRIP"
    cmp -s "$RULES" "$ROUNDTRIP" || { echo "roundtrip MISMATCH: $BIN"; exit 1; }
    rm -f "$ROUNDTRIP"
    echo "roundtrip byte-identical OK"
    echo "packed: $BIN"
}

cmd="${1:-all}"
case "$cmd" in
    build) do_build ;;
    check) do_check ;;
    pack)  do_pack ;;
    all)   do_check; do_pack ;;
    help) usage; exit 0 ;;
    *)     usage >&2; exit 2 ;;
esac
step "$cmd OK"
