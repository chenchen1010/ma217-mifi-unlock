"""Rebuild the released application image using the official LZMA SDK 26.05 tool."""
import argparse, json, lzma, subprocess, tempfile
from pathlib import Path
from profile_ma217 import ORIGINAL_OSLO_SHA, MODIFIED_OSLO_SHA, AP_BASE, PATCHES, check, sha, validate_modified, unpack_ap

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',type=Path,default=Path('firmware/OSLO-original.bin'))
    p.add_argument('--lzma',type=Path,required=True,help='Official SDK bin/x64/lzma.exe')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();b=a.original.read_bytes();check(sha(b)==ORIGINAL_OSLO_SHA,'Unsupported original firmware')
    check(not a.output.exists(),'Refusing to overwrite output')
    raw=bytearray(unpack_ap(b))
    for address,old,new,_ in PATCHES:
        i=address-AP_BASE;check(raw[i:i+2]==bytes.fromhex(old),'Instruction mismatch');raw[i:i+2]=bytes.fromhex(new)
    with tempfile.TemporaryDirectory(prefix='ma217-rebuild-') as folder:
        source=Path(folder)/'ap.bin';target=Path(folder)/'ap.lzma';source.write_bytes(raw)
        subprocess.run([str(a.lzma.resolve()),'e',str(source),str(target),'-d20'],check=True)
        compressed=target.read_bytes()
    check(len(compressed)<=0x92000,'Compressed application exceeds reserved slot')
    candidate=bytearray(b);candidate[0x237000:0x2c9000]=compressed+bytes([255])*(0x92000-len(compressed))
    validate_modified(b,bytes(candidate))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(candidate)
    print(json.dumps({'sha256':sha(candidate),'matches_release':sha(candidate)==MODIFIED_OSLO_SHA,'compressed_size':len(compressed)}))

if __name__=='__main__':main()
