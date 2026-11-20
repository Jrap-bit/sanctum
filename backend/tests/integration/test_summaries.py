from uuid import uuid4
import pytest
from sqlalchemy import select
from app.adapters import llm as ai
from app.workers import summary as summary_worker
from app.db.models import AISummary, SummaryJob
from test_patients import setup, create, path, sign_in, PASSWORD
from test_sessions import new_note, saved, finalized, url

TEXT='The patient denied alcohol use.'

def prepare(c):
    p=create(c);n=finalized(c,p,saved(c,p,new_note(c,p),text=TEXT))
    body={'kind':'single_session','sourceVersions':[{'id':n['id'],'version':n['version'],'type':'session'}],'requestKey':str(uuid4())}
    return p,n,body

def generate(sources, kind, model=None, on_delta=None):
    if on_delta:
        on_delta(TEXT)
    result = ai.Generated.model_validate({
        'summary': [{'text': TEXT, 'evidence': [{'sourceId': 'S1', 'quote': TEXT}]}],
        'facts': [{
            'text': TEXT,
            'label': 'concern',
            'assertion': 'denied',
            'temporality': 'current',
            'subject': 'patient',
            'evidence': [{'sourceId': 'S1', 'quote': TEXT}],
        }],
    })
    return {**ai.grounded(result, sources), 'model': model or 'synthetic', 'modelDigest': 'test', 'promptVersion': 'test'}

def draft(c,factory):
    p,n,body=prepare(c);base=path(p)+'/summaries'
    response=c.post(base,json=body);assert response.status_code==202,response.text
    job=response.json();assert c.post(base,json=body).json()['id']==job['id']
    summary_worker.run_once(factory,generate)
    j=c.get('/api/v1/jobs/'+job['id']).json();assert j['state']=='completed',j
    route=base+'/'+j['resultId'];s=c.get(route).json()
    return p,n,route,s,job

@pytest.mark.integration
def test_generation_encryption_review_and_scope(setup):
    c,factory,_=setup;p,n,route,s,job=draft(c,factory)
    assert s['reviewState']=='pending' and s['freshness']=='current'
    assert s['evidence'][0]['passage']==TEXT and 'text' not in s['sources'][0]
    with factory() as db:
        assert TEXT.encode() not in db.scalar(select(AISummary)).payload
        assert TEXT.encode() not in db.scalar(select(SummaryJob)).payload
    accepted=c.post(route+'/review',json={'expectedVersion':1,'decision':'edit_accept','text':'Clinician reviewed text.'})
    assert accepted.status_code==200,accepted.text
    s=accepted.json();assert s['facts'][0]['state']=='pending' and TEXT in s['originalText']
    f=s['facts'][0];facturl=route+'/facts/'+f['id']+'/review'
    assert c.post(facturl,json={'expectedVersion':1,'decision':'confirm'}).status_code==409
    r=c.post(facturl,json={'expectedVersion':2,'decision':'correct','text':'Corrected by clinician.','label':'observation','assertion':'possible','temporality':'historical','subject':'other'})
    assert r.status_code==200,r.text
    f=r.json()['facts'][0];assert f['state']=='confirmed' and f['subject']=='other' and f['originalFact']['assertion']=='denied' and f['label']=='observation' and f['originalFact']['label']=='concern'
    sign_in(c,'bob');assert c.get(route).status_code==404
    assert c.get('/api/v1/jobs/'+job['id']).status_code==404
    sign_in(c,'admin');assert c.get(route).status_code==403

@pytest.mark.integration
def test_amendment_invalidates_and_filters_sources(setup):
    c,factory,_=setup;p,n,route,s,j=draft(c,factory)
    a=c.post(url(p,n)+'/amendments',json={'expectedVersion':n['version'],'reason':'Correction'}).json()
    assert c.get(route).json()['freshness']=='current'
    a=finalized(c,p,saved(c,p,a,text='Updated account.'))
    assert c.get(route).json()['freshness']=='stale'
    assert c.post(route+'/review',json={'expectedVersion':1,'decision':'accept'}).status_code==409
    ids=[x['id'] for x in c.get(path(p)+'/summaries/eligible-sources').json()['items']]
    assert a['id'] in ids and n['id'] not in ids

@pytest.mark.integration
def test_cancel_during_generation_and_retry(setup):
    c,factory,_=setup;p,n,body=prepare(c)
    j=c.post(path(p)+'/summaries',json=body).json();endpoint='/api/v1/jobs/'+j['id']
    def cancel(sources, kind, *args, **kwargs):
        assert c.post(endpoint+'/cancel').status_code==200
        return generate(sources, kind, *args, **kwargs)
    summary_worker.run_once(factory,cancel)
    assert c.get(endpoint).json()['state']=='cancelled'
    with factory() as db:assert db.scalar(select(AISummary)) is None
    assert c.post(endpoint+'/retry').status_code==202
    def fail(*args):raise ValueError('unsupported_evidence')
    summary_worker.run_once(factory,fail)
    assert c.get(endpoint).json()['state']=='failed'
    assert c.post(endpoint+'/retry').status_code==202
    summary_worker.run_once(factory,generate)
    assert c.get(endpoint).json()['state']=='completed'

@pytest.mark.integration
def test_invalid_sources_and_request_keys(setup):
    c,factory,_=setup;p,n,b=prepare(c);base=path(p)+'/summaries'
    assert c.post(base,json=b).status_code==202
    assert c.post(base,json={**b,'kind':'longitudinal'}).status_code==409
    assert c.post(base,json={**b,'requestKey':str(uuid4()),'sourceVersions':[{'id':n['id'],'version':1,'type':'session'}]}).status_code==409
    d=new_note(c,p)
    assert c.post(base,json={**b,'requestKey':str(uuid4()),'sourceVersions':[{'id':d['id'],'version':1,'type':'session'}]}).status_code==409
    sign_in(c,'bob');assert c.post(base,json=b).status_code==404


@pytest.mark.integration
def test_invalid_fact_category_rejected(setup):
    c,factory,_=setup;p,n,route,s,job=draft(c,factory)
    endpoint=route+'/facts/'+s['facts'][0]['id']+'/review'
    response=c.post(endpoint,json={'expectedVersion':1,'decision':'correct','label':'diagnosis','text':'Example','assertion':'present','temporality':'current','subject':'patient'})
    assert response.status_code==422
    assert c.get(route).json()['version']==1


@pytest.mark.integration
def test_unknown_model_gives_422(setup):
    c, factory, _ = setup
    p, n, body = prepare(c)
    base = path(p) + '/summaries'
    response = c.post(base, json={**body, 'model': 'unsupported_model_123'})
    assert response.status_code == 422


@pytest.mark.integration
def test_chosen_model_stored_passed_and_recorded(setup):
    c, factory, _ = setup
    p, n, body = prepare(c)
    base = path(p) + '/summaries'
    target_model = 'qwen3:1.7b'
    response = c.post(base, json={**body, 'model': target_model})
    assert response.status_code == 202
    job_id = response.json()['id']
    with factory() as db:
        job = db.scalar(select(SummaryJob).where(SummaryJob.id == job_id))
        assert job.model == target_model

    passed_model = []
    def recording_gen(sources, kind, model=None, on_delta=None):
        passed_model.append(model)
        return generate(sources, kind, model, on_delta)

    summary_worker.run_once(factory, recording_gen)
    assert passed_model == [target_model]

    j = c.get('/api/v1/jobs/' + job_id).json()
    assert j['state'] == 'completed'
    s = c.get(base + '/' + j['resultId']).json()
    assert s['model'] == target_model


@pytest.mark.integration
def test_model_catalog_permissions_and_status(setup, monkeypatch):
    c, factory, ids = setup
    # Default user has summaries:write -> 200
    r = c.get('/api/v1/models')
    assert r.status_code == 200
    data = r.json()
    assert 'default' in data and 'items' in data
    assert any(m['id'] == 'qwen3:4b' for m in data['items'])

    # User admin has operations:manage -> 200
    sign_in(c, 'admin')
    r_op = c.get('/api/v1/models')
    assert r_op.status_code == 200

    # User reviewer (oversight, neither summaries:write nor operations:manage) -> 403
    from app.manage import create_user
    with factory() as db:
        create_user(db, 'reviewer', 'Reviewer', 'oversight', PASSWORD)
    sign_in(c, 'reviewer')
    assert c.get('/api/v1/models').status_code == 403
    assert c.get('/api/v1/ai/status').status_code == 403

    # With runtime down, returns items with available: false, not an error
    sign_in(c, 'alice')
    def mock_models_fail():
        raise ValueError('model_unavailable')
    monkeypatch.setattr(ai.engine(), 'models', mock_models_fail)
    r_down = c.get('/api/v1/models')
    assert r_down.status_code == 200
    assert all(item['available'] is False for item in r_down.json()['items'])


@pytest.mark.integration
def test_progress_publish_happens(setup, monkeypatch):
    c, factory, _ = setup
    p, n, body = prepare(c)
    base = path(p) + '/summaries'
    r = c.post(base, json=body)
    assert r.status_code == 202
    events = []
    from app.workers import summary as sw
    orig_publish = sw.publish_progress
    def record_progress(job_id, **kwargs):
        events.append((job_id, kwargs))
        orig_publish(job_id, **kwargs)
    monkeypatch.setattr(sw, 'publish_progress', record_progress)

    sw.run_once(factory, generate)
    stages = [kwargs.get('stage') for _, kwargs in events if 'stage' in kwargs]
    assert 'Waiting for the model' in stages
    assert 'Writing draft' in stages
    deltas = [kwargs.get('delta') for _, kwargs in events if kwargs.get('delta')]
    assert len(deltas) > 0 and TEXT in deltas[0]
    states = [kwargs.get('state') for _, kwargs in events]
    assert 'completed' in states


@pytest.mark.integration
def test_identical_request_replay_returns_the_same_job(setup):
    """TC-24: resending the same request with the same key creates no duplicate work."""
    c,factory,_=setup;p,n,b=prepare(c);base=path(p)+'/summaries'
    first=c.post(base,json=b);assert first.status_code==202,first.text
    second=c.post(base,json=b);assert second.status_code in (200,202),second.text
    assert second.json()['id']==first.json()['id']
    with factory() as db:
        assert len(db.scalars(select(SummaryJob).where(SummaryJob.patient_id==p['id'])).all())==1
