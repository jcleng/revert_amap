#!/usr/bin/env python3
"""Fix [2]: null-guard NaviView.j5 (lane_location) in NaviView.Dd() (classes22.dex).

Dd() ends with a chain of setOnClickListener(this.X6) calls.  Most fields come from
the shared fragment_auto_navi* layouts, but `j5` is findViewById(R.id.lane_location)
which does NOT exist in res/layout/fragment_auto_navi_half.xml -- the layout that
NaviViewManager picks when PlatformUtils.isPlatformUI() is false (e.g. while the app
is in multi-window / split screen).  The neighbouring `i5` (siv_gps_click, also absent
from that layout) is already null-guarded; j5 is not, hence:

  NullPointerException: Attempt to invoke virtual method
  'void android.widget.TextView.setOnClickListener(...)' on a null object reference
  at com.autosdk.drive.navi.view.NaviView.Dd(Unknown Source:168)

Runs inside the baksmali output directory of classes22.dex.
"""
import re
import sys

p = 'smali_out/smali/com/autosdk/drive/navi/view/NaviView.smali'
s = open(p, encoding='utf-8', errors='replace').read()

pat = re.compile(
    r'^(?P<ind>[ \t]*)iget-object +v0, +p0, +Lcom/autosdk/drive/navi/view/NaviView;->j5:Lcom/autonavi/skin/view/SkinTextView;\n'
    r'(?:[ \t]*\n)*'
    r'(?P=ind)iget-object +v1, +p0, +Lcom/autosdk/drive/navi/view/NaviView;->X6:Landroid/view/View\$OnClickListener;\n'
    r'(?:[ \t]*\n)*'
    r'(?P=ind)invoke-virtual +\{v0, +v1\}, +Landroid/widget/TextView;->setOnClickListener\(Landroid/view/View\$OnClickListener;\)V\n',
    re.M)

m = pat.search(s)
assert m, "NaviView.Dd() j5 setOnClickListener anchor not found"
assert len(pat.findall(s)) == 1, "anchor is not unique"

ind = m.group('ind')
repl = (
    f'{ind}iget-object v0, p0, Lcom/autosdk/drive/navi/view/NaviView;->j5:Lcom/autonavi/skin/view/SkinTextView;\n'
    f'\n'
    f'{ind}if-eqz v0, :cond_j5\n'
    f'\n'
    f'{ind}iget-object v1, p0, Lcom/autosdk/drive/navi/view/NaviView;->X6:Landroid/view/View$OnClickListener;\n'
    f'\n'
    f'{ind}invoke-virtual {{v0, v1}}, Landroid/widget/TextView;->setOnClickListener(Landroid/view/View$OnClickListener;)V\n'
    f'\n'
    f'{ind}:cond_j5\n')

s2 = s[:m.start()] + repl + s[m.end():]
open(p, 'w', encoding='utf-8').write(s2)
print("    patched NaviView.Dd() -> null-guard j5 (lane_location)")
