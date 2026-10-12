#!/usr/bin/env python3
"""Fix [6]: make an UNKNOWN power type fall back to EV, not petrol (classes21.dex).

Symptom
-------
On the head unit the navigation bottom-bar button reads 「充电站」 (after the
resources.arsc string fix) but tapping it still opens a **petrol** search page
(加油站 / 优惠油站 / 中国石化 / 中国石油 / 壳牌), i.e. the label and the
behaviour disagree.  The user wants the tap to open the charging-station search.

Root cause
----------
The whole app branches on com.autosdk.bussiness.user.utils.CarUtils.getPowerType():

    public static int getPowerType() {
        ILoginCarData d = iLoginCarData;
        if (d == null) return 1;                 // <-- "unknown" -> EV
        if (d.getPowerType() == -1) return 0;    // <-- "unknown" -> PETROL  (bug)
        return iLoginCarData.getPowerType();
    }

iLoginCarData.getPowerType() delegates to
PlatformUtils.getInstance().getPowerType(), which reads the BYD car property
"power_type" (or CarInfoManagerImpl.getPowerTypeByPlatformB()).  When the
property cannot be read it yields -1 (POWER_TYPE_INVALID).  On a re-signed
third-party build the BYD car service usually refuses the read, so powerType is
permanently -1 and the app degrades to "petrol car" everywhere:

  * DriveAlongSearchCardViewR.J()  keyword = isNewEnergyVehicle() ? "充电站" : "加油站"
  * SearchExtraServiceInitInfo     home category grid (getGas() instead of getCharging())
  * p3.c()                         along-way brand strip (gas brands instead of charge brands)
  * MainMapView                    searchAroundByKey("加油站")
  * RouteRequestController         energy model / continue-charging planning

The two branches contradict each other: a *missing* iLoginCarData means "we do
not know yet" and is treated as EV, while an *explicitly invalid* -1 means "we
could not read it" and is treated as petrol.  The conservative reading of "I
could not read the car type" is not "petrol".

Patch
-----
Return POWER_TYPE_1 (1 = new-energy / EV) instead of POWER_TYPE_0 (0 = petrol)
when the value is POWER_TYPE_INVALID (-1), matching the d == null branch:

    if-ne v0, v1, :cond_1
    const/4 v0, 0x0     ->  const/4 v0, 0x1

Scope note
----------
This is the right fix for a pure-EV car.  For a petrol car the -1 fallback
should stay 0 (or better, be user-selectable); see docs/findings.md §13.

Runs inside the baksmali output directory of classes21.dex.
"""
import re
import sys

p = 'smali_out/smali/com/autosdk/bussiness/user/utils/CarUtils.smali'
s = open(p, encoding='utf-8', errors='replace').read()

# Anchor on the whole getPowerType() body so we cannot hit the identical
# "const/4 v0, 0x0" idiom used elsewhere in the file.
pat = re.compile(
    r'(?P<head>\.method public static getPowerType\(\)I\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*\.locals 2\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*sget-object v0, Lcom/autosdk/bussiness/user/utils/CarUtils;->iLoginCarData:Lcom/autosdk/bussiness/vehicle/ILoginCarData;\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*if-nez v0, :cond_0\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*const/4 v0, 0x1\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*return v0\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*:cond_0\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*invoke-interface \{v0\}, Lcom/autosdk/bussiness/vehicle/ILoginCarData;->getPowerType\(\)I\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*move-result v0\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*const/4 v1, -0x1\n'
    r'(?:[ \t]*\n)*'
    r'[ \t]*if-ne v0, v1, :cond_1\n'
    r'(?:[ \t]*\n)*'
    r')(?P<bad>[ \t]*)const/4 v0, 0x0\n',
    re.M)

m = pat.search(s)
assert m, "CarUtils.getPowerType() -1 fallback anchor not found"
assert len(pat.findall(s)) == 1, "anchor is not unique"

ind = m.group('bad')
s2 = s[:m.start()] + m.group('head') + f'{ind}const/4 v0, 0x1\n' + s[m.end():]
open(p, 'w', encoding='utf-8').write(s2)
print("    patched CarUtils.getPowerType() -> unknown(-1) falls back to 1 (EV), was 0 (petrol)")
