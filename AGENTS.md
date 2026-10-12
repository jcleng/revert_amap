# AGENTS.md — 项目操作指南

> 面向在本仓库中工作的 AI Agent / 开发者。请先读完本文件再动手。

## 1. 项目目标

修复 **BYD DiLink 车机版「高德地图（车道级导航版）」** 在 **分屏（Split-Screen / Multi-Window）** 模式下的闪退。

- 原包名：`com.autonavi.amapauto`
- 构建产物包名：`com.autonavi.amapautolite`（为在预装车机上共存而改，见 §2.4）
- 版本：`V3.15.872.11.910.1.202608311746.2`（versionCode 872，minSdk 24，targetSdk 30）
- 原包 SHA-256：`450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285`

## 2. 根因（六个，互相独立）

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
| #4 包名冲突 | 车机已预装原装高德 | 安装报「与现有软件冲突」 |
| #5 收藏夹线程 | 设置 → 我的 → 收藏夹 | 同步回调在原生线程碰 View → 闪退 |
| #6 车型判定 | 车机读不到 `power_type`（返回 -1） | 底栏「充电站」点了却搜加油站；首页分类也是加油站 |

> 车机分屏**同时**满足 #1 与 #2，所以两个都必须修。手机上用 AOSP 同屏分屏可以单独复现 #2
> （`displayId` 不变，因此 #1 不触发）。#3 与分屏无关，任何设备上都生效。
> #5、#6 也是**原包自带的老 bug**，与分屏无关。

### 2.4 第四个问题：装不上车机 → 改包名

车机安装报「与现有软件冲突」。实测底层错误码是 **`INSTALL_FAILED_CONFLICTING_PROVIDER`**，
冲突的不只是签名，还有 **ContentProvider authority**：

```
Can't install because provider name com.byd.naviauto.mapprovider
(in package com.autonavi.amapautolite) is already used by com.autonavi.amapauto
```

**别走弯路**：官方「高德公开车机版」的包名**也是** `com.autonavi.amapauto`
（实测官网 `guanwangV1.9.0.2080.apk` 与 `Auto_9.5.0.600013_release_signed.apk` 都是），
所以「改成公开版包名」是个空操作，必须换一个真正不同的包名。
本项目用 `com.autonavi.amapautolite`。

要改的地方：

| 位置 | 说明 |
|---|---|
| `AndroidManifest.xml` / `resources.arsc` | 二进制字符串池 + 包名 256 字节字段（`scripts/rename_pkg_binary.py`） |
| dex 类型描述符 | `Lcom/autonavi/amapauto/` 无条件全改（`scripts/fix_RenamePackage.py`） |
| dex 字符串字面量 | 选择性改，服务端上报值保持原样（§3 修复 #4） |
| 两个非包名派生的 authority | `com.byd.naviauto.mapprovider`、`com.byd.automap.fenceprovider` |

> ⚠️ **两个坑**：
> 1. 新包名以旧包名为前缀，`str.replace` 会二次替换产出 `...amapautolitelite`，
>    必须用负向断言 `com\.autonavi\.amapauto(?!lite)`。
> 2. authority 还会以**字段初始化器**形式出现
>    （`.field public static final AUTHORITY:Ljava/lang/String; = "..."`），
>    正则只匹配 `const-string` 会漏掉 `FenceContentProvider.AUTHORITY`。
>
> AIDL 生成的 Binder token（`com.autonavi.amapauto.aidl.*`）**必须跟着改**，
> 否则 `$Stub`/`$Proxy` 对不上会抛「Binder invocation to an incorrect interface」；
> 已在 `fix_RenamePackage.py` 的 `ALWAYS_RENAME` 里处理。

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

### 修复 #5：`UserFavoritesPresenter.v0()` 加主线程守卫

只改 `classes8.dex`（`scripts/fix_UserFavorites.py`）：

```smali
    invoke-static {}, Landroid/os/Looper;->myLooper()Landroid/os/Looper;
    move-result-object v0
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    if-eq v0, v1, :cond_v0_main     # 已在主线程 -> 原逻辑；否则 post 后返回
    new-instance v0, Lk/e/v/h/c/m;
    invoke-direct {v0, p0}, Lk/e/v/h/c/m;-><init>(...UserFavoritesPresenter;)V
    invoke-static {v0}, Lcom/autosdk/bussiness/common/task/TaskManager;->post(Ljava/lang/Runnable;)V
    return-void
    :cond_v0_main
```

同步 SDK 的原生线程池（`bl_thd_pool_worker`，字符串只存在于 `lib/arm64-v8a/libGComm3rd.so`）
回调进来后同步执行到 `v0()` → `k.e.v.j.f.f.h2()` → `updateViewText()` → `TextView.setText()`，
在主线程之外碰 View → `CalledFromWrongThreadException` → `HMI callback exception` → FATAL。
`notify()` 里其余调用（`d2()`/`j2()` 走 `TaskManager.post`、`t0()`/`s0()`/`u0()` 走 RxJava
`observeOn(mainThread)`、`X0()` 是 SharedPreferences 写入）**都已经是线程安全的**，`v0()` 是唯一裸的 UI 操作。

> ⚠️ 必须 `if-eq`（相等才跳转）。用 `if-ne` 会反转判断：主线程调用 → post 分支 →
> `TaskManager.post` 在主线程**内联执行** → 再次进 `v0()` → 无限递归 `StackOverflowError`（实测）。

> ⚠️ **真实入口是「设置 → 我的 → 收藏夹」**（`scripts/goto_favorites.sh`），
> 不是首页右上角的收藏图标——后者打开的是搜索模块收藏页（`slv_search_favorite`），
> 不会创建 `UserFavoritesPresenter`，早期 A/B 因此全是假阴性。
> 一键复现：`scripts/ab_favorites_crash.sh <apk> <label>`。

**这是原包自带的老 bug**（对照组 `classes8.dex` 与修复前逐字节相同，同样必崩）。

### 修复 #6：车型判定 + 「充电站」字符串（`resources.arsc` + `classes21.dex`）

底栏按钮显示「充电站」但点下去打开加油站搜索页。分两步：

**6a 标签** —— `scripts/fix_ChargeStationStrings.py`：
`resources.arsc` 里 26 个 charge 族字符串（`charge_station`、`drive_charge_station`、
`route_result_charge_station`、`search_home_charge_station`、`tts_electric_warning_tips` 等）
被系统性误译成「加油站」。做法是**在全局字符串池尾部追加新串、只重指向受影响的 entry**
（保留原有索引），不动 `gas_station`（它与 `charge_station` 共享池条目 14042）。
结果：53 处 entry 重指向，池 24519→24539，arsc 7130988→7131792 字节。

**6b 行为** —— `scripts/fix_CarUtilsPowerType.py`：
`CarUtils.getPowerType()`（`classes21.dex`）把「读不到车型」（`-1`）回退成**油车**，
与 `iLoginCarData == null` 回退成**电车**自相矛盾：

```java
if (d == null) return 1;                 // 「还不知道」→ 电车
if (d.getPowerType() == -1) return 0;    // 「读不到」  → 油车   ← BUG
```

车机读不到 BYD 属性 `power_type` 时恒为 `-1`（`logcat`：
`needSend.PlatformUtils.getPowerType] value = -1`），于是整个 App 降级为油车。
修复：`const/4 v0, 0x0` → `const/4 v0, 0x1`（正则锚定整个方法体）。

> ⚠️ 两个阶段**必须同时存在**，否则出现「字是充电站、点了是加油站」的不一致。
> ⚠️ 该修复面向**纯电车**。油车应保持 `0`（更好的做法是做成设置项）。

**这是原包自带的老 bug**，与分屏无关。

### 修复 #4：改包名 + 改冲突 authority（为了和车机原装共存）

见 §2.4。字符串口径为 **safe**：服务端上报值保持原样（`UserConstant.PACKAGE_NAME`、
`BydAccountReceiver.PACKAGE_NAME`、`ProtocolUtils`、`AesDemoUtil`、
`com/autosdk/user/presenter/account/`、`CarModelPackageManager` 等，完整清单在
`scripts/fix_RenamePackage.py` 的 `KEEP` 表），本地自用值与 AIDL token 跟着改。

只替换 `classes.dex / classes5 / classes8 / classes9 / classes11 / classes13 /
classes18 / classes21 / classes22 / classes25` 共 10 个 dex，其余 zip 条目逐字节不变，然后重新签名。

- 补丁包（原名版）：`.work/out/amap-splitfix.apk`（修复 #1–#3）
  SHA-256 `93f8831bf43be0566a945e253c0cfa50a456a8a6736551e1e833279bd4b4e6ed`
- **共存版（改包名，推荐装车）**：`.work/out/amap-splitfix-lite.apk`（修复 #1–#6）
  SHA-256 `f1d17de2ca1576112151c59c9de3fdd9478306c6ab13c7b05cedc07d162a293f`
- 对照组（fix#1..#4 + 改名 + 6a 标签，无 #5/#6b，用于证明 #5 与 #6b）：
  `.work/out/amap-nofix5.apk`
- 对照组（fix#1..#6a + 改名，`classes21.dex` 回退为原版，用于证明 #6b）：
  `.work/out/amap-ctl-carutils.apk`
  SHA-256 `361b64b00aa10b021fd6bc8ebd3540c89fef14836e397a3a35e840c0d31b854a`
  （与修复 6b 之前的构建逐字节相同）
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
│   ├── fix_UserFavorites.py      # 修复 #5（收藏夹线程）smali 改写 + 新增 Runnable 类
│   ├── fix_ChargeStationStrings.py # 修复 #6a：arsc 字符串（加油站 → 充电站）
│   ├── fix_CarUtilsPowerType.py  # 修复 #6b：读不到车型时回退为电车
│   ├── fix_RenamePackage.py      # 修复 #4：dex 侧改包名 + 冲突 authority（含 KEEP 表）
│   ├── rename_pkg_binary.py      # 修复 #4：二进制改 manifest / arsc 包名
│   ├── build_apk.sh              # 改包名 + 替换 dex + zipalign + apksigner → 可安装 APK
│   ├── capture.sh                # adb 无线配对 / 连接 / 抓崩溃日志
│   ├── splitscreen.sh            # 分屏测试台（real 同屏分屏 / virt 虚拟屏 / exit / log）
│   ├── repro_navi_npe.sh         # 一键复现根因 #2（真机真实分屏 + 导航）
│   ├── goto_favorites.sh         # 导航到 #5 的真实崩溃入口（设置→我的→收藏夹）
│   ├── ab_favorites_crash.sh     # 一键复现根因 #5 + A/B 统计
│   ├── jxctl.sh / jxq.py         # JADX 常驻查询服务（快速 grep 反编译源码）
│   └── dexstr.py                 # DEX 字符串提取
├── patches/
│   ├── README.md                 # 补丁的 before/after smali
│   ├── mcFixDisplay.patched.smali
│   ├── NaviView.Dd.patched.smali
│   └── DpiScaleManager.applyImmersive.patched.smali
├── tools/
│   ├── JadxServer.java           # JADX 常驻 TCP 查询服务
│   └── Export.java               # JADX 全量源码导出
└── .work/                        # 工作区（不入 git）
    ├── out/amap-splitfix.apk     # 补丁产物（修复 #1–#3，原名）
    ├── out/amap-splitfix-lite.apk # 补丁产物（修复 #1–#5 + 改名，推荐装车）
    ├── out/amap-nofix5.apk       # 对照组（修复 #1–#4 + 改名，无 #5）
    ├── out/amap-splitfix-lite.apk  # ★ 共存版（改包名，推荐装车）
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
# 1) 生成打过补丁 + 改名的 *_pkg.dex（10 个 dex）
bash scripts/build_patch.sh

# 2) 改包名/authority + 替换 dex + zipalign + 重签
bash scripts/build_apk.sh
```

`build_patch.sh` 会：先对 `classes9/22/25/8/21` 跑代码修复（`fix_mcFixDisplay.py` #1、
`fix_NaviView.py` #2、`fix_DpiScaleManager.py` #3、`fix_UserFavorites.py` #5、
`fix_CarUtilsPowerType.py` #6b）得到 `*_patched.dex`，再对全部 10 个 dex 跑
`fix_RenamePackage.py` 得到 `*_pkg.dex`。

`build_apk.sh` 会：
1. `patch_arsc()` 用 `fix_ChargeStationStrings.py` 在 `resources.arsc` 里追加充电站系列字符串
   只重指向受影响 entry（#6a）；
2. 用 `rename_pkg_binary.py` 就地改 `AndroidManifest.xml` 与 `resources.arsc`
   （包名 + 两个冲突 authority）；
3. 逐条复制原 zip，跳过 `META-INF/*.SF|*.RSA|*.DSA|*.EC|MANIFEST.MF`，把 10 个 dex 换成 `*_pkg.dex`；
4. `zipalign -f -p 4`；
5. `apksigner sign`（v1+v2+v3，keystore `.work/keystore/amapfix2.jks`，口令 `amapfix2`）。

产物：`.work/out/amap-splitfix-lite.apk`（包名 `com.autonavi.amapautolite`）。

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
$ADB shell "am force-stop com.autonavi.amapautolite"
# 注意：overlay display 的 displayId 不一定是 2，先查
DID=$($ADB shell "dumpsys display" | grep -oE 'mDisplayId=[0-9]+' | sort -u | grep -v '=0' | tail -1 | cut -d= -f2)
$ADB shell "am start --display $DID -n com.autonavi.amapautolite/com.byd.automap.activity.MainActivity"

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
  **共存版（`amap-splitfix-lite.apk`）不需要卸载**：包名已改成 `com.autonavi.amapautolite`，
  与原装并存，实测 `adb install` 直接成功。装共存版前**不要** `adb uninstall com.autonavi.amapauto`。
- **改包名改出的两个坑**（改包名/加新 authority 时务必先读）：
  1. 新包名以旧包名为前缀 ⇒ 必须用 `com\.autonavi\.amapauto(?!lite)` 负向断言，
     否则二次替换产出 `...amapautolitelite`；
  2. authority 还会写成**字段初始化器**（`.field … = "..."`），只匹配 `const-string` 会漏。
  两个脚本（`fix_RenamePackage.py` / `rename_pkg_binary.py`）都已处理，改动时别退化。
- **改包名后要跟着改 AIDL token**：`com.autonavi.amapauto.aidl.*` 由 AIDL 编译器生成，
  必须与改名后的接口类一致，否则 Binder 调用抛
  「Binder invocation to an incorrect interface」。已放进 `ALWAYS_RENAME`（即使在 KEEP 文件内也改）。
- **改名口径 = safe**：服务端上报的身份字符串（账号绑定/云端接口参数）**保持原样**，
  详见 `scripts/fix_RenamePackage.py` 的 `KEEP` 表。想改成 full 口径就删掉那些条目，
  但会改变服务端看到的包名，可能影响账号/云端接口。
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
- [ ] 实测真实 BYD 车机的 `power_type` 属性是否可读（返回 1/2 时 #6b 为无害冗余）。
- [ ] 若需支持油车，把 #6b 的车型回退改成用户可选项，而不是编译期常量。
- [ ] 确认车机是否存在按原签名指纹校验此 App 的模块。
- [ ] 实测真实 BYD 车机的 `ro.vehicle.type` / `isPlatformUI()`，确认车机是否会踩 #2。
- [ ] 若需保留"非分屏场景纠正显示"的行为，可改为 `if (isInMultiWindowMode()) return false;` 而非完全 no-op。
- [ ] `fragment_auto_navi_half` 还缺 `siv_gps_click`（`i5`，已有判空）与其它若干 View，
      如需彻底对齐可考虑补齐布局而非逐个判空。
