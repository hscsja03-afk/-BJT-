"""Collect existing diagnostic evidence. This script never connects to hardware."""
from pathlib import Path
import csv
import hashlib
import json
import re
import shutil
import struct

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'report/evidence'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retain(name):
    source = ROOT/'build/logs'/name
    target = OUT/name
    shutil.copyfile(source, target)
    return {'path': target.relative_to(ROOT).as_posix(), 'sha256': digest(target)}


def words(text, marker, count):
    found = re.search(re.escape(marker)+r'=([^\n]+)', text)
    if not found: raise ValueError('Missing '+marker)
    result = [int(x) for x in found.group(1).split()]
    if len(result) != count: raise ValueError('Unexpected '+marker+' word count')
    return result


def ddr_writes(text):
    body = re.search(r'proc ps7_ddr_init_data_3_0 \{\} \{(.*?)\n\}', text, re.S).group(1)
    return [tuple(int(x,16) for x in m) for m in re.findall(
        r'mask_write\s+(0[Xx][0-9a-fA-F]+)\s+(0[Xx][0-9a-fA-F]+)\s+(0[Xx][0-9a-fA-F]+)', body)]


def boot_ddr_arrays(path):
    data = path.read_bytes()
    start, size = struct.unpack_from('<II', data, 0x30)
    if start+size > len(data): raise ValueError('FSBL exceeds BOOT.BIN')
    fsbl = data[start:start+size]
    needle = struct.pack('<4I',0x33,0xf8006000,0x1ffff,0x80)
    search = 0
    result = []
    while True:
        offset = fsbl.find(needle,search)
        if offset < 0: break
        search = offset+4
        pos = offset; writes = []
        while pos+4 <= len(fsbl):
            op = struct.unpack_from('<I',fsbl,pos)[0];pos += 4
            if op == 0: break
            if op not in (0x22,0x33,0x42,0x52): raise ValueError('Unknown PS initialization opcode')
            n = op & 15
            args = struct.unpack_from('<'+'I'*n,fsbl,pos);pos += n*4
            if op == 0x33: writes.append(args)
        result.append((offset,writes))
    return result


def collect_version_comparison():
    name = 'ddr_lane_official_2020.2_20261028_181625'
    evidence = retain(name+'.log')
    inputs = retain(name+'_inputs.json')
    text = (ROOT/evidence['path']).read_text(encoding='utf-8-sig')
    v = words(text, 'DDR_LANE_RESULT', 69)
    if v[:3] != [0x44445231, 1, 1] or 'DDR_LANE_DONE' not in text:
        raise ValueError('Incomplete 2020.2 lane probe')
    return {'tool_version':'2020.2', 'baseboard':'official', 'ddr_mhz':533.333,
        'read_comparisons':65536, 'mismatches':sum(v[3:11]),
        'pattern_errors':v[3:11], 'byte_errors_low_to_high':v[11:15],
        'xor_mask_hex':f'{v[15]:08X}', 'even_word_errors':v[16],
        'odd_word_errors':v[17], 'first_bad_address_hex':f'{v[18]:08X}',
        'first_expected_hex':f'{v[19]:08X}', 'first_actual_hex':f'{v[20]:08X}',
        'sample_expected':v[21:37], 'sample_first':v[37:53], 'sample_second':v[53:69],
        'evidence':evidence, 'runtime_inputs_evidence':inputs,
        'runtime_inputs':json.loads((ROOT/inputs['path']).read_text(encoding='utf-8-sig'))}


def collect_debug_port_probe():
    name = 'ddr_dap_official_20261028_181909'
    evidence = retain(name+'.log')
    frames = retain(name+'_frames.csv')
    text = (ROOT/evidence['path']).read_text(encoding='utf-8-sig')
    if 'DDR_DAP_DONE comparisons=4096' not in text:
        raise ValueError('Incomplete debug-port probe')
    patterns, lanes, xor_mask = [0]*8, [0]*4, 0
    seen, failed_examples, first_pass = set(), [], {}
    readback_changed = 0
    with (ROOT/frames['path']).open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            kind, pass_ = int(row['pattern']), int(row['pass'])
            address, expected, actual = (int(row[k], 16) for k in ('address','expected','actual'))
            i, remainder = divmod(address-0x01030000, 4)
            key = kind, pass_, i
            if not (0 <= kind < 8 and pass_ in (0,1) and 0 <= i < 256 and remainder == 0) or key in seen:
                raise ValueError('Invalid/duplicate debug-port sample')
            seen.add(key)
            if kind < 6:
                known = [0, 0xffffffff, 0x55555555, 0xaaaaaaaa, 0x00ff00ff, 0xff00ff00][kind]
            elif kind == 6:
                known = address ^ 0xa53cc35a
            else:
                known = ((i+1)*0x9e3779b9) & 0xffffffff
                known = (known ^ (known << 13)) & 0xffffffff
                known ^= known >> 17
                known = (known ^ (known << 5)) & 0xffffffff
            if expected != known:
                raise ValueError('Debug-port expectation disagrees with specified pattern')
            if pass_ == 0: first_pass[kind,i] = actual
            elif first_pass[kind,i] != actual: readback_changed += 1
            diff = expected ^ actual
            if not diff: continue
            patterns[kind] += 1
            xor_mask |= diff
            for b in range(4): lanes[b] += bool(diff & (0xff << (8*b)))
            if len(failed_examples) < 8: failed_examples.append(row)
    if len(seen) != 4096:
        raise ValueError('Missing debug-port samples')
    if patterns != words(text, 'DDR_DAP_ERRORS', 8) or lanes != words(text, 'DDR_DAP_BYTE_ERRORS', 4):
        raise ValueError('Raw debug-port frames disagree with reported totals')
    logged_mask = int(re.search(r'DDR_DAP_XOR_MASK=(0x[0-9A-F]+)', text).group(1),16)
    if logged_mask != xor_mask: raise ValueError('Debug-port error masks disagree')
    return {'baseboard':'official', 'access':'APU debug memory port; ARM0 halted',
        'cpu_test_program_used':False, 'reset_or_ps_reinitialization':False,
        'inherited_ps_configuration':'2020.2 lane-probe initialization, DDR 533.333 MHz',
        'scratch_start_hex':'01030000', 'scratch_bytes':1024,
        'read_comparisons':4096, 'mismatches':sum(patterns), 'pattern_errors':patterns,
        'byte_errors_low_to_high':lanes, 'xor_mask_hex':f'{xor_mask:08X}',
        'changed_words_between_two_reads':readback_changed,
        'failed_examples':failed_examples, 'evidence':evidence, 'raw_frames':frames,
        'raw_frames_recount':'4096 unique samples; expectations and all reported totals cross-checked',
        'limit':'Does not independently validate the inherited DDR controller settings or all memory addresses'}


def collect_nanya_comparison():
    """Preserve the completed run separately from the earlier connection failure."""
    name = 'ddr_lane_official_2026.1_nanya533_20261028_194837'
    evidence, inputs, summary = [retain(name+suffix) for suffix in
                                 ('.log', '_inputs.json', '_result.json')]
    text = (ROOT/evidence['path']).read_text(encoding='utf-8-sig')
    if ('DDR_LANE_BOARD=official PROFILE=linux_platform_nanya533 '
            'ELF_FOLDER=ddr_lane_probe BOOT_MODE=0') not in text or 'DDR_LANE_DONE' not in text:
        raise ValueError('Incomplete or mismatched Nanya run')
    v = words(text, 'DDR_LANE_RESULT', 69)
    if v[:3] != [0x44445231, 1, 1] or sum(v[3:11]) != v[16]+v[17]:
        raise ValueError('Invalid Nanya result header or parity totals')
    runtime = json.loads((ROOT/inputs['path']).read_text(encoding='utf-8-sig'))
    audit = json.loads((ROOT/'report/hardware/nanya_profile_audit.json').read_text(encoding='utf-8'))
    init = ROOT/'build/work/linux_platform_nanya533/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl'
    if not (digest(init) == runtime['ps_init_sha256'] == audit['ps_init_sha256']):
        raise ValueError('Nanya initialization differs from runtime input hash')
    for relative, key in [('board/diagnostics/ddr/ddr_lane_probe.c', 'source_sha256'),
                          ('build/work/ddr_lane_probe/ddr_lane_probe.elf', 'elf_sha256'),
                          ('build/work/ddr_lane_probe/symbols.txt', 'symbols_sha256')]:
        if digest(ROOT/relative) != runtime['build_manifest'][key]:
            raise ValueError('Nanya probe input changed: '+relative)
    recorded = json.loads((ROOT/summary['path']).read_text(encoding='utf-8-sig'))
    if (recorded['mismatches'] != sum(v[3:11]) or recorded['pattern_errors'] != v[3:11]
            or recorded['byte_errors_low_to_high'] != v[11:15]
            or recorded['xor_error_mask'] != f'{v[15]:08X}'):
        raise ValueError('Nanya summary differs from raw result structure')
    training = words(text, 'DDR_LANE_TRAINING', 12)
    decoded = [{'lane':i, 'address_hex':f'{0xf80061b8+4*i:08X}',
                'raw_hex':f'{value:08X}', 'read_eye_ratio':(value>>20)&1023,
                'write_data_ratio':(value>>10)&1023, 'write_dqs_ratio':value&1023}
               for i,value in enumerate(training[5:9])]
    readback = retain('ddr_nanya533_readonly_20261028.log')
    inspection = (ROOT/readback['path']).read_text(encoding='utf-8-sig')
    if 'DDR_INSPECT_DONE' not in inspection or words(inspection, 'DDR_INSPECT_BOOT', 1) != [0]:
        raise ValueError('Incomplete Nanya read-only inspection')
    earlier = retain('ddr_lane_official_2026.1_nanya533_20261028_194127.log')
    earlier_text = (ROOT/earlier['path']).read_text(encoding='utf-8-sig')
    if 'no targets found' not in earlier_text or 'DDR_LANE_BOARD=' in earlier_text:
        raise ValueError('Earlier attempt no longer matches pre-reset connection failure')
    connection = [retain(n) for n in ('jtag_connection_20261028_query.log',
                                     'jtag_connection_20261028_1mhz.log',
                                     'jtag_connection_20261028_after_reseat.log')]
    return {'tool_version':'2026.1', 'ps_profile':'linux_platform_nanya533',
        'baseboard':'official', 'boot_mode':0, 'complete':True,
        'ddr_passed':sum(v[3:11]) == 0, 'read_comparisons':65536,
        'mismatches':sum(v[3:11]), 'pattern_errors':v[3:11],
        'byte_errors_low_to_high':v[11:15], 'xor_mask_hex':f'{v[15]:08X}',
        'even_word_errors':v[16], 'odd_word_errors':v[17],
        'first_bad_address_hex':f'{v[18]:08X}', 'first_expected_hex':f'{v[19]:08X}',
        'first_actual_hex':f'{v[20]:08X}', 'sample_expected':v[21:37],
        'sample_first':v[37:53], 'sample_second':v[53:69],
        'runtime_inputs':runtime, 'evidence':evidence, 'runtime_inputs_evidence':inputs,
        'summary_evidence':summary, 'offline_audit_evidence':'report/hardware/nanya_profile_audit.json',
        'training_raw_words':training, 'training_ratios':decoded,
        'training_decode_source':'https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/Register-reg6e_710-to-reg6e_713-Details',
        'operating_mode':words(inspection, 'DDR_INSPECT_MODE', 1)[0]&7,
        'readonly_inspection_evidence':readback,
        'earlier_connection_failure':{'evidence':earlier, 'ps_reset_or_init_executed':False,
            'ddr_test_executed':False, 'connection_evidence':connection,
            'recovery':'User confirmed power-off cable reseating and power-on; APU and xc7z020 then enumerated at 10MHz.'},
        'board_state_after_run':'JTAG boot; OCM test complete and in WFI loop. User subsequently asked to power off to inspect board markings.',
        'limits':['Timing correction did not eliminate low-byte errors; component damage remains unproven.',
                  'Training ratios and normal operating mode are not proof of a valid eye or reliable memory.',
                  'Uninitialized DDR samples in the read-only log have no expected pattern and are not additional failures.',
                  'Only counters and 16 paired sample words are retained; not all 65536 raw comparisons.',
                  'Not a whole-memory or long-duration stability test.']}


def collect_training_starts():
    """Recheck the bounded lane0 experiment from its original result structures."""
    name = 'ddr_training_20261028_203330'
    evidence, inputs, summary = [retain(name+s) for s in
                                 ('.log', '_inputs.json', '_result.json')]
    text = (ROOT/evidence['path']).read_text(encoding='utf-8-sig')
    runtime = json.loads((ROOT/inputs['path']).read_text(encoding='utf-8-sig'))
    recorded = json.loads((ROOT/summary['path']).read_text(encoding='utf-8-sig'))
    trials = [[164,0],[164,64],[164,128],[100,0],[100,64],[100,128],
              [228,0],[228,64],[228,128]]
    ids = [str(i) for i in range(9)]+['RESTORE']
    if (runtime['cases'] != trials or runtime['restore_baseline'] != [164,0]
            or not runtime['hardware_requested'] or runtime['altered_register'] != '0xF800612C'
            or runtime['storage_access'] or runtime['pl_download']
            or not recorded['complete'] or not recorded['baseline_restored']
            or 'TRAINING_EXPERIMENT_DONE cases=9 restored=1' not in text
            or 'TRAINING_BASELINE_RESTORED' not in text):
        raise ValueError('Incomplete or different training-start experiment')
    files = [('board/diagnostics/ddr/run_ddr_training_probe.tcl', runtime['tcl_sha256']),
             ('board/diagnostics/ddr/run_ddr_training_probe.ps1', runtime['wrapper_sha256']),
             ('build/work/linux_platform_nanya533/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl', runtime['ps_init_sha256'])]
    for relative,key in [('board/diagnostics/ddr/ddr_lane_probe.c','source_sha256'),
                         ('build/work/ddr_lane_probe/ddr_lane_probe.elf','elf_sha256'),
                         ('build/work/ddr_lane_probe/symbols.txt','symbols_sha256')]:
        files.append((relative,runtime['probe_manifest'][key]))
    for relative,expected_hash in files:
        if digest(ROOT/relative) != expected_hash:
            raise ValueError('Training input hash changed: '+relative)
    results = re.findall(r'TRAINING_CASE_RESULT id=(\w+) values=([^\r\n]+)',text)
    if ([key for key,_ in results] != ids or [r['id'] for r in recorded['rows']] != ids
            or re.findall(r'TRAINING_CASE_DONE id=(\w+)',text) != ids):
        raise ValueError('Missing, duplicate or reordered training cases')
    rows = []
    for (key,raw),trial,saved in zip(results,trials+[[164,0]],recorded['rows']):
        gate,write = trial
        begin = f'TRAINING_CASE_BEGIN id={key} gate={gate} write={write} init={(gate<<10)|write:08X}'
        if text.count(begin) != 1:
            raise ValueError('Unexpected training start values')
        v = [int(x) for x in raw.split()]
        if len(v) != 69 or v[:3] != [0x44445231,1,1] or sum(v[3:11]) != v[16]+v[17]:
            raise ValueError('Invalid training result structure')
        derived = {'id':key,'mismatches':sum(v[3:11]),'comparisons':65536,
                   'ddr_passed':sum(v[3:11]) == 0,'pattern_errors':v[3:11],
                   'byte_errors_low_to_high':v[11:15],'xor_mask':f'{v[15]:08X}'}
        if derived != saved:
            raise ValueError('Training summary differs from result structure')
        status = re.findall(r'TRAINING_CASE_STATUS id='+key+r' reg2c=(\d+) mode=(\d+)',text)
        if len(status) != 1: raise ValueError('Missing training status')
        reg,mode = map(int,status[0])
        derived.update(gate_start=gate,write_start=write,
                       training_raw_ratios=words(text,'TRAINING_CASE_RATIOS id='+key+' values',4),
                       reg2c_hex=f'{reg:08X}',operating_mode=mode&7,
                       first_bad_address_hex=f'{v[18]:08X}',
                       first_expected_hex=f'{v[19]:08X}',first_actual_hex=f'{v[20]:08X}')
        rows.append(derived)
    return {'complete':True,'baseboard':'official','tool_version':'2026.1',
            'ps_profile':'linux_platform_nanya533','baseline_restored':True,
            'all_nine_cases_failed':all(not r['ddr_passed'] for r in rows[:9]),
            'rows':rows,'runtime_inputs':runtime,'evidence':evidence,
            'runtime_inputs_evidence':inputs,'summary_evidence':summary,
            'offline_validation_evidence':[retain('ddr_training_20261028_203305'+s)
                                           for s in ('.log','_inputs.json')],
            'connection_evidence':retain('jtag_after_dc_check_20261028.log'),
            'board_state_after_run':'Baseline Nanya533 initialization restored; ARM0 OCM test finished in WFI loop.',
            'limits':['Exploratory starting points, not PCB delay/PVT bounds or a full margin scan.',
                      'Counters and 16 paired samples retained per run; not all raw comparisons.',
                      'Error count variation does not establish improved or worse stability.',
                      'Does not identify a damaged component or rule out every configuration issue.']}


def collect_factory_boot():
    evidence = retain('factory_sd_failure_evidence_20261028_184414.log')
    stopped = retain('factory_sd_stop_20261028_184157.log')
    disassembly = [retain(n) for n in (
        'factory_fsbl_main_disassembly.txt', 'factory_fsbl_ddrcheck_fallback_disassembly.txt')]
    uart = [retain('uart_factory_sd_20261028_182931'+suffix) for suffix in ('.bin','.log','.json')]
    text = (ROOT/evidence['path']).read_text(encoding='utf-8-sig')
    regs = (ROOT/stopped['path']).read_text(encoding='utf-8-sig')
    if 'FACTORY_BOOT_INSPECT_DONE' not in text or 'FACTORY_STOP_DONE' not in regs:
        raise ValueError('Incomplete factory boot observations')
    boot_mode = words(text, 'FACTORY_BOOT_BOOT_MODE', 1)[0]
    pc = int(re.search(r'\bpc:\s*([0-9a-f]+)', regs).group(1),16)
    lr = int(re.search(r'\blr:\s*([0-9a-f]+)', regs).group(1),16)
    if (boot_mode,pc,lr) != (5,0x18ac,0xe488):
        raise ValueError('Factory boot stop differs from reviewed failure path')
    boot_path = ROOT/'reference/vendor_factory/boot/boot.bin'
    data = boot_path.read_bytes()
    offset, length = struct.unpack_from('<II',data,0x30)
    fsbl = data[offset:offset+length]
    checked = []
    for marker,address,count in (
        ('OCM_FSBL_PREFIX',0,64), ('FSBL_DDR_CHECK_CODE',0xe31c,12),
        ('FSBL_FAILURE_CALL_CODE',0xe468,8), ('FSBL_FAILURE_LOOP_CODE',0x18ac,1)):
        got = words(text,'FACTORY_BOOT_'+marker,count)
        expected = list(struct.unpack_from('<'+'I'*count,fsbl,address))
        if got != expected: raise ValueError('Running OCM code differs from factory image: '+marker)
        checked.append({'address_hex':f'{address:08X}', 'word_count':count, 'match':True})
    expected = 0xaa55aa55
    actual = [words(text,'FACTORY_BOOT_FSBL_DDR_CHECK_WORD'+str(i),1)[0] for i in (1,2)]
    if actual != [expected,0xaa55aaff]: raise ValueError('Factory DDR samples differ from reviewed evidence')
    return {'boot_mode':boot_mode, 'image_boot_bin_sha256':digest(boot_path),
        'image_evidence':'report/hardware/factory_sd_evidence.json',
        'user_confirmed_baseboard':'official', 'user_confirmed_uart_selection':'PS after initial PL selection',
        'ocm_code_matches_factory_image':checked, 'halt_pc_hex':f'{pc:08X}', 'halt_lr_hex':f'{lr:08X}',
        'ddr_sanity_check':{'addresses_hex':['00100000','00200000'],
            'expected_hex':f'{expected:08X}', 'actual_hex':[f'{x:08X}' for x in actual],
            'xor_difference_hex':[f'{x^expected:08X}' for x in actual]},
        'control_flow':'DDR compare at 0xE334 or 0xE348 branches to 0xE468; 0xE484 calls 0x18AC self-loop, matching LR=0xE488.',
        'conclusion':'Unmodified factory FSBL entered its DDR sanity-check failure loop before U-Boot.',
        'uboot_prefix_at_04000000':words(text,'FACTORY_BOOT_DDR_UBOOT_PREFIX',64),
        'uart':{'capture_evidence':uart, 'raw_hex':(ROOT/uart[0]['path']).read_bytes().hex(),
            'limits':'One ten-minute receive-only capture spans the initial PL UART selection and subsequent PS selection; no readable boot output.'},
        'evidence':evidence, 'halt_registers':stopped, 'disassembly':disassembly,
        'board_state_after_observation':'ARM0 halted in the factory failure loop; SD boot mode; no debugger reset/init/download during factory boot.',
        'limits':['The failure does not identify a particular damaged DDR device or rule out incompatible hardware configuration.',
                  'Only the listed OCM blocks were compared, not the whole running FSBL image.']}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    runs = []
    for board, mhz, training, name in [
        ('custom',533.333,'enabled','boot_probe_533_emmc_pass_ddr_fail.txt'),
        ('custom',333.333,'enabled','boot_probe_333_emmc_pass_ddr_fail.txt'),
        ('official',533.333,'enabled','probe_official_linux_platform_20261028_171410_jtag.log'),
        ('official',333.333,'disabled','probe_official_linux_platform333_nowl_20261028_171727_jtag.log')]:
        evidence = retain(name)
        text = (ROOT/evidence['path']).read_text(encoding='utf-8-sig')
        if board == 'official':
            v = words(text,'BOOT_PROBE_RESULT',31)
            if v[:4] != [0x42505431,2,5,1] or v[5] != 0: raise ValueError('Unexpected boot diagnostic result')
            errors,regions,sectors,cid,crc,reset,switches = v[4],v[15:19],v[6],v[8:12],v[12],v[13],v[14]
        else:
            errors = int(re.search(r'four 64KiB regions across 1GiB: errors=(\d+)',text).group(1))
            regions = [int(x) for x in re.findall(r'DDR_REGION [0-9A-F]+ errors=(\d+)',text)]
            sectors = int(re.search(r'eMMC type=2 sectors=(\d+)',text).group(1))
            cid = [int(x,16) for x in re.search(r'CID=([^\r\n]+)',text).group(1).split()]
            crc = int(re.search(r'CRC32=([0-9A-F]+)',text).group(1),16)
            reset = int(re.search(r'RESET_FUNC=(\d+)',text).group(1))
            switches = int(re.search(r'blocked_switches=(\d+)',text).group(1))
            if 'BOOT_PROBE_DONE result=1 phase=5' not in text: raise ValueError('Incomplete custom probe')
        if len(regions)!=4 or sum(regions)!=errors: raise ValueError('DDR totals disagree')
        runs.append({'baseboard':board,'ddr_mhz':mhz,'write_level_training':training,
            'ddr_errors':errors,'region_errors':regions,'emmc_sectors':sectors,'sector_bytes':512,
            'cid_words_hex':[f'{x:08X}' for x in cid],'sector0_crc32':f'{crc:08X}',
            'reset_function':reset,'blocked_switches':switches,'evidence':evidence})
    lane_name = 'ddr_lane_official_533_20261028_173332.log'
    lane_evidence = retain(lane_name)
    lane_text = (ROOT/lane_evidence['path']).read_text(encoding='utf-8-sig')
    v = words(lane_text,'DDR_LANE_RESULT',69)
    if v[:3] != [0x44445231,1,1] or 'DDR_LANE_DONE' not in lane_text: raise ValueError('Incomplete lane probe')
    lane = {'baseboard':'official','ddr_mhz':533.333,'read_comparisons':65536,
        'pattern_errors':v[3:11],'byte_errors_low_to_high':v[11:15],'xor_mask_hex':f'{v[15]:08X}',
        'even_word_errors':v[16],'odd_word_errors':v[17],
        'first_bad_address_hex':f'{v[18]:08X}','first_expected_hex':f'{v[19]:08X}',
        'first_actual_hex':f'{v[20]:08X}','sample_expected':v[21:37],
        'sample_first':v[37:53],'sample_second':v[53:69],
        'evidence':lane_evidence,'build_manifest':json.loads((ROOT/'build/work/ddr_lane_probe/manifest.json').read_text())}
    retained_readback = retain('official_ddr_readback_333_nowl.log')
    current = next((ROOT/'build/work/linux_platform').rglob('ps7_init.tcl'))
    example = next((ROOT/'reference/vendor_pynq').rglob('ps7_init.tcl'))
    reference = ddr_writes(current.read_text())
    audit = {'silicon_revision':3,'mask_write_count':len(reference),
        'generated_init_sha256':digest(current),'pynq_example_init_sha256':digest(example),
        'example_ddr_writes_match':ddr_writes(example.read_text()) == reference,'boot_images':[]}
    for p in (ROOT/'reference/vendor_factory/boot/boot.bin',ROOT/'reference/vendor_pynq/boot/boot.bin'):
        matches = [offset for offset,writes_ in boot_ddr_arrays(p) if writes_ == reference]
        audit['boot_images'].append({'path':p.relative_to(ROOT).as_posix(),'sha256':digest(p),
            'matching_ddr_array_fsbl_offsets_hex':[f'{n:X}' for n in matches]})
        if not matches: raise ValueError('No DDR table match in '+str(p))
    result = {'recorded_date':'2026-10-28','boot_probe_runs':runs,'lane_probe':lane,
        'lane_probe_2020_2':collect_version_comparison(),
        'lane_probe_nanya533':collect_nanya_comparison(),
        'training_start_probe':collect_training_starts(),
        'debug_port_probe':collect_debug_port_probe(),
        'factory_sd_boot':collect_factory_boot(),
        'readback_evidence':retained_readback,'vendor_ddr_audit':audit,
        'provenance_limit':'Older boot-probe logs did not bind runtime ELF/init hashes; do not assign current ELF hashes retrospectively.',
        'storage_content_writes':False,'pl_downloaded':False,'linux_booted':False,
        'limits':['four 64KiB regions are not a full 1GiB qualification',
                  'lane probe uses different patterns/region/access cadence; error counts are not a performance comparison',
                  'Windows host Python checks do not validate ARM/PYNQ hardware behavior']}
    target = ROOT/'report/hardware/hardware_evidence.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Collected',len(runs),'boot probes; lane errors',sum(v[3:11]),';',target)


if __name__ == '__main__': main()
