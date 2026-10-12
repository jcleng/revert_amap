#!/usr/bin/env python3
"""
Binary (no aapt2 / no apktool rebuild) package rename for an APK's
AndroidManifest.xml and resources.arsc.

Why not rebuild with aapt2?  This BYD repack was linked with a custom
`--custom-package com.autosdk`, so the R classes live in ~67 packages and the
resource table holds 14k entries.  Re-linking would renumber resources and drop
manifest attributes.  Instead we rewrite the two binary resource files in place:

  * AndroidManifest.xml -- the XML body addresses strings by *index*, never by
    byte offset, so we only have to rebuild the single RES_STRING_POOL chunk and
    patch the two enclosing size fields.

  * resources.arsc -- the RES_TABLE_PACKAGE_TYPE header stores the package name
    in a fixed 256-byte UTF-16LE field, so that is an in-place overwrite.  The
    global string pool is rebuilt only if it actually contains the old name.

Usage:
    rename_pkg_binary.py inspect <apk> <needle>
    rename_pkg_binary.py rename <in.apk> <out.apk> <old> <new>
"""
import re
import struct
import sys
import zipfile

RES_STRING_POOL = 0x0001
RES_TABLE = 0x0002
RES_XML = 0x0003
RES_TABLE_PACKAGE = 0x0200

UTF8_FLAG = 0x100
SORTED_FLAG = 0x1


def rd16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def rd32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def enc_varint8(v):
    if v > 0x7f:
        return bytes([0x80 | ((v >> 8) & 0x7f), v & 0xff])
    return bytes([v])


def enc_varint16(v):
    if v > 0x7fff:
        return struct.pack('<HH', 0x8000 | ((v >> 16) & 0x7fff), v & 0xffff)
    return struct.pack('<H', v)


def decode_pool(b, off):
    """Decode a RES_STRING_POOL chunk starting at `off`."""
    t = rd16(b, off)
    assert t == RES_STRING_POOL, 'expected string pool, got 0x%04x' % t
    hs = rd16(b, off + 2)
    size = rd32(b, off + 4)
    sc = rd32(b, off + 8)
    stc = rd32(b, off + 12)
    flags = rd32(b, off + 16)
    ss = rd32(b, off + 20)
    sts = rd32(b, off + 24)
    assert stc == 0, 'styleCount=%d not supported' % stc
    utf8 = bool(flags & UTF8_FLAG)
    offs = [rd32(b, off + 28 + 4 * i) for i in range(sc)]
    out = []
    for o in offs:
        p = off + ss + o
        if utf8:
            b0 = b[p]
            p += 1
            if b0 & 0x80:
                l16 = ((b0 & 0x7f) << 8) | b[p]
                p += 1
            else:
                l16 = b0
            b1 = b[p]
            p += 1
            if b1 & 0x80:
                l8 = ((b1 & 0x7f) << 8) | b[p]
                p += 1
            else:
                l8 = b1
            s = b[p:p + l8].decode('utf-8')
            p += l8
            assert b[p] == 0, 'missing utf8 terminator after %r' % s
            assert len(s.encode('utf-16-le')) // 2 == l16, 'u16len mismatch for %r' % s
        else:
            w0 = rd16(b, p)
            p += 2
            if w0 & 0x8000:
                l = ((w0 & 0x7fff) << 16) | rd16(b, p)
                p += 2
            else:
                l = w0
            s = b[p:p + l * 2].decode('utf-16-le')
            p += l * 2
            assert rd16(b, p) == 0, 'missing utf16 terminator after %r' % s
        out.append(s)
    return dict(off=off, header_size=hs, size=size, string_count=sc,
                style_count=stc, flags=flags, utf8=utf8, strings=out)


def encode_pool(strings, utf8, flags):
    """Re-encode a RES_STRING_POOL chunk (styleCount always 0)."""
    n = len(strings)
    offsets = []
    data = bytearray()
    for s in strings:
        offsets.append(len(data))
        if utf8:
            e = s.encode('utf-8')
            l16 = len(s.encode('utf-16-le')) // 2
            data += enc_varint8(l16) + enc_varint8(len(e)) + e + b'\x00'
        else:
            e = s.encode('utf-16-le')
            data += enc_varint16(len(e) // 2) + e + b'\x00\x00'
    while len(data) % 4:
        data += b'\x00'
    header_size = 28
    strings_start = header_size + 4 * n
    size = strings_start + len(data)
    assert size % 4 == 0
    out = bytearray()
    out += struct.pack('<HHIIIIII', RES_STRING_POOL, header_size, size, n, 0,
                       flags, strings_start, 0)
    for o in offsets:
        out += struct.pack('<I', o)
    out += data
    assert len(out) == size
    return bytes(out)


def chunks(b, start):
    """Yield (offset, type, size) for the contiguous chunk chain from `start`."""
    o = start
    while o + 8 <= len(b):
        t = rd16(b, o)
        sz = rd32(b, o + 4)
        yield o, t, sz
        if sz <= 0:
            return
        o += sz


def apply_pairs(text, pairs):
    # The first pair is the package name; NEW starts with OLD
    # ("com.autonavi.amapauto" + "lite"), so anchor it with a negative lookahead to
    # stop it re-matching its own output.  The remaining pairs (colliding
    # ContentProvider authorities) are unrelated prefixes and stay plain.
    for i, (old, new) in enumerate(pairs):
        if i == 0:
            text = re.sub(re.escape(old) + r'(?!lite)', new, text)
        else:
            text = text.replace(old, new)
    return text


def replace_manifest(data, pairs):
    assert rd16(data, 0) == RES_XML, 'not a binary XML'
    assert rd32(data, 4) == len(data), 'xml size field != file size'
    p = decode_pool(data, 8)
    assert not (p['flags'] & SORTED_FLAG), 'string pool is sorted; order would break'
    old_s = p['strings']
    new_s = [apply_pairs(s, pairs) for s in old_s]
    changed = sum(1 for a, c in zip(old_s, new_s) if a != c)
    newpool = encode_pool(new_s, p['utf8'], p['flags'])
    out = bytearray(data[:8]) + newpool + data[8 + p['size']:]
    struct.pack_into('<I', out, 4, len(out))
    return bytes(out), changed, len(old_s)


def replace_arsc(data, pairs):
    """Rewrite the RES_TABLE_PACKAGE_TYPE name field and the global string pool."""
    assert rd16(data, 0) == RES_TABLE, 'not an arsc'
    assert rd32(data, 4) == len(data), 'arsc size field != file size'
    tbl_header_size = rd16(data, 2)

    pkg_changed = 0
    pool_changed = 0

    b = bytearray(data)
    for o, t, sz in chunks(data, tbl_header_size):
        if t == RES_TABLE_PACKAGE:
            cur = bytes(b[o + 12:o + 12 + 256]).decode('utf-16-le').split('\x00')[0]
            newname = apply_pairs(cur, pairs)
            if newname != cur:
                nb = newname.encode('utf-16-le') + b'\x00\x00'
                assert len(nb) <= 256, 'package name too long for 256-byte field'
                b[o + 12:o + 12 + 256] = nb + b'\x00' * (256 - len(nb))
                pkg_changed += 1
    data = bytes(b)

    # global string pool is the first chunk after the table header
    o0, t0, sz0 = next(iter(chunks(data, tbl_header_size)))
    if t0 == RES_STRING_POOL:
        p = decode_pool(data, o0)
        old_s = p['strings']
        new_s = [apply_pairs(s, pairs) for s in old_s]
        pool_changed = sum(1 for a, c in zip(old_s, new_s) if a != c)
        if pool_changed:
            newpool = encode_pool(new_s, p['utf8'], p['flags'])
            out = bytearray(data[:o0]) + newpool + data[o0 + p['size']:]
            struct.pack_into('<I', out, 4, len(out))
            data = bytes(out)
    return data, pkg_changed, pool_changed


def main():
    cmd = sys.argv[1]

    if cmd == 'inspect':
        apk, needle = sys.argv[2], sys.argv[3]
        z = zipfile.ZipFile(apk)
        mf = z.read('AndroidManifest.xml')
        p = decode_pool(mf, 8)
        print('== AndroidManifest.xml string pool: %d strings, utf8=%s, flags=0x%x'
              % (p['string_count'], p['utf8'], p['flags']))
        for i, s in enumerate(p['strings']):
            if needle in s:
                print('   [%3d] %r' % (i, s))
        ar = z.read('resources.arsc')
        print('== resources.arsc')
        print('   table headerSize=%d size=%d' % (rd16(ar, 2), rd32(ar, 4)))
        for o, t, sz in chunks(ar, rd16(ar, 2)):
            kind = {0x0001: 'stringpool', 0x0200: 'package', 0x0201: 'type',
                    0x0202: 'typeSpec'}.get(t, hex(t))
            print('   chunk off=%-9d type=%-10s size=%d' % (o, kind, sz))
            if t == RES_TABLE_PACKAGE:
                nm = bytes(ar[o + 12:o + 12 + 256]).decode('utf-16-le').split('\x00')[0]
                print('        packageName=%r id=0x%x' % (nm, rd32(ar, o + 8)))
            if t == RES_STRING_POOL:
                q = decode_pool(ar, o)
                print('        %d strings utf8=%s' % (q['string_count'], q['utf8']))
                for i, s in enumerate(q['strings']):
                    if needle in s:
                        print('        [%6d] %r' % (i, s))
        return

    if cmd == 'rename':
        src, dst, old, new = sys.argv[2:6]
        assert len(old) <= 255 and len(new) <= 255
        # Extra non-package-derived renames (colliding ContentProvider authorities).
        # Passed as additional old=new pairs after the package rename.
        pairs = [(old, new)]
        for spec in sys.argv[6:]:
            a, b = spec.split('=', 1)
            pairs.append((a, b))
        zin = zipfile.ZipFile(src)
        mf = zin.read('AndroidManifest.xml')
        ar = zin.read('resources.arsc')

        mf2, mf_n, mf_total = replace_manifest(mf, pairs)
        ar2, pkg_n, pool_n = replace_arsc(ar, pairs)

        print('manifest : %d/%d strings changed, %d -> %d bytes'
              % (mf_n, mf_total, len(mf), len(mf2)))
        print('arsc     : %d package-name field(s), %d global string(s) changed, %d -> %d bytes'
              % (pkg_n, pool_n, len(ar), len(ar2)))
        assert mf_n > 0 and pkg_n > 0, 'nothing renamed -- wrong old package name?'

        # rewrite the zip, replacing just these two entries, keeping everything else
        # byte-for-byte (same compression method and same stored order).
        zout = zipfile.ZipFile(dst, 'w')
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == 'AndroidManifest.xml':
                data = mf2
            elif info.filename == 'resources.arsc':
                data = ar2
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zi.internal_attr = info.internal_attr
            zi.create_system = info.create_system
            zout.writestr(zi, data)
        zout.close()
        print('wrote %s' % dst)
        return

    raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
