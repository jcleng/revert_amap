# 高德车机版（比亚迪 DiLink）分屏闪退 —— 逆向结论与修复

目标包：`高德车机版车道级导航版.原包.apk`
- 包名 `com.autonavi.amapauto`，版本 `V3.15.872.11.910.1.202608311746.2`（versionCode 872）
- SHA-256 `450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285`
- 签名者 **CN=amap-fix**（非高德官方），25 个 dex

**分屏闪退有两个独立根因，都已定位并修复、都已在真机上跑通 A/B 对照：**

| # | 位置 | 根因 | 修复 | 验证方式 |
|---|---|---|---|---|
| 1 | `classes9.dex` `MainActivity.mcFixDisplay()` | 第三方注入的 hack：`displayId != 0` 时强行走 `moveTaskToDisplay(0)` 或 `NEW_TASK\|CLEAR_TASK` 重启，把 App 从分屏里拽出去 | 该方法改成 no-op（恒 `return false`） | 虚拟屏 `displayId=2` A/B，见 §7 |
| 2 | `classes22.dex` `NaviView.Dd()` | `this.j5.setOnClickListener(...)` 未判空，而 `j5` = `R.id.lane_location` 在 `fragment_auto_navi_half`（多窗口/非平台化时选用的布局）里**不存在** → NPE 闪退 | 给 `j5` 加判空，与相邻的 `i5` 判空写法一致 | 手机真实分屏 + 导航，见 §8 |

两者触发条件不同：**#1 只在 `displayId != 0` 时触发**（车机分屏 = 独立显示屏）；
**#2 只在 `isInMultiWindowMode() == true` 时触发**（含 `displayId` 仍为 0 的同屏分屏）。
车机上分屏同时满足两个条件，所以两个都必须修。

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

### 3.3 产物

```
.work/patch/classes9_patched.dex    2,107,408 字节
  sha256 5ed376368a9edf17a1f035c7274f00895a2c820f8f65902ad46839a5baced463
.work/patch/classes22_patched.dex   3,549,488 字节
  sha256 8dd4b7d3faf384243082b7019dae7e07dfed78eef6ae7758d79ca5b6ed6b17fe

.work/out/amap-splitfix.apk       280,064,164 字节   ← 两个修复都在里面，推荐使用
  sha256 e32177eec5076656497a02e967f8ad0e2ef58ee03cf8ebe2cedc25da93e9ee1d

.work/out/amap-mcfix-only-signed.apk 280,064,164 字节 ← 只修 #1 的对照组，用于证明 #2 的存在
  sha256 01de14f7620df5f47bc17620a8993a1d5e701d1a136594b8031b44dc74813cf6
```

构建方式（只动 `classes9.dex` 与 `classes22.dex`，其余 14792 个条目逐字节不变）：

```bash
bash scripts/build_patch.sh   # baksmali 两个 dex → 应用 scripts/fix_*.py → smali 回 dex
bash scripts/build_apk.sh     # 替换进原 APK（丢弃旧 META-INF 签名）→ zipalign → apksigner(v1+v2+v3)
```

校验：
- `zipalign -c -p 4` → OK
- `apksigner verify` → v2/v3 通过
- 新 dex 与原 APK 其余所有条目逐字节比对：仅 `classes9.dex`、`classes22.dex` 与 `META-INF/MANIFEST.MF` 变化，其余完全一致
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
