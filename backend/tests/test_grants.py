from test_patients import setup,sign_in,create,path,PASSWORD
from app.manage import create_user
from app.models import User,ClinicalGrant
ROOT='/api/v1/access/grants'
def prepare(setup,cap='clinical:read'):
 c,f,ids=setup;p=create(c)
 with f() as db:create_user(db,'reviewer','Reviewer','oversight',PASSWORD)
 sign_in(c,'bob')
 r=c.post(ROOT,json={'patientId':p['id'],'capability':cap,'reason':'Coverage'})
 assert r.status_code==201,r.text
 return c,f,ids,p,r.json()
def approve(c,g):
 sign_in(c,'reviewer')
 r=c.post(ROOT+'/'+g['id']+'/review',json={'expectedVersion':g['version'],'decision':'approve','comment':'Coverage approved'})
 assert r.status_code==200,r.text
 return r.json()
def test_read_and_revoke(setup):
 c,f,ids,p,g=prepare(setup)
 assert c.get(path(p)).status_code==404
 g=approve(c,g);sign_in(c,'bob')
 assert c.get(path(p)).status_code==200
 assert len(c.get('/api/v1/patients').json()['items'])==1
 assert c.post(path(p)+'/follow-ups',json={'title':'Forbidden'}).status_code==404
 assert c.patch(path(p),json={'expectedVersion':1,'displayName':'Forbidden'}).status_code==404
 assert 'edit' not in c.get(path(p)).json()['allowedActions']
 sign_in(c,'alice');assert c.get(ROOT).json()['items']==[]
 sign_in(c,'reviewer')
 assert c.post(ROOT+'/'+g['id']+'/revoke',json={'expectedVersion':1,'reason':'Stale'}).status_code==409
 assert c.post(ROOT+'/'+g['id']+'/revoke',json={'expectedVersion':g['version'],'reason':'Ended'}).status_code==200
 sign_in(c,'bob');assert c.get(path(p)).status_code==404
 sign_in(c,'alice');assert c.get(path(p)).status_code==200
 with f() as db:assert b'Coverage' not in db.get(ClinicalGrant,g['id']).payload

def test_write_no_self_approval(setup):
 c,f,ids,p,g=prepare(setup,'clinical:write')
 with f() as db:
  u=db.get(User,ids['bob']);u.capabilities=[*u.capabilities,'grants:approve'];db.commit()
 assert c.post(ROOT+'/'+g['id']+'/review',json={'expectedVersion':1,'decision':'approve','comment':'Self'}).status_code==403
 g=approve(c,g);sign_in(c,'bob')
 assert c.post(path(p)+'/follow-ups',json={'title':'Permitted'}).status_code==201

def test_denial_and_identity(setup):
 c,f,ids,p,g=prepare(setup)
 assert c.post(ROOT,json={'patientId':p['id'],'capability':'clinical:read','reason':'Other','subjectId':ids['alice']}).status_code==422
 assert c.post(ROOT,json={'patientId':p['id'],'capability':'clinical:read','reason':'Duplicate'}).status_code==409
 sign_in(c,'alice');assert c.post(ROOT+'/'+g['id']+'/cancel',json={'expectedVersion':1}).status_code==404
 sign_in(c,'reviewer')
 assert c.post(ROOT+'/'+g['id']+'/review',json={'expectedVersion':1,'decision':'deny','comment':'Not needed'}).status_code==200
 sign_in(c,'bob');assert c.get(path(p)).status_code==404

def test_cancel(setup):
 c,f,ids,p,g=prepare(setup)
 assert c.post(ROOT+'/'+g['id']+'/cancel',json={'expectedVersion':1}).status_code==200
 assert c.get(path(p)).status_code==404

def test_read_only_blocks_clinical_work_and_workers(setup):
 from types import SimpleNamespace
 from app import worker,summary_worker
 c,f,ids,p,g=prepare(setup)
 g=approve(c,g);sign_in(c,'bob')
 assert c.post(path(p)+'/sessions',json={'eventDate':None}).status_code==404
 assert c.post(path(p)+'/indicators/evaluate').status_code==404
 job=SimpleNamespace(requested_by=ids['bob'],patient_id=p['id'])
 with f() as db:
  assert not summary_worker.authorised(db,job)
  assert not worker.permitted(db,job,job)

def test_worker_scope_changes_on_revoke(setup):
 from types import SimpleNamespace
 from app import worker,summary_worker
 c,f,ids,p,g=prepare(setup,'clinical:write');g=approve(c,g)
 job=SimpleNamespace(requested_by=ids['bob'],patient_id=p['id'])
 with f() as db:
  assert summary_worker.authorised(db,job)
  assert worker.permitted(db,job,job)
 assert c.post(ROOT+'/'+g['id']+'/revoke',json={'expectedVersion':g['version'],'reason':'Coverage ended'}).status_code==200
 with f() as db:
  assert not summary_worker.authorised(db,job)
  assert not worker.permitted(db,job,job)
