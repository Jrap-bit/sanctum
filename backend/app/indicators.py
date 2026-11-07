from .patients import has_access
"""DT-03: deterministic follow-up results with retained source snapshots."""
from datetime import date
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from .auth import CurrentUser, Db
from .ratings import rows as rating_rows, rating_output, rating_results
from .concerns import rows as concern_rows, concern_output, concern_results, session_snapshot
from .medications import rows as medication_rows, medication_output, medication_results
from .documentation import documentation_snapshot, documentation_results
from .rules import current_rules
from .crypto import decrypt, encrypt
from .models import FollowUp, IndicatorRun, now
from .patients import VersionInput, clinic_today, scoped_patient, require, record_audit, task_output

router=APIRouter(prefix='/api/v1/patients/{patient_id}/indicators',tags=['Indicators'])
RULE_VERSION=1

def snapshot(db,patient_id):
    tasks=[task_output(t) for t in db.scalars(select(FollowUp).where(FollowUp.patient_id==patient_id).order_by(FollowUp.id))]
    # Explicit clinician-created tasks only; no dates inferred from prose or AI.
    return {'evaluationDate':clinic_today().isoformat(),'ruleVersion':RULE_VERSION,'tasks':tasks,'ratingRuleVersion':1,'ratings':[rating_output(db,r) for r in rating_rows(db,patient_id)],'concernRuleVersion':1,'concerns':[concern_output(db,r) for r in concern_rows(db,patient_id)],'sessions':session_snapshot(db,patient_id),'medicationRuleVersion':1,'medications':[medication_output(db,r) for r in medication_rows(db,patient_id)],'documentationRuleVersion':1,'documentation':documentation_snapshot(db,patient_id),'rules':current_rules(db)}

def digest(value):
    return sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def follow_up_result(task,today):
    if task['state'] in {'completed','cancelled'}:
        return 'not_matched','This task is closed, so it is not overdue.'
    if task['state']!='open':return 'not_evaluable','The task state is unknown.'
    if not task.get('dueDate'):return 'not_evaluable','This open task has no due date. Its overdue status cannot be determined.'
    try:due=date.fromisoformat(task['dueDate'])
    except (ValueError,TypeError):return 'not_evaluable','The recorded due date is invalid.'
    if due<today:return 'matched',f'This task is still open and was due {(today-due).days} day(s) before the evaluation date.'
    return 'not_matched','This open task is due today or later; it is not overdue on the evaluation date.'

def compute(inputs,patient_id):
    today=date.fromisoformat(inputs['evaluationDate']);items=[];rules=inputs['rules']
    for task in inputs['tasks'] if rules['overdue-followup']['enabled'] else []:
        outcome,explanation=follow_up_result(task,today)
        items.append({'id':str(uuid4()),'taskId':task['id'],'name':'Follow-up: '+task['title'],
            'ruleId':'overdue-followup','outcome':outcome,'explanation':explanation,
            'conditions':[{'label':'Recorded task state','value':task['state']},{'label':'Due date','value':task.get('dueDate') or 'Not recorded'},{'label':'Evaluation date (clinic timezone)','value':inputs['evaluationDate']}],
            'evidence':[{'title':'Follow-up: '+task['title'],'href':f'/patients/{patient_id}#follow-ups'}]})
    if not items:
        items.append({'id':str(uuid4()),'name':'Follow-up outstanding','ruleId':'overdue-followup','outcome':'not_evaluable',
            'explanation':'No follow-up tasks are recorded. There is no task to evaluate; this does not mean that follow-up care is unnecessary.',
            'conditions':[{'label':'Recorded tasks','value':'0'},{'label':'Evaluation date (clinic timezone)','value':inputs['evaluationDate']}],'evidence':[]})
    if not rules['overdue-followup']['enabled']:items=[]
    if rules['difficulty-scale']['enabled']:items+=rating_results(inputs.get('ratings',[]),today,rules['difficulty-scale']['parameters']['D'])
    if rules['repeated-concern']['enabled']:items+=concern_results(inputs.get('concerns',[]),inputs.get('sessions',[]),today,rules['repeated-concern']['parameters']['W'],rules['repeated-concern']['parameters']['K'])
    if rules['medication-change']['enabled']:items+=medication_results(inputs.get('medications',[]),today,rules['medication-change']['parameters']['L'])
    if rules['missing-documentation']['enabled']:items+=documentation_results(inputs['documentation'])
    for key,rule in rules.items():
        if not rule['enabled']:items.append({'id':str(uuid4()),'name':rule['name'],'ruleId':key,'outcome':'not_evaluable','explanation':'This rule was disabled at evaluation. No result was calculated.','conditions':[],'evidence':[]})
    for item in items:
        rule=rules[item['ruleId']];item.update(enabled=rule['enabled'],ruleVersion=rule['version'],ruleParameters=rule['parameters'])
    return items


def latest(db,patient_id):
    return db.scalar(select(IndicatorRun).where(IndicatorRun.patient_id==patient_id).order_by(IndicatorRun.created_at.desc(),IndicatorRun.id.desc()).limit(1))

def output(db,user,patient,run,live=None):
    can_write=patient.status=='active' and has_access(db,user,patient.id,write=True) and 'indicators:write' in user.capabilities
    if run is None:return {'items':[],'allowedActions':['evaluate'] if can_write else [],'evaluationId':None}
    payload=decrypt(run.payload,f'indicator-run:{patient.id}:{run.id}')
    reviews=decrypt(run.reviews,f'indicator-reviews:{patient.id}:{run.id}')
    current=run.input_digest==digest(live if live is not None else snapshot(db,patient.id))
    items=[]
    for item in payload['results']:
        review=reviews.get(item['id'],{})
        items.append({**item,'version':run.version,'evaluationId':run.id,
            'ruleVersion':item.get('ruleVersion',1),
            'enabled':item.get('enabled',True),'freshness':'current' if current else 'stale','evaluatedAt':run.created_at,
            'reviewState':review.get('state','unreviewed'),'reviewComment':review.get('comment'),
            'reviewedBy':review.get('actor'),'reviewedAt':review.get('at'),
            'allowedActions':['review'] if can_write and current and not review and item.get('enabled',True) else []})
    return {'items':items,'evaluationId':run.id,'allowedActions':['evaluate'] if can_write else []}

@router.get('')
def get_indicators(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    result=output(db,user,patient,latest(db,patient.id));record_audit(db,request,user,'indicator.list',patient.id);db.commit();return result

@router.post('/evaluate')
def evaluate(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Reactivate the patient before evaluating indicators.')
    inputs=snapshot(db,patient.id);fingerprint=digest(inputs);run=latest(db,patient.id)
    # Repeated clicks with unchanged inputs preserve the existing evaluation/reviews.
    if run is None or run.input_digest!=fingerprint:
        rid=str(uuid4());run=IndicatorRun(id=rid,patient_id=patient.id,created_by=user.id,input_digest=fingerprint,version=1,
            payload=encrypt({'inputs':inputs,'results':compute(inputs,patient.id)},f'indicator-run:{patient.id}:{rid}'),
            reviews=encrypt({},f'indicator-reviews:{patient.id}:{rid}'))
        db.add(run);db.flush();record_audit(db,request,user,'indicator.evaluate',rid)
    else:record_audit(db,request,user,'indicator.evaluation_reused',run.id)
    result=output(db,user,patient,run,inputs);db.commit();return result

class Review(VersionInput):
    evaluationId: UUID
    decision: Literal['acknowledge','dismiss']
    comment: str | None = Field(default=None,max_length=2000)

@router.post('/{indicator_id}/review')
def review_indicator(patient_id:UUID,indicator_id:UUID,data:Review,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patient indicators are read-only.')
    run=latest(db,patient.id)
    if run is None or run.id!=str(data.evaluationId) or run.version!=data.expectedVersion:
        raise HTTPException(409,'The evaluation changed. Refresh before recording your decision.')
    if run.input_digest!=digest(snapshot(db,patient.id)):raise HTTPException(409,'The inputs or clinic date changed. Evaluate again before reviewing.')
    payload=decrypt(run.payload,f'indicator-run:{patient.id}:{run.id}')
    iid=str(indicator_id)
    item=next((i for i in payload['results'] if i['id']==iid),None)
    if item is None:raise HTTPException(404,'Indicator unavailable.')
    if not item.get('enabled',True):raise HTTPException(409,'Disabled rules have no calculated result to review.')
    reviews=decrypt(run.reviews,f'indicator-reviews:{patient.id}:{run.id}')
    if iid in reviews:raise HTTPException(409,'This indicator already has a review decision.')
    reviews[iid]={'state':'acknowledged' if data.decision=='acknowledge' else 'dismissed','comment':(data.comment or '').strip() or None,'actor':user.display_name,'actorId':user.id,'at':now().isoformat()}
    run.reviews=encrypt(reviews,f'indicator-reviews:{patient.id}:{run.id}');run.version+=1
    record_audit(db,request,user,'indicator.'+data.decision,iid);db.flush();result=output(db,user,patient,run);db.commit();return result

@router.get('/history/runs')
def history(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    rows=db.scalars(select(IndicatorRun).where(IndicatorRun.patient_id==patient.id).order_by(IndicatorRun.created_at.desc()).limit(50)).all()
    result={'items':[{'id':r.id,'evaluatedAt':r.created_at} for r in rows]}
    record_audit(db,request,user,'indicator.history',patient.id);db.commit();return result

@router.get('/history/runs/{run_id}')
def historical_run(patient_id:UUID,run_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    run=db.scalar(select(IndicatorRun).where(IndicatorRun.id==str(run_id),IndicatorRun.patient_id==patient.id))
    if run is None:raise HTTPException(404,'Evaluation unavailable.')
    result=output(db,user,patient,run)
    for item in result['items']:item['allowedActions']=[]
    result['allowedActions']=[]
    record_audit(db,request,user,'indicator.history_read',run.id);db.commit();return result
