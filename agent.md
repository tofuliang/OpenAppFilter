# OpenAppFilter 本机编译指引

## 目标与约束

- 目标：ImmortalWrt **25.12.2 x86/64**，官方 SDK，GCC 14.3.0 / musl。
- Apple Silicon Mac 使用 Docker `--platform linux/amd64`；实际已用 OrbStack 编译成功。
- SDK 放在 **Linux named volume** 中，不能直接在 macOS 默认大小写不敏感的 bind mount 中构建。源码只读挂载，复制到 SDK 后构建。
- SDK 内编译使用非 root 用户 `builder`（UID 1001）；root 只用于安装宿主依赖、初始化卷。
- 不需要重编完整固件。包格式是 **APK，不是 IPK**。
- `kmod-oaf` 精确内核依赖：`kernel=6.12.103~0413601b1c3f0490e17f340fe09229ea-r1`。仅 `uname -r` 相同不足以保证兼容，不能强制忽略内核依赖。
- 构建当前工作区，包含未提交修改；不要重新 clone 上游代替本地源码。构建不等于授权部署或提交。
- **HomeRouter 不兼容此官方 SDK 模块**：`tofuliang/immortalwrt` 的 `fastbuild-x64-upstream-tags.yaml` / homerouter 固件实际 ABI 为 `34b15bd24dad748e98ddcd217d843951`。用户临时加载官方 SDK 产物时，内核报 `.gnu.linkonce.this_module section size must match ... struct module size`，已证实二进制不兼容；不能修改 world、伪造包依赖或强制加载解决。必须恢复匹配的原内核构建环境后重编。
- 原固件 Release 的 buildinfo 已下载到忽略目录 `build-artifacts/homerouter-25.12.2-buildinfo/`，manifest ABI 与设备一致。Workflow 缓存按系列滚动，复用前必须核对源码、配置、补丁及内核 ABI；当前尚未产出匹配 HomeRouter 的新模块。

## 本机现存环境

- 容器：`oaf-iw25122-x64`，基础镜像 `ubuntu:24.04`，平台 `linux/amd64`，默认停止。
- 卷：`oaf-iw25122-x64-work` → `/work`；SDK：`/work/sdk`。
- 仓库 → `/src`（只读）；本机 `~/.cache/oaf-build/immortalwrt-25.12.2-x86-64` → `/cache`。
- 下载缓存及历史辅助脚本留在上述 cache；**最终产物、日志和配置已移到仓库 `build-artifacts/immortalwrt-25.12.2-x86-64/`**，由根 `.gitignore` 忽略。
- cache 内早期脚本仍将日志写入 `/cache/artifacts`；不要把它当作最终交付目录，也不要未经检查重跑 SDK 初始化脚本。下文使用现有 SDK 增量构建。

## SDK 与固定 feeds

官方目录：<https://downloads.immortalwrt.org/releases/25.12.2/targets/x86/64/>

SDK 文件：

```text
immortalwrt-sdk-25.12.2-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst
SHA256: 4d4631f134c2f27215a91aa7ef5bf9a01ea96c2450d3b8a5c38048c32462ac60
```

SDK 自带 `feeds.conf.default` 固定提交，使用这些版本而不是 feed 最新分支：

| feed | 提交 |
| --- | --- |
| base（SDK 自带配置） | `4fc16f2985a358bd43bb522e43f05395fcbd6ed5` |
| packages | `84bd86384928955b568988ca0e09e2c78c75173d` |
| luci | `d6167ea0645cbd1327708d85f94824f42d0eb872` |

本机 GitHub 直连不稳定，实际用容器内 curl 下载 codeload 的固定提交 tarball，分别解压到 `/work/feeds-src/{base,packages,luci}`。`feeds.conf`：

```text
src-link base /work/feeds-src/base/package
src-link packages /work/feeds-src/packages
src-link luci /work/feeds-src/luci
```

首次安装 feeds：

```sh
./scripts/feeds update base packages luci
./scripts/feeds install -a -p base
./scripts/feeds install libsqlite3 libcurl luci-compat luci-lib-jsonc
```

全新 Ubuntu 容器的已使用依赖：

```sh
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  build-essential clang flex bison gawk gettext git libncurses-dev \
  libssl-dev python3 python3-setuptools rsync swig unzip zlib1g-dev \
  file wget curl time ca-certificates xz-utils zstd pkg-config \
  subversion quilt patch jq
```

SDK 解压时使用 `tar --zstd --strip-components=1`。SDK 初始没有 `.config`，通过以下包配置再 `make defconfig` 生成：

```text
CONFIG_ALL=n
CONFIG_ALL_NONSHARED=n
CONFIG_ALL_KMODS=n
CONFIG_PACKAGE_kmod-oaf=m
CONFIG_PACKAGE_appfilter=m
CONFIG_PACKAGE_luci-app-oaf=m
CONFIG_LUCI_LANG_zh_Hans=y
```

## 使用现有容器增量编译

在本仓库根目录执行。先确认没有另一场构建在运行；不要并发 clean 同一 SDK。

```sh
docker start oaf-iw25122-x64

# 同步最新工作区，排除编辑器垃圾；不改宿主源码。
docker exec --user builder oaf-iw25122-x64 bash -euc '
  for pkg in oaf open-app-filter luci-app-oaf; do
    rsync -a --delete --exclude="*.swp" --exclude="*.swo" --exclude="*~" \
      "/src/$pkg/" "/work/sdk/package/OpenAppFilter/$pkg/"
  done
'

# 全部三个包 clean 后编译；只改某个包时只执行对应目标。
docker exec --user builder --workdir /work/sdk oaf-iw25122-x64 bash -euc '
  make package/oaf/clean V=s
  make package/open-app-filter/clean V=s
  make package/luci-app-oaf/clean V=s
  make -j4 package/oaf/compile V=s
  make -j4 package/open-app-filter/compile V=s
  make -j4 package/luci-app-oaf/compile V=s
'
```

包目录与包名不同：`open-app-filter` 目标生成 `appfilter`（包含 `oafd`）；`oaf` 生成 `kmod-oaf`。LuCI 另生成中文翻译包。

构建可能重打包大量 SDK 内核依赖；不能因此改内核配置或伪造 ABI。长任务应无工具超时或使用受管理的长任务，不能因命令等待超时重复启动构建。中断曾留下空的 `sqlite3.o`，引起 SQLite 链接 undefined references；当确认是中断损坏时，执行 `make package/feeds/packages/sqlite3/clean V=s` 后重建，不能掩盖链接错误。

## 核验与导出

内核包：`/work/sdk/bin/targets/x86/64/packages/kmod-oaf-6.12.103-r1.apk`。
其余包：`/work/sdk/bin/packages/x86_64/base/`。

```sh
OUT="$PWD/build-artifacts/immortalwrt-25.12.2-x86-64"
mkdir -p "$OUT"
docker cp oaf-iw25122-x64:/work/sdk/bin/targets/x86/64/packages/kmod-oaf-6.12.103-r1.apk "$OUT/"
docker cp oaf-iw25122-x64:/work/sdk/bin/packages/x86_64/base/appfilter-7.0.2-r1.apk "$OUT/"
docker cp oaf-iw25122-x64:/work/sdk/bin/packages/x86_64/base/luci-app-oaf-7.0-r2.apk "$OUT/"
# 翻译包版本可能变化，先查实际文件名，再复制；不要保留旧版本充数。
docker exec oaf-iw25122-x64 find /work/sdk/bin/packages/x86_64/base \
  -maxdepth 1 -name 'luci-i18n-oaf-zh-cn-*.apk'
```

用 SDK 自带 `/work/sdk/staging_dir/host/bin/apk`：

- `verify --allow-untrusted <包>` 检查内容完整性；这是本地未签名包，不等于官方签名认证。
- `adbdump <包>` 核对 `arch`、`depends` 和文件清单，内核 ABI 必须与目标固件一致。
- `--allow-untrusted extract --no-chown --destination <已创建的空目录> <包>` 解包检查；不能对旧解包目录直接叠加。
- `file` 确认 `oaf.ko` 和 `oafd` 是 x86-64；LuCI/翻译是 `noarch`。
- 确认包内无 `.swp`、`.swo`、`*~` 文件。已从源码清理 `.dashboard.htm.swp`，并 clean 重编验证。
- `shasum -a 256 "$OUT"/*.apk`；更新同目录 `BUILD-MANIFEST.txt`，保留最终构建日志、配置。

```sh
docker stop --timeout 2 oaf-iw25122-x64
```

保留 named volume 以便重编，不自动删除下载或 SDK。上述验证没有在真实 ImmortalWrt 内核加载模块；安装、重启服务和路由器验证需另行授权。若安装本地 APK 需要 `--allow-untrusted`，只放宽签名信任，不得绕过内核 ABI/依赖检查。
