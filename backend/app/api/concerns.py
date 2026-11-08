"""Explicit clinician-confirmed concerns; values are never inferred from prose."""
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import Field
from pydantic import field_validator
from sqlalchemy import select
from typing import Literal
from uuid import UUID
from uuid import uuid4

from ..adapters.crypto import encrypt
from ..db.models import ClinicalNote
from ..db.models import ConfirmedConcern
from ..db.models import now
from ..services.audit import record_audit
from ..services.authorization import has_access
from ..services.authorization import require
from ..services.authorization import scoped_patient
from ..services.concerns import concern_output
from ..services.concerns import rows
from ..services.sessions import content_of
from ..services.summaries import current_note
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


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


@router.get('')
def list_concerns(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    result={'items':[concern_output(db,r) for r in rows(db,patient.id)],'allowedActions':['create','withdraw'] if patient.status=='active' and has_access(db,user,patient.id,write=True) and 'indicators:write' in user.capabilities else []}
    record_audit(db,request,user,'concern.list',patient.id);db.commit();return result


@router.get('/sources')
def sources(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    from ..services.summaries import snapshot as note_snapshot
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
    from ..services.summaries import snapshot as note_snapshot
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
