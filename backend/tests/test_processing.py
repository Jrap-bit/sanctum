from datetime import timedelta
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select, delete
from app.workers import extraction as worker
from app.db.models import ExtractionJob, ExtractedPage, PatientAccess, now
from app.adapters.crypto import decrypt
from test_patients import setup, create, path, sign_in
from test_documents import upload, pdf


def draft_result(raw, mime, number):
    return {'rawText': f'Synthetic page {number}', 'method': 'embedded_text'}


def prepare(c):
    p=create(c);d=upload(c,p).json();base=path(p)+'/documents/'+d['id']
    return p,d,base


def test_queue_process_encryption_and_access(setup):
    c,factory,_=setup;p,d,base=prepare(c)
    assert c.post(base+'/process',json={}).status_code==202
    assert c.post(base+'/process',json={}).status_code==409
    assert c.get(base+'/pages').status_code==409
    assert worker.run_once(factory,draft_result)
    assert c.get(base+'/pages').json()['pages'][0]['rawText']=='Synthetic page 1'
    with factory() as db:
        page=db.get(ExtractedPage,(d['id'],1));assert b'Synthetic page' not in page.payload
        assert decrypt(page.payload,f"document-page:{p['id']}:{d['id']}:1")['method']=='embedded_text'
    result=c.get(path(p)+'/documents').json()['items'][0]
    assert result['jobState']=='completed' and result['progress']==100
    sign_in(c,'bob');assert c.get(base+'/pages').status_code==404
    assert c.post(base+'/process',json={}).status_code==404
    assert c.get('/api/v1/admin/operations/jobs').status_code==403
    sign_in(c,'admin');assert c.get('/api/v1/admin/operations/jobs').json()['items'][0]['state']=='completed'
    assert c.get(base+'/pages').status_code==403


def test_cancel_retry_and_stale_result(setup):
    c,factory,_=setup;p,d,base=prepare(c)
    c.post(base+'/process',json={})
    def cancel_midway(*args):
        assert c.post(base+'/cancel',json={}).status_code==200
        return draft_result(*args)
    worker.run_once(factory,cancel_midway)
    with factory() as db:
        assert db.scalar(select(ExtractionJob)).state=='cancelled'
        assert db.scalar(select(ExtractedPage)) is None
    assert c.get(base+'/pages').status_code==409
    assert c.post(base+'/retry',json={}).status_code==202
    worker.run_once(factory,draft_result)
    assert c.get(base+'/pages').status_code==200


def test_failed_then_retry(setup):
    c,factory,_=setup;p,d,base=prepare(c);c.post(base+'/process',json={})
    def fail(*args): raise ValueError('ocr_unavailable')
    worker.run_once(factory,fail)
    data=c.get(path(p)+'/documents').json()['items'][0]
    assert data['jobState']=='failed' and 'Tesseract' in data['processingMessage']
    c.post(base+'/retry',json={});worker.run_once(factory,draft_result)
    assert c.get(base+'/pages').status_code==200


def test_stale_lease_recovered_and_revocation_cancels(setup):
    c,factory,_=setup;p,d,base=prepare(c);c.post(base+'/process',json={})
    old=worker.claim(factory)
    with factory() as db:
        job=db.scalar(select(ExtractionJob));job.lease_until=now()-timedelta(seconds=1);db.commit()
    new=worker.claim(factory);assert old[1]!=new[1]
    with factory() as db:
        assert worker.current_job(db,old[0],old[1]) is None
        job=db.scalar(select(ExtractionJob));job.lease_until=now()-timedelta(seconds=1)
        db.execute(delete(PatientAccess).where(PatientAccess.patient_id==p['id']));db.commit()
    worker.run_once(factory,draft_result)
    with factory() as db:assert db.scalar(select(ExtractionJob)).state=='cancelled'


def test_revocation_during_processing_discards_output(setup):
    c,factory,_=setup;p,d,base=prepare(c);c.post(base+'/process',json={})
    def revoke(*args):
        with factory() as db:
            db.execute(delete(PatientAccess).where(PatientAccess.patient_id==p['id']));db.commit()
        return draft_result(*args)
    worker.run_once(factory,revoke)
    with factory() as db:
        assert db.scalar(select(ExtractedPage)) is None
        assert db.scalar(select(ExtractionJob)).state=='cancelled'


def text_pdf():
    writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 18 Tf 50 700 Td (Synthetic patient record for extraction testing.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);return out.getvalue()


def test_real_pdf_text_extraction():
    result=worker.extract_one(text_pdf(),'application/pdf',1)
    assert 'Synthetic patient record' in result['rawText']
    assert result['method']=='embedded_text'


def test_real_image_and_scanned_pdf_ocr():
    image=Image.new('RGB',(1200,300),'white')
    draw=ImageDraw.Draw(image);font=ImageFont.load_default(size=44)
    draw.text((30,60),'SYNTHETIC RECORD 12345',font=font,fill='black')
    for mime,kind in [('image/png','PNG'),('application/pdf','PDF')]:
        out=BytesIO();image.save(out,format=kind)
        result=worker.extract_one(out.getvalue(),mime,1)
        assert 'SYNTHETIC RECORD 12345' in result['rawText']
        assert result['method']=='ocr'


def test_real_mixed_pdf_preserves_page_order_and_draft_state(setup):
    from pypdf import PdfReader
    c,factory,_=setup;p=create(c)
    image=Image.new('RGB',(1200,300),'white');draw=ImageDraw.Draw(image)
    draw.text((30,60),'SECOND PAGE SCANNED 67890',font=ImageFont.load_default(size=44),fill='black')
    scan=BytesIO();image.save(scan,format='PDF')
    writer=PdfWriter();writer.append(PdfReader(BytesIO(text_pdf())));writer.append(PdfReader(BytesIO(scan.getvalue())))
    out=BytesIO();writer.write(out)
    response=upload(c,p,raw=out.getvalue());assert response.status_code==201,response.text
    base=path(p)+'/documents/'+response.json()['id'];c.post(base+'/process',json={})
    worker.run_once(factory)
    pages=c.get(base+'/pages').json()['pages']
    assert [p['pageNumber'] for p in pages]==[1,2]
    assert [p['method'] for p in pages]==['embedded_text','ocr']
    assert 'SECOND PAGE SCANNED 67890' in pages[1]['rawText']
    assert all(p['reviewState']=='unreviewed' for p in pages)


def test_blank_page_is_flagged_not_invented():
    result=worker.extract_one(pdf(),'application/pdf',1)
    assert result['rawText']=='' and result['unreadable'] is True
