"""Read-only snapshot of the verified TCL picture API, including signal parcels."""
import argparse
import datetime
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from picture import NativePicture, SDK_SHA256
from tv import TV

VIDEO_FIELDS = ['is_connected', 'frame_state', 'frame_codec', 'frame_capture_x',
                'frame_capture_y', 'frame_capture_width', 'frame_capture_height',
                'frame_rate', 'is_interlace', 'is_dvi', 'is_xvycc', 'hdr_type',
                'color_space', 'color_matrix', 'color_format', 'color_range',
                'aspect_type', 'rotate_type', 'is_allm', 'vsync_type', 'source_type']
INPUT_FIELDS = ['is_connect', 'frame_state', 'frame_codec', 'frame_capture_x',
                'frame_capture_y', 'frame_capture_width', 'frame_capture_height',
                'frame_rate', 'is_interlace', 'is_dvi', 'is_mhl', 'wss',
                'aspect_ratio', 'afd', 'rotate_type', 'hdr_type', 'color_matrix',
                'color_format', 'color_range', 'is_xvycc', 'is_allm', 'vsync_type',
                'source_type', 'hdmi_provider', 'color_system']
HDR_NAMES = ['SDR', 'HDR10', 'HDR10+', 'HLG', 'HLG18', 'Dolby Vision', 'premium', 'unknown']
NO_WINDOW = ['getBacklight', 'getPictureMode', 'getLightSensorOnoff', 'getLocalDimming',
             'getLocalDimmingRow', 'getLocalDimmingCol', 'getPanelFrameRate',
             'getGammaLevel', 'getMicroDimming', 'getMixDimming', 'getDBCLevel',
             'getEotfPeak', 'getHdrMode', 'getViewAngle', 'getVrrRefreshRate']
WINDOW_ZERO = ['getContrast', 'getBrightness', 'getHue', 'getSaturation', 'getSharpness',
               'getColorTemperature', 'getDynamicContrast', 'getDynamicToneMapping',
               'getBlackStretch', 'getBlueStretch', 'getNR', 'getMpegNR', 'getDeContour',
               'getMotionClarity', 'getMemcBlur', 'getMemcJudder', 'getLedMotionClarity',
               'getAipqEnable', 'getAisrEnable', 'getALLMMode', 'getVRRMode', 'getDLGMode',
               'getLowlantency', 'getInputColorFormat', 'getInputColorRange',
               'getVideoEOTFMode', 'getVideoReferenceStandard', 'getRGBMode', 'getRgbSensor',
               'getOverScanEnable', 'getAspectRatio', 'get24p']


def parcel_words(output):
    if 'Result: Parcel(' not in output:
        raise ValueError('Not a service Parcel response')
    words = []
    for line in output.splitlines():
        words.extend(int(word, 16) for word in re.findall(
            r'(?<![A-Za-z0-9])[0-9a-f]{8}(?![A-Za-z0-9])', line.split("'")[0]))
    if not words or words[0] != 0:
        raise ValueError('Service returned an exception or an empty Parcel')
    return words


def decode_video(output, fields):
    words = parcel_words(output)
    if len(words) < 2:
        raise ValueError('Missing typed-object presence marker')
    if words[1] == 0:
        return {'valid_signal': False, 'reason': 'null object'}
    if words[1] != 1 or len(words) < 3:
        raise ValueError('Invalid typed-object header')
    size = words[2]
    if size < 4 + 4 * len(fields) or size > (len(words) - 2) * 4:
        raise ValueError('Truncated or incompatible signal object')
    data = {}
    for name, value in zip(fields, words[3:]):
        if name.startswith('is_'):
            if value not in (0, 1):
                raise ValueError('Invalid signal boolean: ' + name)
            data[name] = bool(value)
        else:
            data[name] = value if value < 2**31 else value - 2**32
    connected = data.get('is_connected', data.get('is_connect', False))
    data['valid_signal'] = bool(connected and data['frame_capture_width'] > 0
                                and data['frame_capture_height'] > 0)
    # Disconnected zero-valued fields must never be presented as live SDR.
    data['hdr_format'] = (HDR_NAMES[data['hdr_type']] if data['valid_signal']
                          and 0 <= data['hdr_type'] < len(HDR_NAMES) else None)
    data['parcel_bytes'] = size
    return data


def snapshot(tv):
    api = NativePicture(tv)
    api.verify()
    catalog = json.loads((ROOT / 'native/api-catalog.json').read_text())
    if catalog['framework_sha256'] != SDK_SHA256:
        raise RuntimeError('Unverified API catalog')
    methods = catalog['methods']
    result = {'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'window_argument': 0, 'sample': api.sample(), 'values': {}, 'signals': {}}
    for name, args in [(n, []) for n in NO_WINDOW] + [(n, [0]) for n in WINDOW_ZERO]:
        method = methods[name]
        assert method['arguments'] == ['I'] * len(args)
        assert method['returns'] in ('I', 'Z', 'F')
        try:
            raw = tv.shell('service', 'call', 'tcl_tv_display', str(method['transaction']),
                           *[part for value in args for part in ('i32', str(value))])
            words = parcel_words(raw)
            if len(words) != 2:
                raise ValueError('Unexpected scalar response size')
            if method['returns'] == 'F':
                value = struct.unpack('<f', struct.pack('<I', words[1]))[0]
            elif method['returns'] == 'Z':
                if words[1] not in (0, 1):
                    raise ValueError('Invalid boolean response')
                value = bool(words[1])
            else:
                value = words[1] if words[1] < 2**31 else words[1] - 2**32
            result['values'][name] = {'raw_value': value, 'transaction': method['transaction']}
        except (RuntimeError, ValueError) as error:
            result['values'][name] = {'error': str(error)}
    for name, fields in [('getTvVideoInfo', VIDEO_FIELDS), ('getTvInputVideoInfo', INPUT_FIELDS)]:
        method = methods[name]
        raw = tv.shell('service', 'call', 'tcl_tv_display', str(method['transaction']), 'i32', '0')
        try:
            result['signals'][name] = decode_video(raw, fields)
        except ValueError as error:
            result['signals'][name] = {'error': str(error), 'raw_parcel': raw}
    result['caveats'] = [
        'Window-zero results require comparison with the active player/window.',
        'getHdrMode is a configuration setting, not the active HDR format.',
        'Raw zero/false results do not establish hardware non-support.',
        'Native brightness is a control value, not measured panel luminance.',
    ]
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='192.168.1.44:5555')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    tv = TV(args.device)
    tv.connect()
    data = snapshot(tv)
    rendered = json.dumps(data, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end='')
