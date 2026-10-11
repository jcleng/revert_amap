# patches/

本目录存放**打补丁后**的关键 smali 片段，供人工比对与复现。

| 文件 | 目标 dex | 类 | 说明 |
|---|---|---|---|
| `mcFixDisplay.patched.smali` | `classes9.dex` | `com.byd.automap.activity.MainActivity` | 根因 1：`mcFixDisplay()` 短路为 `return false` |
| `NaviView.Dd.patched.smali` | `classes22.dex` | `com.autosdk.drive.navi.view.NaviView` | 根因 2：`Dd()` 中给 `j5`(`lane_location`) 加判空 |

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

## 最终 APK

```
.work/out/amap-splitfix.apk   280,064,164 字节
sha256 e32177eec5076656497a02e967f8ad0e2ef58ee03cf8ebe2cedc25da93e9ee1d
```

与原包相比只有 3 个条目变化：`classes9.dex`、`classes22.dex`、`META-INF/MANIFEST.MF`
（外加签名文件 `AMAPFIX.*` → `AMAPFIX2.*`）。
