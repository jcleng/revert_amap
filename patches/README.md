# patches/

本目录存放**打补丁后**的关键 smali 片段，供人工比对与复现。

| 文件 | 目标 dex | 类 | 说明 |
|---|---|---|---|
| `mcFixDisplay.patched.smali` | `classes9.dex` | `com.byd.automap.activity.MainActivity` | 根因 1：`mcFixDisplay()` 短路为 `return false` |
| `NaviView.Dd.patched.smali` | `classes22.dex` | `com.autosdk.drive.navi.view.NaviView` | 根因 2：`Dd()` 中给 `j5`(`lane_location`) 加判空 |
| `DpiScaleManager.applyImmersive.patched.smali` | `classes25.dex` | `com.wzw.scale.DpiScaleManager` | 根因 3：`applyImmersive()` 不再强制沉浸式全屏 |

---

## 1. `mcFixDisplay.patched.smali`

`com/byd/automap/activity/MainActivity.smali` 中 `mcFixDisplay()` 方法**打补丁后**的完整 smali。
方法体最前面插入三行，使其恒返回 `false`：

```smali
const/4 v0, 0x0

return v0
```

后面原有的注入逻辑**完整保留为死代码**（不可达），这样改动面最小、最不容易引入校验/栈映射问题。

### 原始方法（未打补丁）

```smali
.method private mcFixDisplay()Z
    .locals 7

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;
    ...  # 见 docs/findings.md 第 2 节的 Java 伪代码
.end method
```

### 如何应用

`scripts/build_patch.sh` 会自动完成（它按锚点文本精确替换，并断言锚点唯一）。
手动等价操作是：在 `smali_out/smali/com/byd/automap/activity/MainActivity.smali` 中，
把

```
.method private mcFixDisplay()Z
    .locals 7

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;
```

替换为

```
.method private mcFixDisplay()Z
    .locals 7

    const/4 v0, 0x0

    return v0

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;
```

### 产物校验

打补丁后的 `classes9.dex`：

- 大小 `2,107,408` 字节
- SHA-256 `5ed376368a9edf17a1f035c7274f00895a2c820f8f65902ad46839a5baced463`

---

## 2. `NaviView.Dd.patched.smali`

`com/autosdk/drive/navi/view/NaviView.smali` 中 `Dd()` 方法**打补丁后**的尾部片段。

### 原始（未打补丁，会 NPE）

```smali
    iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->i5:Lcom/autonavi/skin/view/SkinView;

    if-eqz v0, :cond_2                      # i5 有判空

    iget-object v1, p0, Lcom/autosdk/drive/navi/view/NaviView;->X6:Landroid/view/View$OnClickListener;

    invoke-virtual {v0, v1}, Landroid/view/View;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    :cond_2
    iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->j5:Lcom/autonavi/skin/view/SkinTextView;

    iget-object v1, p0, Lcom/autosdk/drive/navi/view/NaviView;->X6:Landroid/view/View$OnClickListener;

    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setOnClickListener(Landroid/view/View$OnClickListener;)V
```

`j5` = `findViewById(R$id.lane_location)`（id `0x7f0a09e7`）。当布局是
`res/layout/fragment_auto_navi_half.xml`（多窗口 / `PlatformUtils.isPlatformUI()==false` 时选用）
时该 View 不存在 → `j5 == null` → `NullPointerException`（偏移 `Dd()+168`）。

### 打补丁后

```smali
    iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->j5:Lcom/autonavi/skin/view/SkinTextView;

    if-eqz v0, :cond_j5                     # ← 新增，与相邻 i5 判空写法一致

    iget-object v1, p0, Lcom/autosdk/drive/navi/view/NaviView;->X6:Landroid/view/View$OnClickListener;

    invoke-virtual {v0, v1}, Landroid/widget/TextView;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    :cond_j5
```

### 如何应用

`scripts/fix_NaviView.py` 按正则精确匹配（断言唯一）后插入 `if-eqz` 与标签。

### 产物校验

打补丁后的 `classes22.dex`：

- 大小 `3,549,488` 字节
- SHA-256 `8dd4b7d3faf384243082b7019dae7e07dfed78eef6ae7758d79ca5b6ed6b17fe`

---

## 3. `DpiScaleManager.applyImmersive.patched.smali`

`com/wzw/scale/DpiScaleManager.smali` 中 `applyImmersive()` 方法**打补丁后**的完整 smali。

### 问题

注入代码无条件执行（`classes25.dex`，`com.wzw.*` 第三方包）：

```java
window.getDecorView().setSystemUiVisibility(5894);   // = 0x1706
```

`0x1706` = `HIDE_NAVIGATION(0x2)` + `FULLSCREEN(0x4)` + `LAYOUT_STABLE(0x100)`
+ `LAYOUT_HIDE_NAVIGATION(0x200)` + `LAYOUT_FULLSCREEN(0x400)` + `IMMERSIVE_STICKY(0x1000)`
——沉浸式粘性全屏，**状态栏与导航栏一起隐藏**，所以界面永远全屏。

### 原始（未打补丁）

```smali
    :cond_1
    :try_start_1
    invoke-virtual {v1}, Landroid/view/Window;->getAttributes()Landroid/view/WindowManager$LayoutParams;
    ...
    const/16 v2, 0x1706
    invoke-virtual {v1, v2}, Landroid/view/View;->setSystemUiVisibility(I)V
    ...
    .line 120
    :try_start_3
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
```

### 打补丁后

在 window 操作前插入 `goto`，直接跳到其后的 `VoiceXtt` 初始化：

```smali
    :cond_1
    goto :goto_mc_no_immersive              # ← 新增

    :try_start_1
    ...（原 window 操作完整保留为死代码）...

    :goto_mc_no_immersive                   # ← 新增
    .line 120
    :try_start_3
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
```

**为什么保留 `VoiceXtt`**：注入的语音功能（小团团音库）初始化就写在同一个方法里，
整段删掉会连带干掉语音。只跳过 window 操作即可。

**为什么不把 `0x1706` 改成 `0x0`**：`0x0` 仍会覆盖掉宿主 App 自己可能设置的 UI 标志，
整段不碰最安全。

### 如何应用

`scripts/fix_DpiScaleManager.py` 按锚点文本精确替换（断言锚点唯一），
并断言补丁后 `0x1706` 仍存在（成为死代码）、`goto` 与标签各出现正确次数。

### 产物校验

打补丁后的 `classes25.dex`：

- 大小 `564,664` 字节
- SHA-256 `2d80033df968503a9813ceb85c04bcb9cb5284fa68c6e93dc9c0fccb7ab17a56`

---

## 最终 APK

```
.work/out/amap-splitfix.apk   280,064,164 字节
sha256 93f8831bf43be0566a945e253c0cfa50a456a8a6736551e1e833279bd4b4e6ed
```

与原包相比只有 4 个条目变化：`classes9.dex`、`classes22.dex`、`classes25.dex`、
`META-INF/MANIFEST.MF`（外加签名文件 `AMAPFIX.*` → `AMAPFIX2.*`）。

### 对照组（用于隔离每个修复的效果）

| APK | SHA-256 | 含哪些修复 |
|---|---|---|
| `amap-mcfix-only-signed.apk` | `01de14f7620df5f47bc17620a8993a1d5e701d1a136594b8031b44dc74813cf6` | 仅 #1 |
| `amap-nofix3.apk` | `e32177eec5076656497a02e967f8ad0e2ef58ee03cf8ebe2cedc25da93e9ee1d` | #1 + #2 |
| `amap-splitfix.apk` | `93f8831bf43be0566a945e253c0cfa50a456a8a6736551e1e833279bd4b4e6ed` | #1 + #2 + #3 |
