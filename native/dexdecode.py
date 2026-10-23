"""Read-only DEX metadata/instruction decoder, using the Python standard library.

Usage: python3 dexdecode.py framework.jar 'ClassPattern' > decoded.json
Outputs class fields, constants, method signatures, code and referenced APIs.
Unknown opcodes fail explicitly; no device commands are performed.
"""
import argparse
import json
import re
import struct
import zipfile


class Dex:
    def __init__(self, data):
        if not data.startswith(b'dex\n'):
            raise ValueError('Not a DEX file')
        self.data = data
        self.strings = []
        count, offset = self.unpack('II', 56)
        for index in range(count):
            pointer = self.unpack('I', offset + index * 4)[0]
            _, pointer = self.uleb(pointer)
            self.strings.append(data[pointer:data.index(0, pointer)].decode('utf-8', 'replace'))
        count, offset = self.unpack('II', 64)
        self.types = [self.strings[self.unpack('I', offset + index * 4)[0]]
                      for index in range(count)]
        self.protos = []
        count, offset = self.unpack('II', 72)
        for index in range(count):
            _, ret, params = self.unpack('III', offset + index * 12)
            args = []
            if params:
                size = self.unpack('I', params)[0]
                args = [self.types[self.unpack('H', params + 4 + j * 2)[0]] for j in range(size)]
            self.protos.append({'arguments': args, 'returns': self.types[ret]})
        self.fields = []
        count, offset = self.unpack('II', 80)
        for index in range(count):
            owner, kind, name = self.unpack('HHI', offset + index * 8)
            self.fields.append({'owner': self.types[owner], 'name': self.strings[name],
                                'type': self.types[kind]})
        self.methods = []
        count, offset = self.unpack('II', 88)
        for index in range(count):
            owner, proto, name = self.unpack('HHI', offset + index * 8)
            self.methods.append({'owner': self.types[owner], 'name': self.strings[name],
                                 **self.protos[proto]})
        self.classes = []
        count, offset = self.unpack('II', 96)
        for index in range(count):
            owner, flags, superclass, _, _, _, class_data, values = self.unpack('IIIIIIII', offset + index * 32)
            record = {'name': self.types[owner], 'flags': flags,
                      'superclass': self.types[superclass] if superclass != 0xffffffff else None,
                      'fields': [], 'methods': []}
            if class_data:
                sizes = []
                pointer = class_data
                for _ in range(4):
                    size, pointer = self.uleb(pointer)
                    sizes.append(size)
                for count in sizes[:2]:
                    field_index = 0
                    for _ in range(count):
                        delta, pointer = self.uleb(pointer)
                        access, pointer = self.uleb(pointer)
                        field_index += delta
                        record['fields'].append({**self.fields[field_index], 'flags': access})
                if values:
                    size, pointer_values = self.uleb(values)
                    for j in range(size):
                        value, pointer_values = self.value(pointer_values)
                        record['fields'][j]['constant'] = value
                for count in sizes[2:]:
                    method_index = 0
                    for _ in range(count):
                        delta, pointer = self.uleb(pointer)
                        access, pointer = self.uleb(pointer)
                        code, pointer = self.uleb(pointer)
                        method_index += delta
                        method = {**self.methods[method_index], 'flags': access}
                        if code:
                            method['code_offset'] = code
                        record['methods'].append(method)
            self.classes.append(record)

    def unpack(self, fmt, offset):
        return struct.unpack_from('<' + fmt, self.data, offset)

    def uleb(self, pointer):
        result = shift = 0
        while True:
            byte = self.data[pointer]
            pointer += 1
            result |= (byte & 127) << shift
            shift += 7
            if byte < 128:
                return result, pointer

    def value(self, pointer):
        head = self.data[pointer]
        pointer += 1
        kind, argument = head & 31, head >> 5
        if kind == 0x1e:
            return None, pointer
        if kind == 0x1f:
            return bool(argument), pointer
        if kind == 0x1c:
            size, pointer = self.uleb(pointer)
            result = []
            for _ in range(size):
                value, pointer = self.value(pointer)
                result.append(value)
            return result, pointer
        if kind == 0x1d:
            raise ValueError('Encoded annotation is not supported')
        size = argument + 1
        raw = self.data[pointer:pointer + size]
        pointer += size
        number = int.from_bytes(raw, 'little', signed=kind in (0, 2, 4, 6))
        tables = {0x17: self.strings, 0x18: self.types, 0x19: self.fields,
                  0x1a: self.methods, 0x1b: self.fields}
        return tables[kind][number] if kind in tables else number, pointer

    def instructions(self, method):
        offset = method.get('code_offset')
        if not offset:
            return []
        registers, ins, _, _, _, count = self.unpack('HHHHII', offset)
        method['register_count'] = registers
        method['incoming_words'] = ins
        words = self.unpack('H' * count, offset + 16)
        result = []
        cursor = 0
        while cursor < count:
            word = words[cursor]
            opcode = word & 255
            width = self.width(words, cursor)
            item = {'offset': cursor, 'opcode': hex(opcode),
                    'words': [hex(w) for w in words[cursor:cursor + width]]}
            if opcode in (0x1a, 0x1b):
                string_id = words[cursor + 1]
                if opcode == 0x1b:
                    string_id |= words[cursor + 2] << 16
                item.update(string=self.strings[string_id], destination=word >> 8)
            elif opcode == 0x12:
                value = word >> 12
                item.update(destination=(word >> 8) & 15, constant=value - 16 if value >= 8 else value)
            elif opcode in (0x13, 0x14, 0x15):
                value = words[cursor + 1]
                if opcode == 0x14:
                    value |= words[cursor + 2] << 16
                if opcode == 0x15:
                    value <<= 16
                bits = 16 if opcode == 0x13 else 32
                if value >= 1 << (bits - 1):
                    value -= 1 << bits
                item.update(destination=word >> 8, constant=value)
            elif opcode in (0x1c, 0x1f, 0x20, 0x22, 0x23):
                item['type'] = self.types[words[cursor + 1]]
            elif 0x52 <= opcode <= 0x6d:
                item['field'] = self.fields[words[cursor + 1]]
            elif 0x6e <= opcode <= 0x72 or 0x74 <= opcode <= 0x78:
                item['method'] = self.methods[words[cursor + 1]]
                if opcode <= 0x72:
                    n = word >> 12
                    packed = words[cursor + 2]
                    regs = [(packed >> (4 * j)) & 15 for j in range(4)] + [(word >> 8) & 15]
                    item['registers'] = regs[:n]
                else:
                    item['registers'] = list(range(words[cursor + 2], words[cursor + 2] + (word >> 8)))
            result.append(item)
            cursor += width
        return result

    @staticmethod
    def width(words, cursor):
        word = words[cursor]
        op = word & 255
        if op == 0:
            payload = word >> 8
            if payload == 1:
                return 4 + words[cursor + 1] * 2
            if payload == 2:
                return 2 + words[cursor + 1] * 4
            if payload == 3:
                count = words[cursor + 2] | words[cursor + 3] << 16
                return 4 + (count * words[cursor + 1] + 1) // 2
            if payload:
                raise ValueError('Unknown payload')
            return 1
        if op in (0x03, 0x06, 0x09, 0x14, 0x17, 0x1b, 0x24, 0x25, 0x26, 0x2a, 0x2b, 0x2c) or 0x6e <= op <= 0x72 or 0x74 <= op <= 0x78 or op in (0xfc, 0xfd):
            return 3
        if op == 0x18:
            return 5
        if op in (0xfa, 0xfb):
            return 4
        if op in (0x02, 0x05, 0x08, 0x13, 0x15, 0x16, 0x19, 0x1a, 0x1c, 0x1f, 0x20, 0x22, 0x23, 0x29, 0xfe, 0xff) or 0x2d <= op <= 0x3d or 0x44 <= op <= 0x6d or 0x90 <= op <= 0xaf or 0xd0 <= op <= 0xe2:
            return 2
        if 0x01 <= op <= 0x11 or op in (0x12, 0x1d, 0x1e, 0x21, 0x27, 0x28) or 0x7b <= op <= 0x8f or 0xb0 <= op <= 0xcf:
            return 1
        raise ValueError(f'Unknown opcode {op:#x} at {cursor}')

    def select(self, pattern):
        output = []
        for source in self.classes:
            if not re.search(pattern, source['name']):
                continue
            record = {**source, 'methods': []}
            for source_method in source['methods']:
                method = dict(source_method)
                try:
                    method['instructions'] = self.instructions(method)
                except (ValueError, IndexError) as error:
                    method['decode_error'] = str(error)
                record['methods'].append(method)
            output.append(record)
        return output

    def enum_records(self):
        """Resolve straight-line Java enum initializers and constructor fields.

        Ordinals remain distinct from custom getValue/native integers. Complex
        initializers are marked incomplete rather than guessed.
        """
        output = {}
        for record in self.classes:
            if not record['flags'] & 0x4000:
                continue
            initializer = next((m for m in record['methods'] if m['name'] == '<clinit>'), None)
            if not initializer:
                continue
            regs, entries = {}, {}
            try:
                instructions = self.instructions(dict(initializer))
                for item in instructions:
                    op = int(item['opcode'], 16)
                    word = int(item['words'][0], 16)
                    if 'constant' in item:
                        regs[item['destination']] = item['constant']
                    elif 'string' in item:
                        regs[item['destination']] = item['string']
                    elif op == 0x22:
                        regs[word >> 8] = {'class': item['type']}
                    elif op in (0x01, 0x04, 0x07):
                        regs[(word >> 8) & 15] = regs.get(word >> 12)
                    elif op in (0x02, 0x05, 0x08):
                        regs[word >> 8] = regs.get(int(item['words'][1], 16))
                    elif op in (0x03, 0x06, 0x09):
                        regs[int(item['words'][1], 16)] = regs.get(int(item['words'][2], 16))
                    elif op in (0x70, 0x76) and item['method']['name'] == '<init>':
                        arguments = [regs.get(r) for r in item['registers']]
                        if not arguments or not isinstance(arguments[0], dict):
                            continue
                        instance = arguments[0]
                        if instance.get('class') != record['name']:
                            continue
                        instance.update(name=arguments[1], ordinal=arguments[2],
                                        constructor_arguments=arguments[1:], fields={})
                        constructor = next((m for m in record['methods']
                                            if m['name'] == '<init>' and
                                            m['arguments'] == item['method']['arguments']), None)
                        if constructor:
                            detail = dict(constructor)
                            body = self.instructions(detail)
                            start = detail['register_count'] - detail['incoming_words']
                            params = {}
                            cursor = start
                            for kind, value in zip([record['name']] + constructor['arguments'], arguments):
                                params[cursor] = value
                                cursor += 2 if kind in ('J', 'D') else 1
                            for step in body:
                                code = int(step['opcode'], 16)
                                head = int(step['words'][0], 16)
                                if 'constant' in step:
                                    params[step['destination']] = step['constant']
                                elif code in (0x01, 0x04, 0x07):
                                    params[(head >> 8) & 15] = params.get(head >> 12)
                                elif 0x59 <= code <= 0x5f:
                                    value = params.get((head >> 8) & 15)
                                    if not isinstance(value, dict):
                                        instance['fields'][step['field']['name']] = value
                    elif op == 0x69:
                        instance = regs.get(word >> 8)
                        if (item['field']['type'] == record['name'] and
                                isinstance(instance, dict) and instance.get('class') == record['name']):
                            value = {k: v for k, v in instance.items() if k != 'class'}
                            for getter in record['methods']:
                                if getter['name'] not in ('getValue', 'getmValue', 'value'):
                                    continue
                                for operation in self.instructions(dict(getter)):
                                    if int(operation['opcode'], 16) in (0x52, 0x53):
                                        field = operation['field']['name']
                                        value[getter['name']] = instance.get('fields', {}).get(field)
                            entries[item['field']['name']] = value
                expected = [f['name'] for f in record['fields'] if f['flags'] & 0x4000]
                output[record['name']] = {
                    'values': entries,
                    'complete': set(expected) == set(entries) and all(
                        isinstance(v.get('ordinal'), int) and all(
                            v.get(k) is not None for k in ('getValue', 'getmValue', 'value') if k in v)
                        for v in entries.values()),
                }
            except (ValueError, IndexError, KeyError, TypeError) as error:
                output[record['name']] = {'values': entries, 'complete': False, 'error': str(error)}
        return output


def load(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return [(name, Dex(archive.read(name))) for name in archive.namelist()
                    if re.fullmatch(r'classes\d*\.dex', name)]
    with open(path, 'rb') as source:
        return [('classes.dex', Dex(source.read()))]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('pattern', nargs='?', default='.')
    args = parser.parse_args()
    print(json.dumps({name: dex.select(args.pattern) for name, dex in load(args.path)}, indent=2))
