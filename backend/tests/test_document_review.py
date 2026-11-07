from io import BytesIO
from datetime import timedelta
import pytest
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app import worker, review
from app.models import ClinicalNote, DocumentImport, StoredDocument
from app.patients import clinic_today
from app.sessions import content_of
from test_patients import setup, create, path, sign_in
from test_documents import upload


def prepare(c, factory, count=2):
    p=create(c); writer=PdfWriter()
    for _ in range(count):writer.add_blank_page(width=72,height=72)
    stream=BytesIO();writer.write(stream)
    d=upload(c,p,raw=stream.getvalue()).json();base=path(p)+'/documents/'+d['id']
    assert c.post(base+'/process',json={}).status_code==202
    worker.run_once(factory,lambda raw,mime,n:{'rawText':f'Raw OCR page {n}','method':'ocr'})
    return p,d,base


def save(c,base,n,**changes):
    body={'correctedText':f'Corrected text page {n}','included':True,'unreadable':False,'expectedVersion':1,**changes}
    return c.patch(base+f'/pages/{n}',json=body)


def confirm(c,base,groups=None,version=None):
    if version is None:version=c.get(base+'/pages').json()['version']
    return c.post(base+'/confirm',json={'expectedVersion':version,'groups':groups or [{'pageNumbers':[1,2],'dateStatus':'unknown','eventDate':None}]})


def test_review_import_provenance_and_idempotency(setup):
    c,factory,_=setup;p,d,base=prepare(c,factory)
    assert confirm(c,base).status_code==422
    assert save(c,base,1).status_code==200
    assert save(c,base,2).status_code==200
    pages=c.get(base+'/pages').json();assert pages['version']==3
    assert pages['pages'][0]['rawText']=='Raw OCR page 1'
    assert pages['pages'][0]['correctedText']=='Corrected text page 1'
    result=confirm(c,base,version=3);assert result.status_code==200,result.text
    assert confirm(c,base,version=3).json()==result.json()
    note_id=result.json()['sessions'][0]['id']
    note=c.get(path(p)+'/sessions/'+note_id).json()
    assert note['state']=='finalized' and note['eventDate'] is None and note['dateStatus']=='unknown'
    assert 'Corrected text page 1' in note['text'] and 'Raw OCR' not in note['text']
    assert note['source']['documentId']==d['id'] and note['source']['pageVersions']==[2,2]
    assert save(c,base,1,expectedVersion=2).status_code==409
    with factory() as db:
        assert len(db.scalars(select(ClinicalNote)).all())==1
        assert b'Corrected text' not in db.scalar(select(ClinicalNote)).payload
    assert c.get(base+'/pages').json()['imported']['sessions'][0]['id']==note_id
    events=c.get(path(p)+'/timeline').json()['items']
    assert next(e for e in events if e['id']==note_id)['title']=='Imported historical session'


def test_page_and_document_conflicts(setup):
    c,factory,_=setup;p,d,base=prepare(c,factory)
    assert save(c,base,1).status_code==200
    assert save(c,base,1,correctedText='Stale overwrite').status_code==409
    assert save(c,base,2).status_code==200
    assert confirm(c,base,version=1).status_code==409
    assert c.get(base+'/pages').json()['pages'][0]['correctedText']=='Corrected text page 1'


@pytest.mark.parametrize('groups', [
    [{'pageNumbers':[1],'dateStatus':'unknown'}],
    [{'pageNumbers':[1,2],'dateStatus':'unknown'},{'pageNumbers':[2],'dateStatus':'unknown'}],
    [{'pageNumbers':[1,3],'dateStatus':'unknown'}],
    [{'pageNumbers':[1,1,2],'dateStatus':'unknown'}],
    [{'pageNumbers':[1,2],'dateStatus':'unknown','eventDate':'2020-01-01'}],
    [{'pageNumbers':[1,2],'dateStatus':'known'}],
    [{'pageNumbers':[1,2],'dateStatus':'known','eventDate':(clinic_today()+timedelta(days=1)).isoformat()}],
])
def test_invalid_groups_rejected(setup,groups):
    c,factory,_=setup;p,d,base=prepare(c,factory);save(c,base,1);save(c,base,2)
    assert confirm(c,base,groups).status_code==422
    with factory() as db:assert db.scalar(select(ClinicalNote)) is None


def test_exclusion_approximate_date_and_amendment_source(setup):
    c,factory,_=setup;p,d,base=prepare(c,factory)
    assert save(c,base,1,included=True,unreadable=True).status_code==422
    assert save(c,base,1,correctedText='',included=False,unreadable=True).status_code==200
    save(c,base,2)
    groups=[{'pageNumbers':[2],'dateStatus':'approximate','eventDate':'2020-01-01'}]
    r=confirm(c,base,groups);assert r.status_code==200,r.text
    nid=r.json()['sessions'][0]['id'];note=c.get(path(p)+'/sessions/'+nid).json()
    assert note['dateStatus']=='approximate' and note['source']['pageNumbers']==[2]
    amend=c.post(path(p)+'/sessions/'+nid+'/amendments',json={'expectedVersion':1,'reason':'Correct reviewed history'}).json()
    body={k:amend[k] for k in ['eventDate','text','concerns','observations','interventions','medicationReported']}
    body.update(expectedVersion=amend['version'],text='Updated historical text')
    saved=c.patch(path(p)+'/sessions/'+amend['id'],json=body).json()
    assert saved['source']==note['source'] and saved['dateStatus']=='approximate'
    assert c.get(path(p)+'/sessions/'+nid).json()['text']==note['text']
    assert confirm(c,base,[{'pageNumbers':[2],'dateStatus':'known','eventDate':'2020-01-01'}]).status_code==409


def test_scope_preview_and_archival(setup):
    c,factory,_=setup;p,d,base=prepare(c,factory)
    image=c.get(base+'/pages/1/original');assert image.status_code==200,image.text[:100] if image.status_code!=200 else ''
    assert image.content.startswith(b'\x89PNG') and image.headers['cache-control']=='no-store'
    assert c.get(base+'/pages/3/original').status_code==404
    sign_in(c,'bob');assert save(c,base,1).status_code==404
    assert c.get(base+'/pages/1/original').status_code==404
    sign_in(c,'admin');assert save(c,base,1).status_code==403
    sign_in(c,'alice');c.post(path(p)+'/archive',json={'expectedVersion':p['version']})
    assert save(c,base,1).status_code==409
    assert confirm(c,base).status_code==409


def test_import_audit_failure_is_atomic(setup,monkeypatch):
    c,factory,_=setup;p,d,base=prepare(c,factory);save(c,base,1);save(c,base,2)
    def fail(*args):raise SQLAlchemyError('synthetic audit failure')
    monkeypatch.setattr(review,'record_audit',fail)
    assert confirm(c,base).status_code==503
    with factory() as db:
        assert db.scalar(select(ClinicalNote)) is None
        assert db.scalar(select(DocumentImport)) is None
        assert db.get(StoredDocument,d['id']).review_version==3
