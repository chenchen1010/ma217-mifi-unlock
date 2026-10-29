"""Create a private workspace from TWO captures of your own device. Offline only."""
import argparse, json
from pathlib import Path
from profile_ma217 import ROOT, OUT, BACKUP, PROFILE, validate_backup, validate_modified, sha, check

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backup',type=Path,required=True)
    p.add_argument('--second-backup',type=Path,required=True)
    p.add_argument('--modified',type=Path,default=Path('firmware/OSLO-unlocked.bin'))
    a=p.parse_args()
    check(a.backup.resolve()!=a.second_backup.resolve(), 'Supply two independently captured files')
    check(not PROFILE.exists() and not BACKUP.exists(), 'Workspace already initialized; preserve it and use a fresh checkout for another device')
    b=a.backup.read_bytes();second=a.second_backup.read_bytes();validate_backup(b);validate_backup(second)
    check(b[:0x540000]==second[:0x540000], 'Firmware or identity region changed between reads')
    check(b[0x560000:0x5b0000]==second[0x560000:0x5b0000], 'WebUI changed between reads')
    modified=a.modified.read_bytes();original=b[0x40000:0x450000]
    before,after=validate_modified(original,modified)
    OUT.mkdir(parents=True,exist_ok=True)
    BACKUP.write_bytes(b)
    (ROOT/'OSLO.bin').write_bytes(original)
    (ROOT/'OBMI.bin').write_bytes(b[0x6000:0x6000+101212])
    (ROOT/'OSLO-unpacked-237000.bin').write_bytes(before)
    (OUT/'OSLO-rate-off.bin').write_bytes(modified)
    (OUT/'AP-rate-off.bin').write_bytes(after)
    report={'backup_sha256':sha(b),'second_capture_sha256':sha(second),
            'two_captures_firmware_and_identity_match':True,'original_oslo_sha256':sha(original),
            'modified_oslo_sha256':sha(modified),'physical_capacity_verified':False,
            'source':'User-supplied original captures; caller must ensure both came from this device'}
    PROFILE.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report));print('Prepared private artifacts/. Next: build, emulate, then no-op verification.')

if __name__=='__main__':main()
