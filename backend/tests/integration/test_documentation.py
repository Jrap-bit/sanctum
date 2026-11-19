import pytest
from test_patients import setup,create,path,sign_in
from test_sessions import new_note,saved,finalized,url


def find(result):return next(i for i in result['items'] if i['ruleId']=='missing-documentation')

@pytest.mark.integration
def test_empty_drafts_and_free_text(setup):
 c,factory,_=setup;p=create(c);ev=path(p)+'/indicators'
 assert find(c.post(ev+'/evaluate').json())['outcome']=='not_evaluable'
 n=saved(c,p,new_note(c,p),text='Narrative-only synthetic note.')
 assert find(c.post(ev+'/evaluate').json())['outcome']=='not_evaluable'
 n=finalized(c,p,n)
 result=find(c.post(ev+'/evaluate').json());assert result['outcome']=='matched'
 assert result['missingFields']==['At least one Concern, Observation or Intervention entry']
 assert result['evidence'][0]['href'].endswith(n['id'])

@pytest.mark.parametrize('section,text,expected',[
 ('concerns','Concern documented','not_matched'),('observations','Observed behavior','not_matched'),
 ('interventions','Intervention documented','not_matched'),('concerns','   ','matched'),
 ('medicationReported','Medication reported','matched')])
@pytest.mark.integration
def test_structured_sections_and_unknown_date(setup,section,text,expected):
 c,factory,_=setup;p=create(c)
 n=saved(c,p,new_note(c,p,None),text='Narrative.',**{section:[{'text':text,'assertion':'present','temporality':'current'}]});finalized(c,p,n)
 assert find(c.post(path(p)+'/indicators/evaluate').json())['outcome']==expected

@pytest.mark.integration
def test_amendment_keeps_history_and_refreshes_completeness(setup):
 c,factory,_=setup;p=create(c);ev=path(p)+'/indicators'
 n=finalized(c,p,saved(c,p,new_note(c,p),text='Narrative.'))
 old=c.post(ev+'/evaluate').json();assert find(old)['outcome']=='matched'
 a=c.post(url(p,n)+'/amendments',json={'expectedVersion':n['version'],'reason':'Complete documentation'}).json()
 a=saved(c,p,a,observations=[{'text':'Observed engagement','assertion':'present','temporality':'current'}])
 assert find(c.get(ev).json())['freshness']=='current'
 finalized(c,p,a)
 assert find(c.get(ev).json())['freshness']=='stale'
 latest=c.post(ev+'/evaluate').json();assert find(latest)['outcome']=='not_matched'
 assert len([i for i in latest['items'] if i['ruleId']=='missing-documentation'])==1
 old_again=c.get(ev+'/history/runs/'+old['evaluationId']).json();assert find(old_again)['outcome']=='matched'
 assert find(old_again)['allowedActions']==[]
 sign_in(c,'bob');assert c.get(ev).status_code==404
 sign_in(c,'admin');assert c.get(ev).status_code==403
