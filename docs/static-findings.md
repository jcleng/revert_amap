# 静态分析发现（高德车机版 com.autonavi.amapauto）

## 包基本情况
- 包名: com.autonavi.amapauto  (比亚迪 DiLink 定制版)
- 版本: V3.15.872.11.910.1.202608311746.2 (versionCode 872)
- minSdk 24 / targetSdk 30
- 类数 18454（含内部类 49261），资源 14794，dex 25 个
- **签名者: CN=amap-fix, OU=dev, O=amap-fix**  ← 非官方签名
- **只有 classes9.dex 的 mtime 是 2026-10-07**（其余全部 2026-09-30）

## 该包已被第三方改动过（重要）
- 注入方法 `MainActivity.mcFixDisplay()`：若 `getDisplay().getDisplayId() != 0`，
  用反射调 `ActivityTaskManager.moveTaskToDisplay(taskId,0)`，失败则
  `startActivity(intent, ActivityOptions.makeBasic().setLaunchDisplayId(0))` 重启自己。
- 注入字段 `MainActivity.mcDispFixTries`、extra `mc_fix_display_relaunched`、
  日志 tag `McDebug`。
- 这些标识（mc = 某位修改者前缀）在原版高德中不存在。
- 含义：有人（可能就是用户/车机圈）已试图用"强制回 display 0"来修分屏/多屏问题。

## 分屏相关代码路径
1. `MainActivity.onMultiWindowModeChanged(boolean, Configuration)`
   - 屏幕 dp 尺寸变化 → `setMapContainerVisible(4)`（隐藏地图容器）
   - `glMapSurface.setZOrderMediaOverlay(true)`
2. `MainActivity.onConfigurationChanged`
   - `DPIUtil.C(...)` 重设密度、`m2.g(...)` 刷新宽高、`DPIUtil.G(decorView)` 判定左右/上下分屏
   - `isInMultiWindowMode()` → 写入 `isFullScreen` 偏好
3. `DPIUtil.G(View)`：按 decorView 屏幕坐标判定 1/2 分屏方位（左/右/上/下）
4. `DPIUtil.u(Activity)`：`isInMultiWindowMode()` 或 面积 ≤ 全屏 2/3 判为多窗口
5. `MainActivity.mcFixDisplay()`：**无 null 检查**直接 `getDisplay().getDisplayId()`；
   在 onCreate/onResume 最前面调用，返回 true 时直接 return（跳过初始化）

## 已识别的可疑点（待运行时验证）
- A. `mcFixDisplay()` 无 null 检查 + 反射调用失败路径会反复 startActivity/finish，
  分屏时可能造成 Activity 反复重建 → 闪退/黑屏。
- B. 地图 SurfaceView 是**进程级单例** `k.h.c.d0.e.d().c()`，
  分屏尺寸变化时在 MainActivity 与仪表/分屏卡片 Activity 之间被 addView/removeView 搬移，
  容易触发 "The specified child already has a parent" 或 surface 已销毁。
- C. `onMultiWindowModeChanged` 里 `setMapContainerVisible(4)` 隐藏容器，
  但随后 `onConfigurationChanged`/`doChangeScreen` 又 `setMapContainerVisible(0)`，
  时序竞争。
- D. `MainActivity.onMultiWindowModeChanged` 未判 `isFinishing/isDestroyed`。

## 下一步（需要运行时）
- 连接车机（无线调试），复现分屏闪退，抓 `logcat` 崩溃栈（尤其是 FATAL EXCEPTION / 
  AndroidRuntime / tombstone），确认是 Java 异常还是 native SIGSEGV。
