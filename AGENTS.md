# AGENTS.md — 项目操作指南

> 面向在本仓库中工作的 AI Agent / 开发者。请先读完本文件再动手。

## 1. 项目目标

修复 **BYD DiLink 车机版「高德地图（车道级导航版）」** 在 **分屏（Split-Screen / Multi-Window）** 模式下的闪退。

- 目标包名：`com.autonavi.amapauto`
- 版本：`V3.15.872.11.910.1.202608311746.2`（versionCode 872，minSdk 24，targetSdk 30）
- 原包 SHA-256：`450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285`

## 2. 根因（三个，互相独立）

原包是**第三方重打包**版本，注入了 `com.byd.automap.activity.MainActivity.mcFixDisplay()`。
该方法在 `getDisplay().getDisplayId() != 0`（车机分屏 / 副屏的**正常**状态）时会：

1. 反射调用 `ActivityTaskManager.getService().moveTaskToDisplay(taskId, 0)`，把任务从副屏拽回主屏；或
2. 反射失败（hiddenapi 拦截）时走 catch：`Intent` + `FLAG_ACTIVITY_NEW_TASK|FLAG_ACTIVITY_CLEAR_TASK`（`0x10008000`）
   + extra `mc_fix_display_relaunched=true` + `ActivityOptions.makeBasic().setLaunchDisplayId(0)`，
   `startActivity()` + `finish()`，即**清栈重启** MainActivity。

两条分支都会让用户看到"一进分屏就闪退 / 被弹出分屏"。→ **根因 #1**

另外，`com.autosdk.drive.navi.view.NaviView.Dd()`（`classes22.dex`）末尾有一串
`setOnClickListener(this.X6)`，其中 `j5`（`findViewById(R$id.lane_location)`）**未判空**
（紧邻的 `i5` 有判空）。而 `j5` 在 `res/layout/fragment_auto_navi_half.xml` 里**不存在**——
该布局正是 `NaviViewManager` 在 `PlatformUtils.isPlatformUI() == false`（多窗口 / 非平台化 UI）时选用的。
于是 `j5 == null` → `NullPointerException`（`NaviView.Dd()+168`）→ 进导航页闪退。→ **根因 #2**

第三个：界面**默认全屏**（状态栏 + 导航栏都被隐藏），同样来自注入。
全代码树里 `setSystemUiVisibility(...)` 只有两处，其中注入的那处在
`com.wzw.scale.DpiScaleManager.applyImmersive()`（`classes25.dex`）：
`window.getDecorView().setSystemUiVisibility(5894)`，
`5894 = 0x1706 = HIDE_NAVIGATION|FULLSCREEN|LAYOUT_STABLE|LAYOUT_HIDE_NAVIGATION|LAYOUT_FULLSCREEN|IMMERSIVE_STICKY`
——沉浸式粘性全屏，**状态栏与导航栏一起隐藏**。
它在 `MainActivity.onCreate()`（紧跟 `mcFixDisplay()`）被无条件调用，且没有任何用户开关。→ **根因 #3**

> 排查时注意：`MainActivity` 的主题叫 `Theme.AppCompat.Byd.Light.NoActionBar.FullScreen.UI.Integrate`，
> 名字里带 `FullScreen` 但**不是原因**——展开整条主题父链后没有任何 `windowFullscreen` 属性，
> 且 `resources.arsc` 的 zip 时间戳仍是 `2026-09-30`（未被重打包改动），说明资源与主题是原版 BYD 的。
> 另一处 `setSystemUiVisibility(5380)`（`k/e/w/r.java`，值 `0x1504`，不含 `HIDE_NAVIGATION`）
> 也是**原版**代码：定义在未被改动的 `classes8.dex`，且有 BYD 设置 `getConfigKeySystemBarOffOn()==0` 保护。

| | 触发条件 | 典型场景 |
|---|---|---|
| #1 `mcFixDisplay` | `getDisplay().getDisplayId() != 0` | 车机分屏 = 独立显示屏 |
| #2 `NaviView.Dd` NPE | `isInMultiWindowMode() == true` | 同屏分屏（displayId 仍为 0） |
| #3 `applyImmersive` | 无（每次 `onCreate` 都执行） | 界面默认全屏、状态栏/导航栏被隐藏 |

> 车机分屏**同时**满足 #1 与 #2，所以两个都必须修。手机上用 AOSP 同屏分屏可以单独复现 #2
> （`displayId` 不变，因此 #1 不触发）。#3 与分屏无关，任何设备上都生效。

## 3. 修复

### 修复 #1：`mcFixDisplay()` 变 no-op

只改 `classes9.dex`：

```smali
.method private mcFixDisplay()Z
    .locals 7
    const/4 v0, 0x0
    return v0
    # 原逻辑保留为死代码
.end method
```

### 修复 #2：`NaviView.Dd()` 给 `j5` 加判空

只改 `classes22.dex`（`scripts/fix_NaviView.py`）：

```smali
    iget-object v0, p0, ...->j5:Lcom/autonavi/skin/view/SkinTextView;
    if-eqz v0, :cond_j5          # ← 新增，与相邻 i5 判空写法一致
    iget-object v1, p0, ...->X6:Landroid/view/View$OnClickListener;
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setOnClickListener(...)V
    :cond_j5
```

### 修复 #3：`applyImmersive()` 不再碰 window

只改 `classes25.dex`（`scripts/fix_DpiScaleManager.py`）：在 window 操作前插入 `goto`，
直接跳到其后的 `VoiceXtt` 初始化（**保留语音功能**）：

```smali
    :cond_1
    goto :goto_mc_no_immersive        # ← 新增

    :try_start_1
    ...getAttributes / layoutInDisplayCutoutMode / setSystemUiVisibility(0x1706)...（保留为死代码）

    :goto_mc_no_immersive             # ← 新增
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
```

不改 `0x1706` 为 `0x0`，是因为 `0x0` 仍会覆盖宿主可能自己设置的 UI 标志；整段不碰最安全。

只替换 `classes9.dex`、`classes22.dex`、`classes25.dex`，其余 14791 个 zip 条目逐字节不变，然后重新签名。

- 补丁包：`.work/out/amap-splitfix.apk`（三个修复都在）
  SHA-256 `93f8831bf43be0566a945e253c0cfa50a456a8a6736551e1e833279bd4b4e6ed`
- 对照组（只修 #1+#2，用于证明 #3）：`.work/out/amap-nofix3.apk`
  SHA-256 `e32177eec5076656497a02e967f8ad0e2ef58ee03cf8ebe2cedc25da93e9ee1d`
- 对照组（只修 #1，用于证明 #2）：`.work/out/amap-mcfix-only-signed.apk`
  SHA-256 `01de14f7620df5f47bc17620a8993a1d5e701d1a136594b8031b44dc74813cf6`

## 4. 目录结构

```
.
├── AGENTS.md                     # 本文件
├── README.md                     # 项目说明
├── 高德车机版车道级导航版.原包.apk   # 原始 APK（280 MB，不入 git）
├── docs/
│   ├── findings.md               # 完整逆向结论 + 运行时 A/B 验证（主文档）
│   └── static-findings.md        # 静态分析速记
├── scripts/
│   ├── build_patch.sh            # 三个 dex → 打补丁 → *_patched.dex
│   ├── fix_mcFixDisplay.py       # 修复 #1 的 smali 改写
│   ├── fix_NaviView.py           # 修复 #2 的 smali 改写
│   ├── fix_DpiScaleManager.py    # 修复 #3（强制全屏）的 smali 改写
│   ├── build_apk.sh              # 替换 dex + zipalign + apksigner → 可安装 APK
│   ├── capture.sh                # adb 无线配对 / 连接 / 抓崩溃日志
│   ├── splitscreen.sh            # 分屏测试台（real 同屏分屏 / virt 虚拟屏 / exit / log）
│   ├── repro_navi_npe.sh         # 一键复现根因 #2（真机真实分屏 + 导航）
│   ├── jxctl.sh / jxq.py         # JADX 常驻查询服务（快速 grep 反编译源码）
│   └── dexstr.py                 # DEX 字符串提取
├── patches/
│   ├── README.md                 # 三个补丁的 before/after smali
│   ├── mcFixDisplay.patched.smali
│   ├── NaviView.Dd.patched.smali
│   └── DpiScaleManager.applyImmersive.patched.smali
├── tools/
│   ├── JadxServer.java           # JADX 常驻 TCP 查询服务
│   └── Export.java               # JADX 全量源码导出
└── .work/                        # 工作区（不入 git）
    ├── out/amap-splitfix.apk     # ★ 补丁产物（三个修复）
    ├── out/amap-nofix3.apk       # 对照组（只修 #1+#2）
    ├── out/amap-mcfix-only-signed.apk  # 对照组（只修 #1）
    ├── patch/classes9_patched.dex
    ├── patch/classes22_patched.dex
    ├── patch/classes25_patched.dex
    ├── keystore/amapfix2.jks
    ├── jadx-src/                 # 全量反编译源码（196 MB）
    ├── logs/                     # 运行时验证日志
    └── installed/                # 从设备抓回的 APK（用于比对）
```

## 5. 环境与工具链

| 工具 | 位置 | 用途 |
|---|---|---|
| JDK 17 | `/usr/lib/jvm/java-17-openjdk-amd64` | apktool / apksigner / JADX |
| apktool 3.0.3 | `/opt/rea-tools/apktool.jar` | 单 dex baksmali/smali |
| JADX MCP jar | `/opt/rea-tools/jadx-headless-mcp-0.7.1-all.jar` | 反编译 |
| adb 37.0.1 | `/opt/rea-tools/platform-tools/adb` | **支持无线 `pair`**（apt 的 29.0.6 不支持） |
| apksigner / zipalign | `apt` 安装 | 重签与对齐 |

> 网络受限时给 apt/curl 加代理：
> `https_proxy=http://127.0.0.1:20171 http_proxy=http://127.0.0.1:20171`

### 单 dex 打补丁技巧

`apktool` 不能直接反编译裸 `.dex`。做法是先把 dex 塞进一个临时 zip：

```bash
cp classes9.dex classes.dex
python3 -c "import zipfile;z=zipfile.ZipFile('in.apk','w');z.write('classes.dex');z.close()"
java -jar /opt/rea-tools/apktool.jar d -f -o smali_out in.apk   # 反编译
# ... 改 smali ...
java -jar /opt/rea-tools/apktool.jar b -o patched.apk smali_out # 回编译
```

## 6. 构建流程

```bash
# 1) 生成打过补丁的 classes9/22/25.dex
bash scripts/build_patch.sh

# 2) 替换进原 APK 并重签
bash scripts/build_apk.sh
```

`build_apk.sh` 会：
1. 逐条复制原 zip，跳过 `META-INF/*.SF|*.RSA|*.DSA|*.EC|MANIFEST.MF`，把 `classes9.dex`/`classes22.dex`/`classes25.dex` 换成补丁版；
2. `zipalign -f -p 4`；
3. `apksigner sign`（v1+v2+v3，keystore `.work/keystore/amapfix2.jks`，口令 `amapfix2`）。

## 7. 验证

### 静态验证
- `zipalign -c -p 4 <apk>` → OK
- `apksigner verify --print-certs <apk>` → v2/v3 通过
- 比对 zip 条目：只应有 `classes9.dex`、`classes22.dex`、`classes25.dex` 与 `META-INF/MANIFEST.MF` 变化

### 运行时验证（A/B 对照）

核心思路：**BYD 分屏的本质是"App 跑在非 0 号 display"**。用 overlay 虚拟屏即可复现触发条件。

```bash
ADB=/opt/rea-tools/platform-tools/adb

# 造一个 displayId=2 的虚拟屏（系统命名"叠加视图 #1"，正是代码里判定分屏的名字）
$ADB shell "settings put global overlay_display_devices '1280x720/213'"

# 把高德丢进虚拟屏
$ADB shell "am force-stop com.autonavi.amapauto"
$ADB shell "am start --display 2 -n com.autonavi.amapauto/com.byd.automap.activity.MainActivity"

# 抓日志
$ADB logcat -d -v threadtime > /tmp/x.log

# 用完还原
$ADB shell "settings put global overlay_display_devices 'null'"
```

**判定标准**

| 观测项 | 原包（未打补丁） | 补丁包 |
|---|---|---|
| `ActivityTaskManager;->getService()` hiddenapi denied | 出现 | 不出现 |
| `mc_fix_display_relaunched=true` | 出现 | 不出现 |
| `update application display id from 2 to new display 0` | 出现 | 不出现 |
| `FATAL EXCEPTION` | 无（是强制重启不是崩溃） | 无 |

详细证据见 `docs/findings.md` 第 7 节。

### 复现根因 #2（真机真实分屏，不需要车机）

真实同屏分屏**不会**改变 `displayId`，只把 `windowingMode` 改成 `multi-window`，
所以 #1 不触发、#2 会触发。一键脚本：

```bash
bash scripts/repro_navi_npe.sh .work/out/amap-splitfix.apk
```

它自动：启动 → `wm shell splitscreen moveToSideStage <taskId> 0` → 点"查找目的地" →
`input text "wanda"` → 点第一条 POI → 点"导航" → 抓 logcat 并统计。

| 观测项 | 只修 #1（`01de14f7…`） | 两个都修（`e32177ee…`） |
|---|---|---|
| `NaviView.Dd` 帧 | 9 | 0 |
| `FATAL EXCEPTION` | 1 | 0 |
| `pidof` | 空（已闪退） | 有（存活） |

## 8. 重要约束 / 已知坑

- **`getDisplay()` 是 API 30+**：注入代码没做版本判断（同包 `BaseMeterActivity` 就老实写了 `if (Build.VERSION.SDK_INT >= 30)`），且没做 null 检查。
- **签名会变**：重签后指纹从 `E4:4F:CB:38…`（CN=amap-fix）变为 `89:B8:C3:05…`。
  已排查的签名校验点均**不阻塞**：
  - Tinker：包内无 `assets/package_meta.txt`，不加载热修补丁；
  - `Sign.checkPackageSign`（native）只被 `CrashLog.checkSign()` 调用，而后者**全包无调用者**（死代码）；
  - 无硬编码签名 MD5 比对；Manifest 无 `sharedUserId`。
  - **但仍未知**车机上是否有其它模块按原指纹校验此 App。
- **安装需先卸载**：签名不同，`adb install -r` 会失败；车机若为系统预装应用可能需要系统权限。
- **不要提交大文件**：APK/dex/反编译源码/keystore 都已在 `.gitignore` 中。
- **磁盘紧张**：`/` 曾到 97%。清理时注意 `.work/jadx-src`（196 MB）、`.work/installed`（535 MB）、`.work/logs`。
- **adb 操作没有交互 stdin**：Shell 工具不能 `read -r`，一切必须用 adb 命令驱动（如 `input tap`、`uiautomator dump`）。
- **App UID 会变**：重装后 `A=100xx` 会变，写脚本解析 taskId 时**不要硬编码** `A=10050`，用 `A=[0-9]+`。
- **两种分屏不要混淆**：虚拟屏（`overlay_display_devices`）只复现 #1；
  真实同屏分屏（`moveToSideStage`）只复现 #2。要完整覆盖必须两种都跑。
- **`isPlatformUI()` 决定布局分支**：`PlatformUtils.isPlatformUI()` = `isUIPlatformized() || "7.0UI".equals(getDiLinkUIVersion()) || "RUI".equals(...)`；
  `getDiLinkUIVersion()` 读系统属性 `ro.vehicle.type`。手机上是 `IVI`/`0.0UI` → `false` → 用 `_half` 布局 → 踩 #2。
  平台化车机走完整布局不会踩 #2。

## 9. 待办

- [ ] 在真车机上抓一次分屏闪退日志（需车机 adb 权限）以最终闭环。
- [ ] 确认车机是否存在按原签名指纹校验此 App 的模块。
- [ ] 实测真实 BYD 车机的 `ro.vehicle.type` / `isPlatformUI()`，确认车机是否会踩 #2。
- [ ] 若需保留"非分屏场景纠正显示"的行为，可改为 `if (isInMultiWindowMode()) return false;` 而非完全 no-op。
- [ ] `fragment_auto_navi_half` 还缺 `siv_gps_click`（`i5`，已有判空）与其它若干 View，
      如需彻底对齐可考虑补齐布局而非逐个判空。
