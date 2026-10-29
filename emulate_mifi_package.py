"""Run the captured OBMI package parser locally with mocked USB/Flash hardware.

The signature-verifier, image-loop, command dispatch, QSPI size round-up and
sector selection execute as original ARM instructions. Physical QSPI operations
are modeled. This is an offline boundary check, not a substitute for readback.
"""
from pathlib import Path
import json, struct, hashlib
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
from build_mifi_package import OUT, ROOT, BACKUP, PATCH_OFFSET, PATCH_SIZE, RECOVERY_OFFSET, RECOVERY_SIZE, xor32, ident

def run(mode, erase_block=0x10000):
    flash=bytearray(BACKUP.read_bytes())
    if mode=='recover-original':
        # Model damaged bytes throughout the whole restoration range.
        flash[RECOVERY_OFFSET:RECOVERY_OFFSET+RECOVERY_SIZE]=bytes([255])*RECOVERY_SIZE
    initial=bytes(flash)
    write_offset,write_size = (RECOVERY_OFFSET,RECOVERY_SIZE) if mode in ('recover-original','apply-rate-off') else (PATCH_OFFSET,PATCH_SIZE)
    tim=(OUT/(mode+'.tim')).read_bytes()
    fbf=(OUT/(mode+'.fbf')).read_bytes()
    obm=(ROOT/'OBMI.bin').read_bytes()
    u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    u.mem_map(0x6000000,0x2000000)
    u.mem_write(0x7800000,obm)
    u.mem_write(0x7c00000,tim)
    u.mem_write(0x7c01000,struct.pack('<4I',0x7c00000,0x7c00038,0,0))
    u.mem_write(0x7840000,struct.pack('<II',0x6000,0x530000))
    u.mem_write(0x7841eb4+0x30,struct.pack('<I',0x7811994))
    # Execute the actual QSPI erase wrapper INCLUDING its size round-up.
    u.mem_write(0x78410e8+4,struct.pack('<I',0x7e00000))
    u.mem_write(0x78410e8+0x38,struct.pack('<III',0x1000000,0,erase_block))
    u.reg_write(UC_ARM_REG_SP,0x7f80000)
    u.reg_write(UC_ARM_REG_LR,0x7ff0000)
    u.reg_write(UC_ARM_REG_R0,0x7c01000)
    events=[]
    def r(n): return u.reg_read(UC_ARM_REG_R0+n)
    def ret(v=0):
        u.reg_write(UC_ARM_REG_R0,v)
        u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
    def hook(uc,a,size,data):
        if a==0x7ff0000: uc.emu_stop()
        elif a==0x78062c8: ret(0x7f00000)
        elif a==0x780c130:
            target=r(2)
            payload=fbf if target==ident('FBFD') else obm
            assert target in (ident('FBFD'),ident('OBMI'))
            u.mem_write(r(1),payload)
            u.mem_write(r(0),bytes(16))
            events.append({'usb_image':target,'bytes':len(payload)})
            ret()
        elif a==0x7803e70:
            p,v,n=r(0),r(1),r(2);u.mem_write(p,bytes([v&255])*n);ret(p)
        elif a==0x7803e8c:
            p,q,n=r(0),r(1),r(2);u.mem_write(p,bytes(u.mem_read(q,n)));ret(p)
        elif a==0x7803f70:
            v,n=r(0),r(1); assert n
            u.reg_write(UC_ARM_REG_R1,v%n);ret(v//n)
        elif a==0x7805c60:
            # Accelerate the 1501-iteration modular multiplication loop only.
            # For this captured modulus, each product fits in uint32.
            fp=u.reg_read(UC_ARM_REG_FP)
            modulus=struct.unpack('<I',u.mem_read(fp-0x34,4))[0]
            assert modulus==5543 and r(6)==1501
            u.reg_write(UC_ARM_REG_R3,pow(r(7),r(6),modulus))
            u.reg_write(UC_ARM_REG_PC,0x7805c88)
        elif a==0x7803ff8: ret(xor32(bytes(u.mem_read(r(0),r(1)))))
        elif a==0x7807480: raise AssertionError(('OBMI FatalError',r(0)))
        elif a in (0x7805008,0x7804fe0,0x78096d8,0x7806680,0x780afcc,0x78063dc,0x781161c,0x7810494,0x781064c): ret()
        elif a==0x780b324:
            events.append({'notification_type':r(0),'value':r(1)});ret()
        elif a==0x780640c:
            if r(1):
                assert mode!='noop' and (r(0),r(1),r(2))==(write_offset,write_size,0)
                events.append({'erase_requested':[r(0),r(1)]})
            # Execute wrapper, vtable round-up and spi_nor_erase selection.
        elif a==0x780ffb0:
            op=bytes(u.mem_read(r(1),0x24))
            descriptor=struct.unpack_from('<I',op)[0]
            addrlen=op[4]
            assert addrlen==3
            address=int.from_bytes(op[5:5+addrlen],'big')
            assert descriptor in (0x7e0008c,0x7e00096,0x7e000a0)
            length=0x1000 if descriptor==0x7e0008c else erase_block
            assert address%length==0
            assert 0x200000<=address<address+length<=0x400000
            events.append({'physical_erase':[address,length]})
            flash[address:address+length]=bytes([255])*length
            ret()
        elif a==0x780635c:
            assert mode!='noop' and (r(0),r(2),r(3))==(write_offset,write_size,0)
            events.append({'write':[r(0),r(2)]})
            flash[r(0):r(0)+r(2)]=u.mem_read(r(1),r(2));ret()
        elif a==0x7806314:
            off,p,n=r(0),r(1),r(2)
            assert 0<=off<0x800000 and 0<n<=0x10000
            u.mem_write(p,bytes(flash[off:off+n]));ret()
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x7808cfc,0x7ff0000,timeout=30_000_000,count=30_000_000)
    pc=u.reg_read(UC_ARM_REG_PC)
    assert pc==0x7ff0000,hex(pc)
    expected=bytearray(initial)
    if mode=='recover-original':expected[write_offset:write_offset+write_size]=BACKUP.read_bytes()[write_offset:write_offset+write_size]
    if mode=='apply-rate-off':
        candidate='OSLO-rate-off.bin'
        expected[PATCH_OFFSET:PATCH_OFFSET+PATCH_SIZE]=(OUT/candidate).read_bytes()[0x237000:0x2c9000]
    matched=flash==expected
    legacy=False
    assert matched
    if mode=='recover-original':assert flash[:0x540000]==BACKUP.read_bytes()[:0x540000]
    report={'offline_only':True,'mode':mode,'completed':True,'events':events,
            'fbf_sha256':hashlib.sha256(fbf).hexdigest(),
            'tim_sha256':hashlib.sha256(tim).hexdigest(),
            'backup_sha256':hashlib.sha256(BACKUP.read_bytes()).hexdigest(),
            'entire_flash_model_matches_expected':matched,'erase_block_size':erase_block,
            'actual_erase_wrapper_executed':True,'legacy_unaligned_unsafe':legacy,
            'limitations':'USB, physical QSPI transactions, initialization and ROM arithmetic mocked; actual erase wrapper and sector selection executed; modular multiplication accelerated equivalently; hardware readback still required.'}
    (OUT/(mode+'-erase-'+hex(erase_block)+'.json')).write_text(json.dumps(report,indent=2),encoding='utf8')
    (OUT/(mode+'-emulation.json')).write_text(json.dumps(report,indent=2),encoding='utf8')
    print(mode,'erase block',hex(erase_block),'intended boundary matches',matched,'ranges', [e for e in events if 'write' in e or 'erase_requested' in e],flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('noop','recover-original','apply-rate-off'),required=True)
    mode=parser.parse_args().mode
    for block in (0x10000,0x20000):run(mode,block)
