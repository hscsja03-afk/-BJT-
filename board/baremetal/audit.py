"""Check ELF load/stack placement, DDR-disabled initialization and build inputs."""
from pathlib import Path
import hashlib
import json
import re
import struct

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/work/baremetal'
INIT=ROOT/'build/work/baseline50/vivado/bjt.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def audit():
    text=INIT.read_text()
    if 'ps7_ddr_init' in text or re.search(r'mask_write\s+0[xX]F8006',text,re.I):
        raise ValueError('PS initialization touches DDR controller')
    bsp=OUT/'software/ocm_platform/ps7_cortexa9_0/baremetal/bsp'
    if 'XPAR_PS7_DDR_0_BASEADDRESS' in (bsp/'include/xparameters.h').read_text():
        raise ValueError('BSP contains external DDR')
    result={'ddr_initialized':False,'storage_written':False,'link_memory_bytes':0x30000,
            'ps_init_sha256':sha(INIT),'images':{},'inputs':{}}
    for relative in ('src/baremetal/main.c','src/baremetal/adda.c','src/baremetal/adda.h','src/baremetal/timebase.h',
                     'board/config/ocm.ld','board/baremetal/build.ps1'):
        result['inputs'][relative]=sha(ROOT/relative)
    for mode in ('probe','adda'):
        p=OUT/f'{mode}.elf';data=p.read_bytes()
        if data[:7]!=b'\x7fELF\x01\x01\x01':raise ValueError('Expected ELF32 little endian')
        header=struct.unpack_from('<HHIIIIIHHHHHH',data,16)
        if header[1]!=40:raise ValueError('Expected ARM machine')
        entry,phoff,phsize,phnum=header[3],header[4],header[8],header[9]
        segments=[]
        for i in range(phnum):
            typ,offset,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,phoff+i*phsize)
            if typ!=1 or not ms:continue
            if va!=pa or pa+ms>0x30000 or fs>ms or offset+fs>len(data):
                raise ValueError('Load segment outside low OCM')
            segments.append({'address':pa,'file_bytes':fs,'memory_bytes':ms})
        symbols=(OUT/f'{mode}_symbols.txt').read_text(encoding='utf-8-sig')
        def symbol(name):
            match=re.search(r'^([0-9a-fA-F]+) \w '+re.escape(name)+r'$',symbols,re.M)
            if not match:raise ValueError('Missing symbol '+name)
            return int(match[1],16)
        end,mailbox= symbol('_end'),symbol('bjt_mailbox')
        heap_bytes=symbol('_heap_end')-symbol('_heap_start')
        stack_bytes=symbol('__stack')-symbol('_stack_end')
        if heap_bytes!=0 or stack_bytes!=0x3000:
            raise ValueError('Linker did not apply the intended zero heap / 12KiB stack')
        if not segments or entry>=0x30000 or end>0x30000 or mailbox+8256>end:
            raise ValueError('Invalid entry/end/mailbox placement')
        table=symbol('MMUTable')
        descriptors=None
        for i in range(phnum):
            typ,offset,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,phoff+i*phsize)
            if typ==1 and va<=table and table+4096<=va+fs:
                descriptors=struct.unpack_from('<1024I',data,offset+table-va)
        if descriptors is None or any(v&3 for v in descriptors[1:]):
            raise ValueError('External DDR sections are not marked as MMU translation faults')
        result['images'][mode]={'sha256':sha(p),'entry':entry,'end':end,
            'remaining_low_ocm_bytes':0x30000-end,'mailbox':mailbox,'load_segments':segments,
            'symbols_sha256':sha(OUT/f'{mode}_symbols.txt'),
            'heap_bytes':heap_bytes,'main_stack_bytes':stack_bytes,
            'ddr_mmu_fault_sections':1023}
    result['bsp_xparameters_sha256']=sha(bsp/'include/xparameters.h')
    result['xsa_sha256']=sha(OUT/'ocm_platform.xsa')
    result['build_id']=int((OUT/'build_id.txt').read_text(encoding='utf-8-sig').strip(),16)
    (OUT/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['images'],indent=2))
    return result
if __name__=='__main__':audit()
