import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.api import rules
from app.manage import create_user
from app.db.models import RuleRevision,RuleHead
from app.domain.rules.dt02_rating_increase import rating_results
from app.domain.rules.dt01_repeated_concern import concern_results
from app.domain.rules.dt04_medication_change import medication_results
from test_patients import setup,create,path,sign_in,PASSWORD
from test_ratings import row
from test_concerns import fixtures
from test_medications import record
from datetime import date

def publisher(factory):
 with factory() as db:create_user(db,'publisher','Rule Publisher','oversight',PASSWORD)

def publish(c,key,params,version=1,enabled=True):return c.post('/api/v1/oversight/rules/'+key+'/publish',json={'parameters':params,'expectedVersion':version,'enabled':enabled,'reason':'Synthetic test change'})

def test_publication_scope_history_and_conflicts(setup):
 c,factory,_=setup
 assert c.get('/api/v1/rules').status_code==200
 assert c.get('/api/v1/oversight/rules').status_code==403
 sign_in(c,'admin');assert publish(c,'difficulty-scale',{'D':3}).status_code==403
 publisher(factory);sign_in(c,'publisher')
 r=publish(c,'difficulty-scale',{'D':3});assert r.status_code==200,r.text
 rule=next(x for x in r.json()['items'] if x['id']=='difficulty-scale')
 assert rule['version']==2 and rule['parameters']=={'D':3}
 assert [v['version'] for v in rule['history']]==[2,1]
 assert publish(c,'difficulty-scale',{'D':4}).status_code==409
 assert publish(c,'difficulty-scale',{'D':3},2).status_code==409
 assert publish(c,'difficulty-scale',{'D':4},2).status_code==200
 with factory() as db:assert db.get(RuleRevision,('difficulty-scale',2)).parameters=={'D':3}

@pytest.mark.parametrize('key,params',[
 ('difficulty-scale',{'D':0}),('difficulty-scale',{'D':11}),('difficulty-scale',{'D':True}),('difficulty-scale',{'D':2.5}),
 ('difficulty-scale',{'D':2,'unknown':1}),('difficulty-scale',{}),('medication-change',{'L':91}),
 ('repeated-concern',{'W':2,'K':3}),('repeated-concern',{'W':11,'K':2}),('overdue-followup',{'D':2})])
def test_bounds(setup,key,params):
 c,factory,_=setup;publisher(factory);sign_in(c,'publisher');assert publish(c,key,params).status_code==422

def test_changed_rules_stale_and_disabled_not_reviewable(setup):
 c,factory,_=setup;p=create(c);base=path(p)+'/indicators';old=c.post(base+'/evaluate').json()
 publisher(factory);sign_in(c,'publisher');assert publish(c,'overdue-followup',{},enabled=False).status_code==200
 sign_in(c,'alice');assert all(i['freshness']=='stale' for i in c.get(base).json()['items'])
 latest=c.post(base+'/evaluate').json();item=next(i for i in latest['items'] if i['ruleId']=='overdue-followup')
 assert not item['enabled'] and item['ruleVersion']==2 and item['allowedActions']==[]
 assert c.post(base+'/'+item['id']+'/review',json={'evaluationId':latest['evaluationId'],'expectedVersion':1,'decision':'acknowledge'}).status_code==409
 history=c.get(base+'/history/runs/'+old['evaluationId']).json();original=next(i for i in history['items'] if i['ruleId']=='overdue-followup')
 assert original['enabled'] and original['ruleVersion']==1

def test_actual_thresholds():
 today=date(2026,11,6)
 assert rating_results([row('2026-11-01',4),row('2026-11-06',6)],today,3)[0]['outcome']=='not_matched'
 sessions,facts=fixtures();facts[0]['assertion']='denied'
 assert concern_results(facts,sessions,today,3,2)[0]['outcome']=='matched'
 assert medication_results([record(eventDate='2026-10-01')],today,40)[0]['outcome']=='matched'
 assert medication_results([record(eventDate='2026-10-01')],today,30)[0]['outcome']=='not_matched'

def test_publication_audit_failure_rolls_back(setup,monkeypatch):
 c,factory,_=setup;publisher(factory);sign_in(c,'publisher')
 def fail(*args):raise SQLAlchemyError('Synthetic failure')
 monkeypatch.setattr(rules,'record_audit',fail)
 assert publish(c,'difficulty-scale',{'D':4}).status_code==503
 with factory() as db:
  assert db.get(RuleRevision,('difficulty-scale',2)) is None
  assert rules.current_rules(db)['difficulty-scale']['version']==1
