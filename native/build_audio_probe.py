"""Build a tiny, read-only Android audio probe without installing an app.

Only calls verified TclAudioManager getters. Java SDK handles nested Binder IPC.
The generated DEX prints raw values; interpretation stays in the host report.
"""
import hashlib
from pathlib import Path
import struct
import zlib

AUDIO = 'Landroid/media/TclAudioManager;'
STREAM = 'Ltcl/media/TAudioStreamInfo;'
PROBE = 'LTvAudioReader;'
PRINT = 'Ljava/io/PrintStream;'
SYSTEM = 'Ljava/lang/System;'
STRING = 'Ljava/lang/String;'
READS = [
    ('sound_mode', 'getAudioOption', [12289], 'I'),
    ('sound_scene', 'getAudioOption', [12296], 'I'),
    ('atmos_enabled', 'getAudioOption', [12295], 'I'),
    ('processing_enabled', 'getAudioOption', [12288], 'I'),
    ('surround', 'getAudioOption', [12290], 'I'),
    ('bass', 'getAudioOption', [12291], 'I'),
    ('dialogue', 'getAudioOption', [12292], 'I'),
    ('treble', 'getAudioOption', [12293], 'I'),
    ('auto_volume', 'getAudioOption', [12294], 'I'),
    ('volume_leveller', 'getAudioOption', [12297], 'I'),
    ('processing_effect', 'getAudioOption', [38], 'I'),
    ('audio_technology', 'getAudioOption', [16], 'I'),
    ('adaptive_content', 'getAudioOption', [20736], 'I'),
    ('hearing_assistant', 'getAudioOption', [20481], 'I'),
    ('vertical_field', 'getAudioOption', [20482], 'I'),
    ('balance', 'getAudioBalance', [], 'I'),
    ('digital_output_mode', 'getSpdifMode', [], 'I'),
    ('digital_output_delay', 'getSpdifDelay', [], 'I'),
] + [('support_' + name, 'isAudioFunctionSupport', [selector], 'Z')
     for name, selector in [('auto_volume', 0), ('atmos', 1), ('balance', 2),
                            ('dsp', 3), ('ddp_passthrough', 4), ('dts_drc', 5),
                            ('passthrough', 6), ('wireless_speaker', 7), ('vertical_field', 9)]]
STREAM_FIELDS = [('streamId', 'I'), ('audioType', 'I'), ('audioFormat', 'I'),
                 ('isAtmos', 'Z'), ('dtsLogoType', 'I')]


def uleb(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def build(destination):
    methods = {
        (PROBE, 'main', 'V', ('[Ljava/lang/String;',)),
        (AUDIO, 'getInstance', AUDIO, ()),
        (AUDIO, 'getTAudioStreamInfo', STREAM, ()),
        (PRINT, 'print', 'V', (STRING,)), (PRINT, 'println', 'V', ('I',)),
    }
    for _, name, args, ret in READS:
        methods.add((AUDIO, name, ret, ('I',) * len(args)))
    fields = [(SYSTEM, 'out', PRINT)] + [(STREAM, name, kind) for name, kind in STREAM_FIELDS]
    types = {PROBE, AUDIO, STREAM, PRINT, SYSTEM, STRING, 'Ljava/lang/Object;',
             '[Ljava/lang/String;', 'I', 'V', 'Z'}
    shorty = lambda ret, args: ''.join(t if len(t) == 1 else 'L' for t in (ret, *args))
    prototypes = {(ret, args) for _, _, ret, args in methods}
    labels = [name + '=' for name, *_ in READS] + ['stream.' + name + '=' for name, _ in STREAM_FIELDS]
    strings = sorted(types | {m[1] for m in methods} | {f[1] for f in fields}
                     | set(labels) | {shorty(*p) for p in prototypes})
    si = {s: i for i, s in enumerate(strings)}
    types = sorted(types, key=si.get)
    ti = {t: i for i, t in enumerate(types)}
    prototypes = sorted(prototypes, key=lambda p: (ti[p[0]], tuple(ti[a] for a in p[1])))
    pi = {p: i for i, p in enumerate(prototypes)}
    methods = sorted(methods, key=lambda m: (ti[m[0]], si[m[1]], pi[(m[2], m[3])]))
    mi = {(m[0], m[1]): i for i, m in enumerate(methods)}
    fields.sort(key=lambda f: (ti[f[0]], si[f[1]], ti[f[2]]))
    fi = {(f[0], f[1]): i for i, f in enumerate(fields)}
    counts = [len(strings), len(types), len(prototypes), len(fields), len(methods), 1]
    offsets, end = [], 112
    for count, size in zip(counts, [4, 4, 12, 8, 8, 32]):
        offsets.append(end)
        end += count * size
    data_start = (end + 3) & ~3
    buf = bytearray(data_start)
    sections = [(0, 1, 0)] + [(i + 1, count, offset) for i, (count, offset) in enumerate(zip(counts, offsets))]

    def align():
        buf.extend(bytes((-len(buf)) % 4))

    params = {}
    for _, args in prototypes:
        if not args or args in params:
            continue
        align()
        params[args] = len(buf)
        buf.extend(struct.pack('<I' + 'H' * len(args), len(args), *(ti[t] for t in args)))
    sections.append((0x1001, len(params), min(params.values())))
    string_offsets = []
    for s in strings:
        string_offsets.append(len(buf))
        buf.extend(uleb(len(s)) + s.encode() + b'\0')
    sections.append((0x2002, len(strings), string_offsets[0]))
    align()
    code_offset = len(buf)
    code = [0x0071, mi[(AUDIO, 'getInstance')], 0, 0x000c,
            0x0262, fi[(SYSTEM, 'out')]]

    def print_value(label):
        code.extend([0x041a, si[label], 0x206e, mi[(PRINT, 'print')], 0x0042,
                     0x206e, mi[(PRINT, 'println')], 0x0012])

    for label, name, args, _ in READS:
        if args:
            value = args[0]
            if -32768 <= value <= 32767:
                code.extend([0x0113, value & 0xffff])
            else:
                code.extend([0x0114, value & 0xffff, (value >> 16) & 0xffff])
        code.extend([0x206e if args else 0x106e, mi[(AUDIO, name)], 0x0010 if args else 0,
                     0x010a])
        print_value(label + '=')
    code.extend([0x106e, mi[(AUDIO, 'getTAudioStreamInfo')], 0, 0x030c])
    branch = len(code)
    code.extend([0x0338, 0])  # if-eqz v3, return
    for name, kind in STREAM_FIELDS:
        code.extend([0x3155 if kind == 'Z' else 0x3152, fi[(STREAM, name)]])
        print_value('stream.' + name + '=')
    code[branch + 1] = len(code) - branch
    code.append(0x000e)
    buf.extend(struct.pack('<HHHHII', 6, 1, 2, 0, 0, len(code)))
    buf.extend(struct.pack('<' + 'H' * len(code), *code))
    sections.append((0x2001, 1, code_offset))
    class_offset = len(buf)
    buf.extend(b'\0\0\1\0' + uleb(mi[(PROBE, 'main')]) + uleb(9) + uleb(code_offset))
    sections.append((0x2000, 1, class_offset))
    align()
    map_offset = len(buf)
    sections.append((0x1000, 1, map_offset))
    sections.sort(key=lambda item: item[2])
    buf.extend(struct.pack('<I', len(sections)))
    for kind, count, offset in sections:
        buf.extend(struct.pack('<HHII', kind, 0, count, offset))
    for i, offset in enumerate(string_offsets):
        struct.pack_into('<I', buf, offsets[0] + i * 4, offset)
    for i, kind in enumerate(types):
        struct.pack_into('<I', buf, offsets[1] + i * 4, si[kind])
    for i, (ret, args) in enumerate(prototypes):
        struct.pack_into('<III', buf, offsets[2] + i * 12, si[shorty(ret, args)], ti[ret], params.get(args, 0))
    for i, (owner, name, kind) in enumerate(fields):
        struct.pack_into('<HHI', buf, offsets[3] + i * 8, ti[owner], ti[kind], si[name])
    for i, (owner, name, ret, args) in enumerate(methods):
        struct.pack_into('<HHI', buf, offsets[4] + i * 8, ti[owner], pi[(ret, args)], si[name])
    struct.pack_into('<IIIIIIII', buf, offsets[5], ti[PROBE], 1, ti['Ljava/lang/Object;'],
                     0, 0xffffffff, 0, class_offset, 0)
    buf[:8] = b'dex\n035\0'
    struct.pack_into('<IIIIII', buf, 32, len(buf), 112, 0x12345678, 0, 0, map_offset)
    for i, (count, offset) in enumerate(zip(counts, offsets)):
        struct.pack_into('<II', buf, 56 + i * 8, count, offset)
    struct.pack_into('<II', buf, 104, len(buf) - data_start, data_start)
    buf[12:32] = hashlib.sha1(buf[32:]).digest()
    struct.pack_into('<I', buf, 8, zlib.adler32(buf[12:]) & 0xffffffff)
    Path(destination).write_bytes(buf)


if __name__ == '__main__':
    import sys
    build(sys.argv[1])
