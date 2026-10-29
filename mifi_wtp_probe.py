"""Bounded, read-only WTPTP identification through the signed WinUSB driver.

No image selection, RAM downloads, flash writes, erase, OTP or identity commands.
Protocol references: artifacts/research/fbf1803/{WTPdef.h,WTPCOMMCLASS.c}.
This identifies an already enumerated download port; it does not enter that mode.
Observed on this unit: GetVersion holds download flow and Disconnect times out.
After identification, power-cycle before using the separate Flash Upload reader.
"""
import argparse
if not __debug__:
    raise RuntimeError('Do not run device tools with Python -O')
import ctypes as C
from ctypes import wintypes as W
import datetime as dt
import json
from pathlib import Path
import re
import struct
import time
import uuid

GUID_TEXT = '0C8AB63E-040C-428C-8050-1776087AD742'
ALLOWED_IDS = {(0x1286, 0x8130), (0x1286, 0x8181), (0x2ecc, 0x3001), (0x2ecc, 0x3002)}
ALLOWED_COMMANDS = {0x20, 0x2b, 0x31, 0x34, 0x35}  # identification, messages, disconnect


def command_packet(command):
    if command not in ALLOWED_COMMANDS:
        raise ValueError('Command excluded from the read-only probe')
    return struct.pack('<BBBBI', command, 0, 0, 0, 0)


def parse_response(data, command):
    if len(data) < 6 or data[0] != command or data[1:3] != b'\0\0':
        raise ValueError('Short or mismatched WTPTP response')
    if len(data) != 6 + data[5]:
        raise ValueError('WTPTP response length does not match its header')
    return {'command': command, 'status': data[3], 'flags': data[4],
            'payload_hex': data[6:].hex()}


class GUID(C.Structure):
    _fields_ = [('data', C.c_ubyte * 16)]


class InterfaceData(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('guid', GUID), ('flags', W.DWORD), ('reserved', C.c_size_t)]


class InterfaceDescriptor(C.Structure):
    _pack_ = 1
    _fields_ = [(name, C.c_ubyte) for name in ('length', 'type', 'number', 'alternate',
                'endpoints', 'klass', 'subclass', 'protocol', 'index')]


class PipeInfo(C.Structure):
    _fields_ = [('type', C.c_int), ('id', C.c_ubyte), ('packet', C.c_ushort), ('interval', C.c_ubyte)]


def api(dll, name, restype, *args):
    f = getattr(dll, name)
    f.restype, f.argtypes = restype, args
    return f


def check(ok, operation):
    if not ok:
        raise OSError(C.get_last_error(), operation)


def interfaces():
    setup = C.WinDLL('setupapi', use_last_error=True)
    getset = api(setup, 'SetupDiGetClassDevsW', W.HANDLE, C.POINTER(GUID), W.LPCWSTR, W.HWND, W.DWORD)
    enum = api(setup, 'SetupDiEnumDeviceInterfaces', W.BOOL, W.HANDLE, C.c_void_p, C.POINTER(GUID), W.DWORD, C.POINTER(InterfaceData))
    detail = api(setup, 'SetupDiGetDeviceInterfaceDetailW', W.BOOL, W.HANDLE, C.POINTER(InterfaceData), C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p)
    destroy = api(setup, 'SetupDiDestroyDeviceInfoList', W.BOOL, W.HANDLE)
    guid = GUID((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(GUID_TEXT).bytes_le))
    handle = getset(C.byref(guid), None, None, 0x12)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    found = []
    try:
        index = 0
        while True:
            entry = InterfaceData()
            entry.cbSize = C.sizeof(entry)
            if not enum(handle, None, C.byref(guid), index, C.byref(entry)):
                if C.get_last_error() == 259:
                    break
                raise C.WinError(C.get_last_error())
            length = W.DWORD()
            detail(handle, C.byref(entry), None, 0, C.byref(length), None)
            if not 8 <= length.value <= 32768:
                raise ValueError('Unexpected interface path length')
            buf = C.create_string_buffer(length.value)
            C.cast(buf, C.POINTER(W.DWORD))[0] = 8 if C.sizeof(C.c_void_p) == 8 else 6
            check(detail(handle, C.byref(entry), buf, length.value, None, None), 'Device interface path')
            path = C.wstring_at(C.addressof(buf) + 4)
            match = re.search(r'vid_([0-9a-f]{4})&pid_([0-9a-f]{4})', path, re.I)
            if match and tuple(int(x, 16) for x in match.groups()) in ALLOWED_IDS:
                found.append(path)
            index += 1
    finally:
        destroy(handle)
    return found


class WinUsb:
    def __init__(self, path, timeout_ms=2000):
        self.file = self.usb = None
        k = C.WinDLL('kernel32', use_last_error=True)
        u = C.WinDLL('winusb', use_last_error=True)
        create = api(k, 'CreateFileW', W.HANDLE, W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE)
        self.close_handle = api(k, 'CloseHandle', W.BOOL, W.HANDLE)
        init = api(u, 'WinUsb_Initialize', W.BOOL, W.HANDLE, C.POINTER(W.HANDLE))
        self.free = api(u, 'WinUsb_Free', W.BOOL, W.HANDLE)
        query = api(u, 'WinUsb_QueryInterfaceSettings', W.BOOL, W.HANDLE, C.c_ubyte, C.POINTER(InterfaceDescriptor))
        pipe = api(u, 'WinUsb_QueryPipe', W.BOOL, W.HANDLE, C.c_ubyte, C.c_ubyte, C.POINTER(PipeInfo))
        policy = api(u, 'WinUsb_SetPipePolicy', W.BOOL, W.HANDLE, C.c_ubyte, W.ULONG, W.ULONG, C.c_void_p)
        self.write = api(u, 'WinUsb_WritePipe', W.BOOL, W.HANDLE, C.c_ubyte, C.c_void_p, W.ULONG, C.POINTER(W.ULONG), C.c_void_p)
        self.read = api(u, 'WinUsb_ReadPipe', W.BOOL, W.HANDLE, C.c_ubyte, C.c_void_p, W.ULONG, C.POINTER(W.ULONG), C.c_void_p)
        self.file = create(path, 0xc0000000, 3, None, 3, 0x40000000, None)
        if self.file == C.c_void_p(-1).value:
            self.file = None
            raise C.WinError(C.get_last_error())
        try:
            self.usb = W.HANDLE()
            check(init(self.file, C.byref(self.usb)), 'WinUsb initialize')
            desc = InterfaceDescriptor()
            check(query(self.usb, 0, C.byref(desc)), 'Interface descriptor')
            self.pipes = []
            for i in range(desc.endpoints):
                pi = PipeInfo()
                check(pipe(self.usb, 0, i, C.byref(pi)), 'Pipe descriptor')
                self.pipes.append({'id': pi.id, 'type': pi.type, 'packet_size': pi.packet})
            incoming = [p['id'] for p in self.pipes if p['type'] == 2 and p['id'] & 0x80]
            outgoing = [p['id'] for p in self.pipes if p['type'] == 2 and not p['id'] & 0x80]
            if len(incoming) != 1 or len(outgoing) != 1:
                raise ValueError('Expected one bulk IN and one bulk OUT pipe')
            self.pin, self.pout = incoming[0], outgoing[0]
            if not 1000 <= timeout_ms <= 30000:
                raise ValueError('Invalid bounded USB timeout')
            timeout = W.ULONG(timeout_ms)
            for endpoint in (self.pin, self.pout):
                check(policy(self.usb, endpoint, 3, C.sizeof(timeout), C.byref(timeout)), 'Pipe timeout')
        except Exception:
            self.close()
            raise

    def close(self):
        if self.usb:
            self.free(self.usb)
            self.usb = None
        if self.file:
            self.close_handle(self.file)
            self.file = None

    def validate_packet(self, packet):
        if packet != bytes.fromhex('00d3022b') and packet not in [command_packet(c) for c in ALLOWED_COMMANDS]:
            raise ValueError('Packet excluded from read-only probe')

    def exchange(self, packet, read_size=16384):
        self.validate_packet(packet)
        if not 6 <= read_size <= 16384:
            raise ValueError('Unexpected read buffer size')
        buf = C.create_string_buffer(packet)
        count = W.ULONG()
        check(self.write(self.usb, self.pout, buf, len(packet), C.byref(count), None), 'Bulk write query')
        if count.value != len(packet):
            raise ValueError('Partial query write')
        buf = C.create_string_buffer(read_size)
        check(self.read(self.usb, self.pin, buf, len(buf), C.byref(count), None), 'Bulk read response')
        return buf.raw[:count.value]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--probe', action='store_true', help='Send bounded identification queries; default lists interfaces only')
    ap.add_argument('--resume-from', type=Path, help='Resume a recently observed four-byte preamble echo from a saved probe report')
    ap.add_argument('--wait-seconds', type=int, default=0, choices=range(0,121), metavar='0..120',
                    help='Wait for an already authorized normal reboot to expose the download interface')
    args = ap.parse_args()
    report = {'captured_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'read_only': True,
              'responses': [], 'firmware_extracted': False}
    usb = None
    synchronized = False
    try:
        start = time.monotonic()
        paths = interfaces()
        while not paths and time.monotonic() - start < args.wait_seconds:
            time.sleep(0.05)
            paths = interfaces()
        report['interface_wait_seconds'] = round(time.monotonic() - start, 3)
        report['download_interfaces_found'] = len(paths)
        report['device_ids'] = [re.search(r'vid_[0-9a-f]{4}&pid_[0-9a-f]{4}', p, re.I).group(0) for p in paths]
        if args.probe:
            if len(paths) != 1:
                raise ValueError('Expected exactly one supported download interface')
            usb = WinUsb(paths[0])
            report['pipes'] = usb.pipes
            if args.resume_from:
                prior = json.loads(args.resume_from.read_text(encoding='utf-8'))
                age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(prior['captured_at_utc'])).total_seconds()
                if not (0 <= age <= 600 and prior.get('preamble_response_hex') == '00d3022b'
                        and prior.get('device_ids') == report['device_ids'] and not prior.get('responses')):
                    raise ValueError('Prior report does not establish a recent unfinished preamble handshake')
                report['resumed_handshake_from'] = str(args.resume_from)
            else:
                preamble = usb.exchange(bytes.fromhex('00d3022b'))
                report['preamble_response_hex'] = preamble.hex()
                # CI2Download.c echoes exactly PREAMBLE_SIZE bytes. Host ReadUSB accepts
                # short reads; its requested length of 38 is not a required wire length.
                if preamble != bytes.fromhex('00d3022b'):
                    raise ValueError('Unexpected preamble response; stopping without additional commands')
            synchronized = True
            # Official GetVersion first drains boot messages, even before querying version.
            for _ in range(8):
                parsed = parse_response(usb.exchange(command_packet(0x2b)), 0x2b)
                report['responses'].append(parsed)
                if not parsed['flags'] & 1:
                    break
            else:
                raise ValueError('Initial message queue exceeded bounded probe')
            for command in (0x20, 0x34, 0x35):
                raw = usb.exchange(command_packet(command))
                parsed = parse_response(raw, command)
                report['responses'].append(parsed)
                if parsed['status'] != 0:
                    break
                for _ in range(8):
                    if not parsed['flags'] & 1:
                        break
                    raw = usb.exchange(command_packet(0x2b))
                    parsed = parse_response(raw, 0x2b)
                    report['responses'].append(parsed)
                else:
                    raise ValueError('Message queue exceeded bounded probe')
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if usb:
            if synchronized:
                # WTPCOMMCLASS.c Disconnect: release the temporary bootloader session.
                # No Done, download header, image selection or flash operation is sent.
                try:
                    for _ in range(2):
                        parsed = parse_response(usb.exchange(command_packet(0x31)), 0x31)
                        report['responses'].append(parsed)
                        if parsed['status'] == 0:
                            report['disconnect_acknowledged'] = True
                            break
                except Exception as exc:
                    report['disconnect_error'] = str(exc)
            usb.close()
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        dest = Path(__file__).parent / 'artifacts' / f'wtp-probe-{stamp}.json'
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        print(f'Saved {dest}')
    if args.probe and not any(x.get('command')==0x20 and x.get('status')==0 for x in report['responses']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
