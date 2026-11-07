from datetime import date
from uuid import uuid4
import pytest
from sqlalchemy import select
from app import indicators
from app.ratings import rating_results
from app.models import ConfirmedRating
from test_patients import setup,create,path,sign_in
from test_sessions import new_note,saved,finalized,url

def row(day,value,**changes):
 return {'id':str(uuid4()),'state':'confirmed','freshness':'current','dateStatus':'known','eventDate':day,'scaleName':'Anxiety','value':value,'higherMeans':'more_difficulty','href':'/source',**changes}

@pytest.mark.parametrize('previous,latest,expected',[(4,6,'matched'),(4,5,'not_matched'),(6,4,'not_matched'),(0,10,'matched'),(4.5,6.5,'matched')])
def test_delta_boundary(previous,latest,expected):
 result=rating_results([row('2026-11-01',previous),row('2026-11-06',latest)],date(2026,11,6))
 assert result[0]['outcome']==expected

@pytest.mark.parametrize('values',[
 [],[row('2026-11-01',4)],
 [row('2026-11-01',4),row('2026-11-06',6,scaleName='Sleep')],
 [row('2026-11-01',4),row('2026-11-06',6,higherMeans='less_difficulty')],
 [row('2026-11-01',4),row(None,6,dateStatus='unknown')],
 [row('2026-11-01',4),row('2026-11-06',6,dateStatus='approximate')],
 [row('2026-10-06',4),row('2026-11-06',6)],
 [row('2026-11-06',4),row('2026-11-06',6)],
 [row('2026-11-01',4),row('2026-11-06',6,freshness='stale')],
 [row('2026-11-01',4),row('2026-11-06',6,state='withdrawn')],
])
def test_incompatible_or_missing(values):
 assert all(r['outcome']=='not_evaluable' for r in rating_results(values,date(2026,11,6)))

def test_inclusive_window_and_latest_pair_only():
 assert rating_results([row('2026-10-07',4),row('2026-11-06',6)],date(2026,11,6))[0]['outcome']=='matched'
 assert rating_results([row('2026-11-01',2),row('2026-11-04',6),row('2026-11-06',5)],date(2026,11,6))[0]['outcome']=='not_matched'

def note(c,p,day):return finalized(c,p,saved(c,p,new_note(c,p,day),text='Synthetic rating source.'))
def body(n,value=4):return {'sourceId':n['id'],'sourceVersion':n['version'],'scaleName':'Anxiety','value':value,'higherMeans':'more_difficulty','confirmed':True}

def test_confirm_withdraw_amendment_and_evaluation(setup,monkeypatch):
 c,factory,_=setup;monkeypatch.setattr(indicators,'clinic_today',lambda:date(2026,11,6));p=create(c);n=note(c,p,'2026-11-01');n2=note(c,p,'2026-11-06');base=path(p)+'/ratings';ev=path(p)+'/indicators'
 r=c.post(base,json=body(n));assert r.status_code==201,r.text;first=r.json()
 assert c.post(base,json=body(n)).status_code==409
 assert c.post(base,json=body(n2,6)).status_code==201
 result=c.post(ev+'/evaluate').json();rating=next(i for i in result['items'] if i['ruleId']=='difficulty-scale');assert rating['outcome']=='matched'
 with factory() as db:
  record=db.get(ConfirmedRating,first['id']);original=record.payload;assert b'Anxiety' not in original
 r=c.post(base+'/'+first['id']+'/withdraw',json={'expectedVersion':1,'reason':'Wrong value'});assert r.status_code==200,r.text
 with factory() as db:assert db.get(ConfirmedRating,first['id']).payload==original
 assert c.get(ev).json()['items'][0]['freshness']=='stale'
 assert c.post(base,json=body(n,5)).status_code==201
 result=c.post(ev+'/evaluate').json();assert next(i for i in result['items'] if i['ruleId']=='difficulty-scale')['outcome']=='not_matched'
 a=c.post(url(p,n2)+'/amendments',json={'expectedVersion':n2['version'],'reason':'Correct source'}).json();finalized(c,p,a)
 assert any(r['freshness']=='stale' for r in c.get(base).json()['items'])
 assert c.post(base,json=body(n2,8)).status_code==409
 assert c.get(ev).json()['items'][0]['freshness']=='stale'

@pytest.mark.parametrize('changes',[{'value':-1},{'value':11},{'confirmed':False},{'scaleName':'  '},{'higherMeans':'guess'},{'sourceVersion':1}])
def test_validation(setup,changes):
 c,factory,_=setup;p=create(c);n=note(c,p,'2026-11-01');r=c.post(path(p)+'/ratings',json={**body(n),**changes});assert r.status_code in {409,422}

def test_scope_and_archive(setup):
 c,factory,_=setup;p=create(c);n=note(c,p,'2026-11-01');base=path(p)+'/ratings'
 sign_in(c,'bob');assert c.get(base).status_code==404;assert c.post(base,json=body(n)).status_code==404
 sign_in(c,'admin');assert c.get(base).status_code==403
 sign_in(c,'alice');pnow=c.get(path(p)).json();c.post(path(p)+'/archive',json={'expectedVersion':pnow['version']})
 assert c.post(base,json=body(n)).status_code==409
 assert c.get(base).json()['allowedActions']==[]
