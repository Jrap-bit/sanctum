from datetime import date
import pytest
from sqlalchemy import select
from app.medications import medication_results
from app.models import ConfirmedMedication
from test_patients import setup,create,path,sign_in
from test_sessions import new_note,saved,finalized,url

def record(**kw):return {'state':'confirmed','freshness':'current','medicationName':'Synthetic medication','changeStatus':'changed','dateStatus':'known','eventDate':'2026-11-06','href':'/source','quotation':'A change was documented.',**kw}
@pytest.mark.parametrize('changes,expected',[
 ({},'matched'),({'eventDate':'2026-10-07'},'matched'),({'eventDate':'2026-10-06'},'not_matched'),
 ({'changeStatus':'no_change'},'not_matched'),({'changeStatus':'uncertain'},'not_evaluable'),
 ({'dateStatus':'unknown','eventDate':None},'not_evaluable'),({'dateStatus':'approximate'},'not_evaluable'),
 ({'eventDate':'2026-11-07'},'not_evaluable'),({'state':'withdrawn'},'not_evaluable'),({'freshness':'stale'},'not_evaluable')])
def test_boundaries(changes,expected):assert medication_results([record(**changes)],date(2026,11,6))[0]['outcome']==expected

def test_partial_coverage_is_not_hidden():
 results=medication_results([record(),record(changeStatus='uncertain')],date(2026,11,6))
 assert [r['outcome'] for r in results]==['matched','not_evaluable']
 assert medication_results([],date(2026,11,6))[0]['outcome']=='not_evaluable'

def body(note):return {'sourceId':note['id'],'sourceVersion':note['version'],'medicationName':'Synthetic medication','changeStatus':'changed','quotation':'A medication change was documented.','confirmed':True}
def note(c,p):return finalized(c,p,saved(c,p,new_note(c,p,'2026-11-06'),text='A medication change was documented.'))

def test_lifecycle(setup):
 c,factory,_=setup;p=create(c);n=note(c,p);base=path(p)+'/medications';ev=path(p)+'/indicators'
 response=c.post(base,json=body(n));assert response.status_code==201,response.text;r=response.json()
 assert c.post(base,json=body(n)).status_code==409
 evaluation=c.post(ev+'/evaluate').json();assert next(i for i in evaluation['items'] if i['ruleId']=='medication-change')['outcome']=='matched'
 with factory() as db:
  original=db.get(ConfirmedMedication,r['id']).payload;assert b'Synthetic medication' not in original
 assert c.post(base+'/'+r['id']+'/withdraw',json={'expectedVersion':1,'reason':'Incorrect classification'}).status_code==200
 with factory() as db:assert db.get(ConfirmedMedication,r['id']).payload==original
 assert c.get(ev).json()['items'][0]['freshness']=='stale'
 assert c.post(base,json={**body(n),'changeStatus':'uncertain'}).status_code==201
 a=c.post(url(p,n)+'/amendments',json={'expectedVersion':n['version'],'reason':'Source correction'}).json();finalized(c,p,a)
 assert all(x['freshness']=='stale' for x in c.get(base).json()['items'])
 assert c.post(base,json=body(n)).status_code==409
 assert c.get(ev+'/history/runs/'+evaluation['evaluationId']).status_code==200

def test_validation_scope_and_archive(setup):
 c,factory,_=setup;p=create(c);n=note(c,p);base=path(p)+'/medications'
 for changes in [{'confirmed':False},{'medicationName':'   '},{'changeStatus':'inferred'},{'quotation':'invented quotation'},{'sourceVersion':1}]:assert c.post(base,json={**body(n),**changes}).status_code in {409,422}
 sign_in(c,'bob');assert c.get(base).status_code==404;assert c.post(base,json=body(n)).status_code==404
 sign_in(c,'admin');assert c.get(base).status_code==403
 sign_in(c,'alice');current=c.get(path(p)).json();c.post(path(p)+'/archive',json={'expectedVersion':current['version']})
 assert c.post(base,json=body(n)).status_code==409
 assert c.get(base).json()['allowedActions']==[]
