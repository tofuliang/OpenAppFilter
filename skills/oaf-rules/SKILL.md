---
name: oaf-rules
description: OpenAppFilter/OAF 自定义特征规则全流程：抓包采集域名、分析清洗、去重命名、整合官方特征库、构建验证、FWXB 打包、零重启热部署到 OpenWrt 路由器。Use when 用户要给 OAF/OpenAppFilter 添加或修改应用识别规则、新增/更新 feature 规则、分析抓包产出的域名、合并官方 feature_official、打包或部署 feature.bin、排查规则不生效，或提到「自定义特征」「加规则」「oaf rules」「feature.bin 部署」「规则工作流」。
---

# OAF 自定义特征规则（custom feature rules）

给 OpenAppFilter 添加/修改应用识别规则的端到端工作流。本 skill 是入口、硬约束与验收标准；**执行细节以仓库文档为准，先读文档再动手**。适用于任何支持 SKILL.md 的 agent（opencode、Claude Code 等）。

- 工作仓库：本 skill 随仓库分发（`skills/oaf-rules/`），仓库根 = 本文件上溯两级；或从 cwd 向上 `git rev-parse --show-toplevel`（含 `docs/rule-workflow.md` 与 `tools/`）
- 数据目录：环境变量 `OAF_TMP` 指定，未设置时用脚本内置默认值（唯一事实源：`tools/pipeline.sh` 开头的 `TMP=`，各 .py 脚本同款 fallback）；规则明文、抓包产出、feature.bin 均放这里
- 脚本在 `tools/`，全部支持 `OAF_TMP` 环境变量覆盖数据目录，任意 cwd 可直接运行
- 关联代码：`oaf/`（内核引擎）、`open-app-filter/`（oafd 守护进程）、`luci-app-oaf/`（Web UI）

## 1. 先读权威文档

`docs/rule-workflow.md`（仓库根相对路径，278 行，§0–§12）。按需跳读：

| 场景 | 章节 |
|---|---|
| 日常新增少量规则（最常见） | §11 快速路径 |
| 全新抓包采集 | §2（tcpdump DNS/SNI → `/tmp/pcap/features_draft.txt`，`oaf_brief.sh` 推送） |
| 分析清洗 / 去重命名 | §3、§4（PSL 折叠、HOST_FIX、NAME_OVERRIDE 152） |
| 整合官方特征 | §5、§11 官方升级分支 |
| 构建验证三连 / 打包图标 | §6、§7 |
| 部署与回滚 | §8 |
| 规则为什么长这样、引擎语义 | §9（三形态、中段命中、逗号颗弹） |
| 踩坑清单（动手前必读） | §10 |
| 当前基线（规则 md5、feature.bin md5、备份、图标数） | §0 |

## 2. 一键流水线

```bash
cd "$(git rev-parse --show-toplevel)"   # OpenAppFilter 仓库根
tools/pipeline.sh check   # 构建 + AC 回归 + 场景验证（set -e 失败即停）
tools/pipeline.sh pack    # FWXB 加密 + 解密回读 cmp 字节比对 → $OAF_TMP/feature.bin.new
tools/pipeline.sh all     # 两者
```

验收线：exit 0；build 输出 `VALIDATION: OK`；明文 md5 与 §0 基线一致——**md5 变更必须是有意的**，并同步更新 §0。

## 3. 硬约束（不可违反）

- **禁止重启 OpenWrt**；部署一律零重启热加载，部署过程不重启服务、不杀任何 oaf 进程。
- **oaf 进程管理只走 init 脚本**：不要直接 `kill`/`killall` `oafd`、`rule_manager`；确需停止或重启服务时用 `/etc/init.d/appfilter stop`、`/etc/init.d/appfilter start`（procd 依 respawn 60 5 5 重新拉起，无需手动补位）。
- 热加载 ≠ 杀进程：备份 → scp 到路由器 `/tmp/feature.bin` → 确认 oafd 健康 FD → `kill -USR1 <pid>` 仅发重载信号（进程不终止）；回滚 = 恢复备份 + 再次 SIGUSR1。
- `tools/gen_official_gap_data.py` 只在真实官方特征升级时重跑；对已合并基线重跑会产出错误数据（内置守卫会 exit 1，`OAF_ALLOW_EMPTY_GAP=1` 才可越过），重跑后必须过 `pipeline.sh check` 并核对 md5。
- 规则格式红线：行 <800B、host ≤31B、应用名 ≤63B 且不含 `#~:;,[]`；中段命中/子服务 apex/逗号颗弹等语义见 §9-§10。
- 部署后必须回归：`pipeline.sh check` + 路由器侧 `status==200`、md5 比对、`ubus call fwx class_list`（请求需带 `CopyRight=www.fanchmwrt.com`）、uci 规则覆盖数（167/167）。
- 生成类数据文件（`tools/official_gap_data.py`、`tools/name_overrides.py`）带 `-- do not edit` 头，只能由对应 gen 脚本再生成。

## 4. 部署摘要（细节读 §8）

1. 备份 `/etc/fwxd/feature.bin`（已有官方原版 `.bak.premerge`，勿覆盖）
2. `scp $TMP/feature.bin root@<路由器IP>:/tmp/feature.bin`（本环境为 192.168.2.1，以文档 §0/实际网络为准）
3. 挑 FD 正常的 oafd 实例 → `kill -USR1 <pid>`（发重载信号，进程不退出；服务级重启才用 `/etc/init.d/appfilter stop` + `start`，绝不直接 kill）
4. 验证：md5、`feature_info.json`、ubus 调用、图标 tar 同步、uci 覆盖

## 5. 收尾验收（本仓库实践过的循环）

改动 `tools/` 或 `docs/` 后：加载 `code-review-expert` skill → 出评审 → 修复 → 再评审，**循环直到 P2 及以上为 0**（P3 可选清）。最后跑 `tools/pipeline.sh all` 留证，报告逐项列出验证命令与结果。

## 6. 关键背景

- `oafd` 由 `/etc/init.d/appfilter`（procd，respawn 60 5 5）托管，是 LuCI OAF 页面的 ubus 后端（`fwx` 对象）；关闭过滤功能或进程退出都会被 procd 拉起——属正常，不是 bug。停止/重启一律走 `/etc/init.d/appfilter stop` / `start`。
- 在线更新已禁用（`appfilter.feature.update='0'`），手动部署不会被覆盖。
- rtk 工具怪癖（若环境存在 rtk）：输出 300 行截断（用 `rtk recall <id>` 取全量）；zsh 下 `echo ===x===` 会坏，别用；glob 一律加引号。
- 历史基线：638 应用规则（432 → 638 全量迭代实战产物），851 个图标。
