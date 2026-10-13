# 高德车机版分屏闪退修复

逆向分析并修复 **BYD DiLink 车机版「高德地图（车道级导航版）」** 在 **分屏（Split-Screen）** 模式下的闪退问题。

📦 **现成修复包下载：[Releases / 1.0.0](https://github.com/jcleng/revert_amap/releases/tag/1.0.0)**

## 结论速览

| 项目 | 内容 |
|---|---|
| 原包名 | `com.autonavi.amapauto` |
| **新包名** | `com.autonavi.amapautolite`（为与原装共存而改，见问题 4） |
| 版本 | `V3.15.872.11.910.1.202608311746.2`（versionCode 872） |
| 原包 SHA-256 | `450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285` |
| **根因 1** | 第三方重打包注入的 `MainActivity.mcFixDisplay()`（`classes9.dex`） |
| **根因 2** | `NaviView.Dd()` 对 `j5`(= `lane_location`) 未判空 → NPE（`classes22.dex`） |
| **根因 3** | 第三方注入的 `DpiScaleManager.applyImmersive()` 强制沉浸式全屏，隐藏状态栏+导航栏（`classes25.dex`） |
| **根因 4** | 预装同包名应用签名不同 → `INSTALL_FAILED_UPDATE_INCOMPATIBLE`（车机显示「与现有软件冲突」） |
| **根因 5** | `UserFavoritesPresenter.v0()` 在原生线程上直接 `TextView.setText()` → `CalledFromWrongThreadException`（`classes8.dex`，**原包自带老 bug**） |
| **根因 6** | `CarUtils.getPowerType()` 的 `-1`（读不到车型）回退成**油车** → 底栏「充电站」按钮点击却打开加油站搜索（`classes21.dex`，**原包自带老 bug**） |
| **修复** | #1 短路为 `return false`；#2 加判空；#3 跳过整段 window 操作；#5 给 `v0()` 加主线程守卫；#6 改 arsc 字符串 + `-1` 回退为电车；#4 改包名共存。只改 5 个 dex + `resources.arsc` 并重签 |
| 补丁包 SHA-256 | `f1d17de2ca1576112151c59c9de3fdd9478306c6ab13c7b05cedc07d162a293f`（`amap-splitfix-lite.apk`，含修复 #1–#6） |

六个 bug 的触发条件不同，**车机上分屏会同时踩到 #1 和 #2**，#3 则与分屏无关、每次启动都生效：

| | 触发条件 | 场景 |
|---|---|---|
| #1 `mcFixDisplay` | `getDisplay().getDisplayId() != 0` | 车机分屏 = 独立显示屏 |
| #2 `NaviView.Dd` NPE | `isInMultiWindowMode() == true` | 同屏分屏（displayId 仍为 0） |
| #3 `applyImmersive` | 无（每次 `onCreate` 都执行） | 界面默认全屏、状态栏/导航栏被隐藏 |
| #4 包名冲突 | 车机已装原装高德 | 安装报「与现有软件冲突」，装不上 |
| #5 收藏夹线程 | 设置 → 我的 → 收藏夹 | 同步回调从原生线程更新 UI → 闪退 |
| #6 车型判定 | 车机读不到 `power_type` 属性（返回 -1） | 底栏「充电站」点了却搜加油站；首页分类也是加油站 |

## 问题是什么

两个问题，都来自同一个第三方改包：

1. 在比亚迪 DiLink 车机上把高德车机版放进**分屏**后，App 会立刻退出分屏（用户感知为"闪退"）。
2. 这个包**默认全屏**：状态栏和底部导航键被隐藏（官方包不会这样）。

## 为什么

原包**不是官方包**——签名是 `CN=amap-fix`（非高德官方），且只有 `classes9.dex` 的修改时间是 `2026-10-07`，其余 dex 都是 `2026-09-30`。

有人在里面注入了 `MainActivity.mcFixDisplay()`：

```java
private boolean mcFixDisplay() {
    if (getDisplay().getDisplayId() == 0) { mcDispFixTries = 0; return false; }
    if (mcDispFixTries >= 3) return false;
    mcDispFixTries++;
    try {
        // 反射: ActivityTaskManager.getService().moveTaskToDisplay(taskId, 0)
        ...
        return false;
    } catch (Throwable th) {
        Intent intent = new Intent(getIntent());
        intent.addFlags(0x10008000);          // NEW_TASK | CLEAR_TASK
        intent.putExtra("mc_fix_display_relaunched", true);
        startActivity(intent,
            ActivityOptions.makeBasic().setLaunchDisplayId(0).toBundle());
        finish();
        return true;
    }
}
```

它被放在 `onCreate()` 和 `onResume()` 的最前面，返回 `true` 时直接 `return`，跳过所有初始化。

**问题在于**：比亚迪的分屏就是"虚拟显示屏"。代码里 `k/e/d/q0/w1.b()` 明确把 `displayId == 1`、`displayId == 2`、名字以 `fission_` 开头、以及 `叠加视图 #1` 的显示设备当作分屏。也就是说——**App 在分屏里运行时 `getDisplayId() != 0` 是正常的**。

而注入代码把"不在 display 0"当成错误，于是：

- **反射成功** → `moveTaskToDisplay(taskId, 0)`，把任务从分屏拽回主屏；
- **反射失败**（Android 9+ 的 hiddenapi 会拦截 `ActivityTaskManager.getService()`）→ 走 catch，
  用 `NEW_TASK|CLEAR_TASK` **清空任务栈**重启 MainActivity，并指定 `setLaunchDisplayId(0)`。

两条路都会把 App 弄出分屏。而 `mc_fix_display_relaunched` 这个 extra 写进去之后**全包没有任何地方读取**，所以也没有"只重启一次"的保护；`mcDispFixTries` 是 static，进程一重启就归零，理论上能形成反复重启。

结论：**第三方作者想用"强制回 display 0"来修分屏，结果这个 hack 本身就是分屏闪退的来源。**

## 怎么修

### 修复一：`mcFixDisplay()` 变 no-op

```smali
.method private mcFixDisplay()Z
    .locals 7
    const/4 v0, 0x0
    return v0
    # 原逻辑保留为死代码
.end method
```

### 修复二：`NaviView.Dd()` 给 `j5` 加判空

`j5` = `findViewById(R.id.lane_location)`。多窗口 / 非平台化时选用的布局
`fragment_auto_navi_half` 里**根本没有这个 View**（用 `aapt d xmltree` 逐个布局核对过），
而 `Dd()` 直接裸调 `this.j5.setOnClickListener(...)` → NPE → 闪退。

```smali
    iget-object v0, p0, ...->j5:Lcom/autonavi/skin/view/SkinTextView;
    if-eqz v0, :cond_j5          # ← 新增，与相邻的 i5 判空写法一致
    iget-object v1, p0, ...->X6:Landroid/view/View$OnClickListener;
    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setOnClickListener(...)V
    :cond_j5
```

只替换 `classes9.dex`、`classes22.dex` 与 `classes25.dex`，其余 14791 个 zip 条目逐字节不变，然后重新签名。

### 修复三：`DpiScaleManager.applyImmersive()` 不再强制全屏

界面默认全屏**不是**主题造成的。`MainActivity` 的主题虽然叫
`Theme.AppCompat.Byd.Light.NoActionBar.FullScreen.UI.Integrate`，但把它整条父链展开后
**没有任何 `windowFullscreen` / `windowLayoutInDisplayCutoutMode` 属性**；
而且 `resources.arsc` 的 zip 时间戳仍是 `2026-09-30`（未被重打包改动），说明资源和主题是**原版 BYD**的。

真正的来源是注入的 `com/wzw/scale/DpiScaleManager.applyImmersive()`：

```java
// 全代码树里 setSystemUiVisibility 只有两处，这是被注入的那一处
window.getDecorView().setSystemUiVisibility(5894);   // = 0x1706
```

`0x1706` = `HIDE_NAVIGATION(0x2)` + `FULLSCREEN(0x4)` + `LAYOUT_STABLE(0x100)`
+ `LAYOUT_HIDE_NAVIGATION(0x200)` + `LAYOUT_FULLSCREEN(0x400)` + `IMMERSIVE_STICKY(0x1000)`
——**沉浸式粘性全屏，状态栏和导航栏一起隐藏**。
它还被无条件调用：

```java
// MainActivity.java:2705-2711  onCreate()
if (mcFixDisplay()) { return; }
Log.e("McDebug", "logger enabled for diagnosis");   // ← 同批注入
DpiScaleManager.applyImmersive(this);                // ← 注入的全屏
```

另一处 `setSystemUiVisibility(5380)`（`k/e/w/r.java`，值 `0x1504`，不含 `HIDE_NAVIGATION`）
是**原版**代码：定义在未被改动的 `classes8.dex`，且有 BYD 设置 `getConfigKeySystemBarOffOn()==0` 保护。

修复方式：让 `applyImmersive()` 整段 window 操作直接跳过（**保留其后的 `VoiceXtt` 初始化**，
避免误伤注入的语音功能）：

```smali
    :cond_1
    goto :goto_mc_no_immersive        # ← 新增

    :try_start_1
    ...getAttributes / layoutInDisplayCutoutMode / setSystemUiVisibility...（保留为死代码）

    :goto_mc_no_immersive             # ← 新增
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
```

### 修复五：`UserFavoritesPresenter.v0()` 加主线程守卫

登录后进 **设置 → 我的 → 收藏夹** 必闪退。同步 SDK 的原生线程池（`bl_thd_pool_worker`，
该字符串只存在于 `lib/arm64-v8a/libGComm3rd.so`）回调进来后一路同步执行到
`v0()` → `k.e.v.j.f.f.h2()` → `updateViewText()` → `TextView.setText()`，
在主线程之外碰 View → `CalledFromWrongThreadException` → `HMI callback exception` → FATAL。

`notify()` 里其余调用（`d2()`/`j2()` 走 `TaskManager.post`、`t0()`/`s0()`/`u0()` 走
RxJava `observeOn(mainThread)`、`X0()` 是 SharedPreferences 写入）**都已经是线程安全的**，
`v0()` 是唯一裸的 UI 操作。**这是原包自带的老 bug**，不是补丁引入的。

```smali
.method public v0()V
    .locals 9
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
    ...原 v0() 逻辑...
```

> ⚠️ 必须 `if-eq`（相等才跳转）。用 `if-ne` 会反转判断：主线程调用 → post 分支 →
> `TaskManager.post` 在主线程**内联执行** → 再次进 `v0()` → 无限递归 `StackOverflowError`。

**正确的复现入口是「设置 → 我的 → 收藏夹」，不是首页右上角的收藏图标**
——后者打开的是搜索模块的收藏页（`slv_search_favorite`），根本不创建
`UserFavoritesPresenter`，早期测试因此全是假阴性。脚本：`scripts/goto_favorites.sh`、
`scripts/ab_favorites_crash.sh`。

## 运行时验证（A/B 对照，已完成）

在 Redmi 手机（Android 16）上用 overlay 虚拟屏模拟车机分屏（`settings put global overlay_display_devices '1280x720/213'` → 得到 `displayId=2`，系统名为 `叠加视图 #1`），再用 `am start --display 2` 启动高德。

**未打补丁的原包**，日志出现完整触发链路：

```
E tonavi.amapauto: hiddenapi: Accessing hidden method
    Landroid/app/ActivityTaskManager;->getService()... reflection: denied
I ActivityTaskManager: START u0 {flg=0x10008000 ...} from pid 2576
E MainActivity: [onResume] extra: Bundle[{mc_fix_display_relaunched=true}]
D ActivityThread: Handle activity config changed,
    update application display id from 2 to new display 0
E AutoApplication: [onActivityDestroyed: activity is MainActivity]
```

**打补丁后**：`mc_fix_display_relaunched=0`、`ActivityTaskManager.getService()=0`，注入分支被彻底短路。

## 第二个根因的验证（真机真实分屏，A/B 对照）

手机上用 `wm shell splitscreen moveToSideStage <taskId> 0` 进**真实分屏**（`displayId` 仍为 0，
`isInMultiWindowMode()==true`）——这种场景**不会**触发 #1，但会触发 #2。

复现脚本 `scripts/repro_navi_npe.sh <apk>`：启动 → 进分屏 → 搜索 `wanda` → 选第一条 → 点导航。

| 包 | `NaviView.Dd` 帧 | `FATAL EXCEPTION` | 进程 |
|---|---|---|---|
| 只修 #1（`01de14f7…`） | **9** | **1** | 已死（闪退） |
| 两个都修（`e32177ee…`） | **0** | **0** | 存活，导航页正常 |

完整证据见 [`docs/findings.md`](docs/findings.md) 第 7、8 节。

## 第三个根因的验证（全屏，A/B 对照）

同一台手机，对照组 `amap-nofix3.apk`（`e32177ee…`，只含修复 #1+#2，`classes25.dex` 未改）
vs 修复组 `amap-splitfix.apk`（`93f8831b…`）：

| 判据 | 对照组（无 #3） | 修复组（含 #3） |
|---|---|---|
| `dumpsys window displays` 里 `type=statusBars visible=` | **`false`** | **`true`** |
| logcat `WZW_DPI : applyImmersive` 次数 | 2 | **0**（`goto` 生效） |
| logcat `WZWXTT`（VoiceXtt 仍运行） | 有 | **有**（语音未被误伤） |
| App 窗口 `layoutInDisplayCutoutMode=always` | 有 | **无** |
| 顶部 122px 截图 | 无状态栏内容 | 有状态栏内容，App 自带 `status_bar_bg` 可见，地图内容下移到 `y=87+` |

对照实验同时确认：原包运行时 App 在前台 `statusBars visible=false`，按 Home 回桌面立刻变 `true`
——证明是 **App 自己**隐藏了状态栏。详见 [`docs/findings.md`](docs/findings.md) 第 10 节。

## 第五个根因的验证（收藏夹闪退，A/B 对照）

同一台手机，入口 = 设置 → 我的 → 收藏夹。对照组 `amap-nofix5.apk`（fix#1..#4 + 改包名，
`classes8.dex` 与修复前逐字节相同）vs 修复组 `amap-splitfix-lite.apk`：

| 判据 | 对照组（无 #5） | 修复组（含 #5） |
|---|---|---|
| 进程存活 | **否（闪退）** | **是** |
| `CalledFromWrongThread` | **11** | **0** |
| `HMI callback exception` | **10** | **0** |
| `FATAL EXCEPTION` | **1** | **0** |
| 收藏页 `slv_favorite_list` | — | 渲染成功 |

详见 [`docs/findings.md`](docs/findings.md) 第 12 节。

## 第六个根因的验证（底栏「充电站」点击行为，A/B 对照）

底栏按钮文字改成「充电站」后，**点下去仍然打开加油站搜索页**。链路是：
`cl_navi_charging_station` → `onStartAlongWaySearch(1, "")` →
`DriveAlongSearchCardViewR.J()`：

```java
this.y4 = CarUtils.isNewEnergyVehicle() ? "充电站" : "加油站";
```

而 `CarUtils.getPowerType()`（`classes21.dex`）把「读不到车型」（`-1`）
回退成了**油车**，与 `iLoginCarData == null` 时回退成**电车**自相矛盾：

```java
if (d == null) return 1;                 // 「还不知道」→ 电车
if (d.getPowerType() == -1) return 0;    // 「读不到」  → 油车   ← BUG
```

车机读不到 BYD 属性 `power_type` 时恒为 `-1`（`logcat`：
`needSend.PlatformUtils.getPowerType] value = -1`），于是**整个 App 降级为油车**：
底栏点击搜加油站、首页分类是加油站、沿途品牌条是油站品牌。

修复（`scripts/fix_CarUtilsPowerType.py`）：`-1` 回退由 `0` 改为 `1`。
配合 arsc 字符串修复（`scripts/fix_ChargeStationStrings.py`），
标签与行为一致。

同一台手机（`PlatformUtils.getPowerType()` 同样返回 `-1`，所以可完整验证）：

| 判据 | 修复前（仅改标签） | 修复后（标签 + 行为） |
|---|---|---|
| 底栏按钮文字 | 充电站 | 充电站 |
| 点击后筛选条 | **优惠油站** | **快充 / 超充** |
| 点击后结果 | **中国石化 / 中国石油 / 壳牌** | **小朗充电汽车充电站 / 蔚景云汽车充电站** |
| 点击后价格单位 | 元/升 | **元/度** |
| 首页搜索分类 | **加油站** | **充电站** |
| `FATAL EXCEPTION` | 0 | 0 |

严格 A/B：同一构建流程，只把 `classes21.dex` 换回未修版（`const/4 v0, 0x0`）
生成对照包，其 SHA 与修复 6b 之前的构建**逐字节相同**（`361b64b0…`），
证明差异只有那一个 `const/4`。

详见 [`docs/findings.md`](docs/findings.md) 第 13 节。

## 使用方法

### 直接下载现成包

到 [**Releases / 1.0.0**](https://github.com/jcleng/revert_amap/releases/tag/1.0.0) 下载：

| 文件 | 内容 |
|---|---|
| `amap-splitfix-lite-v1.0.0.zip` | **修复包**（含修复 #1–#6），解压得 `amap-splitfix-lite.apk` |
| `amap-original-v1.0.0.zip` | **原始未修改包**，仅供对照/复现 |

修复包 SHA-256 `f1d17de2ca1576112151c59c9de3fdd9478306c6ab13c7b05cedc07d162a293f`（`amap-splitfix-lite.apk`）。

### 安装

装到**已预装高德**的车机上（要共存）用改包名版：

```bash
adb install -r amap-splitfix-lite.apk
# 安装后：com.autonavi.amapauto（原装）与 com.autonavi.amapautolite（修复版）共存
```

装到**没有预装高德**的设备上，可以用不改包名的版本：

```bash
adb uninstall com.autonavi.amapauto
adb install -r .work/out/amap-splitfix.apk
```

## 自己构建

```bash
bash scripts/build_patch.sh   # 生成打过补丁 + 改名的 *_pkg.dex
bash scripts/build_apk.sh     # 改包名/authority + 替换 dex + zipalign + apksigner
```

产物在 `.work/out/amap-splitfix-lite.apk`（改包名，`com.autonavi.amapautolite`）。

改包名涉及的坑（新包名以旧包名为前缀、authority 的字段初始化器写法、
AIDL token 必须跟着改）见 [`docs/findings.md`](docs/findings.md) 第 11 节。

## 仓库结构

```
docs/findings.md         完整逆向结论 + 运行时验证（主文档）
docs/static-findings.md  静态分析速记
scripts/build_patch.sh   dex 打补丁（5 个代码修复）
scripts/fix_mcFixDisplay.py   修复 #1 的 smali 改写
scripts/fix_NaviView.py       修复 #2 的 smali 改写
scripts/fix_DpiScaleManager.py 修复 #3（强制全屏）的 smali 改写
scripts/fix_UserFavorites.py  修复 #5（收藏夹线程）的 smali 改写 + 新增 Runnable 类
scripts/fix_ChargeStationStrings.py 修复 #6a（arsc 字符串）
scripts/fix_CarUtilsPowerType.py  修复 #6b（车型判定）
scripts/fix_RenamePackage.py   dex 侧改包名（类型描述符 + 选择性字符串 + 目录搬迁）
scripts/rename_pkg_binary.py   二进制改 AndroidManifest.xml / resources.arsc 的包名
scripts/build_apk.sh     改包名 + 打包 + 重签（含 #6a arsc 修复）
scripts/capture.sh       adb 无线配对 / 抓崩溃日志
scripts/splitscreen.sh   分屏测试台（real 同屏分屏 / virt 虚拟屏）
scripts/repro_navi_npe.sh 一键复现 #2（真机真实分屏）
scripts/goto_favorites.sh 导航到 #5 的真实崩溃入口（设置→我的→收藏夹）
scripts/ab_favorites_crash.sh 一键复现 #5 + A/B 统计
tools/JadxServer.java    JADX 常驻查询服务（加速反复 grep）
AGENTS.md                Agent / 开发者操作指南
```

## 注意事项

- ⚠️ **签名会变**。重签后证书指纹从 `E4:4F:CB:38…` 变为 `89:B8:C3:05…`。
  已排查的签名校验点（Tinker 热修、`Sign.checkPackageSign`、硬编码 MD5、`sharedUserId`）均**不阻塞**，
  但**尚不确定**车机上是否有其它模块按原指纹校验此 App。
- ⚠️ 车机若为系统预装应用，替换可能需要系统权限。**改包名版可绕过这一点**：
  它与原装共存，不覆盖系统应用（实测 `adb install` 成功，两个包同时存在）。
- ⚠️ **共存版与原装是两套数据**。账号登录状态、离线地图、设置各自独立，需要重新登录/下载。
- ⚠️ 车机上以 `com.autonavi.amapauto` 为键的**系统集成**（语音唤醒、方向盘按键、
  仪表/HUD 投射、`json_protocol_service` / `carlie` AIDL）仍绑定**原装**那个应用，
  不会自动切到共存包。这是共存的必然代价。
- ℹ️ 官方「高德公开车机版」的包名也是 `com.autonavi.amapauto`（实测官网 V1.9.0 与 V9.5.0
  两个包均如此），所以"改成公开版包名"无法解决冲突，必须换成真正不同的包名。
- ⚠️ 本仓库**不包含** APK / dex / 反编译源码等大文件（见 `.gitignore`）。请自备原包。
- ℹ️ `NaviView.Dd()` 的 NPE（根因 2）在**非平台化设备**（`PlatformUtils.isPlatformUI()==false`，
  例如 `ro.vehicle.type` 为 `IVI` / DiLink UI 版本为 `0.0UI`）上必现；平台化车机走完整布局不会崩，
  但只要车机不在白名单内，分屏进导航就会崩——所以建议两个修复都打。

## 免责声明

本项目仅用于**个人设备上已购应用的兼容性修复**与技术研究。请勿用于分发或商业用途。所有商标与版权归各自权利人所有。
