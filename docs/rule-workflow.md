# OpenAppFilter 规则维护工作流

> 从抓包到部署的完整流水线。整理自 2026-09 实战会话（432 → 638 应用规则的全量迭代）。
> 关联代码：本仓库 `oaf/`（内核引擎）、`open-app-filter/`（oafd 守护进程）。
> 流水线脚本已入库：`tools/`；数据文件在本地工作目录 `TMP=/var/folders/6p/.../T/opencode`（macOS）。

---

## 0. 当前基线（2026-09-29）

| 项 | 值 |
|---|---|
| 规则文件（明文源） | `TMP/features_rules_final_new.txt` — 653 行 = 4 头 + 11 `#class` 段 + **638 应用规则**，md5 `1e5520ee6aac888a31c9867941d07d4f` |
| 已安装产物 | 路由器 `/etc/fwxd/feature.bin`（FWXB 加密），md5 `409285f9e68a6fb0fce5337b6dfe5e1e`，version `26.09.29` |
| 备份 | `/etc/fwxd/feature.bin.bak.premerge`（官方原版 15912B, md5 `c39c88fddf213b3ce68ca7e61eab7197`） |
| 图标 | `/www/luci-static/resources/oaf/app_icons/` 851 个文件（506 官方 + 344 补齐） |
| 路由器 | `rtk ssh root@192.168.2.1`；`appfilter.feature.update='0'`（在线更新已禁用，手动安装不会被覆盖） |

---

## 1. 全景流程

```
① 抓包        tcpdump 抓 DNS/SNI ──→ features_draft.txt (kind|host)
② 分析清洗    HOST_RE/IP 过滤、PSL 注册域折叠、cloudfront 统一、umeng.co 修正
③ 去重命名    同名规则合并 + 800B 拆分 + 域名→友好名 (NAME_OVERRIDE)
④ 整合官方    gen_official_gap_data.py → official_gap_data.py：官方独有应用/宿主缺口/载荷特征/分类/官方appid
⑤ 构建验证    build_rules.py → VALIDATION OK → simulate_ac_matching (LEFT-MID 0) → verify_match_scenarios
⑥ 打包补图    fwxb_pack.py → feature.bin (FWXB) + icons_out/*.png
⑦ 部署验证    候选文件 + SIGUSR1 热加载（零重启）→ ubus 校验 → 图标落盘
```

每一轮迭代：改 ②③④ 的数据或脚本 → 重跑 ⑤⑥⑦。① 只在采集新流量时需要。⑤⑥ 可用 `tools/pipeline.sh check` / `tools/pipeline.sh pack` 一键执行（`all` = 两者，set -e 失败即停）。

---

## 2. ① 抓包（数据采集）

**产物**（都在路由器 `/tmp/pcap/`，定期拉回本地 TMP）：
- `features_draft.txt` — 每行 `类型|域名`（如 `dns|api.example.com`、`sni|...`），抓包的原始观察集合
- `features_rules.txt` — 从官方/在线库抓到的原始规则行（`id~name:[...]` 格式）
- `brief.log` + `oaf_brief.sh` — 增量简报脚本：diff 新域名/新规则，企业微信推送（`sh oaf_brief.sh` 单次 / `loop` 每 30 分钟）

**做法**：
1. 路由器上 tcpdump 抓 `br-lan` 的 53/UDP（DNS 查询名）与 443/TCP 前几 KB（TLS SNI），或抓 HTTP Host。
2. 解析出主机名，按 `kind|host` 追加进 `features_draft.txt`（sort -u 去重）。
3. 收集期结束后 **务必清理**：kill 掉 tcpdump/brief 循环，检查 `crontab -l` 无残留、`/tmp/pcap/STOP_FLAG`（brief 脚本的停止开关）。

**拉回本地**：`rtk scp root@192.168.2.1:/tmp/pcap/features_draft.txt $TMP/`

---

## 3. ② 分析与清洗（build_rules.py 前半段）

输入：`features_rules_final.txt`（上一版基线 432 行）+ `features_draft.txt` + `features_rules.txt`。

关键逻辑（都在 `build_rules.py`）：
- **HOST_RE** = `^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$`，IP_RE 排除裸 IP；不符合的 draft 条目直接丢弃（曾挡掉 8 个 hex 哈希宿主等垃圾）。
- **PSL 注册域折叠** `registrable()`：`cdn-static.abchina.com.cn` → `abchina.com.cn`（父域已是规则时子域自动折叠，避免冗余）。
- **canon() 统一**：`HOST_FIX`（`umeng.co`→`umeng.com` 这类截断修正）+ `UNIFY_SUFFIX`（`*.cloudfront.net` 全部统一到 `.cloudfront.net`，丢弃随机 dist-id 前缀）。
- **手工定点**：`HOST_APPEND`（给已有规则追加宿主，如 20238 微信 + `weixin.qq.com`）、`MANUAL`（手工新增应用，如腾讯视频/百度地图/Gemini）。
- **审计脚本**（按需跑）：`audit_boundary.py`（短模式中段误伤扫描）、`plain_fp_scan.py`（裸模式 mid-label 扫描）、`audit_subservice_rules.py`（大集团子服务拆分分析）。

---

## 4. ③ 去重与命名

- **同名合并**：`scan_duplicate_names.py` 扫出重复名 → `build_rules.py` 合并段按名字分组，字段兼容（**排除宿主字段**再比较）则并集宿主合成一条；超 800B 触发拆分。
- **800B 拆分**：引擎 `MAX_FEATURE_LINE_LEN=800`（`fwx.h`），超限按宿主+载荷条目做均衡切分，**同名多条**，首条保留原 id，续条 `next_id++`（从 max(id)+1 起）。
- **域名 → 友好名**：`NAME_OVERRIDE`（152 条，`name_overrides.py`）。新域名研究流程：
  1. `scan_duplicate_names.py` 列出域名形名称 → `split_names_for_research.py` 切 3 个 chunk；
  2. 每个 chunk 交给 librarian 代理查 ICP/官网/whois，输出 `<id> <域名> → 名 | high/med/low/KEEP | 依据`；
  3. 汇总 `name_results.txt` → `gen_name_overrides.py` 生成 `name_overrides.py`（KEEP=查不出，保留域名作名）。

**命名硬约束**：名 ≤63 字节，字符集禁止 `# ~ : ; , [ ]`（`#` 尤其致命，见 §9）。

---

## 5. ④ 整合官方特征

**数据源**：`feature_official.txt`（官方在线库解密明文，#version/#format/#class 头 + 311 规则）。

**生成器**：`python3 tools/gen_official_gap_data.py`（任意目录可跑，数据走 TMP 绝对路径）→ `tools/official_gap_data.py`：
> ⚠️ **重跑 gen 的语义**：`load_our` 读 `features_rules_final_new.txt`。现有 `official_gap_data.py` 是**首合并时基于合并前基线**算出的全量缺口（NEW_APPS=262 / HOST_ADDS=18），是已验证的现状数据。若在合并后的 638 基线上、用同一份官方库重跑 gen，官方应用已全部同名存在 → NEW_APPS=0、HOST_ADDS 变增量语义，曾把 `3001~抖音` 顶到 802B 导致校验失败。**只有官方库真升级时才重跑**（§11），且重跑后必须跑满 §6 三连并核对输出 md5。

| 数据 | 内容 |
|---|---|
| `ID_MAP` | 官方名 → 官方 appid（我们已有同名应用时**采纳官方 id**，家长控制 uci 规则引用的就是这些 id） |
| `CLASS_MAP` | 官方名 → 分类 id |
| `NEW_APPS` | `[rid, 名, class, [域名], [verbatim特征]]` 官方独有应用 |
| `HOST_ADDS` | 已有应用的宿主/载荷缺口（按名追加） |
| `OFFICIAL_LOOSE` | 86 个碎片宿主（`momo`、`iqiyi`、`.uu.cc`…），**只允许以 verbatim 特征形式透传**，校验白名单 |

**合并规则**（build_rules.py 流水线顺序）：normalize 5 元组 → NAME_OVERRIDE → 同名合并（并集 verb）→ HOST_ADDS → ID_MAP 采纳 id → NEW_APPS 追加 → 分类指派（CLASS_MAP 优先，否则关键词分类：游戏→2 视频→3 购物→4 …默认 10 生活）→ 官方数据 bug 修正（1905 电影/豆瓣电影宿主互换）。

**输出头 + 分类段**（与官方库同构）：
```
#version 26.09.29
#format v4.0
#type 0
#free 1
#class chat 1 聊天
1002~微信:[...]
...
#class game 2 游戏
...
```
分类段顺序固定：1,2,3,4,5,6,7,8,10,11,14。

---

## 6. ⑤ 构建与验证（每次必跑）

一键（推荐，失败即停）：`tools/pipeline.sh check` = 下面三连，任一步非 0 立即退出（三脚本均以退出码 0/1 表达结果）。手动分步：

```bash
python3 tools/build_rules.py            # → $TMP/features_rules_final_new.txt + 打印 VALIDATION（有错 exit 1）
python3 tools/simulate_ac_matching.py   # 必须 RESULT: PASS 且 LEFT-MID 0（否则 exit 1）
python3 tools/verify_match_scenarios.py # 17 场景 OK + 仅 2 已知误报，否则 exit 1
```

**build_rules.py 校验器通过条件**：id 唯一（1≤id<20900）、名合规、**行 <800 字节**、每特征 8 字段（官方 6 字段风格也接受）、宿主 ≤31 字节、PSL/IP/宿主正则、同规则冗余、跨规则 prefix-steal/raw-steal、期望特征数一致、源↔输出一致。任何一条不过 = 不可部署。

**simulate_ac_matching.py**：模拟引擎 AC（最早结束优先、同结束最长优先）+ 正则回退，语料 ~3200 域名。`LEFT-MID`（模式在域名中段命中、非标签边界）**必须为 0**——这是 huami.com 被 `mi.com` 误分类那类事故的回归测试。已知白例：`zenvideo.qq.com`（同厂）、LOOSE 桶（官方碎片模式的既定行为）。

**verify_match_scenarios.py**：17 个真实场景（子服务 apex 归属等）全 OK + 2 个已知误报（`weixinbridge.com` 仅 AC 模拟假象、尾链污染类）。

---

## 7. ⑥ 打包（FWXB）与图标

### feature.bin 打包
一键（推荐）：`tools/pipeline.sh pack` — 打包 + 解密回读 + `cmp` 字节比对，失败即停，产出 `$TMP/feature.bin.new`。手动分步：
```bash
python3 tools/fwxb_pack.py encrypt $TMP/features_rules_final_new.txt $TMP/feature.bin.new
python3 tools/fwxb_pack.py decrypt $TMP/feature.bin.new /tmp/check.txt   # 回读必须字节一致
```

**FWXB 格式**（与 `open-app-filter/src/fwx_feature.c` 字节级互证过）：
- 24B 头：`'FWXB' + ver(1) + alg(1) + le16 hdr_size(24) + le32 plain_len + le32 crc32(明文) + le64 nonce`
- 体：XTEA-CTR 对称加解密，key `{0x8f4c29a1,0x73b6d502,0xc14e87f3,0x2ad95b60}`，32 轮 delta `0x9e3779b9`，v0 索引 `sum&3` / v1 索引 `(sum>>11)&3`（中间有 `sum+=delta`），计数器 = nonce 起，每 8B 块按 **lo32,hi32 小端** 编码 → XTEA 加密 → 异或；crc = zlib.crc32。
- 证明基线：官方 bin 解密 == feature_official.txt；原 nonce 重打包 == 官方 bin（md5 相同）。

### 图标补齐
- 目标 = 规则 id − `iids.txt`（路由器已有图标清单）。
- 抓取顺序：`/apple-touch-icon.png` → `/favicon.png` → Google s2 favicons（先抓无效域名的"地球"图存哈希，命中=拒绝兜底图；**注意国内网络 google 不可达，s2 常为 0 收获**）。
- 兜底：首字母色块 PNG（128×128，颜色 = 复刻 `oaf_icon.js hashColor`：`h = c + ((ToInt32(h)<<5) - h)` 浮点语义，`|h|%10` 取 10 色板；ASCII 用 Arial Bold，中文用 Arial Unicode，保证非空白）。
- 产出 `icons_out/<appid>.png`，目标 100% 覆盖（fetch 失败必须落到色块，失败数必须为 0）。

---

## 8. ⑦ 部署（零重启热加载）与验证

> 约束：**禁止重启 OpenWrt**。oafd 自带候选文件热更新通道，全程不需要 reboot，也不需要重启服务。

```bash
# 1. 备份（一次性；之后每轮可用新名字再备一份）
rtk ssh root@192.168.2.1 "cp /etc/fwxd/feature.bin /etc/fwxd/feature.bin.bak.premerge"

# 2. 推候选文件（路径必须是 /tmp/feature.bin —— FWX_FEATURE_CANDIDATE_PATH）
rtk scp feature.bin.new root@192.168.2.1:/tmp/feature.bin

# 3. ⚠️ 只给"健康"的 oafd 发 SIGUSR1 —— 先查 FD！
rtk ssh root@192.168.2.1 "for p in \$(pidof oafd); do echo pid=\$p fd=\$(ls /proc/\$p/fd|wc -l); done"
#    fd ≈ 1024（耗尽）的实例万万不可发信号：它会因打不开文件校验失败，
#    并把候选文件 unlink 掉，导致健康实例拷贝失败（本会话踩过：status 400）
rtk ssh root@192.168.2.1 "kill -USR1 <健康pid>"

# 4. 验证
rtk ssh root@192.168.2.1 "cat /tmp/feature_upgrade.status"        # 必须 200
rtk ssh root@192.168.2.1 "md5sum /etc/fwxd/feature.bin"            # 必须 == 本地 md5
rtk ssh root@192.168.2.1 "cat /tmp/feature_info.json"              # version/app_count 应为新值
rtk ssh root@192.168.2.1 "ubus call fwx common '{\"api\":\"get_feature_info\"}'"
#   → code 2000 + 新 version + app_count == 规则数
rtk ssh root@192.168.2.1 "ubus call fwx common '{\"api\":\"class_list\",\"CopyRight\":\"www.fanchmwrt.com\"}'"
#   → 11 个 app_list、应用总数 == 规则数、缺图标标志(",0") == 0
#   （class_list 是唯一校验 CopyRight 的 API，值固定 www.fanchmwrt.com）

# 5. 图标（可与特征库独立部署，无需信号）
tar czf icons.tgz -C icons_out .
rtk scp icons.tgz root@192.168.2.1:/tmp/
rtk ssh root@192.168.2.1 "cd /www/luci-static/resources/oaf/app_icons && tar xzf /tmp/icons.tgz"

# 6. uci 覆盖率（家长控制引用的 app_id 必须全部存在于新库）
#    展开 uci show appfilter 里的 range（'1003-1011'）→ 与规则 id 求交，
#    "在 uci ∩ 官方库 − 我们的库" 必须为空
```

**回滚**（同样零重启）：`scp 备份 → /tmp/feature.bin`（或本地解密官方 bin 重新打包）→ 对健康 pid 发 SIGUSR1。

**热加载原理**：SIGUSR1 → `fwx_feature_process_candidate()` 校验候选（解密+crc+#version/#format 行）→ `fwx_feature_apply_candidate()`（当前 bin 备份到 .bak → 原子替换 → 删候选）→ `g_feature_update=1` → 1 秒定时器 `reload_feature()` → 内存重载 + `fwx_load_feature_to_kernel`（先 clean 再逐行 netlink 下发）→ 写 `/tmp/feature_info.json`。校验失败 = status 401，拷贝失败 = 400，成功 = 200，**失败时原文件不受损**。

**oafd 进程管理**（背景知识）：`/etc/init.d/appfilter`（procd，`S96appfilter` 自启）无条件启动 `oafd` + `rule_manager` 两实例，`respawn 60 5 5`（进程退出后 5 秒自动拉起）。`appfilter.global.enable=0` 只关过滤执行，**不影响进程存活**——oafd 是 LuCI 页面的 ubus 后端，必须常驻。**进程管理一律走 `/etc/init.d/appfilter stop` / `start`，不要直接 kill oafd/rule_manager**（包括异常实例清理：init 脚本的 stop 内部用 killall 收尸，start 由 procd 重新拉起）。

---

## 9. 引擎语义与规则格式（为什么规则长这样）

**规则行**：`id~name:[feat,feat,...]`；特征 = `proto;sport;dport;host;request;dict;search;ignore`（官方 6 字段风格 `proto;;dport;host;uri;payload` 也合法）。

**宿主三种形态**（build_rules.py 自动选择）：

| 形态 | 何时用 | 示例 | 命中方式 |
|---|---|---|---|
| 双轨 `.host` + apex 正则 | 有真实 TLD 的普通域名 | `tcp;;;.mi.com;;;;` + `tcp;;;^mi\.com[*]*$;;;;` | 子域走 AC 快路径；裸域 `mi.com` 走第③步正则（AC 不会短路） |
| 裸模式 plain | 子服务宿主（父域本身是规则，如 `video.qq.com`）；或末段非 TLD 的截断域名（`music.163`） | `tcp;;;video.qq.com;;;;` | AC 子串；apex 位置 0 命中；同结束位置最长者胜 → 能压过父域 `.qq.com` |
| verbatim 透传 | 官方载荷/端口/碎片特征 | `tcp;;80;;/mmtls;`、`tcp;;;;;04:2f\|05:66` | 原样进引擎 |

**为什么必须双轨**（huami 教训）：引擎 AC 是**纯子串**匹配、无标签边界检查——`mi.com` 会中段命中 `huami.com` → 误分类小米。纯 `.mi.com` 又会在 apex（`mi.com` 无前导点）漏配。所以子域 `.p`（快）+ 裸域精确正则（准）。

**正则检测规则**（`af_is_regex_host_pattern`）：host 必须同时以 `^` 开头、含 `*`、含 `$` 才走正则通道；K&R 迷你正则无分组无 alternation。apex 精确式 = `^esc(h)[*]*$`（长度超限退 `^esc[:-1]最后字符*$`，再退 `^首段\..*$`）。

**硬约束速查**：

| 约束 | 值 | 违反后果 |
|---|---|---|
| 行长 | **<800 B**（`MAX_FEATURE_LINE_LEN`；netlink 上限 1024） | 内核拒收整行 |
| 宿主字段 | **≤31 B**（`host_url[32]`） | 截断 |
| 逗号 | **宿主字段禁止逗号**——逗号是特征分隔符！多宿主必须拆成多个特征（`tcp;;;h1;;;;,tcp;;;h2;;;;`） | 续块 proto 无效被丢弃；首块宿主变空 → **匹配所有 TCP 流的炸弹** |
| `#` | 行内任意位置出现 `#` | oafd 下发时整行跳过（名字符集已禁 `#`） |
| id 空间 | 我们 20001–20900；官方采纳 id ≤14027；拆分续号从 max+1 | 唯一性冲突 |
| 特征数/应用 | 引擎定义 16 但**未启用**，实际不受限；靠 800B 自然限长 | — |

**内核匹配三步**（`fwx_main.c`）：① AC 扫 SNI/DNS（最早结束优先、同结束最长优先、命中即短路）→ ② 正则扫 DNS 名 → ③ 线性回退（纯宿主节点被跳过，**裸宿主只能靠 AC**；正则节点 vs SNI+DNS）。因此 plain/dot 宿主必须进 AC，精确裸域靠"正则节点在③"补。

---

## 10. 踩坑清单

1. **逗号宿主炸弹**：合并官方库时 12 条规则 28 个坏块，空宿主节点会匹配任意 TCP——已修（一宿主一特征），改动后靠校验器防回归。
2. **huami/mi.com 中段误伤** → 双轨形态 + sim 的 LEFT-MID=0 硬门槛。
3. **子服务 apex 输给父域**：`.video.qq.com` 匹配不到裸 `video.qq.com`，AC 被父域 `.qq.com` 短路 → 父域化的子服务宿主用 plain（`verify_match_scenarios` 场景用例守门）。
4. **SIGUSR1 双实例竞争**：FD 耗尽的坏实例会抢删候选文件 → 发信号前必须 `ls /proc/PID/fd | wc -l`。
5. **cloudfront dist-id**：随机前缀当宿主会产生海量规则 → 统一 `.cloudfront.net`。
6. **rtk 包装器**：输出截断 ~300 行（用 `rtk recall <id>` 取全文）；**zsh 里禁止 `echo ===x===`**（`==` 解析错误）；引号包 glob；`rtk ssh` 远端是裸 ash，无 rtk。
7. **改文件前重读**：edit 工具的 hash 标签每次读取都变。
8. **官方库已知 bug**：3100/3101（1905 电影 ↔ 豆瓣电影）宿主互换——build 时已修，升级官方库时注意。
9. **同名不同应用**：官方 8079 谷歌 vs 我们 20550 Gemini、智联 `zhaopin` 碎片会吸走 `alizhaopin.com`——LOOSE 桶既定接受，报告里注明即可。

---

## 11. 快速路径：日常新增少量规则

大多数情况不需要动抓包，直接：

1. **加数据**（三选一）：
   - 已有应用补宿主 → `build_rules.py` 的 `HOST_APPEND`（id → [宿主]）；
   - 全新应用 → `MANUAL` 列表 `(id, 名, [宿主])`，id 用 20551+ 空段；
   - 或者把新域名丢进 `features_draft.txt` 走全量解析。
2. 名称是域名 → 按 §4 查 ICP 补 `NAME_OVERRIDE`。
3. **校验**（§6）：`tools/pipeline.sh check`（= build → simulate → verify 三连，失败即停），全绿才继续。
4. **打包**（§7）：`tools/pipeline.sh pack`。
5. **部署**（§7/§8）：备份可选 → 候选 + SIGUSR1（查 FD！）→ ubus 验证 → 图标（如有新应用）。

**官方库升级**：拉新版官方明文 → 覆盖 `feature_official.txt` → `python3 tools/gen_official_gap_data.py` → 回到第 3 步（ID_MAP/NEW_APPS/LOOSE 自动重算）。

**部署后自检口诀**：status=200、双 md5 一致、`feature_info.json` 数字对、class_list 应用数对且 0 缺图标、uci 覆盖差集为空。

---

## 12. 文件索引

> 脚本在仓库 `tools/`（下表所列即 `tools/` 内文件）；数据文件（抓包原始、基线、图标、官方明文等）放在本地工作目录 `TMP=/var/folders/6p/34qnc0t57jdcnjhjfbdxm63h0000gn/T/opencode`。脚本内数据路径默认均指向该 TMP，且全部脚本与 `pipeline.sh` 均支持环境变量 `OAF_TMP` 覆盖（默认值即该固定 TMP 路径），**任意工作目录可直接运行**（如 `python3 tools/build_rules.py`）；`official_gap_data.py` / `name_overrides.py` 由对应 gen 脚本写入 `tools/` 同目录（build 时 import 同目录），属生成数据而非手工编辑。

| 文件 | 作用 |
|---|---|
| `pipeline.sh` | 编排入口（set -e 失败即停）：`check`=构建+回归三连、`pack`=打包+回读比对、`all`=两者；数据目录可用环境变量 `OAF_TMP` 覆盖（各脚本同样支持，见上） |
| `build_rules.py` | 主构建器（解析/合并/官方整合/渲染/800B 拆分/校验器）；TMP 中历史备份 `build_final.py.pre_merge` |
| `official_gap_data.py` + `gen_official_gap_data.py` | 官方缺口数据（生成物）与再生成器 |
| `name_overrides.py` + `gen_name_overrides.py` + `name_results.txt` | 命名覆写（152 条）与生成链（`name_results.txt` 在 TMP） |
| `simulate_ac_matching.py` / `verify_match_scenarios.py` | 匹配语义回归（LEFT-MID 0 / 17 场景 + 2 已知误报） |
| `fwxb_pack.py` | FWXB 加解密（官方 bin 字节级互证） |
| `icons_out/` | 344 个待装图标 |
| `features_rules_final.txt`(432 源) / `features_rules_final_new.txt`(638 产物) | 规则基线与输出 |
| `feature_official.txt` / `feature.bin.official` | 官方明文 / 官方密文 |
| `features_draft.txt` / `features_rules.txt` | 抓包原始数据 |
| `iids.txt` | 路由器已有图标清单（图标差集用） |
| `oaf_brief.sh` | 路由器端增量简报/推送脚本 |
