from io import BytesIO
from uuid import uuid4
import pytest
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from app.services import documents
from app.adapters.crypto import decrypt
from app.db.models import StoredDocument, PatientAccess, AuditEvent, PatientEvent
from test_patients import setup, create, path, sign_in


def pdf(encrypted=False):
    stream = BytesIO(); writer = PdfWriter(); writer.add_blank_page(width=72, height=72)
    if encrypted: writer.encrypt('synthetic-test-password')
    writer.write(stream)
    return stream.getvalue()


def picture(kind):
    stream = BytesIO(); Image.new('RGB', (8, 8), 'white').save(stream, format=kind)
    return stream.getvalue()


def upload(client, patient, raw=None, name='original.pdf', mime='application/pdf'):
    return client.post(path(patient) + '/documents', files={'file': (name, pdf() if raw is None else raw, mime)})


@pytest.mark.parametrize('name,mime,raw', [('original.pdf','application/pdf',pdf()), ('photo.png','image/png',picture('PNG')), ('photo.jpg','image/jpeg',picture('JPEG'))])
def test_upload_list_download_and_encryption(setup, name, mime, raw):
    client, factory, _ = setup; patient = create(client)
    response = upload(client, patient, raw, name, mime)
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc['jobState'] == 'not_started' and doc['pageCount'] == 1
    assert doc['allowedActions'] == ['download']
    listing = client.get(path(patient) + '/documents').json()['items']
    assert listing[0]['filename'] == name
    with factory() as db:
        row = db.get(StoredDocument, doc['id'])
        assert row.original_payload != raw and not row.original_payload.startswith(raw[:8])
        assert name.encode() not in row.metadata_payload
        assert decrypt(row.metadata_payload, f"document-meta:{patient['id']}:{row.id}")['filename'] == name
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == 'document.upload', AuditEvent.target_id == row.id))
    download = client.get(path(patient) + '/documents/' + doc['id'] + '/original')
    assert download.status_code == 200 and download.content == raw
    assert download.headers['content-disposition'].startswith('attachment;')
    assert download.headers['cache-control'] == 'no-store'
    assert download.headers['x-content-type-options'] == 'nosniff'
    events = client.get(path(patient) + '/timeline').json()['items']
    event = next(e for e in events if e['type'] == 'document')
    assert event['eventDate'] is None


def test_duplicate_is_patient_scoped_and_name_independent(setup):
    c, _, _ = setup; a = create(c); b = create(c)
    assert upload(c, a).status_code == 201
    assert upload(c, a, name='renamed.pdf').status_code == 409
    assert upload(c, b).status_code == 201
    assert len(c.get(path(a) + '/documents').json()['items']) == 1


def test_scope_admin_and_revocation(setup):
    c, factory, ids = setup; p = create(c); doc = upload(c, p).json()
    url = path(p) + '/documents/' + doc['id'] + '/original'
    sign_in(c, 'bob')
    assert c.get(url).status_code == 404
    assert c.get(path(p) + '/documents').status_code == 404
    assert upload(c, p).status_code == 404
    sign_in(c, 'admin')
    assert c.get(url).status_code == 403
    assert upload(c, p).status_code == 403
    sign_in(c, 'alice'); other = create(c)
    assert c.get(path(other) + '/documents/' + doc['id'] + '/original').status_code == 404
    with factory() as db:
        db.execute(delete(PatientAccess).where(PatientAccess.patient_id == p['id'])); db.commit()
    assert c.get(url).status_code == 404


@pytest.mark.parametrize('raw,name,mime,status', [(b'', 'empty.pdf','application/pdf',422), (b'not a pdf','fake.pdf','application/pdf',422), (b'%PDF-broken','broken.pdf','application/pdf',422), (pdf(True),'locked.pdf','application/pdf',422), (picture('PNG'),'fake.jpg','image/jpeg',422), (pdf(),'file.exe','application/pdf',415), (pdf(),'file.pdf','text/html',415)])
def test_invalid_files_leave_no_records(setup, raw, name, mime, status):
    c, factory, _ = setup; p = create(c)
    assert upload(c, p, raw, name, mime).status_code == status
    with factory() as db: assert db.scalar(select(StoredDocument)) is None


def test_file_and_body_limits_without_content_length(setup, monkeypatch):
    c, _, _ = setup; p = create(c)
    monkeypatch.setattr(documents, 'MAX_BYTES', 10)
    assert upload(c, p).status_code == 413
    monkeypatch.setattr(documents, 'MAX_BODY', 10)
    r = c.post(path(p) + '/documents', content=iter([b'x'*6,b'x'*6]), headers={'Content-Type': 'multipart/form-data; boundary=test'})
    # The stream limit also applies when Content-Length is absent.
    assert r.status_code == 413


def test_multipart_shape_and_archive(setup):
    c, _, _ = setup; p = create(c); url = path(p) + '/documents'
    assert c.post(url, json={}).status_code == 415
    assert c.post(url, files={'other': ('a.pdf',pdf(),'application/pdf')}).status_code == 422
    assert c.post(url, files=[('file',('a.pdf',pdf(),'application/pdf')),('file',('b.pdf',pdf(),'application/pdf'))]).status_code == 422
    doc = upload(c, p).json()
    assert c.post(path(p)+'/archive',json={'expectedVersion':p['version']}).status_code == 200
    assert upload(c, p).status_code == 409
    assert c.get(url+'/'+doc['id']+'/original').status_code == 200


def test_tampered_ciphertext_is_not_downloaded(setup):
    c, factory, _ = setup; p = create(c); doc = upload(c,p).json()
    with factory() as db:
        db.get(StoredDocument,doc['id']).original_payload=b'tampered'; db.commit()
    assert c.get(path(p)+'/documents/'+doc['id']+'/original').status_code == 503


def test_audit_failure_rolls_back_file_and_timeline(setup, monkeypatch):
    c, factory, _ = setup; p=create(c)
    def fail(*args): raise SQLAlchemyError('synthetic')
    monkeypatch.setattr(documents,'record_audit',fail)
    assert upload(c,p).status_code == 503
    with factory() as db:
        assert db.scalar(select(StoredDocument)) is None
        assert db.scalar(select(PatientEvent).where(PatientEvent.kind=='document')) is None


def test_filename_is_sanitized(setup):
    c, _, _ = setup; p=create(c)
    r=upload(c,p,name='../../private/record.pdf')
    assert r.status_code == 201
    assert r.json()['filename']=='record.pdf'
