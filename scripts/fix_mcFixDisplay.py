#!/usr/bin/env python3
"""Fix [1]: neutralize the injected MainActivity.mcFixDisplay() hack (classes9.dex).

Runs inside the baksmali output directory of classes9.dex.
"""
import sys

p = 'smali_out/smali/com/byd/automap/activity/MainActivity.smali'
s = open(p, encoding='utf-8').read()
old = """.method private mcFixDisplay()Z
    .locals 7

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;"""
new = """.method private mcFixDisplay()Z
    .locals 7

    const/4 v0, 0x0

    return v0

    invoke-virtual {p0}, Landroid/app/Activity;->getDisplay()Landroid/view/Display;"""
n = s.count(old)
assert n == 1, f"mcFixDisplay anchor count = {n}"
open(p, 'w', encoding='utf-8').write(s.replace(old, new, 1))
print("    patched mcFixDisplay -> always return false")
