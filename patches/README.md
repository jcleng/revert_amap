# patches/

## `mcFixDisplay.patched.smali`

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
