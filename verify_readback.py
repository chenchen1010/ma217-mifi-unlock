"""Verify a completed capture against the locally prepared original. No device writes."""
import argparse, json
from pathlib import Path
from profile_ma217 import BACKUP, BASELINE_SHA, OUT, PATCH_OFFSET, PATCH_SIZE, check, sha

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path)
    p.add_argument('--variant',choices=('original','modified'),required=True)
    p.add_argument('--noop-proof',action='store_true')
    a=p.parse_args();b=a.capture.read_bytes();original=BACKUP.read_bytes();meta=json.loads(a.capture.with_suffix('.json').read_text(encoding='utf8'))
    check(len(b)==meta['bytes_read']==0x800000 and sha(b)==meta['sha256'],'Incomplete or inconsistent readback')
    check(sha(original)==BASELINE_SHA,'Local backup changed')
    expected=bytearray(original)
    if a.variant=='modified':expected[PATCH_OFFSET:PATCH_OFFSET+PATCH_SIZE]=(OUT/'OSLO-rate-off.bin').read_bytes()[0x237000:0x2c9000]
    r={'capture':a.capture.name,'backup_sha256':BASELINE_SHA,'readback_sha256':sha(b),'variant':a.variant,
       'expected_firmware_matches':b[:0x540000]==expected[:0x540000],
       'original_firmware_matches':b[:0x540000]==original[:0x540000],
       'identity_region_matches':b[0x20000:0x40000]==original[0x20000:0x40000],
       'webui_matches':b[0x560000:0x5b0000]==original[0x560000:0x5b0000],
       'does_not_prove':'Normal boot, SIM identity, Internet connectivity or physical flash capacity'}
    dest=a.capture.with_name(a.capture.stem+'-comparison.json');dest.write_text(json.dumps(r,indent=2),encoding='utf8')
    check(r['expected_firmware_matches'] and r['identity_region_matches'] and r['webui_matches'],'Readback differs: do not continue flashing')
    if a.noop_proof:
        check(a.variant=='original','No-op proof must match original firmware')
        Path('artifacts/noop-readback-comparison.json').write_text(json.dumps(r,indent=2),encoding='utf8')
    print(json.dumps(r,indent=2))

if __name__=='__main__':main()
