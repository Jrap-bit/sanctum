"""Explicit clinician-confirmed ratings; values are never inferred from prose."""
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
from ..db.models import ConfirmedRating
from ..db.models import now
from ..services.audit import record_audit
from ..services.authorization import has_access
from ..services.authorization import require
from ..services.authorization import scoped_patient
from ..services.ratings import rating_output
from ..services.ratings import rows
from ..services.sessions import content_of
from ..services.summaries import current_note
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


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


@router.get('')
def list_ratings(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    result={'items':[rating_output(db,r) for r in rows(db,patient.id)],'allowedActions':['create','withdraw'] if patient.status=='active' and has_access(db,user,patient.id,write=True) and 'indicators:write' in user.capabilities else []}
    record_audit(db,request,user,'rating.list',patient.id);db.commit();return result


@router.get('/sources')
def sources(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    from ..services.summaries import snapshot as note_snapshot
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
