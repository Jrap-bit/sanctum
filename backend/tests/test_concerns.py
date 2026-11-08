from datetime import date
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.domain.rules.dt01_repeated_concern import concern_results
from app.db.models import ConfirmedConcern
from test_patients import setup,create,path,sign_in
from test_sessions import new_note,saved,finalized,url

def fixtures():
 sessions=[{'id':str(i),'version':3,'eventDate':f'2026-11-0{i}','dateStatus':'known','href':'/source'} for i in (1,2,3)]
 facts=[{'sourceId':s['id'],'sourceVersion':3,'concernCode':'sleep_difficulty','state':'confirmed','freshness':'current','assertion':'present','temporality':'current','subject':'patient','quotation':'Sleep difficulty reported.'} for s in sessions]
 return sessions,facts

@pytest.mark.parametrize('change,outcome',[
 ({},'matched'),({'assertion':'denied'},'not_matched'),({'assertion':'possible'},'not_evaluable'),
 ({'subject':'other'},'not_matched'),({'temporality':'historical'},'not_matched'),
 ({'assertion':'unknown'},'not_evaluable'),({'state':'withdrawn'},'not_evaluable'),({'freshness':'stale'},'not_evaluable')])
def test_semantics(change,outcome):
 sessions,facts=fixtures();facts[0].update(change)
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']==outcome

def test_window_uses_all_sessions_and_distinct_sources():
 sessions,facts=fixtures()
 assert concern_results(facts,sessions[:2],date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions.append({'id':'4','version':1,'eventDate':'2026-11-04','dateStatus':'known','href':'/4'})
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions[-1]['eventDate']='2026-11-01'
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions.pop();facts.append(facts[0].copy())
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'

def test_dates_and_same_day_distinct_sessions():
 sessions,facts=fixtures();sessions[0]['dateStatus']='approximate'
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions[0]['dateStatus']='known'
 for s in sessions:s['eventDate']='2026-11-01'
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='matched'

def note(c,p,day):return finalized(c,p,saved(c,p,new_note(c,p,day),text='Sleep difficulty reported.'))
def body(n):return {'sourceId':n['id'],'sourceVersion':n['version'],'concernCode':'sleep_difficulty','assertion':'present','temporality':'current','subject':'patient','quotation':'Sleep difficulty reported.','confirmed':True}

def test_lifecycle_and_history(setup):
 c,factory,_=setup;p=create(c);base=path(p)+'/concerns';notes=[note(c,p,f'2026-11-0{i}') for i in (1,2,3)]
 records=[]
 for n in notes:
  r=c.post(base,json=body(n));assert r.status_code==201,r.text;records.append(r.json())
 assert c.post(base,json=body(notes[0])).status_code==409
 ev=path(p)+'/indicators';result=c.post(ev+'/evaluate').json()
 assert next(i for i in result['items'] if i['ruleId']=='repeated-concern')['outcome']=='matched'
 with factory() as db:
  original=db.get(ConfirmedConcern,records[0]['id']).payload;assert b'Sleep difficulty' not in original
 r=c.post(base+'/'+records[0]['id']+'/withdraw',json={'expectedVersion':1,'reason':'Wrong classification'});assert r.status_code==200
 with factory() as db:assert db.get(ConfirmedConcern,records[0]['id']).payload==original
 assert c.get(ev).json()['items'][0]['freshness']=='stale'
 assert c.post(base,json={**body(notes[0]),'quotation':'Invented quote'}).status_code==422
 a=c.post(url(p,notes[1])+'/amendments',json={'expectedVersion':notes[1]['version'],'reason':'Correction'}).json();finalized(c,p,a)
 assert any(x['freshness']=='stale' for x in c.get(base).json()['items'])
 assert c.post(base,json=body(notes[1])).status_code==409
 assert c.get(ev+'/history/runs/'+result['evaluationId']).status_code==200

def test_scope_validation_archive(setup):
 c,factory,_=setup;p=create(c);n=note(c,p,'2026-11-01');base=path(p)+'/concerns'
 for changes in [{'confirmed':False},{'concernCode':'invented'},{'quotation':'   '},{'sourceVersion':1}]:assert c.post(base,json={**body(n),**changes}).status_code in {409,422}
 sign_in(c,'bob');assert c.get(base).status_code==404;assert c.post(base,json=body(n)).status_code==404
 sign_in(c,'admin');assert c.get(base).status_code==403
 sign_in(c,'alice');current=c.get(path(p)).json();c.post(path(p)+'/archive',json={'expectedVersion':current['version']})
 assert c.post(base,json=body(n)).status_code==409
 assert c.get(base).json()['allowedActions']==[]
