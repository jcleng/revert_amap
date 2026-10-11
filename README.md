# 高德车机版分屏闪退修复

逆向分析并修复 **BYD DiLink 车机版「高德地图（车道级导航版）」** 在 **分屏（Split-Screen）** 模式下的闪退问题。

## 结论速览

| 项目 | 内容 |
|---|---|
| 目标包 | `com.autonavi.amapauto` |
| 版本 | `V3.15.872.11.910.1.202608311746.2`（versionCode 872） |
| 原包 SHA-256 | `450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285` |
| **根因 1** | 第三方重打包注入的 `MainActivity.mcFixDisplay()`（`classes9.dex`） |
| **根因 2** | `NaviView.Dd()` 对 `j5`(= `lane_location`) 未判空 → NPE（`classes22.dex`） |
| **修复** | #1 短路为 `return false`；#2 加判空。只改这两个 dex 并重签 |
| 补丁包 SHA-256 | `e32177eec5076656497a02e967f8ad0e2ef58ee03cf8ebe2cedc25da93e9ee1d` |

两个 bug 的触发条件不同，**车机上分屏会同时踩到两个**：

| | 触发条件 | 场景 |
|---|---|---|
| #1 `mcFixDisplay` | `getDisplay().getDisplayId() != 0` | 车机分屏 = 独立显示屏 |
| #2 `NaviView.Dd` NPE | `isInMultiWindowMode() == true` | 同屏分屏（displayId 仍为 0） |

## 问题是什么

在比亚迪 DiLink 车机上把高德车机版放进**分屏**后，App 会立刻退出分屏（用户感知为"闪退"）。

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

只替换 `classes9.dex` 与 `classes22.dex`，其余 14792 个 zip 条目逐字节不变，然后重新签名。

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

## 使用方法

```bash
# 补丁包与原包签名不同，必须先卸载
adb uninstall com.autonavi.amapauto
adb install -r .work/out/amap-splitfix.apk
```

## 自己构建

```bash
bash scripts/build_patch.sh   # 生成打过补丁的 classes9.dex 与 classes22.dex
bash scripts/build_apk.sh     # 替换进原 APK + zipalign + apksigner
```

产物在 `.work/out/amap-splitfix.apk`。

## 仓库结构

```
docs/findings.md         完整逆向结论 + 运行时验证（主文档）
docs/static-findings.md  静态分析速记
scripts/build_patch.sh   dex 打补丁（两个修复）
scripts/fix_mcFixDisplay.py  修复 #1 的 smali 改写
scripts/fix_NaviView.py      修复 #2 的 smali 改写
scripts/build_apk.sh     打包 + 重签
scripts/capture.sh       adb 无线配对 / 抓崩溃日志
scripts/splitscreen.sh   分屏测试台（real 同屏分屏 / virt 虚拟屏）
scripts/repro_navi_npe.sh 一键复现 #2（真机真实分屏）
tools/JadxServer.java    JADX 常驻查询服务（加速反复 grep）
AGENTS.md                Agent / 开发者操作指南
```

## 注意事项

- ⚠️ **签名会变**。重签后证书指纹从 `E4:4F:CB:38…` 变为 `89:B8:C3:05…`。
  已排查的签名校验点（Tinker 热修、`Sign.checkPackageSign`、硬编码 MD5、`sharedUserId`）均**不阻塞**，
  但**尚不确定**车机上是否有其它模块按原指纹校验此 App。
- ⚠️ 车机若为系统预装应用，替换可能需要系统权限。
- ⚠️ 本仓库**不包含** APK / dex / 反编译源码等大文件（见 `.gitignore`）。请自备原包。
- ℹ️ `NaviView.Dd()` 的 NPE（根因 2）在**非平台化设备**（`PlatformUtils.isPlatformUI()==false`，
  例如 `ro.vehicle.type` 为 `IVI` / DiLink UI 版本为 `0.0UI`）上必现；平台化车机走完整布局不会崩，
  但只要车机不在白名单内，分屏进导航就会崩——所以建议两个修复都打。

## 免责声明

本项目仅用于**个人设备上已购应用的兼容性修复**与技术研究。请勿用于分发或商业用途。所有商标与版权归各自权利人所有。
