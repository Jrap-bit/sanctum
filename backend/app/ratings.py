from .patients import has_access
"""Explicit clinician-confirmed ratings; values are never inferred from prose."""
from uuid import UUID,uuid4
from datetime import date,timedelta
from hashlib import sha256
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import Field,field_validator
from sqlalchemy import select
from .auth import CurrentUser,Db
from .models import ConfirmedRating,ClinicalNote,now
from .crypto import encrypt,decrypt
from .patients import Input,VersionInput,scoped_patient,require,record_audit
from .summaries import current_note
from .sessions import content_of
router=APIRouter(prefix='/api/v1/patients/{patient_id}/ratings',tags=['Confirmed ratings'])

class RatingInput(Input):
    sourceId: UUID
    sourceVersion: int=Field(ge=1)
    scaleName: str=Field(min_length=1,max_length=100)
    value: float=Field(ge=0,le=10,allow_inf_nan=False)
    higherMeans: Literal['more_difficulty','less_difficulty','unknown']
    confirmed: Literal[True]
    @field_validator('scaleName')
    @classmethod
    def clean(cls,value):
        value=' '.join(value.split())
        if not value:raise ValueError('Name the scale as documented in the source.')
        return value

class Withdrawal(VersionInput):
    reason: str=Field(min_length=1,max_length=1000)
    @field_validator('reason')
    @classmethod
    def clean(cls,value):
        if not value.strip():raise ValueError('Explain why this rating is being withdrawn.')
        return value.strip()

def rows(db,pid):return db.scalars(select(ConfirmedRating).where(ConfirmedRating.patient_id==pid).order_by(ConfirmedRating.created_at,ConfirmedRating.id)).all()

def rating_output(db,row):
    payload=decrypt(row.payload,f'rating:{row.patient_id}:{row.id}')
    note=db.get(ClinicalNote,payload['sourceId'])
    current=bool(note and note.patient_id==row.patient_id and current_note(db,note) and note.version==payload['sourceVersion'])
    return {'id':row.id,'version':row.version,'state':row.state,'freshness':'current' if current else 'stale',**payload,'confirmedAt':row.created_at.isoformat(),'withdrawalReason':decrypt(row.withdrawal,f'rating-withdrawal:{row.patient_id}:{row.id}')['reason'] if row.withdrawal else None}

@router.get('')
def list_ratings(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    result={'items':[rating_output(db,r) for r in rows(db,patient.id)],'allowedActions':['create','withdraw'] if patient.status=='active' and has_access(db,user,patient.id,write=True) and 'indicators:write' in user.capabilities else []}
    record_audit(db,request,user,'rating.list',patient.id);db.commit();return result

@router.get('/sources')
def sources(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    from .summaries import snapshot as note_snapshot
    notes=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient.id,ClinicalNote.state=='finalized').order_by(ClinicalNote.created_at)).all()
    items=[{k:v for k,v in note_snapshot(n).items() if k!='text'} for n in notes if current_note(db,n)]
    record_audit(db,request,user,'rating.sources',patient.id);db.commit();return {'items':items}

@router.post('',status_code=201)
def create_rating(patient_id:UUID,data:RatingInput,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patients are read-only.')
    note=db.scalar(select(ClinicalNote).where(ClinicalNote.id==str(data.sourceId),ClinicalNote.patient_id==patient.id))
    if not current_note(db,note) or note.version!=data.sourceVersion:raise HTTPException(409,'Select a current finalized source note.')
    for old in rows(db,patient.id):
        value=rating_output(db,old)
        if old.state=='confirmed' and value['sourceId']==note.id and value['scaleName'].casefold()==data.scaleName.casefold():
            raise HTTPException(409,'This source already has a confirmed rating for that scale. Withdraw the incorrect rating before recording its replacement.')
    rid=str(uuid4());content=content_of(note)
    payload={'sourceId':note.id,'sourceVersion':note.version,'scaleName':data.scaleName,'value':data.value,'higherMeans':data.higherMeans,
        'eventDate':note.event_date.isoformat() if note.event_date else None,'dateStatus':content.get('dateStatus','known' if note.event_date else 'unknown'),
        'confirmedBy':user.display_name,'confirmedById':user.id,'href':f'/patients/{patient.id}/sessions/{note.id}'}
    row=ConfirmedRating(id=rid,patient_id=patient.id,created_by=user.id,state='confirmed',version=1,payload=encrypt(payload,f'rating:{patient.id}:{rid}'))
    db.add(row);record_audit(db,request,user,'rating.confirm',rid);db.flush();result=rating_output(db,row);db.commit();return result

@router.post('/{rating_id}/withdraw')
def withdraw(patient_id:UUID,rating_id:UUID,data:Withdrawal,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patients are read-only.')
    row=db.scalar(select(ConfirmedRating).where(ConfirmedRating.id==str(rating_id),ConfirmedRating.patient_id==patient.id))
    if row is None:raise HTTPException(404,'Rating unavailable.')
    if row.version!=data.expectedVersion or row.state!='confirmed':raise HTTPException(409,'This rating changed. Refresh before withdrawing it.')
    row.state='withdrawn';row.version+=1;row.withdrawal=encrypt({'reason':data.reason,'actorId':user.id,'at':now().isoformat()},f'rating-withdrawal:{patient.id}:{row.id}')
    record_audit(db,request,user,'rating.withdraw',row.id);db.flush();result=rating_output(db,row);db.commit();return result


def rating_results(ratings,today,threshold=2):
    # Each named scale is evaluated separately; unknown/approximate dates cannot establish order.
    active=[r for r in ratings if r['state']=='confirmed' and r['freshness']=='current']
    groups={}
    for r in active:groups.setdefault(r['scaleName'].casefold(),[]).append(r)
    results=[]
    if not groups:groups[''] = []
    for group in groups.values():
        name=group[0]['scaleName'] if group else 'Reported rating increase'
        conditions=[{'label':'Increase threshold','value':f'{threshold} points'},{'label':'Comparison window','value':'Latest two dated ratings; both within the last 30 days (inclusive)'}]
        evidence=[];outcome='not_evaluable'
        explanation='Two confirmed, current ratings on the same named 0–10 scale are required.'
        excluded=sum(r['state']=='confirmed' and r['freshness']=='stale' for r in ratings)
        conditions.append({'label':'Superseded-source ratings excluded (all scales)','value':str(excluded)})
        if group:
            evidence=[{'title':f"{r['scaleName']}: {r['value']:g}/10 · {r['eventDate'] or 'Undated'}",'href':r['href']} for r in group]
            if any(r['dateStatus']!='known' or not r['eventDate'] for r in group):
                explanation='An active rating has an unknown or approximate date. The latest comparable pair cannot be established.'
            else:
                dated=sorted(group,key=lambda r:(r['eventDate'],r['id']),reverse=True)
                recent=[r for r in dated if today-timedelta(days=30)<=date.fromisoformat(r['eventDate'])<=today]
                conditions.append({'label':'Ratings within the date window','value':str(len(recent))})
                if len(recent)>=2:
                    newer,older=recent[:2]
                    # Ties at either selected date make choosing a pair arbitrary.
                    if sum(r['eventDate']==newer['eventDate'] for r in recent)>1 or sum(r['eventDate']==older['eventDate'] for r in recent)>1:
                        explanation='Multiple ratings share a selected date. Their order is ambiguous; no pair was chosen.'
                    elif any(r['higherMeans']!='more_difficulty' for r in (older,newer)):
                        explanation='Both selected ratings must explicitly use a scale where higher means more difficulty.'
                    else:
                        delta=round(newer['value']-older['value'],6)
                        outcome='matched' if delta>=threshold else 'not_matched'
                        explanation=f"The recorded rating changed from {older['value']:g}/10 to {newer['value']:g}/10 ({delta:+g}). "+(f'The increase meets the {threshold}-point rule.' if delta>=threshold else f'The increase does not meet the {threshold}-point rule.')
                        conditions += [{'label':'Previous rating','value':f"{older['value']:g}/10 on {older['eventDate']}"},{'label':'Latest rating','value':f"{newer['value']:g}/10 on {newer['eventDate']}"},{'label':'Change','value':f'{delta:+g}'}]
                        evidence=[{'title':f"{r['scaleName']}: {r['value']:g}/10 · {r['eventDate']}",'href':r['href']} for r in (older,newer)]
        results.append({'id':str(uuid4()),'name':'Rating increase: '+name if group else name,'ruleId':'difficulty-scale','outcome':outcome,'explanation':explanation,
            'conditions':conditions,'evidence':evidence})
    return results
