from uuid import uuid4
import pytest
from sqlalchemy import select
from app import ai, summary_worker
from app.models import AISummary, SummaryJob
from test_patients import setup, create, path, sign_in
from test_sessions import new_note, saved, finalized, url

TEXT='The patient denied alcohol use.'

def prepare(c):
    p=create(c);n=finalized(c,p,saved(c,p,new_note(c,p),text=TEXT))
    body={'kind':'single_session','sourceVersions':[{'id':n['id'],'version':n['version'],'type':'session'}],'requestKey':str(uuid4())}
    return p,n,body

def generate(sources,kind):
    result=ai.Generated.model_validate({'summary':[{'text':TEXT,'evidence':[{'sourceId':'S1','quote':TEXT}]}],
      'facts':[{'text':TEXT,'label':'concern','assertion':'denied','temporality':'current','subject':'patient','evidence':[{'sourceId':'S1','quote':TEXT}]}]})
    return {**ai.grounded(result,sources),'model':'synthetic','modelDigest':'test','promptVersion':'test'}

def draft(c,factory):
    p,n,body=prepare(c);base=path(p)+'/summaries'
    response=c.post(base,json=body);assert response.status_code==202,response.text
    job=response.json();assert c.post(base,json=body).json()['id']==job['id']
    summary_worker.run_once(factory,generate)
    j=c.get('/api/v1/jobs/'+job['id']).json();assert j['state']=='completed',j
    route=base+'/'+j['resultId'];s=c.get(route).json()
    return p,n,route,s,job

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

def test_amendment_invalidates_and_filters_sources(setup):
    c,factory,_=setup;p,n,route,s,j=draft(c,factory)
    a=c.post(url(p,n)+'/amendments',json={'expectedVersion':n['version'],'reason':'Correction'}).json()
    assert c.get(route).json()['freshness']=='current'
    a=finalized(c,p,saved(c,p,a,text='Updated account.'))
    assert c.get(route).json()['freshness']=='stale'
    assert c.post(route+'/review',json={'expectedVersion':1,'decision':'accept'}).status_code==409
    ids=[x['id'] for x in c.get(path(p)+'/summaries/eligible-sources').json()['items']]
    assert a['id'] in ids and n['id'] not in ids

def test_cancel_during_generation_and_retry(setup):
    c,factory,_=setup;p,n,body=prepare(c)
    j=c.post(path(p)+'/summaries',json=body).json();endpoint='/api/v1/jobs/'+j['id']
    def cancel(sources,kind):
        assert c.post(endpoint+'/cancel').status_code==200
        return generate(sources,kind)
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

def test_invalid_sources_and_request_keys(setup):
    c,factory,_=setup;p,n,b=prepare(c);base=path(p)+'/summaries'
    assert c.post(base,json=b).status_code==202
    assert c.post(base,json={**b,'kind':'longitudinal'}).status_code==409
    assert c.post(base,json={**b,'requestKey':str(uuid4()),'sourceVersions':[{'id':n['id'],'version':1,'type':'session'}]}).status_code==409
    d=new_note(c,p)
    assert c.post(base,json={**b,'requestKey':str(uuid4()),'sourceVersions':[{'id':d['id'],'version':1,'type':'session'}]}).status_code==409
    sign_in(c,'bob');assert c.post(base,json=b).status_code==404

@pytest.mark.parametrize('source,quote',[('S2',TEXT),('S1','Alcohol use confirmed.'),('S1','   ')])
def test_invalid_evidence_rejected(source,quote):
    result=ai.Generated.model_validate({'summary':[{'text':'Example','evidence':[{'sourceId':source,'quote':quote}]}],'facts':[]})
    with pytest.raises(ValueError,match='unsupported_evidence'):ai.grounded(result,[{'text':TEXT}])

def test_source_limit_never_truncates():
    with pytest.raises(ValueError,match='source_limit'):ai.check_size([{'wordCount':1,'text':'a'*8001}],'single_session')


def test_passage_references_use_exact_original_text():
    text='Alex said “I feel worried.”\nThe patient denied alcohol use.'
    source={'id':'note','text':text,'title':'Session','href':'/source','version':3}
    result=ai.SelectedGeneration.model_validate({'summary':[{'text':'Alcohol use was denied.','evidence':[{'sourceId':'S1','passageId':'P2'}]}],'facts':[]})
    output=ai.resolve_passages(result,[source])
    assert output['paragraphs'][0]['evidence'][0]['passage']=='The patient denied alcohol use.'
    assert output['paragraphs'][0]['evidence'][0]['sourceVersion']==3


@pytest.mark.parametrize('sid,pid',[('S2','P1'),('S1','P99')])
def test_invented_passage_references_are_rejected(sid,pid):
    result=ai.SelectedGeneration.model_validate({'summary':[{'text':'Example','evidence':[{'sourceId':sid,'passageId':pid}]}],'facts':[]})
    with pytest.raises(ValueError,match='unsupported_evidence'):
        ai.resolve_passages(result,[{'text':'A documented observation.'}])


def test_long_passages_preserve_content_and_fit_quote_limit():
    text=' '.join(['documented']*150)+'。'+'文'*600
    parts=ai.passages(text)
    assert all(len(p)<=450 and p in text for p in parts.values())
    assert ''.join(parts.values())==text


def test_invalid_fact_category_rejected(setup):
    c,factory,_=setup;p,n,route,s,job=draft(c,factory)
    endpoint=route+'/facts/'+s['facts'][0]['id']+'/review'
    response=c.post(endpoint,json={'expectedVersion':1,'decision':'correct','label':'diagnosis','text':'Example','assertion':'present','temporality':'current','subject':'patient'})
    assert response.status_code==422
    assert c.get(route).json()['version']==1


@pytest.mark.parametrize('text,label,expected',[
 ('Alex rated anxiety as 7/10.','intervention','observation'),
 ('Alex attended a team meeting.','intervention','other'),
 ('The therapist guided Alex through a CBT exercise.','intervention','intervention'),
])
def test_conservative_category_checks(text,label,expected):
    evidence=[{'sourceId':'S1','quote':text}]
    result=ai.Generated.model_validate({'summary':[{'text':text,'evidence':evidence}],'facts':[{'text':text,'evidence':evidence,'label':label,'assertion':'present','temporality':'current','subject':'patient'}]})
    source={'id':'test','version':1,'title':'Test','href':'/test','text':text}
    fact=ai.grounded(result,[source])['facts'][0]
    assert fact['label']==expected
    if label!=expected:assert fact['modelProposedLabel']==label and fact['reviewNote']
