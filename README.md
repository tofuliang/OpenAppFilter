

## Introduction
OAF is a parental control software based on OpenWrt. It supports popular applications across gaming, video streaming, instant messaging, such as TikTok, YouTube, Facebook. Currently, it supports hundreds of different applications.   
For a detailed introduction, please visit [www.openappfilter.com](http://www.openappfilter.com).

## Features
- DPI-based protocol identification: Supports Layer 7 protocol parsing and HTTPS domain resolution, and operates independently of DNS.
- Industry-standard architecture:  Flow-based identification for high efficiency, with extremely low hardware requirements.
- Supports custom protocol signatures: Offers a high degree of flexibility and customization.
- Supports installation as a plugin on OpenWrt systems: Compatible with all OpenWrt-enabled devices.You can download the plugin package corresponding to your architecture from the releases page.

### LuCI user list

The user list scrolls with the LuCI page. It reveals devices in batches of 15, automatically filling the visible area and loading further batches near the bottom. Automatic updates change displayed devices in place without moving or reordering the list. Use the list's refresh control to load a new snapshot, including newly discovered devices and the latest ordering.

### LuCI application records

The online and history tabs load records in batches of 15 as the LuCI page scrolls; neither tab has page controls or a second vertical scrollbar. Switching tabs preserves the rows already loaded. History search or reset starts a fresh filtered list, and a failed batch can be retried without discarding earlier rows. The updated service gives history rows persistent IDs (migrated from existing SQLite rows) so overlapping offset pages do not display the same visit twice; deploy the updated daemon together with LuCI for this behavior. Offset pagination still cannot guarantee that no unseen records are skipped when visits are added or reordered between requests.

Terminal-detail visit records and the global online/history record tables show upstream, downstream, and total traffic in bytes, formatted for display. This requires deploying a rebuilt `kmod-oaf`, `oafd`, and LuCI together. Counters start when an application is identified and count observable layer-3 bytes at the late FORWARD hook; pre-identification traffic, rejected packets, local traffic, record-whitelisted devices, and traffic bypassing the hooks (including flow offload) are not added. These are observed application counters, not billing totals. In bypass mode only observable upstream traffic is attributed; unavailable downstream and total values remain `—`. Updates arrive with the existing approximately 60-second kernel reporting cycle.

Per-app byte increments travel in bounded `app_traffic` netlink messages separately from visit activity, so they do not duplicate terminal traffic or online-time accounting. The daemon accumulates them per terminal/application in the accepted visit record; filtered visits report zero transferred bytes. History storage migrates existing SQLite records without replacing their IDs; previously unmeasured directions remain `NULL` and display `—`, distinct from a measured `0 B`. Restarting/reloading the kernel starts new in-memory counters; past traffic cannot be reconstructed.
Visits with at least one measured traffic direction are retained in history even when shorter than the configured minimum visit duration, including single-report visits. The duration threshold still applies when both traffic directions are unknown.

Each app-traffic datagram contains at most eight applications and remains below the 1024-byte protocol limit. A bounded 64-entry snapshot rotates fairly through pending applications; a successful send deducts only its snapshot, retaining concurrent increments. Failed sends keep pending bytes for later reporting, but stale application/client state is reclaimed after 600 seconds without relevant activity, even if delivery remains unavailable. This is bounded in-memory reporting, not durable delivery. The normal activity report remains one message per period (at most eight selected applications) to avoid counting terminal duration more than once.

Per-app traffic reporting honors the existing HTTP minimum connection-count threshold without inheriting the normal activity report's top-N limit; pending bytes are retained until the threshold is met or the existing retention window expires.
Per-app reports also follow the existing local-midnight suppression window: messages received in the first 120 seconds of each day are discarded. Their byte increments are not replayed; a successful kernel send has already consumed them, and this protocol has no userspace acknowledgement.

The application-records page adds an App Traffic Statistics tab with a selectable time range. It aggregates complete visits whose intervals overlap the range, including active visits; it does not split a visit at the range boundaries. The result is therefore an overlap-based whole-visit aggregate, not exact traffic observed strictly inside the selected window.

Both aggregate app-traffic tables retain every measured direction's bytes when other selected visits have unknown traffic. A complete direction displays its measured sum. An incomplete direction with at least one measured visit displays `≥ X` and an **Incomplete** marker; its tooltip gives unknown visits / selected visits. This includes `≥ 0 B` when the measured part is zero. If every selected visit is unknown in a direction, it displays `—` with the marker, never an unmarked `0 B`. The total lower bound adds all measured upstream and downstream bytes, including a measured direction whose opposite direction is unknown; it displays `—` only if neither direction has any measured visit. Total tooltips list upstream and downstream unknown counts separately, because one visit can be unknown in both directions. Displayed lower bounds are rounded down in their display unit so they never overstate the known bytes. Unknown traffic is not treated as measured zero.

The `get_app_traffic_stats` API exposes `known_up_bytes`, `known_down_bytes`, and `known_total_bytes` as the measured byte sums, with `known_total_bytes = known_up_bytes + known_down_bytes`. These fields are numeric, including zero when no selected visit was measured; distinguish that case using `record_count` and `unknown_up_count` / `unknown_down_count`. The existing `up_bytes` / `down_bytes` fields remain `null` if any selected visit is unknown in that direction, and `total_bytes` remains `null` if either direction is incomplete. Apps are ordered by descending known total, then application ID. Deploy the updated daemon and LuCI together to expose these lower bounds. Raw access-record `null` values and their `—` display are unchanged.

App Traffic Statistics accepts an optional terminal MAC filter. Its device suggestions show nicknames (falling back to hostnames) alongside MAC addresses and can be searched by device name or MAC. Suggestions use the complete device list; manual MAC entry remains available even if that list cannot load, and an empty MAC includes all devices. Devices with no matching visits show no data. The terminal-detail App Statistics tab retains its runtime-duration chart and separately lists upstream, downstream and total traffic for every observed app overlapping the browser-local current day. This traffic follows the same whole-visit overlap semantics and incomplete-total presentation described above, not an exact split at midnight.
When a MAC filter is active, the displayed query scope includes its device name and MAC; unknown devices fall back to the MAC. The scope is updated when the device list arrives, without changing the submitted filter.

Dashboard stat cards and chart containers remain independent siblings; Top8 and active-terminal links open the corresponding device by MAC. Unknown traffic remains a valid JSON `null` in nullable daemon statistics and history fields, not a backend error; queries containing unknown directions still succeed. The two aggregate app-traffic tables use the explicit known sums and completeness counts rather than discarding measured bytes.

Terminal visit records initialize when their tab opens, load additional pages near the bottom of the page viewport, and retain an explicit error/retry state when a page response is invalid. The table grows with the page without an inner vertical scrollbar; wide tables can still scroll horizontally.
An explicit zero record total with an empty `{}` list from the LuCI ubus bridge is treated as “no records,” not a load failure. Paging checks are scheduled independently of rendering frames.
Visit records do not poll or refresh page one in the background. Switching tabs keeps the loaded records. The Refresh button beside the device title reloads only the active tab's data without navigating; for visit records it resets paging and loads page one.

All reachable OAF tab groups (terminal detail, application records, feature library and whitelist) use `#tab=<id>` as the explicit tab selection. Browser reloads, shared links and back/forward navigation restore it without reloading the page on tab changes. When no valid hash is provided, existing application-record `?tab=history/traffic` links take precedence over saved state; otherwise the last tab in local storage is used before the page default. Terminal-detail saved state is isolated by MAC. Invalid or unavailable tabs and inaccessible local storage fall back safely to a valid tab.

### LuCI exact hourly traffic ledger

The **Exact Hourly Traffic** tab is a separate v2 ledger. It starts with v2 kernel deltas only; legacy visits and legacy hourly statistics are never backfilled into it. Every packet is assigned to the UTC hour in which it reaches OAF's late `FORWARD` hook, and queries use the half-open interval `[start, end)`, with both boundaries aligned to whole UTC hours. This is an observed layer-3 scope: it is not a total for every physical router interface or every wire byte. Packets that never reach that hook (for example local traffic, rejected traffic, flow-offloaded traffic, or other bypass paths) are outside the ledger, and coverage remains unverified even when the returned totals reconcile.

The exact ledger records application categories and direction bytes independently of legacy visit completeness. `appid = 0` is a first-class **measured, unclassified** category; it is not an unknown direction and does not mean that measurement is missing. A measured zero is consequently different from a legacy visit direction that is unavailable (`NULL`/`—`). The device total in an exact response is the sum of the same selected `traffic_hourly_v2` rows, including appid 0, so identified-app bytes plus unknown bytes must reconcile with the selected-device total in both directions. Reconciliation proves arithmetic consistency of committed facts, not complete capture or physical-interface coverage.

Each kernel batch is identified by `(boot_id, seq)` and is immutable while it is in flight. The daemon validates the entire batch, writes its UTC-hour facts and deduplication identity in one SQLite transaction, and uses `PRAGMA synchronous=FULL`; only after that durable commit does it send the matching ACK. The kernel retries an unacknowledged batch with the same identity, while SQLite deduplication prevents a committed retry from being counted twice. This commit/ACK guarantee applies only to the exact v2 ledger. The legacy `app_traffic` protocol described above remains bounded in-memory reporting with no userspace acknowledgement, and its existing loss/retry caveats are unchanged.

The ACK cannot make data that is still only in kernel RAM durable. Unsent or uncommitted facts may be lost on module unload, kernel restart, or power loss, so the configured history directory must be persistent if exact data must survive a router reboot. A path under `/tmp` is not reboot-persistent. The exact API reports committed SQLite snapshots; a current or future UTC hour is not a final total, and `coverage_unverified`, kernel-reported gaps, or retention pruning keep the result incomplete. Retention prunes whole UTC hours and keeps a durable floor so delayed batches below that floor cannot resurrect deleted hours.

Manual Clear has a deliberate boundary: when a legacy date selection cuts through hours, exact rows are deleted only for complete UTC buckets wholly inside the selection, while `(boot_id, seq)` deduplication identities are retained. Manual Clear does not prove that an unseen delayed batch cannot later repopulate a bucket that is not below the retention floor; use the retention policy as the durable replay boundary. Reverting to the old kernel/service/LuCI component is supported for the legacy views and protocol. Back up `client.db` before rollback; the `traffic_hourly_v2` tables and their metadata may remain in that database and are ignored by the old component rather than requiring destructive deletion.

The exact contract requires a matching rebuilt kernel module, `oafd`, and LuCI package to be deployed together; updating only one layer is not a supported mixed-version deployment. These repository changes do not deploy or modify any device.

### LuCI built-in feature details

On the feature library's Basic Info tab, hover an application icon/name or focus its entry to inspect the current feature library's raw matching rules. Entries load their rules on demand from the service and cache them for the open page; the existing custom-application editor is unchanged. This requires deploying both the updated LuCI app and a rebuilt `open-app-filter` service (`oafd`): older services have no `get_builtin_feature` API. Updating LuCI files alone cannot show built-in rules. The installed `feature.bin` need not be rebuilt.

### LuCI themes

OAF pages use LuCI theme colors for forms, tables, dialogs, and status text. The dashboard also updates its charts when the active theme changes without reloading the page. Themes that render a dark page without setting LuCI's `data-darkmode` marker, such as Argon whose dark stylesheet also omits the `--*-color-*` variables, are detected at runtime: `common.js` publishes `data-oaf-dark` on the root element from the rendered page palette, `common.css` defines the LuCI color variables for that marker, and pages that need extra treatment key their rules on it as well. The rule-editor dialogs detect the applied page palette the same way, and selected checkboxes always render an explicit blue background with a white check mark.

## How to Compile
1. Prepare a set of OpenWrt source code that has already been successfully compiled into firmware.
(Instructions for compiling OpenWrt source code can be found via independent tutorials and will not be covered here.)
2. Clone the OAF source code.
Navigate to the root directory of your OpenWrt source code and execute the following command:
```
git clone https://github.com/destan19/OpenAppFilter.git package/OpenAppFilter
```
3. Enable the OAF compilation options.
Application Filtering consists of three distinct source packages, corresponding to the LuCI App, the service daemon, and the kernel module.
Before compiling, you must enable the build options for these three packages. You can do this by selecting `luci-app-oaf` via the `make menuconfig` graphical interface.
Alternatively, you can enable them by executing the following commands (run from the source code root directory):
```
echo "CONFIG_PACKAGE_luci-app-oaf=y" >>.config
make defconfig
```
This will automatically enable the compilation options for all three modules.

4. Begin compiling OAF.
If you have previously successfully compiled your OpenWrt source code, you can choose to compile only the individual packages:
```
make package/luci-app-oaf/compile V=s
make package/open-app-filter/compile V=s
make package/oaf/compile V=s
```
Alternatively, you can recompile the entire firmware image; this will integrate the plug-in directly into the firmware build:
```
make V=s
```

## Discussion Group

[https://t.me/openappfilter](https://t.me/openappfilter) (Telegram)

If you encounter some issues during installation or usage, you can join the group for discussion(The group was created only recently).

## License
- Individuals can use this software completely free of charge, and are also permitted to develop upon and redistribute it.
- If you undertake derivative development based on OAF, you must adhere to the GPL 2.0 license and retain references to the OAF repository or website information.
- If a company wishes to use this software, please contact the author for authorization.

## Star
If you find this project helpful, please give it a star.  
[![Stargazers over time](https://starchart.cc/destan19/OpenAppFilter.svg?variant=adaptive)](https://starchart.cc/destan19/OpenAppFilter)

## Policy-Routing Marks and Safe Deployment

OAF reserves the low 16 bits of a packet/connection mark for its own state. The multi-WAN line identifier MUST NOT use those bits. Line identifiers are stored in bits 16–19 instead:

| Line | Mark value | Line-mask example |
| --- | ---: | ---: |
| WAN | `0x00010000` | `mark & 0x000f0000` → `0x00010000` |
| VWAN1 | `0x00020000` | `mark & 0x000f0000` → `0x00020000` |
| IPTV | `0x00030000` | `mark & 0x000f0000` → `0x00030000` |
| VWAN2 | `0x00040000` | `mark & 0x000f0000` → `0x00040000` |

Use `0x000f0000` as the line-field mask when matching or replacing a line identifier. Preserve every other mark bit, including OAF's low 16 bits and any higher-bit state. For example, replace only the line field with `(old_mark & ~0x000f0000) | 0x00020000`; do not assign a complete mark value that overwrites unrelated state. Connection-tracking marks must be treated the same way: only the line field may be changed, while non-line bits remain intact.

### Deployment safety

Changing nftables rules, policy rules, or conntrack mark handling can interrupt active connections. Schedule the change for a maintenance window, expect existing sessions to reset, and ensure local or out-of-band console access before applying it. Keep a tested rollback script and a copy of the previous nftables and `ip rule` configuration available.

Do not directly overwrite a live router over SSH with an unverified build or script. First validate the package and rollback procedure on a staging device or disposable image; transfer artifacts through the approved, integrity-checked deployment process; and keep the current management session open until the new rules and connectivity have been verified. A failed startup may leave an old nftables backup in place; in that case, restore the corresponding old `ip rule` configuration rather than assuming the backup alone is sufficient.

These instructions describe local build and deployment precautions only. They do not mean that any router has been deployed or modified remotely.

### Kernel memory safety

Regular-expression character classes such as `[*]` require a rebuilt `kmod-oaf` containing the `regexp.c` allocation/free fix. Updating `feature.bin`, LuCI, or `oafd` alone does not update an already loaded kernel module. The `appfilter.global.enable=0` setting disables filtering decisions but does not unregister the module's packet hooks; stop the service and unload the module before replacing it. Unreachable kernel allocations from an older module are not recovered by unloading it and may require a controlled reboot.

Verify a new build on a staging image before restoring traffic. Monitor `/proc/meminfo` (`MemAvailable`, `SUnreclaim`), `/proc/vmstat` (`oom_kill`), and service/process memory over a sustained traffic window. Device retention for a large number of distinct MAC addresses within the configured history window remains a separate capacity concern, not a permanent allocation leak.

