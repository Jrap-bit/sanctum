from datetime import date
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.services import indicators
from app.db.models import IndicatorRun
from test_patients import setup,create,path,sign_in


def task(c,p,due=None):
 r=c.post(path(p)+'/follow-ups',json={'title':'Synthetic follow-up','dueDate':due});assert r.status_code==201,r.text;return r.json()

@pytest.mark.integration
def test_saved_results_reviews_and_staleness(setup,monkeypatch):
 c,factory,_=setup;monkeypatch.setattr(indicators,'clinic_today',lambda:date(2026,11,6));p=create(c);t=task(c,p,'2026-11-05');base=path(p)+'/indicators'
 r=c.post(base+'/evaluate');assert r.status_code==200,r.text;result=r.json();item=result['items'][0]
 assert item['outcome']=='matched' and item['version']==1
 assert c.post(base+'/evaluate').json()['evaluationId']==result['evaluationId']
 with factory() as db:
  run=db.scalar(select(IndicatorRun));original=run.payload
  assert b'Synthetic follow-up' not in run.payload
 body={'evaluationId':result['evaluationId'],'expectedVersion':1,'decision':'dismiss','comment':'Discussed at appointment'}
 r=c.post(base+'/'+item['id']+'/review',json=body);assert r.status_code==200,r.text
 assert r.json()['items'][0]['outcome']=='matched' and r.json()['items'][0]['reviewState']=='dismissed'
 assert c.get(path(p)+'/follow-ups').json()['items'][0]['state']=='open'
 assert c.post(base+'/'+item['id']+'/review',json=body).status_code==409
 with factory() as db:assert db.scalar(select(IndicatorRun)).payload==original
 assert c.post(base+'/evaluate').json()['items'][0]['reviewState']=='dismissed'
 c.patch(path(p)+'/follow-ups/'+t['id'],json={'state':'completed'})
 assert c.get(base).json()['items'][0]['freshness']=='stale'
 new=c.post(base+'/evaluate').json();assert new['items'][0]['outcome']=='not_matched' and new['evaluationId']!=result['evaluationId']
 old=c.get(base+'/history/runs/'+result['evaluationId']).json()['items'][0]
 assert old['outcome']=='matched' and old['reviewState']=='dismissed' and old['allowedActions']==[]
 assert len(c.get(base+'/history/runs').json()['items'])==2
 monkeypatch.setattr(indicators,'clinic_today',lambda:date(2026,11,7))
 assert c.get(base).json()['items'][0]['freshness']=='stale'

@pytest.mark.integration
def test_missing_inputs_scope_and_archive(setup):
 c,factory,_=setup;p=create(c);base=path(p)+'/indicators'
 assert c.get(base).json()['items']==[]
 result=c.post(base+'/evaluate').json();assert result['items'][0]['outcome']=='not_evaluable'
 task(c,p);result=c.post(base+'/evaluate').json();assert result['items'][0]['outcome']=='not_evaluable'
 sign_in(c,'bob');assert c.get(base).status_code==404;assert c.post(base+'/evaluate').status_code==404
 sign_in(c,'admin');assert c.get(base).status_code==403
 sign_in(c,'alice');current=c.get(path(p)).json();assert c.post(path(p)+'/archive',json={'expectedVersion':current['version']}).status_code==200
 assert c.post(base+'/evaluate').status_code==409
 assert c.get(base).json()['items'][0]['allowedActions']==[]

@pytest.mark.integration
def test_stale_review_and_audit_rollback(setup,monkeypatch):
 c,factory,_=setup;p=create(c);t=task(c,p);base=path(p)+'/indicators';result=c.post(base+'/evaluate').json();i=result['items'][0]
 task(c,p)
 assert c.post(base+'/'+i['id']+'/review',json={'evaluationId':result['evaluationId'],'expectedVersion':1,'decision':'acknowledge'}).status_code==409
 def fail(*args):raise SQLAlchemyError('synthetic audit failure')
 monkeypatch.setattr(indicators,'record_audit',fail)
 assert c.post(base+'/evaluate').status_code==503
 with factory() as db:assert len(db.scalars(select(IndicatorRun)).all())==1
