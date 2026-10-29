"""Read device-proven flash ranges via WTPTP Upload, without an image download.

Requires a fresh bootloader session after the identification probe: GetVersion
enters download flow in the reference OBM and MUST NOT be repeated in this flow.
Protocol: FBFDownloader_C/WtptpDownloader.c UploadDataFromTarget.
Subtype 27 = QSPI_FLASH, verified in official SWDownloader 5.0.0.2 PE at
VA 0x45e469 (name to value) and 0x45f803 (value to name). Release 4.9.1.0
introduced this subtype for ASR1803. The old SPI subtype 10 was rejected.
No RAM image, erase, OTP, identity or arbitrary write command is implemented.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import struct
import time

from mifi_wtp_probe import WinUsb, interfaces, parse_response

SIZE = 256
SUBTYPE = 27
HEADER = struct.pack('<BBBBI', 0x32, 0, 0, 0, 16) + struct.pack('<BBBBIIBBBB', 0, SUBTYPE, 0, 1, 0, SIZE, 0, 0, 0, 0)


def command(number):
    if number not in (0x2b, 0x30, 0x31, 0x33, 0x34, 0x35):
        raise ValueError('Not a readback or session-control command')
    return struct.pack('<BBBBI', number, 0, 0, 0, 0)


class HeaderReader(WinUsb):
    header_accepted = False
    complete = False
    finished = False

    def validate_packet(self, packet):
        if packet == bytes.fromhex('00d3022b') or packet in [command(c) for c in (0x2b, 0x34, 0x35)]:
            return
        if packet == HEADER and not self.header_accepted:
            return
        if packet == command(0x33) and self.header_accepted and not self.complete:
            return
        if packet == command(0x30) and self.complete:
            return
        if packet == command(0x31) and self.finished:
            return
        raise ValueError('Packet excluded from bounded header read')


def control(usb, number, report):
    value = parse_response(usb.exchange(command(number)), number)
    report['responses'].append(value)
    return value


def drain(usb, value, report):
    for _ in range(16):
        if not value['flags'] & 1:
            return
        value = control(usb, 0x2b, report)
    raise ValueError('Too many pending messages')


def main():
    global SIZE, HEADER
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--identification', type=Path, help='JSON from your own preceding mifi_wtp_probe.py run')
    ap.add_argument('--header-file', type=Path, default=Path('artifacts/header.bin'))
    ap.add_argument('--tim-file', type=Path, default=Path('artifacts/tim.bin'))
    ap.add_argument('--read-header', action='store_true')
    ap.add_argument('--read-tim', action='store_true', help='Read the TIM length proven by the captured device header')
    ap.add_argument('--read-images', action='store_true', help='Read only the span proven by the captured TIM image table')
    ap.add_argument('--read-flash-8m', action='store_true', help='Back up through the observed PSM banks at 0x7e0000/0x7f0000; capacity still requires independent verification')
    ap.add_argument('--wait-replug', action='store_true')
    ap.add_argument('--wait-seconds', type=int, default=120, choices=range(1, 901))
    args = ap.parse_args()
    if args.read_tim or args.read_images or args.read_flash_8m:
        b = args.header_file.read_bytes()
        assert hashlib.sha256(b).hexdigest() == '70393f1122520ba30bdfa41e71c21b4c0ada725c5539a3b1865c1649ac6fd99a'
        assert struct.unpack_from('<II', b) == (0x30400, 0x54494d48)
        assert struct.unpack_from('<I', b, 40)[0] == 0x5350491b
        SIZE = struct.unpack_from('<I', b, 56 + 16)[0]
        assert SIZE == 3920
        if args.read_images or args.read_flash_8m:
            tim = args.tim_file.read_bytes()
            assert hashlib.sha256(tim).hexdigest() == '5a0e55959d40dd262df6600953de58751c0bcf5b40b097177f8ccede94cf159c'
            assert struct.unpack_from('<I', tim, 44)[0] == 7
            regions = [struct.unpack_from('<24I', tim, 56 + n * 96) for n in range(7)]
            SIZE = max(a[2] + a[4] for a in regions)
            assert SIZE == 0x540000
            if args.read_flash_8m:
                SIZE = 0x800000
        HEADER = struct.pack('<BBBBI', 0x32, 0, 0, 0, 16) + struct.pack('<BBBBIIBBBB', 0, SUBTYPE, 0, 1, 0, SIZE, 0, 0, 0, 0)
    if not (args.read_header or args.read_tim or args.read_images or args.read_flash_8m):
        print(json.dumps({'dry_run': True, 'offset': 0, 'size': SIZE, 'subtype': SUBTYPE,
                          'wire_header_hex': HEADER.hex(), 'flash_write_commands': []}))
        return
    # Require the actual identification evidence, not an assumed chip family.
    if args.identification is None:ap.error('--identification from your own device is required')
    prior = json.loads(args.identification.read_text('utf-8'))
    Path('artifacts').mkdir(exist_ok=True)
    assert any(r['command'] == 0x20 and r['status'] == 0 and
               r['payload_hex'] == '313133331420010633415a4e' for r in prior['responses'])
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    mode = '8m' if args.read_flash_8m else ('images' if args.read_images else ('tim' if args.read_tim else 'header'))
    dest = Path('artifacts') / f'flash-{mode}-{stamp}'
    report = {'started_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'offset': 0, 'requested_bytes': SIZE, 'subtype': SUBTYPE, 'responses': [],
              'bytes_read': 0, 'complete_firmware_backup': False, 'flash_write_commands': []}
    usb = None
    try:
        deadline = time.monotonic() + args.wait_seconds
        if args.wait_replug:
            print('Waiting for physical disconnection of the current download interface.', flush=True)
            while interfaces():
                if time.monotonic() > deadline:
                    raise TimeoutError('No device disconnection observed')
                time.sleep(0.1)
        print('Waiting for a fresh boot download interface.', flush=True)
        paths = interfaces()
        while not paths:
            if time.monotonic() > deadline:
                raise TimeoutError('No new boot interface observed')
            time.sleep(0.05)
            paths = interfaces()
        if len(paths) != 1 or 'vid_2ecc&pid_3001' not in paths[0].lower():
            raise ValueError('Expected exactly the known boot interface')
        usb = HeaderReader(paths[0], timeout_ms=15000)
        echo = usb.exchange(bytes.fromhex('00d3022b'))
        report['preamble'] = echo.hex()
        if echo != bytes.fromhex('00d3022b'):
            raise ValueError('Preamble mismatch')
        proto = control(usb, 0x34, report)
        if proto['status'] != 0 or proto['payload_hex'] != '01010000':
            raise ValueError('Protocol mismatch')
        drain(usb, proto, report)
        params = control(usb, 0x35, report)
        if params['status'] != 0 or struct.unpack_from('<I', bytes.fromhex(params['payload_hex']))[0] != 8192:
            raise ValueError('Target buffer mismatch')
        drain(usb, params, report)
        value = parse_response(usb.exchange(HEADER), 0x32)
        report['responses'].append(value)
        if value['status'] != 0:
            drain(usb, value, report)
            raise ValueError('Flash header read rejected by bootloader')
        usb.header_accepted = True
        drain(usb, value, report)
        sha = hashlib.sha256()
        with dest.with_suffix('.partial').open('xb') as output:
            while report['bytes_read'] < SIZE:
                chunk = min(8186, SIZE - report['bytes_read'])
                data = usb.exchange(command(0x33), read_size=chunk + 6)
                if len(data) != 6 + chunk or data[:4] != bytes.fromhex('33000000'):
                    report['unexpected_data_header_hex'] = data[:16].hex()
                    report['unexpected_data_length'] = len(data)
                    raise ValueError('Unexpected flash data response')
                image = data[6:]
                if report['bytes_read'] == 0:
                    report['prefix_hex'] = image[:32].hex()
                output.write(image)
                sha.update(image)
                report['bytes_read'] += chunk
                if data[4] & 1:
                    drain(usb, {'flags': data[4]}, report)
                if report['bytes_read'] // 1048576 != (report['bytes_read'] - chunk) // 1048576:
                    print(f"Read {report['bytes_read']} / {SIZE} bytes", flush=True)
        usb.complete = True
        dest.with_suffix('.partial').rename(dest.with_suffix('.bin'))
        report.update(sha256=sha.hexdigest(), output_file=str(dest.with_suffix('.bin')))
        done = control(usb, 0x30, report)
        if done['status'] != 0:
            raise ValueError('Read completion was not acknowledged')
        usb.finished = True
        drain(usb, done, report)
        try:
            value = control(usb, 0x31, report)
            report['disconnect_acknowledged'] = value['status'] == 0
        except OSError as exc:
            report['disconnect_error'] = str(exc)
            report['boot_interface_gone'] = not interfaces()
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if usb:
            usb.close()
        report['finished_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        dest.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    if report.get('error') or report['bytes_read']!=SIZE:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
