# 高德车机版（比亚迪 DiLink）分屏闪退 —— 逆向结论与修复

目标包：`高德车机版车道级导航版.原包.apk`
- 包名 `com.autonavi.amapauto`，版本 `V3.15.872.11.910.1.202608311746.2`（versionCode 872）
- SHA-256 `450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285`
- 签名者 **CN=amap-fix**（非高德官方），25 个 dex

**已知问题共三个，都已定位并修复、都已在真机上跑通 A/B 对照：**

| # | 位置 | 根因 | 修复 | 验证方式 |
|---|---|---|---|---|
| 1 | `classes9.dex` `MainActivity.mcFixDisplay()` | 第三方注入的 hack：`displayId != 0` 时强行走 `moveTaskToDisplay(0)` 或 `NEW_TASK\|CLEAR_TASK` 重启，把 App 从分屏里拽出去 | 该方法改成 no-op（恒 `return false`） | 虚拟屏 `displayId=2` A/B，见 §7 |
| 2 | `classes22.dex` `NaviView.Dd()` | `this.j5.setOnClickListener(...)` 未判空，而 `j5` = `R.id.lane_location` 在 `fragment_auto_navi_half`（多窗口/非平台化时选用的布局）里**不存在** → NPE 闪退 | 给 `j5` 加判空，与相邻的 `i5` 判空写法一致 | 手机真实分屏 + 导航，见 §8 |
| 3 | `classes25.dex` `DpiScaleManager.applyImmersive()` | 第三方注入的沉浸式全屏：无条件 `setSystemUiVisibility(0x1706)`（`HIDE_NAVIGATION\|FULLSCREEN\|LAYOUT_*\|IMMERSIVE_STICKY`）并强制 `layoutInDisplayCutoutMode=3`，导致**状态栏与导航栏同时被隐藏**、界面永远全屏 | 跳过整段 window 操作（保留其后的 VoiceXtt 初始化） | 手机 A/B：`dumpsys window displays` 里 `statusBars visible` 由 `false` 变 `true`，见 §10 |

触发条件各不相同：**#1 只在 `displayId != 0` 时触发**（车机分屏 = 独立显示屏）；
**#2 只在 `isInMultiWindowMode() == true` 时触发**（含 `displayId` 仍为 0 的同屏分屏）；
**#3 每次启动都触发**（与分屏无关，是独立的全屏问题）。
车机上分屏同时满足 #1 与 #2，所以两个都必须修；#3 则解释了“为什么官方包不会默认全屏”。

## 1. 这个包已经被第三方改过（关键前提）

| 证据 | 说明 |
|---|---|
| 签名 `CN=amap-fix, OU=dev, O=amap-fix` | 不是官方签名，说明整包被重打过 |
| `classes9.dex` mtime 2026-10-07，其余 dex 2026-09-30 | 只有这一个 dex 被改动过 |
| `MainActivity.mcFixDisplay()` / `mcDispFixTries` / extra `mc_fix_display_relaunched` / log tag `McDebug`、`McGuard` | 原版高德不存在，是注入代码 |
| `com.wzw.*` 包（DpiScaleManager、VoiceXtt、HeadlightLinkManager…）跨几十个文件被引用 | 第三方功能注入 |
| `com.byd.split.VirtualPip`（引用外部 App `com.wzw.bydmodule`） | 分屏/双 PIP 集成，当前无调用者（死代码） |

## 2. 根因（静态可证）

**`MainActivity.mcFixDisplay()` 是这次分屏闪退的直接原因。**

反编译（`classes9.dex`）+ smali 双重确认，逻辑如下：

```java
private boolean mcFixDisplay() {
    if (getDisplay().getDisplayId() == 0) { mcDispFixTries = 0; return false; }
    if (mcDispFixTries >= 3) return false;
    mcDispFixTries++;
    int taskId = getTaskId();
    try {
        // 反射 ActivityTaskManager.getService().moveTaskToDisplay(taskId, 0)
        ...;
        mcDispFixTries = 0; return false;
    } catch (Throwable th) {
        Intent intent = new Intent(getIntent());
        intent.addFlags(0x10008000);            // NEW_TASK | CLEAR_TASK
        intent.putExtra("mc_fix_display_relaunched", true);
        k.h.c.r.r.f14146b = false;
        startActivity(intent, ActivityOptions.makeBasic().setLaunchDisplayId(0).toBundle());
        finish();
        return true;
    }
}
```

它在 `onCreate()`（`super.onCreate` 之后第一件事）和 `onResume()` 开头被调用，返回 true 时**直接 return，跳过全部初始化**。

为什么这会表现成"分屏闪退"：

1. **比亚迪的分屏 = 虚拟显示屏。** `k/e/d/q0/w1.java:23` 枚举 `DisplayManager.getDisplays()`，明确把 `displayId == 1`、`displayId == 2` 以及名字 `fission_*` / `叠加视图 #1` 的显示设备当作分屏/副屏。也就是说，App 在分屏里运行时 `getDisplay().getDisplayId() != 0` 是**正常状态**。
2. 注入代码把"不在 display 0"当成错误，强行 `moveTaskToDisplay(taskId, 0)`，即**把任务从分屏显示设备上拽回主屏**——用户看到的就是"一进分屏就退出/闪退"。
3. 如果反射失败（BYD 的 `ActivityTaskManager` 有定制，或 SELinux/权限拦截），就走 `catch` 分支：用 `NEW_TASK|CLEAR_TASK` 重建 MainActivity 并 `finish()` 自己。**CLEAR_TASK 会清空整个任务栈**，等于把用户正在导航的界面整个重启一次；`mc_fix_display_relaunched` 这个 extra 写进去以后**全包内没有任何地方读取**，所以没有任何"只重启一次"的保护。
4. `mcDispFixTries` 的上限 3 是 static 的，进程内有效；一旦 Activity 重建、进程重启就归零，可能形成"重启 → 又不在 display 0 → 再重启"的循环，也就是**反复闪退**。
5. 附带缺陷：`getDisplay()` 是 API 30+ 的 Activity 方法，注入代码**没有做版本判断**（同包 `BaseMeterActivity.getDisplayConfig()` 就老老实实写了 `if (Build.VERSION.SDK_INT >= 30)`）；而且 `getDisplay()` 可能返回 null，这里直接 `.getDisplayId()` 是裸调用。

结论：**第三方作者想用"强制回 display 0"来"修"分屏问题，结果这个 hack 本身就是分屏闪退的来源。**

## 3. 修复

### 3.1 修复一：`MainActivity.mcFixDisplay()` 变 no-op

把 `MainActivity.mcFixDisplay()` 变成 no-op（恒返回 false），即恢复"尊重系统给的显示屏"的原始行为。

改动后的 smali 方法体：
```smali
.method private mcFixDisplay()Z
    .locals 7
    const/4 v0, 0x0
    return v0
    ... 原代码保留为死代码 ...
.end method
```

### 3.2 修复二：`NaviView.Dd()` 给 `j5` 加判空

见 §8。

### 3.3 修复三：`DpiScaleManager.applyImmersive()` 不再强制全屏

见 §10。

### 3.4 产物

```
.work/patch/classes9_patched.dex    2,107,408 字节
  sha256 5ed376368a9edf17a1f035c7274f00895a2c820f8f65902ad46839a5baced463
.work/patch/classes22_patched.dex   3,549,488 字节
  sha256 8dd4b7d3faf384243082b7019dae7e07dfed78eef6ae7758d79ca5b6ed6b17fe
.work/patch/classes25_patched.dex     564,664 字节
  sha256 2d80033df968503a9813ceb85c04bcb9cb5284fa68c6e93dc9c0fccb7ab17a56

.work/out/amap-splitfix.apk       280,064,164 字节   ← 三个修复都在里面，推荐使用
  sha256 93f8831bf43be0566a945e253c0cfa50a456a8a6736551e1e833279bd4b4e6ed

.work/out/amap-nofix3.apk         280,064,164 字节 ← 只修 #1+#2 的对照组，用于证明 #3 的存在
  sha256 e32177eec5076656497a02e967f8ad0e2ef58ee03cf8ebe2cedc25da93e9ee1d

.work/out/amap-mcfix-only-signed.apk 280,064,164 字节 ← 只修 #1 的对照组，用于证明 #2 的存在
  sha256 01de14f7620df5f47bc17620a8993a1d5e701d1a136594b8031b44dc74813cf6
```

构建方式（只动 `classes9/22/25.dex`，其余 14791 个条目逐字节不变）：

```bash
bash scripts/build_patch.sh   # baksmali 三个 dex → 应用 scripts/fix_*.py → smali 回 dex
bash scripts/build_apk.sh     # 替换进原 APK（丢弃旧 META-INF 签名）→ zipalign → apksigner(v1+v2+v3)
```

校验：
- `zipalign -c -p 4` → OK
- `apksigner verify` → v2/v3 通过
- 新 dex 与原 APK 其余所有条目逐字节比对：仅 `classes9.dex`、`classes22.dex`、`classes25.dex` 与 `META-INF/MANIFEST.MF` 变化，其余完全一致
- 改后 dex 可被 apktool 重新反编译，确认方法体与预期一致

## 4. 签名风险已排查（可以放心重签）

- **Tinker 热修**：`ShareSecurityCheck.init()` 只是把当前签名 MD5 存下来，用它去校验**补丁文件**；包内没有 `assets/package_meta.txt`，即没有待加载的补丁，**不会**因为重签而失败。
- **`Sign.checkPackageSign`（native，com.autonavi.common.tool.sign）**：调用链是 `CrashLog.checkSign()`，而 `CrashLog.checkSign` **全包无调用者**，属于死代码。
- 全包没有任何硬编码的签名 MD5 比对（已 grep `e44fcb38` / `E4:4F:CB` 等）。
- Manifest 无 `sharedUserId`（比亚迪系的签名白名单约束通常靠这个）。

即：重签后安装/运行不会被签名校验拦下。**但签名指纹会变**（`amap-fix` 原指纹 `E4:4F:CB:38…` → 新指纹 `89:B8:C3:05…`），如果车机上还有别的模块按原指纹校验这个 App，需要另行处理。

## 5. 剩下的验证工作（需要车机）

以上是静态证据链。要 100% 确认，需要在车机上抓一次分屏闪退的 logcat，看是不是走到 `mcFixDisplay` 的重启分支。

已备好脚本 `.work/capture.sh`：

```bash
bash .work/capture.sh pair  <ip:port> <配对码>    # 首次配对
bash .work/capture.sh connect <ip:port>          # 连接
bash .work/capture.sh run                        # 清日志 → 复现 → 抓崩溃
```

`run` 会抓：完整 logcat、crash buffer、`FATAL EXCEPTION/AndroidRuntime/McDebug/mc_fix_display` 标记、
`/data/tombstones`、`dumpsys dropbox`、`dumpsys display`（看 App 当时在哪个 displayId）。

判定标准：
- 若日志出现 `McDebug` / `mc_fix_display_relaunched` / `moveTaskToDisplay`，或 `dumpsys display` 显示 App 在 display 1/2 而随后进程被杀 → **确认根因**，装的补丁包即为修复。
- 若崩溃栈指向别处（如 `MapSurfaceView` 重复 addView、`DpiScaleManager.overrideDensity` 改 Configuration），再针对性处理。

## 6. 备选/后续

- 若确认是 `mcFixDisplay` 引起，但用户希望保留"非分屏场景下纠正显示"的行为，可改成只在该 Activity 未处于多窗口模式时才执行（加 `isInMultiWindowMode()` 判断），而不是完全 no-op。
- `MeterSmallScreenActivity.u()` 每次都 `new MapSurfaceView(this)` 且反复 `s()`→`u()`，有 GL 上下文泄漏风险（与分屏无关但同属多屏路径）。
- `MainActivity.initMapSurfaceView()` 使用进程级单例 SurfaceView `k.h.c.d0.e.d().c()` 并跨 Activity 搬运，理论上存在重复 addView 风险，但目前未见对应崩溃证据。

---

# 7. 运行时验证（已用 Redmi 手机 + 虚拟显示屏完成 A/B 对照）

> 设备：Redmi 2312DRA50C (garnet, Android 16/SDK 36)，adb 192.168.10.167。
> 不是 BYD 车机，但 **BYD 分屏的本质是"App 跑在非 0 号 display"**，可用
> `settings put global overlay_display_devices '1280x720/213'` 造出 displayId=2
> 的虚拟屏（系统命名为 `叠加视图 #1`，正是 `k/e/d/q0/w1.b()` 判定分屏的那个名字），
> 再 `am start --display 2` 把高德丢进去，即可复现触发条件。

## 7.1 对照组：**未打补丁**的原包（`450a1848…`）

```
adb install -r 高德车机版车道级导航版.原包.apk
adb shell am start --display 2 -n com.autonavi.amapauto/com.byd.automap.activity.MainActivity
```

观测到的日志链路（`.work/logs/d2-unpatched2.log`，1 次启动即完整复现）：

```
E tonavi.amapauto: hiddenapi: Accessing hidden method
    Landroid/app/ActivityTaskManager;->getService()... from
    Lcom/byd/automap/activity/MainActivity; using reflection: denied
I ActivityTaskManager: START u0 {flg=0x10008000 xflg=0x4
    cmp=com.autonavi.amapauto/com.byd.automap.activity.MainActivity (has extras)}
    ... from pid 2576 callingPackage com.autonavi.amapauto
E MainActivity: [onResume] extra: Bundle[{mc_fix_display_relaunched=true}]
D ActivityThread: Handle activity config changed, update application display id from 2 to new display 0
E AutoApplication: [onActivityDestroyed: activity is MainActivity]
```

- `ActivityTaskManager.getService()` 被 **hiddenapi 拒绝** → `mcFixDisplay()` 里
  `Class.forName(...).getMethod("getService")` 抛异常 → 进入 **catch 分支**。
- catch 分支构造 `Intent(getIntent())` + `addFlags(0x10008000)` =
  `NEW_TASK|CLEAR_TASK`，带 `mc_fix_display_relaunched=true`，
  `setLaunchDisplayId(0)`，`startActivity()` + `finish()`。
- 结果：Activity 被销毁重建、从 display 2 被拽回 display 0。

统计（单次 30s 观测窗口）：
`McDebug=1, onCreate=1, mc_fix_display_relaunched=1, onActivityDestroyed=1, hiddenapi denied=1, display 2→0 切换=1`

## 7.2 实验组：**已打补丁**的包（`01de14f7…`）

同一命令、同一虚拟屏：

```
I ActivityTaskManager: START ... {flg=0x10008000 ...}
E MainActivity: [onResume] extra: Bundle[{mc_fix_display_relaunched=true}]   ← 仅 1 次，来自历史
```

统计：`mc_fix_display_relaunched=0`（本次启动未再注入）、`ActivityTaskManager;->getService()=0`
（反射根本没执行）、`FATAL EXCEPTION=0`、进程全程存活。

> 注：实验组仍出现 `update application display id from 2 to new display 0` 与
> `Schedule relaunch activity`，但那是 **测试手法副作用**——`am start` 指定
> display 2 后，系统又因为 overlay display 的特殊策略把 task 挪回 display 0，
> 并触发正常的 configuration-change relaunch。关键区别是**日志里不再有
> `ActivityTaskManager.getService` 反射与 `mc_fix_display_relaunched` 注入**，
> 即 `mcFixDisplay()` 已被彻底短路。

## 7.3 结论

**根因确认（Evidence：运行时 A/B 对照）**：

> 第三方重打包注入的 `MainActivity.mcFixDisplay()` 在
> `getDisplay().getDisplayId() != 0` 时（BYD 分屏 / 副屏正是这种情况）会走
> catch 分支，用 `NEW_TASK|CLEAR_TASK` + `setLaunchDisplayId(0)` 强行重启
> MainActivity，把 App 从分屏里拽出去。用户看到的"分屏闪退"就是这个强制重启。

补丁（`mcFixDisplay()` 直接 `return false`）在运行时**确实阻止了该注入分支**。

## 7.4 环境说明（重要）

- 本轮验证用的是 **Redmi 手机 + overlay 虚拟屏**，不是 BYD 车机。
  手机上虚拟屏的 displayId 命名/编号与车机不完全一致，但 `displayId != 0`
  这一触发条件与车机分屏等价。
- 车机上 `ActivityTaskManager.getService()` 是否同样被 hiddenapi 拒绝，
  决定走的是 `moveTaskToDisplay(0)` 分支还是 `CLEAR_TASK` 重启分支；
  **两条分支都会把 App 弄出分屏**，因此补丁都有效。
- 安装的包 SHA-256 已核对：
  - 原包 = `450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285`
  - 补丁包 = `01de14f7620df5f47bc17620a8993a1d5e701d1a136594b8031b44dc74813cf6`
  （验证过程中手机上一度就是补丁包，已抓包比对确认字节一致）

---

# 8. 第二个独立根因：`NaviView.Dd()` 空指针（`classes22.dex`）

## 8.1 怎么发现的

在手机上用 **真实分屏**（AOSP `wm shell splitscreen moveToSideStage`）复现时，
修好 `mcFixDisplay` 的包**仍然会闪退**，但栈完全不同，而且**与 `classes9.dex` 无关**
（所以不是补丁引入的）：

```
java.lang.NullPointerException: Attempt to invoke virtual method
  'void android.widget.TextView.setOnClickListener(android.view.View$OnClickListener)'
  on a null object reference
    at com.autosdk.drive.navi.view.NaviView.Dd(Unknown Source:168)
    at com.autosdk.drive.navi.view.NaviView.U1(Unknown Source:1083)
    at com.autosdk.drive.navi.presenter.NaviPresenter.onViewCreated(Unknown Source:24)
    at k.e.j.c.o.onViewCreated(Unknown Source:20)
    at androidx.fragment.app.Fragment.performViewCreated(Unknown Source:4)
```

触发路径：进主页 → 搜索目的地 → 点进 POI 详情 → 点"导航" → 进 `NaviFragment` → 崩。

## 8.2 静态根因

`NaviView.Dd()` 尾部是一串 `setOnClickListener(this.X6)`，其中 `j5` 这一项**没有判空**
（紧邻的 `i5` 却有）：

```smali
    iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->i5:Lcom/autonavi/skin/view/SkinView;
    if-eqz v0, :cond_2                      # ← i5 有判空
    iget-object v1, p0, ...->X6:...OnClickListener;
    invoke-virtual {v0, v1}, Landroid/view/View;->setOnClickListener(...)V
    :cond_2
    iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->j5:Lcom/autonavi/skin/view/SkinTextView;
    iget-object v1, p0, ...->X6:...OnClickListener;   # ← j5 没判空 → NPE
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setOnClickListener(...)V
```

偏移量 168 也正好落在这条 `invoke-virtual` 上（逐条按 dalvik 指令宽度累加算出来的）。

`j5` 的来源（`NaviView` 的 `initViews`，smali 行 11892）：

```smali
sget v1, Lcom/autosdk/drive/R$id;->lane_location:I     # 0x7f0a09e7
invoke-virtual {p0, v1}, ...->findViewById(I)Landroid/view/View;
check-cast v1, Lcom/autonavi/skin/view/SkinTextView;
iput-object v1, p0, Lcom/autosdk/drive/navi/view/NaviView;->j5:...
```

### 布局选择链（为什么 `j5` 会是 null）

用 `aapt d xmltree` 把三份布局逐个比对：

| 布局 | `lane_location` | `siv_gps_click` | 谁用 |
|---|---|---|---|
| `fragment_auto_navi` | ✅ | ❌ | 普通（竖屏/默认） |
| `fragment_auto_navi_1_3` | ✅ | ❌ | 平台化 UI（`isPlatformUI()==true`） |
| `fragment_auto_navi_half` | ❌ | ❌ | **多窗口 / 非平台化** ← 崩的就是这个 |

选择逻辑：

```
NaviViewManager.f.c()  →  若 PlatformUtils.isPlatformUI()  →  _1_3 / fragment_auto_navi
                          否则                             →  fragment_auto_navi_half
```

而 `isPlatformUI()`：

```java
public static boolean isPlatformUI() {
    return isUIPlatformized()
        || DILINK_UI_7.equals(getDiLinkUIVersion())   // "7.0UI"
        || "RUI".equals(getDiLinkUIVersion());
}
```

`getDiLinkUIVersion()` 读系统属性 `ro.vehicle.type`（经 `DiLinkPlatformImpl`）。

**手机实测**：`PlatformUtils: [main][getPlatform] platform: IVI` → `getDiLinkUIVersion()` = `"0.0UI"`
→ `isPlatformUI() == false` → 多窗口时选 `fragment_auto_navi_half` → `lane_location` 不存在
→ `j5 == null` → NPE。

**也就是说：这是一条"非平台化设备"才会踩到的路径。** 比亚迪车机若 `isPlatformUI()==true`，
走的是完整布局，不会崩；但若车机 UI 版本不在白名单（老 DiLink / `0.0UI`），分屏进导航就会崩。

## 8.3 修复

按相邻 `i5` 的写法给 `j5` 加判空（`scripts/fix_NaviView.py`）：

```smali
    iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->j5:Lcom/autonavi/skin/view/SkinTextView;
    if-eqz v0, :cond_j5
    iget-object v1, p0, Lcom/autosdk/drive/navi/view/NaviView;->X6:Landroid/view/View$OnClickListener;
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setOnClickListener(Landroid/view/View$OnClickListener;)V
    :cond_j5
```

## 8.4 可复现脚本

`scripts/repro_navi_npe.sh <apk|->` 把整条路径自动化：

```
启动 → 进分屏(moveToSideStage) → 点"查找目的地" → input text "wanda"
→ 点第一条 POI → 点"导航" → 抓 logcat 并统计
```

## 8.5 A/B 对照结果（手机真实分屏，全程可复现）

| 包 | `NaviView.Dd` 帧 | `FATAL EXCEPTION` | 进程 | 导航页 |
|---|---|---|---|---|
| 只修 #1（`amap-mcfix-only-signed.apk`, `01de14f7…`） | **9** | **1** | 已死（`pidof` 空） | 未显示 |
| 两个都修（`amap-splitfix.apk`, `e32177ee…`） | **0** | **0** | 存活 `pid=24056` | 正常渲染（`NaviFragment.onViewCreated` → `BaseNaviView.initViews` 正常走完） |

日志：`.work/logs/amap-mcfix-only-signed-navinpe.log`（崩）、
`.work/logs/amap-splitfix-navinpe.log`（不崩）。

> 结论：**#2 是独立于 #1 的真实缺陷，且在非平台化设备上是分屏进导航的致命崩溃。**

## 8.6 两种分屏的差异（重要，避免误判）

| | 触发 `mcFixDisplay` (#1) | 触发 `NaviView.Dd` (#2) |
|---|---|---|
| 车机 BYD 分屏（独立显示屏 `displayId=1/2`） | ✅ | ✅（若 `isPlatformUI()==false`） |
| 手机 `overlay_display_devices` 虚拟屏（`displayId=2`） | ✅ | ✖（未进导航） |
| 手机 AOSP 分屏（`windowingMode=multi-window`，`displayId=0`） | ✖ | ✅ |

- 真实同屏分屏**不会**改变 `displayId`，只改 `windowingMode`，所以 `mcFixDisplay()` 不触发；
  这种场景靠 `isInMultiWindowMode()` 选布局，于是暴露 #2。
- 车机分屏是独立显示屏，**两个条件同时满足**，所以车机上两个 bug 都会碰到。
- 复现 #2 不需要车机：任何 Android 设备 `wm shell splitscreen moveToSideStage <taskId> 0` 即可。

## 8.7 局限

- 车机侧仍无法直连 adb，`isPlatformUI()` 在真实 BYD 车机上的取值未实测；
  但 #1 已由虚拟屏 A/B 直接证明，#2 已由真机 A/B 直接证明，两者的修复都不依赖该取值。
- 建议车机上仍做一次安装验证（见 §9）。

---

# 9. 安装注意事项

补丁包签名与原包**不同**（原 `E4:4F:CB:38…` → 新 `89:B8:C3:05…`），因此：

- **必须卸载原 App 再安装补丁包**（签名不一致无法覆盖安装），会丢失 App 内数据/登录态。
- 若车机把高德作为**系统预装应用**，卸载/替换需要 root，或把补丁包刷进 system 分区。
- 若车机上还有别的模块按原签名指纹校验本 App，需要一并处理（本包内部无此校验，见 §4）。

```bash
adb uninstall com.autonavi.amapauto
adb install -r .work/out/amap-splitfix.apk
```

---

# 10. 第三个根因：注入代码强制沉浸式全屏（界面永远全屏）

## 10.1 现象

安装这个改包后，App 界面**默认全屏**：状态栏和底部导航键都被隐藏，和官方包行为不一致。

## 10.2 排查：先排除"主题自带全屏"

`MainActivity` 的主题是
`@style/Theme.AppCompat.Byd.Light.NoActionBar.FullScreen.UI.Integrate`（`0x7f13039f`），
名字里带 `FullScreen`，很像是资源层面的全屏。但逐级展开主题父链后可以排除：

| 主题 | `windowFullscreen` (0x0101020c) | `windowLayoutInDisplayCutoutMode` |
|---|---|---|
| `Theme.AppCompat.Byd.Light.NoActionBar.FullScreen.UI.Integrate` | 无 | 无 |
| `Theme.AppCompat.Byd.DayNight.NoActionBar` | 无 | 无 |
| `Theme.AppCompat.Byd.NoActionBar` | 无 | 无 |
| `Theme.AppCompat.Byd` | 无 | 无 |
| `Base.Theme.AppCompat.Byd` | 无 | 无 |
| …（一直到 `Platform.V25.AppCompat`） | 无 | 无 |

关键旁证：**`resources.arsc` 的 zip 时间戳仍是 2026-09-30**（未被重打包改动过），
而三个被注入改写的 dex 时间戳分别是 2026-10-07 / 2026-10-01 / 2026-10-01。
也就是说主题与资源是**原版 BYD**的，主题链里根本没有 `windowFullscreen` 属性。

## 10.3 真凶：注入的 `DpiScaleManager.applyImmersive()`

全代码树里 `setSystemUiVisibility(...)` 只有两处调用：

| 位置 | 值 | 判断 |
|---|---|---|
| `k/e/w/r.java:112` | `5380` = `0x1504` = `FULLSCREEN\|LAYOUT_STABLE\|LAYOUT_FULLSCREEN\|IMMERSIVE_STICKY` | **原版**：定义在 `classes8.dex`（未被改动），且被 BYD 设置 `getConfigKeySystemBarOffOn()==0` 保护 |
| `com/wzw/scale/DpiScaleManager.java:102` | `5894` = `0x1706` = `HIDE_NAVIGATION\|FULLSCREEN\|LAYOUT_STABLE\|LAYOUT_HIDE_NAVIGATION\|LAYOUT_FULLSCREEN\|IMMERSIVE_STICKY` | **注入**：`com.wzw.*` 第三方包，定义在 `classes25.dex`（2026-10-01 被改） |

`0x1706` 里多了 `HIDE_NAVIGATION(0x2)` 与 `LAYOUT_HIDE_NAVIGATION(0x200)`，
即**状态栏和导航栏一起隐藏**的沉浸式粘性全屏 —— 与"界面永远全屏"的现象完全吻合。

调用点：

```java
// com/byd/automap/activity/MainActivity.java:2705-2711  onCreate()
super.onCreate(bundle);
if (mcFixDisplay()) { return; }
Logger.setLog(true);
Log.e("McDebug", "logger enabled for diagnosis");   // ← 同批注入的日志
DpiScaleManager.applyImmersive(this);                // ← 注入的全屏
```

`applyImmersive()` 还无条件把 `layoutInDisplayCutoutMode` 设为 3（`ALWAYS`），
并顺带调用注入的 `VoiceXtt.attachContext()/installAsync()`（小团团语音）。
它**没有任何用户开关**（`DpiScaleManager` 的 SharedPreferences `wzw_dpi_scale`
只有 `map`/`ui` 两个缩放键）。

## 10.4 运行时证据（原包，未打补丁）

| 检查 | 结果 |
|---|---|
| 启动日志 | `I WZW_DPI : applyImmersive sdk=36` |
| App 在前台 `dumpsys window displays \| grep type=statusBars` | `visible=false` |
| 按 Home 回桌面后同一命令 | `visible=true` |
| `dumpsys window windows`（App 窗口 `mAttrs`） | 含 `layoutInDisplayCutoutMode=always` |

App 在前台时状态栏 `visible=false`、退到后台立刻变 `true`，说明是 **App 自己**把它隐藏的。

## 10.5 修复

`applyImmersive()` 里整段 window 操作（`getAttributes` / `layoutInDisplayCutoutMode`
/ `setSystemUiVisibility`）直接跳过，**保留其后的 `VoiceXtt` 初始化**，
避免连带干掉注入的语音功能：

```smali
    :cond_1
    goto :goto_mc_no_immersive        # ← 新增：跳过整段 window 操作

    :try_start_1
    invoke-virtual {v1}, Landroid/view/Window;->getAttributes()...
    ...（原代码保留为死代码）...

    :goto_mc_no_immersive             # ← 新增：跳转目标
    .line 120
    :try_start_3
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
```

选择"跳过"而不是"改 `0x1706` 为 `0x0`"，是因为 `0x0` 仍会覆盖掉宿主 App 自己
可能设置的 UI 标志；整段不碰最安全。也不删整个方法，因为 `VoiceXtt` 初始化在里面。

脚本：`scripts/fix_DpiScaleManager.py`（锚点唯一性有断言保护）。

## 10.6 A/B 对照（手机，同一台设备、同一 APK 其余条目逐字节相同）

对照组 `amap-nofix3.apk`（`e32177ee…`，只含修复 #1+#2，`classes25.dex` 未改）
vs 修复组 `amap-splitfix.apk`（`93f8831b…`，三个修复都含）：

| 判据 | 对照组（无 #3） | 修复组（含 #3） |
|---|---|---|
| `type=statusBars visible=` | **`false`** | **`true`** |
| logcat `WZW_DPI : applyImmersive` 出现次数 | 2 | **0**（证明 `goto` 生效） |
| logcat `WZWXTT`（VoiceXtt 仍在跑） | 有 | **有**（证明语音未被误伤） |
| App 窗口 `mAttrs` 里的 `layoutInDisplayCutoutMode=always` | 有 | **无** |
| 状态栏 122px 区域截图 | 无状态栏内容（`std=0.054`） | 有状态栏内容（`std=0.157`） |
| `uiautomator dump` 顶部节点 | — | App 自带 `status_bar_bg` (ImageView) 位于 `y=0..122`，地图内容下移到 `y=87+` |
| 进程存活 / `FATAL EXCEPTION` | 存活 / 0 | 存活 / 0 |

日志：`.work/logs/immersive-nofix3.log`（对照）、`.work/logs/immersive-fixed.log`（修复），
截图：`.work/logs/immersive-nofix3.png`、`.work/logs/immersive-fixed.png`。

## 10.7 三个修复叠加后的整体回归

`scripts/repro_navi_npe.sh`（真实分屏 + 搜索 + 起导航）在三个修复都打上的包上：

```
pid=16022                  ← 进程存活（对照组此处置空 = 闪退）
NaviView.Dd           0    ← 无 NPE
FATAL EXCEPTION       0
mInSplitScreen=true   9
isInMultiWindowMode:true  1
type=statusBars visible=true   ← 分屏导航中状态栏依然可见
```

---

# 11. 第四个问题：装不上车机（「与现有软件冲突」）→ 改包名

## 11.1 现象

车机（比亚迪 DiLink）上安装重打包的 APK 时，安装器报「与现有软件冲突」，
安装失败。手机侧 `adb install` 能复现底层错误码。

## 11.2 先排除一个常见的误判

用户最初的想法是「改成高德公开车机版的包名」。**这条路是死路**：
实测下载官网两个公开车机版，包名与当前重打包完全相同。

| 来源 | 文件 | 包名 | versionCode |
|---|---|---|---|
| 官网老版 | `guanwangV1.9.0.2080.apk` (33,264,452 B) | `com.autonavi.amapauto` | 546 |
| 官网最新 V950 | `Auto_9.5.0.600013_release_signed.apk` (154,947,836 B) | `com.autonavi.amapauto` | 26000001 |
| 本仓库重打包 | `高德车机版车道级导航版.原包.apk` | `com.autonavi.amapauto` | 872 |

三个包名完全一致 ⇒ 「改成公开车机版包名」是个空操作，解决不了冲突。
**必须换一个真正不同的包名。**

## 11.3 真正的冲突原因（实测错误码）

在已装 `com.autonavi.amapauto` 的手机上装改名后的包，`adb install` 给出：

```
INSTALL_FAILED_CONFLICTING_PROVIDER: Scanning Failed.:
Can't install because provider name com.byd.naviauto.mapprovider
(in package com.autonavi.amapautolite) is already used by com.autonavi.amapauto
```

所以冲突不只是「签名不同」，还有 **ContentProvider authority 撞车**。
车机上的原装应用和我们的包会同时声明这些 authority，Android 直接拒绝安装。

排查出**两个不由包名派生**的 authority：

| authority | 声明它的 Provider | 权限 |
|---|---|---|
| `com.byd.naviauto.mapprovider` | `com.autosdk.drive.magspace.MagSpaceContentProvider` | `...mapprovider.permission.READ_NAVI_DATA` |
| `com.byd.automap.fenceprovider` | `com.autosdk.bussiness.geofence.FenceContentProvider` | `...fenceprovider.permission.ACCESS_FENCE_DATA` |

其余 authority（`ExternalProvider` / `fx.provider` / `utilcode.provider` /
`androidx-startup`）都从包名派生，改包名时自动跟着变，不会冲突。

## 11.4 改包名的完整改动面

包名 `com.autonavi.amapauto` → `com.autonavi.amapautolite`，同时改这两个 authority。

| 位置 | 改法 | 脚本 |
|---|---|---|
| `AndroidManifest.xml`（二进制） | 重建字符串池，14→18 条字符串 | `scripts/rename_pkg_binary.py` |
| `resources.arsc`（二进制） | 包名 256 字节字段 | 同上 |
| dex 类型描述符 `Lcom/autonavi/amapauto/` | 无条件全改（13 个类 + 引用） | `scripts/fix_RenamePackage.py` |
| dex 字符串字面量 | 选择性改，见 §11.5 | 同上 |
| 两个 authority 及其权限名 | 全改 | 同上（`EXTRA` 表） |

> **坑 1**：新包名 `com.autonavi.amapautolite` 以旧包名 `com.autonavi.amapauto`
> 为前缀，直接用 `str.replace` 会把上一次的结果再替换一次，产出
> `com.autonavi.amapautolitelite`。两个脚本都用负向断言
> `com\.autonavi\.amapauto(?!lite)` 锚定。
>
> **坑 2**：authority 除了出现在 `const-string` 指令里，还会以字段初始化器的
> 形式出现：`.field public static final AUTHORITY:Ljava/lang/String; = "..."`。
> 正则要同时覆盖这两种写法，否则会漏掉
> `FenceContentProvider.AUTHORITY`。

## 11.5 「safe」口径：哪些字符串不改

按用户选定的保守口径，**保持原样**（这些值是上报给高德/比亚迪服务端的身份标识）：

- `UserConstant.PACKAGE_NAME`、`BydAccountReceiver.PACKAGE_NAME`（账号绑定 / 云端接口参数）
- `BydAccountReceiver$CallBackNotify`、`BydAccountReceiver` 的
  `lambda$onReceive$0` / `lambda$onReceive$1` / `unBindRequest`
- `ProtocolUtils`、`AesDemoUtil`、`k/e/g/d2/b/h`、`SettingAssetPresenter`、
  `com/autosdk/user/presenter/account/`（账号相关）
- `CarModelPackageManager`（`"com.autonavi.amapauto.bydcar"` 是与外部数据比对的 JSON `format` 常量）
- `AutoApplication`、`android/media/AudioTrack`（车机平台标识 / GAODE_VEHICLE 通道判断）

**必须跟着改**：AIDL 生成的 Binder token
（`com.autonavi.amapauto.aidl.IJsonProtocol*`）。这些 token 由 AIDL 编译器按
`<包名>.<接口名>` 生成，必须和改名后的接口类保持一致，否则
`$Stub` 与 `$Proxy` 对不上，调用会抛
「Binder invocation to an incorrect interface」。两端都在本 APK 内，
不涉及外部对端。因此脚本里把它们放进 `ALWAYS_RENAME`，即使在 KEEP 文件内也改。

## 11.6 验证结果（手机，与旧包共存）

安装前手机已装 `com.autonavi.amapauto`（原包），直接安装改包名后的 APK：

```
$ adb install -r .work/out/amap-splitfix-lite.apk
Install command complete in 8155 ms          ← 不再报冲突

$ adb shell pm list packages | grep amap
package:com.autonavi.amapauto                ← 原装保留
package:com.autonavi.amapautolite            ← 新包共存
```

两个包都能各自正常启动（`pidof` 都返回进程号）。

改包名后三个修复依然生效（`.work/logs/renamed-launch.log`）：

| 判据 | 结果 |
|---|---|
| 进程存活 | ✔ `pid=7245` |
| `FATAL EXCEPTION` | 0 |
| `mc_fix_display_relaunched`（fix#1） | 0 |
| `WZW_DPI : applyImmersive`（fix#3） | 0 |
| `WZWXTT`（注入语音仍在跑） | 11 行，未误伤 |
| `type=statusBars visible=` | `true` |
| `com.byd.naviauto.mapprovider` 旧串残留 | 0 |
| manifest 结构 vs 原包（归一化后） | 完全一致（997 行 / 613 属性） |
| 25 个 dex 头部校验 | 全部通过 |

另外用虚拟显示（`overlay_display_devices`，displayId≠0，即比亚迪分屏的等价物）
启动新包：`mc_fix_display_relaunched=0`、`FATAL EXCEPTION=0`、进程存活 ⇒ fix#1 在改包名后依然有效。

## 11.7 已知取舍

改成独立包名后，它就是**另一个 App**。车机上以 `com.autonavi.amapauto`
为键的系统集成（语音唤醒、方向盘按键、仪表/HUD 投射、
`json_protocol_service` / `carlie` AIDL）仍会绑定到**车机原装的那个**应用，
不会自动接到我们这个共存包上。这是「与原装共存」的必然代价。

---

# 12. 修复 #5：个人中心 → 收藏夹 闪退（`CalledFromWrongThreadException`）

## 12.1 现象

登录后进入 **设置 → 我的 → 收藏夹**，App 立刻闪退。Logcat：

```
FATAL EXCEPTION: main
Process: com.autonavi.amapautolite, PID: 9891
java.lang.RuntimeException: HMI callback exception:ThreadId(15544):
  android.view.ViewRootImpl$CalledFromWrongThreadException:
  Only the original thread that created a view hierarchy can touch its views.
  Expected: main  Calling: bl_thd_pool_wor
    android.view.ViewRootImpl.checkThread(ViewRootImpl.java:13447)
    android.view.ViewRootImpl.requestLayout(ViewRootImpl.java:3564)
    android.view.View.requestLayout(View.java:30022)
    android.widget.AbsListView.requestLayout(AbsListView.java:2124)
    android.widget.TextView.checkForRelayout(TextView.java:11812)
    android.widget.TextView.setText(TextView.java:7557)
    k.e.j.d.j0.updateViewText(Unknown Source:6)
    k.e.v.j.f.f.h2(Unknown Source:47)
    com.autosdk.user.presenter.behavior.UserFavoritesPresenter.v0
    com.autosdk.user.presenter.behavior.UserFavoritesPresenter$3.notify
    com.autosdk.bussiness.user.model.SyncSdkModel.notify
    com.autonavi.gbl.user.router.SyncSDKServiceObserverRouter.notify
    com.autonavi.gbl.user.router.SyncsdkObserverJNI.SwigDirector_...
    com.byd.hotfix.ExceptionProcessImpl$1.handleMessage
```

## 12.2 崩溃链

```
SyncSDK 原生回调（GBL 线程池 "bl_thd_pool_worker"）
  -> SyncSDKServiceObserverRouter.notify
  -> SyncSdkModel.notify(4, 0)                // SyncSdkEventSyncEnd = 4
  -> UserFavoritesPresenter$3.notify(4, 0)
  -> UserFavoritesPresenter.v0()
  -> k.e.v.j.f.f.h2()
  -> k.e.j.d.j0.updateViewText()
  -> TextView.setText()  ->  requestLayout()  ->  ViewRootImpl.checkThread()
  -> CalledFromWrongThreadException
  -> ExceptionProcessImpl$1.handleMessage 在主线程重新抛出 RuntimeException
  -> FATAL EXCEPTION
```

`bl_thd_pool` 这个字符串**只存在于 `lib/arm64-v8a/libGComm3rd.so`**，
说明回调来自原生线程池，不是 Java 线程。

## 12.3 根因（静态 + 运行时确认）

`notify()` 里所有调用**只有 `v0()` 是裸的 View 操作**，其余都已经是线程安全的：

| `notify()` 内的调用 | 线程安全性 |
|---|---|
| `d2()` / `j2()` | `TaskManager.post(...)` 已经派发到主线程 |
| `X0()` → `W0()` | SharedPreferences 写入，本身线程安全 |
| `t0()` / `s0()` / `u0()` | RxJava `.observeOn(mainThread)` 已经派发 |
| **`v0()`** | **直接 `TextView.setText()`，无任何保护** ← 唯一真凶 |

**这是原包（BYD/高德集成层）自带的老 bug，不是我们补丁引入的。**
用未修改的 `classes8.dex` 同样必崩（见 12.6 对照组）。

## 12.4 修复

在 `v0()` 入口插入主线程守卫：非主线程时通过 `TaskManager.post(...)` 重新派发后返回。
`TaskManager.post()` 在已经在主线程时会**内联执行**，因此主线程调用路径行为完全不变。

```smali
.method public v0()V
    .locals 9

    invoke-static {}, Landroid/os/Looper;->myLooper()Landroid/os/Looper;
    move-result-object v0
    invoke-static {}, Landroid/os/Looper;->getMainLooper()Landroid/os/Looper;
    move-result-object v1
    if-eq v0, v1, :cond_v0_main          # 已在主线程 -> 直接跑原逻辑

    new-instance v0, Lk/e/v/h/c/m;        # 否则 post 到主线程再跑
    invoke-direct {v0, p0}, Lk/e/v/h/c/m;-><init>(...UserFavoritesPresenter;)V
    invoke-static {v0}, Lcom/autosdk/bussiness/common/task/TaskManager;->post(Ljava/lang/Runnable;)V
    return-void

    :cond_v0_main
    ...原 v0() 逻辑...
```

新增 `Lk/e/v/h/c/m;`（`Runnable` 转发到 `v0()`）。
选这个包名是因为 `k/e/v/h/c/` 下 `a..l` 已经是 `UserFavoritesPresenter` 的合成 lambda，
`m` 全 dex 未占用，且不受改包名影响。

### ⚠️ 分支方向（踩过的坑）

**必须用 `if-eq`（相等才跳转）**，不能用 `if-ne`。

- `if-eq v0, v1, :cond` = `myLooper() == getMainLooper()` 时进入原逻辑 ✔
- 用了 `if-ne` 会反转判断：主线程调用 → 走 post 分支 → `TaskManager.post` 在主线程**内联执行**
  → 再次进入 `v0()` → 再次 post → **无限递归 `StackOverflowError`**（实测 8188KB 栈爆掉）。
- `myLooper()==null`（原生线程）→ 与主 Looper 不等 → 走 post 分支，行为正确。

## 12.5 正确的复现路径（关键）

**入口是「设置」页里的「我的」标签，不是首页的收藏图标。**

首页右上角的 `siv_favorite_entry` 打开的是**搜索模块的收藏页**
（列表 id = `slv_search_favorite`），根本不会创建 `UserFavoritesPresenter`，
所以早期 A/B 全是假阴性（连诊断日志都不打）。

真正触发崩溃的路径（已固化到 `scripts/goto_favorites.sh`）：

```
首页 -> 底部栏「设置」(540,2598) -> 左侧「我 的」标签 -> 「收藏夹」
     -> UserFavoritesFragment (k.e.v.j.f.f, 列表 id = slv_favorite_list)
     -> initData() 发起同步 -> 原生回调 -> v0() -> 崩溃
```

## 12.6 A/B 对照（手机，可复现）

对照组 `amap-nofix5.apk`（fix#1..#4 + 改包名，**不含 fix#5**，`classes8.dex`
与修复前逐字节相同 `37ebb189…`）vs 修复组 `amap-splitfix-lite.apk`：

| 判据 | 对照组（无 #5） | 修复组（含 #5） |
|---|---|---|
| 进程存活 | **否（闪退）** | **是** |
| `CalledFromWrongThread` | **11** | **0** |
| `HMI callback exception` | **10** | **0** |
| `FATAL EXCEPTION` | **1** | **0** |
| `slv_favorite_list` 页面 | — | **渲染成功** |

复现脚本：

```bash
scripts/goto_favorites.sh                       # 导航到崩溃入口
scripts/ab_favorites_crash.sh <apk> <label>     # 安装 + 触发 + 统计
```

## 12.7 已知取舍

修复只把 `v0()` 的 UI 更新挪回主线程，**不改变同步逻辑、不改数据**。
`TaskManager.post` 在主线程内联，所以主线程路径零额外开销（仅多一次 Runnable 分配）。

---

# 13. 修复六：底栏「充电站」按钮点击打开的是加油站（行为与标签不一致）

## 13.1 现象

修复六的第一阶段（`resources.arsc` 字符串替换）完成后，导航页底部栏按钮的文字已经是
**「充电站」**（原为「加油站」），但**点下去仍然打开加油站搜索页**（筛选条是
「优惠油站」，结果是「中国石化 / 中国石油 / 壳牌」）。用户诉求：

> 「不对，显示`充电站`，点击也要是`充电站`才行」

同时首页搜索页的分类入口也显示为「加油站」。

## 13.2 排查：先把点击链路整条走通

从布局到搜索关键字，逐跳确认（全部为静态可证 + 运行时确认）：

```
res/layout/fragment_auto_navi.xml:97-100
  cl_navi_charging_station (SkinConstraintLayout)
    ├─ sl_navi_charging_station  (SkinLottieAnimationView, src=@drawable/icon_layer_btn_charging_day)
    └─ SkinTextView  android:text="@string/charge_station"   ← 无 resource-id
              │
              ▼  NaviView.smali:12555  sget cl_navi_charging_station
                 NaviView.smali:12561  iput-object ... R4
                 NaviView.smali:6689   iget-object ... R4
                 NaviView.smali:3454   R4.setOnClickListener
              ▼
NaviView.java:1380   ((d7) f10189d).onStartAlongWaySearch(1, p3.a())
              ▼
RouteResultMapPresenter.java:3975
   onStartAlongWaySearch(int i2, String str)
       -> onStartAlongWaySearch(1, o2.c(i2, null), null, false)
          # 传入的 p3.a() 被丢弃；第一个实参硬编码为 1
              ▼
k/e/d/q0/o2.java  c(1, null) == f(1, null, ...)  → 返回 ""（空关键字）
              ▼
j2.H4(1, "", null)   (j2.java:1086)
       -> new DriveAlongSearchCardViewR(..., C4 = 1, y4 = "", x4 = null, ...)
              ▼
DriveAlongSearchCardViewR.J()   (doSearch, line 1652)

    if (TextUtils.isEmpty(this.y4) && this.C4 != 3) {
        this.C4 = 2;
        this.y4 = CarUtils.isNewEnergyVehicle() ? "充电站" : "加油站";   // ← 真正的分叉点
    }
              ▼
    G1() -> DriveAlongSearchCardPresenterR.doEnSearch(C4, y4, ...)
```

**结论：图标本身是充电枪闪电（`icon_layer_btn_charging_day.xml`，`#ff9f19`），
英文资源是 `"Charge"`，整条链路都指向充电站——唯一把结果掰成加油站的是
`CarUtils.isNewEnergyVehicle()` 返回了 `false`。**

## 13.3 根因：`CarUtils.getPowerType()` 的 `-1` 回退方向写反了

`classes21.dex` 里 `com.autosdk.bussiness.user.utils.CarUtils`：

```java
public static int getPowerType() {
    ILoginCarData d = iLoginCarData;
    if (d == null) return 1;                 // 「还不知道」→ 电车
    if (d.getPowerType() == -1) return 0;    // 「读不到」  → 油车   ← BUG
    return iLoginCarData.getPowerType();
}
```

* `iLoginCarData` 的实现是 `k.e.d.q0.b2`，其 `getPowerType()` 转发给
  `PlatformUtils.getInstance().getPowerType()`（同在 `classes21.dex`）。
* `PlatformUtils.getPowerType()` 读取 BYD 车机属性 `"power_type"`
  （`VehicleInfoConstant.PLATFORM_PROPERTY` 同族机制）。**读不到时返回 `-1`**
  （`POWER_TYPE_INVALID`）。
* `PlatformUtils.getPowerType()` 里本来有一个 `-1 → 1`（电车）的兜底，但**只在
  `isTargetProject(app, "kd")` 成立时生效**；本包 manifest 的 `PRODUCT = "l5"`，
  所以兜底永不触发，值一路保持 `-1`。

于是在这台车机上（第三方重签名包，BYD 车服务拒绝读属性），**整个 App 降级为「油车」**：

| 位置 | 受影响的分支 |
|---|---|
| `DriveAlongSearchCardViewR.J()` | 关键字 `isNewEnergyVehicle() ? "充电站" : "加油站"` |
| `SearchExtraServiceInitInfo` | 首页分类宫格 `getGas()` 而非 `getCharging()` |
| `k/e/g/k2/d/p3.c()` | 沿途品牌条：油站品牌而非充电品牌 |
| `MainMapView` | `searchAroundByKey("加油站")` |
| `RouteRequestController` | 能耗模型 / 继续充电规划 |
| `com.autosdk.drive.widget.MapWidgetUtil` | `getChargeDrawableID` 等 5 处 `R$string.charge_station` |

**运行时确认**（`logcat`，`E D/SendCacheTool`）：

```
[main][needSend.PlatformUtils.getPowerType] value = -1, cache = (-1, 116570271), ret = false
```

`value = -1` 恒定出现，确认车机属性读不到。

> 这是**原包自带的老 bug**，不是补丁引入的，也不是分屏导致的。
> 两个分支自相矛盾：`iLoginCarData == null`（「还不知道」）被当成电车，
> 而 `-1`（「明确读不到」）被当成油车。「读不到车型」的保守解释不应该是「油车」。

## 13.4 修复

`scripts/fix_CarUtilsPowerType.py`：把 `-1` 回退分支的返回值由 `0`（油车）
改为 `1`（电车），与 `d == null` 分支保持一致。

```smali
    if-ne v0, v1, :cond_1
    const/4 v0, 0x0     ->  const/4 v0, 0x1
```

正则锚定整个 `getPowerType()` 方法体（含 `.locals 2` 与 `sget-object … iLoginCarData`），
避免误命中文件里其它相同的 `const/4 v0, 0x0`。

**范围说明**：这个改法面向**纯电车**。若车是油车，`-1` 回退应保持 `0`
（更好的做法是做成用户可选项）。本仓库按用户确认的车型（纯电）落地。

## 13.5 修复六的两个组成部分

| 阶段 | 脚本 | 改动 | 效果 |
|---|---|---|---|
| 6a 标签 | `scripts/fix_ChargeStationStrings.py` | 改 `resources.arsc`：26 个 charge 族字符串（53 处 entry 重指向） | 底栏/首页/沿途 文字变为「充电站」 |
| 6b 行为 | `scripts/fix_CarUtilsPowerType.py` | 改 `classes21.dex`：`getPowerType()` `-1` 回退 `0 → 1` | 点击打开充电站搜索页；首页分类、沿途品牌条同步 |

两者**必须同时存在**，否则会出现「字是充电站、点了是加油站」或反之的不一致。

## 13.6 运行时验证（手机，可复现）

设备：Redmi（Android 16）。虽然它不是 BYD 车机，但 `PlatformUtils.getPowerType()`
在这台手机上**同样返回 `-1`**（`logcat` 已确认），所以修复**可以在这台手机上完整验证**。

导航页底栏 `cl_navi_charging_station` 中心坐标 `(744,1082)`（横屏 2712×1220）。

| 判据 | 修复前（仅 6a） | 修复后（6a + 6b） |
|---|---|---|
| 底栏按钮文字 | 充电站 | 充电站 |
| 点击后筛选条 | **优惠油站** | **快充 / 超充** |
| 点击后结果 | **中国石化 / 中国石油 / 壳牌** | **小朗充电汽车充电站 / 蔚景云汽车充电站** |
| 点击后价格单位 | 元/升 | **元/度** |
| 首页搜索分类 | **加油站** | **充电站** |
| `FATAL EXCEPTION` | 0 | 0 |

点击后的页面文本（`uiautomator dump` 摘录）：

```
充电站
终点附近   快充   附近500米   超充
1  小朗充电汽车充电站(小朗充电-兰花丽景二期充电站)
   214米 · 石桥铺街道,石新路兰花丽景二期负一层275
2  蔚景云汽车充电站(雷鳗兰花丽景二期地下停车场B1层227号车位充电站)
   0.66 元/度
```

**严格 A/B 对照**：用同一套构建流程，只把 `classes21.dex` 换回未修版本
（`const/4 v0, 0x0`）生成对照包 `amap-ctl-carutils.apk`：

| 包 | SHA-256 | 说明 |
|---|---|---|
| `amap-ctl-carutils.apk` | `361b64b00aa10b021fd6bc8ebd3540c89fef14836e397a3a35e840c0d31b854a` | 仅 6a（标签），点击仍为加油站 |
| `amap-splitfix-lite.apk` | `f1d17de2ca1576112151c59c9de3fdd9478306c6ab13c7b05cedc07d162a293f` | 6a + 6b（标签 + 行为） |

对照包的 SHA 与**修复 6b 之前的构建逐字节相同**（`361b64b0…`），证明两个包之间的差异
**只有 `CarUtils.getPowerType()` 里的那一个 `const/4`**。

## 13.7 已知取舍

* 该修复把「读不到车型」一律当作**电车**。若把此包装到油车上，会出现「显示充电站、
  实际要找加油站」的反向不一致。更好的长期方案是把车型做成设置项，而不是编译期常量。
* 手机验证的是**关键字分叉**（`isNewEnergyVehicle()`），车机上还有
  `PlatformUtils.getPowerType()` 的其它直接消费者（见 13.3 表格），它们会一并转为电车路径——
  与纯电车型一致。
* `-1` 这个值本身在车机上代表「属性不可读」，不排除在**真正的 BYD 车机**上
  `power_type` 可正常读取（返回 1/2），那样 `-1` 分支根本不会走到，本修复为无害冗余。
