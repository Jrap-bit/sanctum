from datetime import date
import pytest
from app.services import indicators
from app.db.models import ConfirmedRating
from test_patients import setup,create,path,sign_in
from test_sessions import new_note,saved,finalized,url


def note(c,p,day):return finalized(c,p,saved(c,p,new_note(c,p,day),text='Synthetic rating source.'))
def body(n,value=4):return {'sourceId':n['id'],'sourceVersion':n['version'],'scaleName':'Anxiety','value':value,'higherMeans':'more_difficulty','confirmed':True}

@pytest.mark.integration
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
@pytest.mark.integration
def test_validation(setup,changes):
 c,factory,_=setup;p=create(c);n=note(c,p,'2026-11-01');r=c.post(path(p)+'/ratings',json={**body(n),**changes});assert r.status_code in {409,422}

@pytest.mark.integration
def test_scope_and_archive(setup):
 c,factory,_=setup;p=create(c);n=note(c,p,'2026-11-01');base=path(p)+'/ratings'
 sign_in(c,'bob');assert c.get(base).status_code==404;assert c.post(base,json=body(n)).status_code==404
 sign_in(c,'admin');assert c.get(base).status_code==403
 sign_in(c,'alice');pnow=c.get(path(p)).json();c.post(path(p)+'/archive',json={'expectedVersion':pnow['version']})
 assert c.post(base,json=body(n)).status_code==409
 assert c.get(base).json()['allowedActions']==[]
