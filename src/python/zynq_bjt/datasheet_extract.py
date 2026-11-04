"""Offline PDF table extraction with page provenance and explicit review flags."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

VERSION = 4
FIELDS = ('parameter','symbol','conditions','min','typ','max','value','unit')
HEADERS = {'parameter':('parameter','characteristic','rating','参数','项目'),
           'symbol':('symbol','符号'), 'conditions':('test conditions','conditions','测试条件','条件'),
           'min':('min','minimum','最小'), 'typ':('typ','typical','典型'),
           'max':('max','maximum','最大'), 'value':('value','数值','值'), 'unit':('unit','单位')}


def clean(value):
    # Preserve signs, decimal points, units and conditions. Do not infer missing
    # glyphs (e.g. µ / degree symbols) or silently select one model in a family.
    value=''.join('�' if ord(c)<32 and c not in '\t\r\n' else c for c in (value or ''))
    return re.sub(r'\s+', ' ', value).strip()


def header(value):
    value=clean(value).lower().strip('.: ')
    return next((key for key,names in HEADERS.items() if value in names),None)


def watermark_spans(page):
    """Recognize the distributor's rotated stamp, not arbitrary Chinese text."""
    found=[]
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            text=''.join(s['text'] for s in line['spans']).strip()
            if abs(line['dir'][1])>.1 and text and not text.replace('芯查查',''):
                found.append(dict(text=text,bbox=list(line['bbox']),direction=list(line['dir'])))
    return found


def filtered_table_rows(table, stamps):
    # PyMuPDF's table extractor uses its page-local character list. The worker
    # is isolated from GUI rendering; restore it even when extraction fails.
    # Keep the original rows separately, including the excluded stamp text.
    import pymupdf.table as tables
    original=tables.CHARS
    def stamp_char(char):
        if char['upright'] or char['text'] not in '芯查':return False
        x=(char['x0']+char['x1'])/2;y=(char['top']+char['bottom'])/2
        return any(s['bbox'][0]<=x<=s['bbox'][2] and s['bbox'][1]<=y<=s['bbox'][3] for s in stamps)
    try:
        tables.CHARS=[c for c in original if not stamp_char(c)]
        return table.extract()
    finally:tables.CHARS=original


def apply_reviewed_fields(result):
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))/'data'
    path=base/'datasheets'/'parameter_reviews'/(result['sha256']+'.json')
    if not path.exists():return
    review=json.loads(path.read_text(encoding='utf8'))
    if review.get('source_sha256')!=result['sha256']:return
    lookup={(r['page'],r['table'],r['row']):r for r in review['rows']}
    for row in result['parameters']:
        checked=lookup.get((row['page'],row['table'],row['row']))
        if not checked or any(row.get(k,'')!=v for k,v in checked['expected_limits'].items()):continue
        row['extracted_candidate']={k:row[k] for k in FIELDS+('review_notes','uncertain_fields')}
        row.update(checked['fields']);row.update(review_status='已对照原页',review_notes=[],uncertain_fields=[])
        row['review_evidence']=dict(source_sha256=review['source_sha256'],page=row['page'],reviewed_at=review['reviewed_at'])
    result['review_required']=any(r['review_status']!='已对照原页' for r in result['parameters'])
    result['reviewed_parameter_count']=sum(r['review_status']=='已对照原页' for r in result['parameters'])
    if result['parameters'] and not result['review_required']:result['status']='recognized_parameters_checked'
    result['coverage']='Recognized parameter rows only; original page text and other tables retained'


def extract(path):
    import pymupdf
    path=Path(path).resolve()
    result=dict(schema_version=VERSION,source_file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                parameters=[],pages=[],warnings=[],review_required=True)
    with pymupdf.open(path) as document:
        if document.is_encrypted: raise ValueError('加密PDF请先解锁')
        for page in document:
            page_text=page.get_text(sort=True)
            # MuPDF's table text can DROP undefined glyphs, including minus
            # signs. Trace them geometrically so the remaining positive-looking
            # candidate cannot silently masquerade as a complete condition.
            missing=[pymupdf.Rect(char[3]) for span in page.get_texttrace() for char in span['chars']
                     if char[0]==0xfffd or (char[0]<32 and char[0] not in (9,10,13))]
            stamps=watermark_spans(page)
            page_record=dict(page=page.number+1,text=page_text,tables=[],excluded_watermarks=stamps)
            result['pages'].append(page_record)
            columns=None; previous={}; width=0
            for table_number,table in enumerate(page.find_tables().tables):
                original_rows=table.extract()
                rows=filtered_table_rows(table,stamps) if stamps else original_rows
                page_record['tables'].append(dict(bbox=list(table.bbox),rows=original_rows,filtered_rows=rows))
                for row_number,row in enumerate(rows):
                    mapping={i:header(cell) for i,cell in enumerate(row) if header(cell)}
                    if len(mapping)>=3 and set(mapping.values()) & {'min','max','value'}:
                        columns=mapping; width=len(row); previous={};continue
                    if not columns or len(row)!=width:continue
                    cells={columns[i]:clean(cell) for i,cell in enumerate(row) if i in columns}
                    if not any(re.search(r'\d',cells.get(k,'')) for k in ('min','typ','max','value')):continue
                    flags=[]
                    uncertain=[]
                    for i,key in columns.items():
                        box=table.rows[row_number].cells[i]
                        if box and any(pymupdf.Rect(box).intersects(rect) for rect in missing):
                            uncertain.append(key)
                            if cells.get(key):cells[key]+=' [缺字待核对]'
                    if uncertain:flags.append('缺失字形：'+', '.join(uncertain)+'；符号/正负号可能不完整')
                    # Only inherit merged identity/unit cells, never numerical limits.
                    for i,key in columns.items():
                        if row[i] is None and key in ('parameter','symbol','unit','conditions') and previous.get(key):
                            cells[key]=previous[key];flags.append('合并单元格继承，核对适用型号/条件')
                    if not (cells.get('parameter') or cells.get('symbol')):continue
                    if any(ord(c)<32 and c not in '\r\n\t' or c=='\ufffd' for cell in row if cell for c in cell):
                        flags.append('PDF字形编码异常，需对照原页')
                    if any('\n' in (row[i] or '').strip() for i,key in columns.items() if key in ('min','typ','max','value')):
                        flags.append('同格多值，保留原顺序，未自动分配型号')
                    unmapped=[clean(cell) for i,cell in enumerate(row) if i not in columns and clean(cell)]
                    record={key:cells.get(key,'') for key in FIELDS}
                    record.update(page=page.number+1,table=table_number+1,row=row_number+1,
                                  raw_cells=original_rows[row_number],filtered_cells=row,unmapped_cells=unmapped,review_notes=list(dict.fromkeys(flags)),
                                  uncertain_fields=uncertain,
                                  page_context=page_text,review_status='待核对')
                    result['parameters'].append(record);previous=cells
            if not page_text.strip(): result['warnings'].append('第{}页无文本层，需OCR/人工核对，未猜测参数'.format(page.number+1))
        result['page_count']=len(document)
    if not result['parameters']:result['warnings'].append('未识别到参数表；保留各页原文，请核对或OCR后重新导入')
    result['status']='extracted_for_review' if result['parameters'] else 'needs_ocr_or_review'
    apply_reviewed_fields(result)
    return result


def cached_extract(path, cache):
    path=Path(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    target=cache/(digest+'.json')
    if target.exists():
        result=json.loads(target.read_text(encoding='utf-8'))
        if result.get('schema_version')==VERSION:
            result['source_file']=str(path.resolve());return result,target
    result=extract(path)
    temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.partial')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
    return result,target


def export_csv(result,path):
    fields=('page',)+FIELDS+('review_status','review_notes','source_sha256')
    with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in result['parameters']:
            values={k:row.get(k,'') for k in fields}
            values.update(review_notes='；'.join(row['review_notes']),source_sha256=result['sha256'])
            writer.writerow(values)


def extract_isolated(path,cache,cancel=None):
    """Keep MuPDF table extraction out of the GUI's rendering process."""
    import os
    import subprocess
    import sys
    import time
    if cancel is not None and cancel.is_set():raise InterruptedError('提取已取消')
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    target=Path(cache)/(digest+'.json')
    if target.exists():
        result=json.loads(target.read_text(encoding='utf-8'))
        if result.get('schema_version')==VERSION:return result,target
    command=([sys.executable,'--extract-datasheet',str(path),'--extract-output',str(cache)] if getattr(sys,'frozen',False)
             else [sys.executable,str(Path(__file__).resolve()),str(path),'--out',str(cache)])
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    deadline=time.monotonic()+180
    try:
        while True:
            if cancel is not None and cancel.is_set():raise InterruptedError('提取已取消')
            if time.monotonic()>deadline:raise TimeoutError('手册提取超时')
            try:stdout,stderr=process.communicate(timeout=.2);break
            except subprocess.TimeoutExpired:continue
        if process.returncode:raise RuntimeError(stderr.decode('utf-8',errors='replace')[-1500:])
    finally:
        if process.poll() is None:
            process.kill();process.communicate(timeout=3)
    return json.loads(target.read_text(encoding='utf-8')),target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    result,target=cached_extract(args.pdf,args.out)
    export_csv(result,target.with_suffix('.csv'))
    print(json.dumps(dict(json=str(target),parameters=len(result['parameters']),status=result['status']),ensure_ascii=False))


if __name__=='__main__':main()
