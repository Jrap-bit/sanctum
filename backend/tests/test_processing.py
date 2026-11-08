from datetime import timedelta
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select, delete

from app.core.cache import get_redis
from app.db.models import AuditEvent, ExtractedPage, ExtractionJob, PatientAccess, StoredDocument, User, now
from app.services.raw_text import get_raw
from app.workers import extraction as worker
from test_patients import setup, create, path, sign_in
from test_documents import upload, pdf


def draft_result(raw, mime, number):
    return {'rawText': f'Synthetic page {number}', 'method': 'embedded_text'}


def prepare(c, pages=1):
    p = create(c)
    if pages > 1:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        stream = BytesIO()
        writer.write(stream)
        raw = stream.getvalue()
    else:
        raw = None
    d = upload(c, p, raw=raw).json()
    base = path(p) + '/documents/' + d['id']
    return p, d, base


def test_queue_process_encryption_and_access(setup):
    c, factory, _ = setup
    p, d, base = prepare(c)
    assert c.post(base + '/process', json={}).status_code == 202
    assert c.post(base + '/process', json={}).status_code == 409
    assert c.get(base + '/pages').status_code == 409
    assert worker.run_once(factory, draft_result)

    # Raw text is served from Redis
    assert c.get(base + '/pages').json()['pages'][0]['rawText'] == 'Synthetic page 1'

    # ExtractedPage rows exist ONLY once a person has saved a review
    with factory() as db:
        assert db.get(ExtractedPage, (d['id'], 1)) is None

    # Raw text in Redis is ciphertext
    raw_bytes = get_redis().get(f"ocr:{d['id']}:1")
    assert raw_bytes is not None
    assert b'Synthetic page' not in raw_bytes
    assert raw_bytes.startswith(b'SNCTM1')

    with factory() as db:
        doc_row = db.get(StoredDocument, d['id'])
        decrypted_raw = get_raw(doc_row, 1)
        assert decrypted_raw['rawText'] == 'Synthetic page 1'

    result = c.get(path(p) + '/documents').json()['items'][0]
    assert result['jobState'] == 'completed' and result['progress'] == 100
    sign_in(c, 'bob')
    assert c.get(base + '/pages').status_code == 404
    assert c.post(base + '/process', json={}).status_code == 404
    assert c.get('/api/v1/admin/operations/jobs').status_code == 403
    sign_in(c, 'admin')
    assert c.get('/api/v1/admin/operations/jobs').json()['items'][0]['state'] == 'completed'
    assert c.get(base + '/pages').status_code == 403


def test_cancel_retry_and_stale_result(setup):
    c, factory, _ = setup
    p, d, base = prepare(c)
    c.post(base + '/process', json={})

    def cancel_midway(*args):
        assert c.post(base + '/cancel', json={}).status_code == 200
        return draft_result(*args)

    worker.run_once(factory, cancel_midway)
    with factory() as db:
        assert db.scalar(select(ExtractionJob)).state == 'cancelled'
        assert db.scalar(select(ExtractedPage)) is None
    assert c.get(base + '/pages').status_code == 409
    assert c.post(base + '/retry', json={}).status_code == 202
    worker.run_once(factory, draft_result)
    assert c.get(base + '/pages').status_code == 200


def test_retry_and_cancel_do_not_delete_reviews(setup):
    c, factory, _ = setup
    p, d, base = prepare(c, pages=2)
    c.post(base + '/process', json={})
    worker.run_once(factory, draft_result)
    assert c.get(base + '/pages').status_code == 200

    # Human reviews page 1
    review_resp = c.patch(base + '/pages/1', json={
        'correctedText': 'Human corrected page 1',
        'included': True,
        'unreadable': False,
        'expectedVersion': 1,
    })
    assert review_resp.status_code == 200
    with factory() as db:
        assert db.get(ExtractedPage, (d['id'], 1)) is not None

    # Simulate failure to allow retry
    with factory() as db:
        job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == d['id']))
        job.state = 'failed'
        db.commit()

    # Retry extraction job sets state to queued
    assert c.post(base + '/retry', json={}).status_code == 202
    with factory() as db:
        assert db.get(ExtractedPage, (d['id'], 1)) is not None

    # Cancel while queued
    assert c.post(base + '/cancel', json={}).status_code == 200
    with factory() as db:
        assert db.get(ExtractedPage, (d['id'], 1)) is not None
        assert db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == d['id'])).state == 'cancelled'

    # Retry again and run worker
    assert c.post(base + '/retry', json={}).status_code == 202
    worker.run_once(factory, draft_result)
    with factory() as db:
        row = db.get(ExtractedPage, (d['id'], 1))
        assert row is not None
        assert row.version == 2


def test_expired_draft_requeues_and_preserves_reviews(setup):
    c, factory, _ = setup
    p, d, base = prepare(c, pages=2)
    c.post(base + '/process', json={})
    worker.run_once(factory, draft_result)

    # Save review for page 1
    c.patch(base + '/pages/1', json={
        'correctedText': 'Saved review 1',
        'included': True,
        'unreadable': False,
        'expectedVersion': 1,
    })

    # Expire Redis raw text key for page 2 (unreviewed page)
    get_redis().delete(f"ocr:{d['id']}:2")

    # Read pages: draft expired, user has documents:write -> requeues job
    resp = c.get(base + '/pages')
    assert resp.status_code == 409
    assert 'The draft text has expired and is being extracted again. Try again shortly.' in resp.json()['message']

    with factory() as db:
        job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == d['id']))
        assert job.state == 'queued'
        assert job.attempts == 0
        assert job.run_id is None
        assert job.lease_until is None
        # Reviewed page 1 remains
        assert db.get(ExtractedPage, (d['id'], 1)) is not None
        # Audit event recorded
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'document.extraction_requeued'))

    # Delete redis for page 2 again and test read with user lacking write perm
    get_redis().delete(f"ocr:{d['id']}:2")
    with factory() as db:
        job = db.scalar(select(ExtractionJob).where(ExtractionJob.document_id == d['id']))
        job.state = 'completed'
        bob = db.scalar(select(User).where(User.username == 'bob'))
        bob.capabilities = ['clinical:read']
        db.add(PatientAccess(patient_id=p['id'], user_id=bob.id))
        db.commit()
    sign_in(c, 'bob')
    bob_resp = c.get(base + '/pages')
    assert bob_resp.status_code == 409
    assert 'The draft text has expired. Ask someone with document access to extract it again.' in bob_resp.json()['message']


def test_withdraw_behaviour(setup):
    c, factory, _ = setup
    p, d, base = prepare(c, pages=1)
    c.post(base + '/process', json={})
    worker.run_once(factory, draft_result)

    # Withdraw document
    resp = c.post(base + '/withdraw', json={})
    assert resp.status_code == 200
    doc_data = resp.json()
    assert doc_data['reviewState'] == 'withdrawn'
    assert 'withdraw' not in doc_data['allowedActions']

    # Redis raw text deleted
    assert get_redis().get(f"ocr:{d['id']}:1") is None

    with factory() as db:
        doc = db.get(StoredDocument, d['id'])
        assert doc.withdrawn_at is not None
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'document.withdrawn', AuditEvent.target_id == d['id']))

    # Withdrawn document cannot be processed, reviewed, or confirmed (409)
    assert c.post(base + '/process', json={}).status_code == 409
    assert c.post(base + '/retry', json={}).status_code == 409
    assert c.post(base + '/cancel', json={}).status_code == 409
    assert c.patch(base + '/pages/1', json={'correctedText': 't', 'included': True, 'unreadable': False, 'expectedVersion': 1}).status_code == 409
    assert c.post(base + '/confirm', json={'expectedVersion': 1, 'groups': [{'pageNumbers': [1], 'dateStatus': 'unknown'}]}).status_code == 409

    # Original stays downloadable
    dl = c.get(base + '/original')
    assert dl.status_code == 200


def test_failed_then_retry(setup):
    c, factory, _ = setup
    p, d, base = prepare(c)
    c.post(base + '/process', json={})

    def fail(*args):
        raise ValueError('ocr_unavailable')

    worker.run_once(factory, fail)
    data = c.get(path(p) + '/documents').json()['items'][0]
    assert data['jobState'] == 'failed' and 'Tesseract' in data['processingMessage']
    c.post(base + '/retry', json={})
    worker.run_once(factory, draft_result)
    assert c.get(base + '/pages').status_code == 200


def test_stale_lease_recovered_and_revocation_cancels(setup):
    c, factory, _ = setup
    p, d, base = prepare(c)
    c.post(base + '/process', json={})
    old = worker.claim(factory)
    with factory() as db:
        job = db.scalar(select(ExtractionJob))
        job.lease_until = now() - timedelta(seconds=1)
        db.commit()
    new = worker.claim(factory)
    assert old[1] != new[1]
    with factory() as db:
        assert worker.current_job(db, old[0], old[1]) is None
        job = db.scalar(select(ExtractionJob))
        job.lease_until = now() - timedelta(seconds=1)
        db.execute(delete(PatientAccess).where(PatientAccess.patient_id == p['id']))
        db.commit()
    worker.run_once(factory, draft_result)
    with factory() as db:
        assert db.scalar(select(ExtractionJob)).state == 'cancelled'


def test_revocation_during_processing_cancels(setup):
    c, factory, _ = setup
    p, d, base = prepare(c)
    c.post(base + '/process', json={})

    def revoke(*args):
        with factory() as db:
            db.execute(delete(PatientAccess).where(PatientAccess.patient_id == p['id']))
            db.commit()
        return draft_result(*args)

    worker.run_once(factory, revoke)
    with factory() as db:
        assert db.scalar(select(ExtractionJob)).state == 'cancelled'


def text_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 18 Tf 50 700 Td (Synthetic patient record for extraction testing.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_real_pdf_text_extraction():
    result = worker.extract_one(text_pdf(), 'application/pdf', 1)
    assert 'Synthetic patient record' in result['rawText']
    assert result['method'] == 'embedded_text'


def test_real_image_and_scanned_pdf_ocr():
    image = Image.new('RGB', (1200, 300), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=44)
    draw.text((30, 60), 'SYNTHETIC RECORD 12345', font=font, fill='black')
    for mime, kind in [('image/png', 'PNG'), ('application/pdf', 'PDF')]:
        out = BytesIO()
        image.save(out, format=kind)
        result = worker.extract_one(out.getvalue(), mime, 1)
        assert 'SYNTHETIC RECORD 12345' in result['rawText']
        assert result['method'] == 'ocr'


def test_real_mixed_pdf_preserves_page_order_and_draft_state(setup):
    c, factory, _ = setup
    p = create(c)
    image = Image.new('RGB', (1200, 300), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((30, 60), 'SECOND PAGE SCANNED 67890', font=ImageFont.load_default(size=44), fill='black')
    scan = BytesIO()
    image.save(scan, format='PDF')
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(text_pdf())))
    writer.append(PdfReader(BytesIO(scan.getvalue())))
    out = BytesIO()
    writer.write(out)
    response = upload(c, p, raw=out.getvalue())
    assert response.status_code == 201, response.text
    base = path(p) + '/documents/' + response.json()['id']
    c.post(base + '/process', json={})
    worker.run_once(factory)
    pages = c.get(base + '/pages').json()['pages']
    assert [p['pageNumber'] for p in pages] == [1, 2]
    with factory() as db:
        doc_row = db.get(StoredDocument, response.json()['id'])
        assert [get_raw(doc_row, 1)['method'], get_raw(doc_row, 2)['method']] == ['embedded_text', 'ocr']
    assert 'SECOND PAGE SCANNED 67890' in pages[1]['rawText']
    assert all(p['reviewState'] == 'unreviewed' for p in pages)


def test_blank_page_is_flagged_not_invented():
    result = worker.extract_one(pdf(), 'application/pdf', 1)
    assert result['rawText'] == '' and result['unreadable'] is True
