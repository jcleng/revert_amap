#!/usr/bin/env python3
"""Fix [3]: stop the injected DpiScaleManager.applyImmersive() from forcing
immersive-sticky fullscreen (classes25.dex).

Evidence
--------
* resources.arsc in the APK still carries the stock timestamp (2026-09-30), i.e. the
  resource table was NOT touched by the repack.  The MainActivity theme
  Theme.AppCompat.Byd.Light.NoActionBar.FullScreen.UI.Integrate and its whole parent
  chain contain no `windowFullscreen` / `windowLayoutInDisplayCutoutMode` attribute.
  -> the theme is stock BYD and cannot be the cause.
* The only `setSystemUiVisibility(...)` call sites in the whole decompiled tree are
  `k/e/w/r.java` (stock BYD dialog, guarded by the BYD setting
  `getConfigKeySystemBarOffOn()==0`) and the injected
  `com/wzw/scale/DpiScaleManager.java`.
* applyImmersive() does:
      window.getAttributes().layoutInDisplayCutoutMode = 3   (ALWAYS)
      window.getDecorView().setSystemUiVisibility(5894)      (0x1706)
  0x1706 = HIDE_NAVIGATION(0x2) | FULLSCREEN(0x4) | LAYOUT_STABLE(0x100)
         | LAYOUT_HIDE_NAVIGATION(0x200) | LAYOUT_FULLSCREEN(0x400)
         | IMMERSIVE_STICKY(0x1000)
  i.e. immersive-sticky fullscreen that hides BOTH the status bar and the navigation
  bar -- exactly the reported symptom.
* It is called unconditionally from MainActivity.onCreate() (line 2710), right next to
  the other injection (`Log.e("McDebug", ...)`), and has no user-facing switch.

Runtime confirmation (Redmi 2312DRA50C / Android 16, stock APK installed)
  app foreground -> dumpsys window displays | grep type=statusBars  => visible=false
  home screen    -> dumpsys window displays | grep type=statusBars  => visible=true
  logcat on launch: "I WZW_DPI : applyImmersive sdk=36"

Fix
---
Make applyImmersive() leave the window completely alone, while KEEPING the trailing
VoiceXtt.attachContext()/installAsync() calls (those are the injected voice feature and
are unrelated to the fullscreen complaint).  Implemented by branching over the whole
window-manipulation block straight to the VoiceXtt block.

Runs inside the baksmali output directory of classes25.dex.
"""
p = 'smali_out/smali/com/wzw/scale/DpiScaleManager.smali'
s = open(p, encoding='utf-8', errors='replace').read()

# --- anchor 1: entry of the window-manipulation try block -------------------
a1_old = """    :cond_1
    :try_start_1
    invoke-virtual {v1}, Landroid/view/Window;->getAttributes()Landroid/view/WindowManager$LayoutParams;
"""
a1_new = """    :cond_1
    goto :goto_mc_no_immersive

    :try_start_1
    invoke-virtual {v1}, Landroid/view/Window;->getAttributes()Landroid/view/WindowManager$LayoutParams;
"""

# --- anchor 2: entry of the VoiceXtt try block (jump target) ----------------
a2_old = """    .line 120
    :try_start_3
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
"""
a2_new = """    :goto_mc_no_immersive
    .line 120
    :try_start_3
    invoke-static {p0}, Lcom/wzw/voice/VoiceXtt;->attachContext(Landroid/content/Context;)V
"""

for name, old in (('cond_1', a1_old), ('VoiceXtt', a2_old)):
    n = s.count(old)
    assert n == 1, f"anchor {name} count = {n}"

s = s.replace(a1_old, a1_new, 1).replace(a2_old, a2_new, 1)

assert s.count('0x1706') == 1, "0x1706 should still be present (dead code now)"
assert s.count('goto :goto_mc_no_immersive') == 1
assert s.count(':goto_mc_no_immersive') == 2

open(p, 'w', encoding='utf-8').write(s)
print("    patched DpiScaleManager.applyImmersive -> no longer touches the window")
