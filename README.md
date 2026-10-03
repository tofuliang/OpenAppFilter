

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

