#!/usr/bin/env python3
"""
fix #6 -- repair the systematic Chinese mistranslation of the *charging*
(充电) string family in resources.arsc.

Problem
-------
The repack's Chinese resources translate the whole "charge" family as
「加油站」(petrol station).  `charge_station` is 「加油站」 in `values/` and
`values-zh/`, while `values-en/` correctly says "Charge".  So the navigation
bottom bar shows a lightning-bolt icon labelled 「加油站」, and the charging
preference dialogs read 「加油站偏好」.  In total 26 resources are affected;
the word 「充电站」 does not appear anywhere in the APK.

Root cause is purely a localisation defect: the *behaviour* already branches on
the vehicle power type
(`DriveAlongSearchCardViewR.java:1655` -> `CarUtils.isNewEnergyVehicle() ?
"充电站" : "加油站"`), only the static labels never did.

Why not just rewrite the string pool in place?
----------------------------------------------
`charge_station` and `gas_station` (the correct petrol label) share the *same*
pool entry (`'加油站'`, index 14042).  Overwriting it would relabel the petrol
strings too.  So instead we:

  1. append the corrected strings to the *end* of the global RES_STRING_POOL
     (existing indices are untouched),
  2. repoint only the affected ResTable entries' `Res_value.data` at the new
     indices,
  3. shift the following RES_TABLE_PACKAGE chunk (its internal offsets are all
     relative to its own start, so moving it wholesale is safe).

Note that `加油站` and `充电站` are both 3 UTF-16 code units / 9 UTF-8 bytes, so
every substitution is length preserving, but the implementation does not rely
on that.

Usage:
    fix_ChargeStationStrings.py probe <apk>
    fix_ChargeStationStrings.py patch <in.apk> <out.apk>
"""
import struct
import sys
import zipfile

RES_STRING_POOL = 0x0001
RES_TABLE = 0x0002
RES_TABLE_PACKAGE = 0x0200
RES_TABLE_TYPE = 0x0201

TYPE_STRING = 0x12          # resource type id of `string`
VALUE_STRING = 0x03         # Res_value dataType for a string reference
FLAG_COMPLEX = 0x0001
NO_ENTRY = 0xFFFFFFFF

OLD_WORD = '加油站'
NEW_WORD = '充电站'

# Resource names that belong to the *charging* (电) family.  Each is verified
# against its English value: every one of these says "charging"/"charge" in
# `values-en/`.  The parallel petrol strings (gas_station, gas_warning_*,
# routecarresult_gas_*, route_search_gas_preference, search_home_gas_station,
# search_category_text_gasstation, simpledesc_gasstation, tts_gas_warning_tips,
# auto_navi_title_along_search, auto_search_classify_data_zgshjyz,
# auto_navi_text_location_waypoint, search_error_text_link_*) are deliberately
# NOT in this list -- 「加油站」 is the correct label for those.
CHARGE_STRINGS = (
    'auto_navi_continue_charge_title',
    'auto_navi_text_recommand_charge_station_fold',
    'auto_search_result_map_text_title_energy',
    'charge_station',
    'charging_voltage_not_enough_suggest',
    'charging_voltage_not_enough_tip',
    'drive_charge_open_confirm_btn',
    'drive_charge_open_title_closed',
    'drive_charge_open_title_soon',
    'drive_charge_open_toast_closed',
    'drive_charge_open_toast_soon',
    'drive_charge_station',
    'drive_charge_station_tag',
    'drive_finish_charge_station',
    'electric_warning_advise',
    'electric_warning_find',
    'navi_facility_charge_total_more',
    'route_result_charge_station',
    'route_result_charge_station_short',
    'routecarresult_charge_station',
    'routecarresult_charge_station_pref_dialog_title',
    'routecarresult_charge_station_pref_title',
    'routecarresult_text_btn_tips_query_charge_station',
    'search_home_charge_station',
    'settings_navi_auto_continue_tips',
    'tts_electric_warning_tips',
)


# --------------------------------------------------------------------------
# little-endian readers
# --------------------------------------------------------------------------
def rd16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def rd32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def chunks(b, start):
    o = start
    while o + 8 <= len(b):
        t = rd16(b, o)
        sz = rd32(b, o + 4)
        yield o, t, sz
        if sz <= 0:
            return
        o += sz


# --------------------------------------------------------------------------
# RES_STRING_POOL
# --------------------------------------------------------------------------
def decode_pool(b, off):
    """Decode a RES_STRING_POOL chunk.  styleCount must be 0."""
    assert rd16(b, off) == RES_STRING_POOL, 'not a string pool at %d' % off
    header_size = rd16(b, off + 2)
    size = rd32(b, off + 4)
    count = rd32(b, off + 8)
    style_count = rd32(b, off + 12)
    flags = rd32(b, off + 16)
    strings_start = rd32(b, off + 20)
    assert style_count == 0, 'styleCount=%d unsupported' % style_count
    utf8 = bool(flags & 0x100)
    offsets = [rd32(b, off + header_size + 4 * i) for i in range(count)]
    out = []
    for o in offsets:
        p = off + strings_start + o
        if utf8:
            b0 = b[p]
            p += 1
            if b0 & 0x80:
                u16len = ((b0 & 0x7f) << 8) | b[p]
                p += 1
            else:
                u16len = b0
            b1 = b[p]
            p += 1
            if b1 & 0x80:
                blen = ((b1 & 0x7f) << 8) | b[p]
                p += 1
            else:
                blen = b1
            s = b[p:p + blen].decode('utf-8')
            p += blen
            assert b[p] == 0, 'missing utf8 terminator after %r' % s
            assert len(s.encode('utf-16-le')) // 2 == u16len, 'u16len mismatch for %r' % s
        else:
            w0 = rd16(b, p)
            p += 2
            if w0 & 0x8000:
                n = ((w0 & 0x7fff) << 16) | rd16(b, p)
                p += 2
            else:
                n = w0
            s = b[p:p + n * 2].decode('utf-16-le')
            p += n * 2
            assert rd16(b, p) == 0, 'missing utf16 terminator after %r' % s
        out.append(s)
    return dict(off=off, header_size=header_size, size=size, count=count,
                flags=flags, utf8=utf8, strings_start=strings_start, strings=out)


def _enc_varint8(v):
    if v > 0x7f:
        return bytes([0x80 | ((v >> 8) & 0x7f), v & 0xff])
    return bytes([v])


def _enc_varint16(v):
    if v > 0x7fff:
        return struct.pack('<HH', 0x8000 | ((v >> 16) & 0x7fff), v & 0xffff)
    return struct.pack('<H', v)


def encode_pool(strings, utf8, flags):
    """Re-encode a RES_STRING_POOL chunk (styleCount always 0)."""
    n = len(strings)
    offsets = []
    data = bytearray()
    for s in strings:
        offsets.append(len(data))
        if utf8:
            e = s.encode('utf-8')
            u16len = len(s.encode('utf-16-le')) // 2
            data += _enc_varint8(u16len) + _enc_varint8(len(e)) + e + b'\x00'
        else:
            e = s.encode('utf-16-le')
            data += _enc_varint16(len(e) // 2) + e + b'\x00\x00'
    while len(data) % 4:
        data += b'\x00'
    header_size = 28
    strings_start = header_size + 4 * n
    size = strings_start + len(data)
    out = bytearray()
    out += struct.pack('<HHIIIIII', RES_STRING_POOL, header_size, size, n, 0,
                       flags, strings_start, 0)
    for o in offsets:
        out += struct.pack('<I', o)
    out += data
    assert len(out) == size
    return bytes(out)


# --------------------------------------------------------------------------
# RES_TABLE_PACKAGE / RES_TABLE_TYPE
# --------------------------------------------------------------------------
def cfg_name(cfg):
    """Best-effort locale tag for a ResTable_config (for reporting only)."""
    if len(cfg) < 12:
        return 'default'
    lang = cfg[8:10].decode('ascii', 'replace').strip('\x00')
    ctry = cfg[10:12].decode('ascii', 'replace').strip('\x00')
    if not lang and not ctry:
        return 'default'
    return lang + ('-' + ctry if ctry else '')


def parse_type_chunks(ar, pkg_off):
    """-> list of dicts describing every RES_TABLE_TYPE chunk in the package."""
    header_size = rd16(ar, pkg_off + 2)
    out = []
    for o, t, sz in chunks(ar, pkg_off + header_size):
        if t != RES_TABLE_TYPE:
            continue
        out.append(dict(
            off=o,
            type_id=ar[o + 8],
            entry_count=rd32(ar, o + 12),
            entries_start=rd32(ar, o + 16),
            header_size=rd16(ar, o + 2),
            cfg=bytes(ar[o + 20:o + rd16(ar, o + 2)]),
            offsets=[rd32(ar, o + rd16(ar, o + 2) + 4 * i)
                     for i in range(rd32(ar, o + 12))],
        ))
    return out


def entry_at(ar, tc, idx, key_pool, value_pool):
    """Return (name, res_value_offset, dataType, data) or None for a sparse entry."""
    off = tc['offsets'][idx]
    if off == NO_ENTRY:
        return None
    p = tc['off'] + tc['entries_start'] + off
    entry_size = rd16(ar, p)
    flags = rd16(ar, p + 2)
    key = rd32(ar, p + 4)
    name = key_pool[key] if key < len(key_pool) else '<key#%d>' % key
    if flags & FLAG_COMPLEX:
        return name, None, None, None
    vp = p + entry_size
    return name, vp, ar[vp + 3], rd32(ar, vp + 4)


# --------------------------------------------------------------------------
# the patch
# --------------------------------------------------------------------------
def patch_arsc(data, verbose=True):
    """Append corrected strings and repoint the charge-family entries."""
    assert rd16(data, 0) == RES_TABLE, 'not a resources.arsc'
    assert rd32(data, 4) == len(data), 'arsc size field != file size'
    table_header_size = rd16(data, 2)

    chunks_after = list(chunks(data, table_header_size))
    pool_off, pool_type, _ = chunks_after[0]
    assert pool_type == RES_STRING_POOL, 'first chunk is not the string pool'
    pkg_off = next(o for o, t, _ in chunks_after if t == RES_TABLE_PACKAGE)

    pool = decode_pool(data, pool_off)
    assert not (pool['flags'] & 0x1), 'string pool is sorted; appending would break lookup'
    strings = list(pool['strings'])

    key_pool_off = pkg_off + rd32(data, pkg_off + 276)
    key_pool = decode_pool(data, key_pool_off)['strings']

    pkg = bytearray(data[pkg_off:])
    type_chunks = parse_type_chunks(data, pkg_off)

    # offsets inside the package chunk are all relative to its own start, so the
    # package can be moved wholesale -- but `parse_type_chunks` reports absolute
    # offsets into `data`, hence the `- pkg_off` below.
    base = pkg_off

    targets = []
    for tc in type_chunks:
        if tc['type_id'] != TYPE_STRING:
            continue
        for i in range(tc['entry_count']):
            info = entry_at(data, tc, i, key_pool, strings)
            if info is None:
                continue
            name, vp, dtype, dval = info
            if name not in CHARGE_STRINGS:
                continue
            if dtype != VALUE_STRING or dval >= len(strings):
                continue
            cur = strings[dval]
            if OLD_WORD not in cur:
                continue                      # e.g. the (correct) `en` values
            targets.append((tc, i, name, cfg_name(tc['cfg']), dval, cur))

    if not targets:
        raise SystemExit('no charge-family strings matched -- wrong input APK?')

    # 1. append the corrected values, reusing one new index per distinct value
    def skip(cfg, cur):
        """`en` configs are already translated -- except where the English
        resource still carries the untranslated Chinese fallback
        (tts_electric_warning_tips)."""
        return cfg.startswith('en') and all(ord(c) < 0x2e80 for c in cur)

    new_index = {}
    for _, _, _, cfg, _, cur in targets:
        if skip(cfg, cur):
            continue
        fixed = cur.replace(OLD_WORD, NEW_WORD)
        if fixed not in new_index:
            new_index[fixed] = len(strings)
            strings.append(fixed)

    # 2. repoint the entries (offsets inside the package chunk are unchanged)
    repointed = []
    for tc, i, name, cfg, old_idx, cur in targets:
        if skip(cfg, cur):
            continue
        fixed = cur.replace(OLD_WORD, NEW_WORD)
        off = tc['offsets'][i]
        p = tc['off'] + tc['entries_start'] + off - base
        entry_size = rd16(pkg, p)
        vp = p + entry_size
        assert pkg[vp + 3] == VALUE_STRING
        struct.pack_into('<I', pkg, vp + 4, new_index[fixed])
        repointed.append((name, cfg, old_idx, new_index[fixed], cur, fixed))

    # 3. reassemble: new pool, then the (moved) package chunk
    new_pool = encode_pool(strings, pool['utf8'], pool['flags'])
    out = bytearray(data[:pool_off]) + new_pool + bytes(pkg)
    struct.pack_into('<I', out, 4, len(out))

    if verbose:
        print('    arsc string fix: %d entries repointed (%d matched), %d new pool '
              'strings, pool %d -> %d strings, arsc %d -> %d bytes'
              % (len(repointed), len(targets), len(new_index), pool['count'],
                 len(strings), len(data), len(out)))
        for name, cfg, old_idx, new_idx, cur, fixed in repointed:
            print('      %-52s %-8s %d -> %d  %s => %s'
                  % (name, cfg, old_idx, new_idx, cur, fixed))
    return bytes(out), len(repointed)


# --------------------------------------------------------------------------
def probe(apk):
    z = zipfile.ZipFile(apk)
    data = z.read('resources.arsc')
    pool_off = next(o for o, t, _ in chunks(data, rd16(data, 2))
                    if t == RES_STRING_POOL)
    pool = decode_pool(data, pool_off)
    print('arsc %d bytes, global pool %d strings, utf8=%s flags=0x%x'
          % (len(data), pool['count'], pool['utf8'], pool['flags']))
    pkg_off = next(o for o, t, _ in chunks(data, rd16(data, 2))
                   if t == RES_TABLE_PACKAGE)
    key_pool = decode_pool(data, pkg_off + rd32(data, pkg_off + 276))['strings']
    strings = pool['strings']
    for tc in parse_type_chunks(data, pkg_off):
        if tc['type_id'] != TYPE_STRING:
            continue
        for i in range(tc['entry_count']):
            info = entry_at(data, tc, i, key_pool, strings)
            if info is None:
                continue
            name, _, dtype, dval = info
            if name not in CHARGE_STRINGS or dtype != VALUE_STRING:
                continue
            print('  %-52s %-8s idx=%-6d %r'
                  % (name, cfg_name(tc['cfg']), dval, strings[dval]))
    print('pool entries containing %r: %d'
          % (OLD_WORD, sum(1 for s in strings if OLD_WORD in s)))
    print('pool entries containing %r: %d'
          % (NEW_WORD, sum(1 for s in strings if NEW_WORD in s)))


def main():
    cmd = sys.argv[1]
    if cmd == 'probe':
        probe(sys.argv[2])
        return
    if cmd == 'patch':
        src, dst = sys.argv[2], sys.argv[3]
        zin = zipfile.ZipFile(src)
        ar = zin.read('resources.arsc')
        ar2, _ = patch_arsc(ar)
        # keep every entry byte-for-byte identical apart from resources.arsc
        # (same compression method, same order, same attributes)
        zout = zipfile.ZipFile(dst, 'w', allowZip64=True)
        for info in zin.infolist():
            data = ar2 if info.filename == 'resources.arsc' else zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            zout.writestr(zi, data)
        zout.close()
        zin.close()
        print('wrote %s' % dst)
        return
    raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
