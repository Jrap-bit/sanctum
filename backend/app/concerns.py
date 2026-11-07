from .patients import has_access
"""Explicit clinician-confirmed concerns; values are never inferred from prose."""
from uuid import UUID,uuid4
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import Field,field_validator
from sqlalchemy import select
from .auth import CurrentUser,Db
from .models import ConfirmedConcern,ClinicalNote,now
from .crypto import encrypt,decrypt
from .patients import Input,VersionInput,scoped_patient,require,record_audit
from .summaries import current_note
from .sessions import content_of
router=APIRouter(prefix='/api/v1/patients/{patient_id}/concerns',tags=['Confirmed concerns'])

class ConcernInput(Input):
    sourceId: UUID
    sourceVersion: int=Field(ge=1)
    concernCode: Literal['sleep_difficulty','anxiety','low_mood','concentration_difficulty','fatigue','irritability','social_avoidance','work_stress']
    assertion: Literal['present','denied','possible','unknown']
    temporality: Literal['current','historical','unknown']
    subject: Literal['patient','other','unknown']
    quotation: str=Field(min_length=3,max_length=2000)
    confirmed: Literal[True]


class Withdrawal(VersionInput):
    reason: str=Field(min_length=1,max_length=1000)
    @field_validator('reason')
    @classmethod
    def clean(cls,value):
        if not value.strip():raise ValueError('Explain why this concern is being withdrawn.')
        return value.strip()

def rows(db,pid):return db.scalars(select(ConfirmedConcern).where(ConfirmedConcern.patient_id==pid).order_by(ConfirmedConcern.created_at,ConfirmedConcern.id)).all()

def concern_output(db,row):
    payload=decrypt(row.payload,f'concern:{row.patient_id}:{row.id}')
    note=db.get(ClinicalNote,payload['sourceId'])
    current=bool(note and note.patient_id==row.patient_id and current_note(db,note) and note.version==payload['sourceVersion'])
    return {'id':row.id,'version':row.version,'state':row.state,'freshness':'current' if current else 'stale',**payload,'confirmedAt':row.created_at.isoformat(),'withdrawalReason':decrypt(row.withdrawal,f'concern-withdrawal:{row.patient_id}:{row.id}')['reason'] if row.withdrawal else None}

@router.get('')
def list_concerns(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    result={'items':[concern_output(db,r) for r in rows(db,patient.id)],'allowedActions':['create','withdraw'] if patient.status=='active' and has_access(db,user,patient.id,write=True) and 'indicators:write' in user.capabilities else []}
    record_audit(db,request,user,'concern.list',patient.id);db.commit();return result

@router.get('/sources')
def sources(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    from .summaries import snapshot as note_snapshot
    notes=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient.id,ClinicalNote.state=='finalized').order_by(ClinicalNote.created_at)).all()
    items=[{k:v for k,v in note_snapshot(n).items() if k!='text'} for n in notes if current_note(db,n)]
    record_audit(db,request,user,'concern.sources',patient.id);db.commit();return {'items':items}

@router.post('',status_code=201)
def create_concern(patient_id:UUID,data:ConcernInput,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patients are read-only.')
    note=db.scalar(select(ClinicalNote).where(ClinicalNote.id==str(data.sourceId),ClinicalNote.patient_id==patient.id))
    if not current_note(db,note) or note.version!=data.sourceVersion:raise HTTPException(409,'Select a current finalized source note.')
    for old in rows(db,patient.id):
        value=concern_output(db,old)
        if old.state=='confirmed' and value['sourceId']==note.id and value['concernCode']==data.concernCode:
            raise HTTPException(409,'This source already has a confirmed concern for that category. Withdraw the incorrect concern before recording its replacement.')
    rid=str(uuid4());content=content_of(note)
    from .summaries import snapshot as note_snapshot
    if not data.quotation.strip() or ' '.join(data.quotation.split()) not in ' '.join(note_snapshot(note)['text'].split()):
        raise HTTPException(422,'Copy a supporting quotation from the selected source note.')
    payload={'sourceId':note.id,'sourceVersion':note.version,'concernCode':data.concernCode,'assertion':data.assertion,'temporality':data.temporality,'subject':data.subject,'quotation':data.quotation,
        'eventDate':note.event_date.isoformat() if note.event_date else None,'dateStatus':content.get('dateStatus','known' if note.event_date else 'unknown'),
        'confirmedBy':user.display_name,'confirmedById':user.id,'href':f'/patients/{patient.id}/sessions/{note.id}'}
    row=ConfirmedConcern(id=rid,patient_id=patient.id,created_by=user.id,state='confirmed',version=1,payload=encrypt(payload,f'concern:{patient.id}:{rid}'))
    db.add(row);record_audit(db,request,user,'concern.confirm',rid);db.flush();result=concern_output(db,row);db.commit();return result

@router.post('/{concern_id}/withdraw')
def withdraw(patient_id:UUID,concern_id:UUID,data:Withdrawal,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patients are read-only.')
    row=db.scalar(select(ConfirmedConcern).where(ConfirmedConcern.id==str(concern_id),ConfirmedConcern.patient_id==patient.id))
    if row is None:raise HTTPException(404,'Concern unavailable.')
    if row.version!=data.expectedVersion or row.state!='confirmed':raise HTTPException(409,'This concern changed. Refresh before withdrawing it.')
    row.state='withdrawn';row.version+=1;row.withdrawal=encrypt({'reason':data.reason,'actorId':user.id,'at':now().isoformat()},f'concern-withdrawal:{patient.id}:{row.id}')
    record_audit(db,request,user,'concern.withdraw',row.id);db.flush();result=concern_output(db,row);db.commit();return result



CATEGORIES={'sleep_difficulty':'Sleep difficulty','anxiety':'Anxiety','low_mood':'Low mood','concentration_difficulty':'Concentration difficulty','fatigue':'Fatigue','irritability':'Irritability','social_avoidance':'Social avoidance','work_stress':'Work-related stress'}

def session_snapshot(db,patient_id):
    notes=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient_id,ClinicalNote.state=='finalized').order_by(ClinicalNote.id)).all()
    return [{'id':n.id,'version':n.version,'eventDate':n.event_date.isoformat() if n.event_date else None,
        'dateStatus':content_of(n).get('dateStatus','known' if n.event_date else 'unknown'),
        'href':f'/patients/{patient_id}/sessions/{n.id}'} for n in notes if current_note(db,n)]

def concern_results(concerns,sessions,today,window=3,threshold=3):
    eligible=sorted([s for s in sessions if s['dateStatus']=='known' and s['eventDate'] and s['eventDate']<=today.isoformat()],key=lambda s:(s['eventDate'],s['id']),reverse=True)
    selected=eligible[:window]
    # Same-day notes are distinct sessions; a tie crossing the window boundary is ambiguous.
    ambiguous=len(eligible)>window and eligible[window-1]['eventDate']==eligible[window]['eventDate']
    active=[c for c in concerns if c['state']=='confirmed' and c['freshness']=='current']
    codes=sorted({c['concernCode'] for c in active})
    results=[]
    for code in codes or [None]:
        count=0;missing=0;evidence=[]
        for session in selected:
            candidates=[c for c in active if c['sourceId']==session['id'] and c['sourceVersion']==session['version'] and c['concernCode']==code]
            if len(candidates)!=1:missing+=1;continue
            c=candidates[0]
            evidence.append({'title':f"{CATEGORIES.get(code,'Concern')} · {session['eventDate']} · {c['assertion']}",'href':session['href'],'passage':c['quotation']})
            if c['assertion']=='unknown' or c['assertion']=='possible' or c['temporality']=='unknown' or c['subject']=='unknown':missing+=1
            elif c['assertion']=='present' and c['temporality']=='current' and c['subject']=='patient':count+=1
        outcome='not_evaluable'
        if code is None:explanation='No confirmed concern categories are recorded.'
        elif len(selected)<window:explanation=f'{window} finalized sessions with known dates are required.'
        elif ambiguous:explanation='Several sessions share the date at the selected-session boundary. The latest window cannot be chosen unambiguously.'
        elif missing:explanation=f'{missing} of the latest {window} sessions lack a definite confirmed classification for this concern. Missing information is not treated as absence.'
        else:
            outcome='matched' if count>=threshold else 'not_matched'
            explanation=f'The patient has this concern confirmed as present at {count} of the latest {window} sessions. The rule requires {threshold} of {window}. Denied, historical and other-person statements do not count.'
        results.append({'id':str(uuid4()),'name':'Repeated concern: '+CATEGORIES[code] if code else 'Repeated concerns','ruleId':'repeated-concern','outcome':outcome,'explanation':explanation,
            'conditions':[{'label':'Required pattern','value':f'{threshold} of the latest {window} sessions'},
              {'label':'Eligible dated sessions','value':str(len(eligible))},{'label':'Confirmed present in selected sessions','value':str(count)},
              {'label':'Selected sessions without definite classification','value':str(missing)},
              {'label':'Undated, approximate or future sessions excluded','value':str(len(sessions)-len(eligible))},
              {'label':'Withdrawn or superseded concern records excluded','value':str(len(concerns)-len(active))}],
            'evidence':evidence+[{'title':'Selected session · '+s['eventDate'],'href':s['href']} for s in selected]})
    return results
