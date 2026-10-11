# AGENTS.md — 项目操作指南

> 面向在本仓库中工作的 AI Agent / 开发者。请先读完本文件再动手。

## 1. 项目目标

修复 **BYD DiLink 车机版「高德地图（车道级导航版）」** 在 **分屏（Split-Screen / Multi-Window）** 模式下的闪退。

- 目标包名：`com.autonavi.amapauto`
- 版本：`V3.15.872.11.910.1.202608311746.2`（versionCode 872，minSdk 24，targetSdk 30）
- 原包 SHA-256：`450a1848ec6ecbda9a981598b9338f58784dcd6951a81d7ec8a8e198f10bf285`

## 2. 根因（一句话）

原包是**第三方重打包**版本，注入了 `com.byd.automap.activity.MainActivity.mcFixDisplay()`。
该方法在 `getDisplay().getDisplayId() != 0`（车机分屏 / 副屏的**正常**状态）时会：

1. 反射调用 `ActivityTaskManager.getService().moveTaskToDisplay(taskId, 0)`，把任务从副屏拽回主屏；或
2. 反射失败（hiddenapi 拦截）时走 catch：`Intent` + `FLAG_ACTIVITY_NEW_TASK|FLAG_ACTIVITY_CLEAR_TASK`（`0x10008000`）
   + extra `mc_fix_display_relaunched=true` + `ActivityOptions.makeBasic().setLaunchDisplayId(0)`，
   `startActivity()` + `finish()`，即**清栈重启** MainActivity。

两条分支都会让用户看到"一进分屏就闪退 / 被弹出分屏"。

## 3. 修复

把 `MainActivity.mcFixDisplay()` 变成 **no-op**（恒 `return false`），只改 `classes9.dex`，其余 14793 个 zip 条目逐字节不变，然后重新签名。

- 补丁包：`.work/out/amap-splitfix.apk`
  SHA-256 `01de14f7620df5f47bc17620a8993a1d5e701d1a136594b8031b44dc74813cf6`
- 改动后的 smali：
  ```smali
  .method private mcFixDisplay()Z
      .locals 7
      const/4 v0, 0x0
      return v0
      # 原逻辑保留为死代码
  .end method
  ```

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
│   ├── build_patch.sh            # classes9.dex → 打补丁 → classes9_patched.dex
│   ├── build_apk.sh              # 替换 dex + zipalign + apksigner → 可安装 APK
│   ├── capture.sh                # adb 无线配对 / 连接 / 抓崩溃日志
│   ├── jxctl.sh / jxq.py         # JADX 常驻查询服务（快速 grep 反编译源码）
│   └── dexstr.py                 # DEX 字符串提取
├── tools/
│   ├── JadxServer.java           # JADX 常驻 TCP 查询服务
│   └── Export.java               # JADX 全量源码导出
└── .work/                        # 工作区（不入 git）
    ├── out/amap-splitfix.apk     # ★ 补丁产物
    ├── patch/classes9_patched.dex
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
# 1) 生成打过补丁的 classes9.dex
bash scripts/build_patch.sh

# 2) 替换进原 APK 并重签
bash scripts/build_apk.sh
```

`build_apk.sh` 会：
1. 逐条复制原 zip，跳过 `META-INF/*.SF|*.RSA|*.DSA|*.EC|MANIFEST.MF`，把 `classes9.dex` 换成补丁版；
2. `zipalign -f -p 4`；
3. `apksigner sign`（v1+v2+v3，keystore `.work/keystore/amapfix2.jks`，口令 `amapfix2`）。

## 7. 验证

### 静态验证
- `zipalign -c -p 4 <apk>` → OK
- `apksigner verify --print-certs <apk>` → v2/v3 通过
- 比对 zip 条目：只应有 `classes9.dex` 与 `META-INF/MANIFEST.MF` 变化

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

## 9. 已知的其它崩溃路径（与本次修复无关）

在 Redmi 手机（Android 16）上以**全屏**启动时复现了一个**不同的**崩溃：

```
java.lang.NullPointerException: Attempt to invoke virtual method
  'void android.widget.TextView.setOnClickListener(...)' on a null object reference
    at com.autosdk.drive.navi.view.NaviView.Dd(Unknown Source:168)
    at com.autosdk.drive.navi.view.NaviView.U1(Unknown Source:1083)
    at com.autosdk.drive.navi.presenter.NaviPresenter.onViewCreated(Unknown Source:24)
```

这是导航页（`NaviView`）在非车机环境下的布局缺失导致，**不是** `mcFixDisplay` 引起，也不是分屏闪退。在真车机上导航页正常，因此不作为本次修复目标。

## 10. 待办

- [ ] 在真车机上抓一次分屏闪退日志（需车机 adb 权限）以最终闭环。
- [ ] 确认车机是否存在按原签名指纹校验此 App 的模块。
- [ ] 若需保留"非分屏场景纠正显示"的行为，可改为 `if (isInMultiWindowMode()) return false;` 而非完全 no-op。
