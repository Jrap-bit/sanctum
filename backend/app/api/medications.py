"""Explicit clinician-confirmed medications; values are never inferred from prose."""
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
from ..db.models import ConfirmedMedication
from ..db.models import now
from ..services.audit import record_audit
from ..services.authorization import has_access
from ..services.authorization import require
from ..services.authorization import scoped_patient
from ..services.medications import medication_output
from ..services.medications import rows
from ..services.sessions import content_of
from ..services.summaries import current_note
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router=APIRouter(prefix='/api/v1/patients/{patient_id}/medications',tags=['Confirmed medications'])


class MedicationInput(Input):
    sourceId: UUID
    sourceVersion: int=Field(ge=1)
    medicationName: str=Field(min_length=1,max_length=160)
    changeStatus: Literal['changed','no_change','uncertain']
    @field_validator('medicationName')
    @classmethod
    def clean_name(cls,value):
        value=' '.join(value.split())
        if not value:raise ValueError('Enter the medication name as documented.')
        return value
    quotation: str=Field(min_length=3,max_length=2000)
    confirmed: Literal[True]


class Withdrawal(VersionInput):
    reason: str=Field(min_length=1,max_length=1000)
    @field_validator('reason')
    @classmethod
    def clean(cls,value):
        if not value.strip():raise ValueError('Explain why this medication is being withdrawn.')
        return value.strip()


@router.get('')
def list_medications(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    result={'items':[medication_output(db,r) for r in rows(db,patient.id)],'allowedActions':['create','withdraw'] if patient.status=='active' and has_access(db,user,patient.id,write=True) and 'indicators:write' in user.capabilities else []}
    record_audit(db,request,user,'medication.list',patient.id);db.commit();return result


@router.get('/sources')
def sources(patient_id:UUID,user:CurrentUser,db:Db,request:Request):
    patient=scoped_patient(db,user,patient_id,clinical=True)
    from ..services.summaries import snapshot as note_snapshot
    notes=db.scalars(select(ClinicalNote).where(ClinicalNote.patient_id==patient.id,ClinicalNote.state=='finalized').order_by(ClinicalNote.created_at)).all()
    items=[{k:v for k,v in note_snapshot(n).items() if k!='text'} for n in notes if current_note(db,n)]
    record_audit(db,request,user,'medication.sources',patient.id);db.commit();return {'items':items}


@router.post('',status_code=201)
def create_medication(patient_id:UUID,data:MedicationInput,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patients are read-only.')
    note=db.scalar(select(ClinicalNote).where(ClinicalNote.id==str(data.sourceId),ClinicalNote.patient_id==patient.id))
    if not current_note(db,note) or note.version!=data.sourceVersion:raise HTTPException(409,'Select a current finalized source note.')
    for old in rows(db,patient.id):
        value=medication_output(db,old)
        if old.state=='confirmed' and value['sourceId']==note.id and value['medicationName'].casefold()==data.medicationName.casefold():
            raise HTTPException(409,'This source already has a confirmed medication for that medication. Withdraw the incorrect medication before recording its replacement.')
    rid=str(uuid4());content=content_of(note)
    from ..services.summaries import snapshot as note_snapshot
    if not data.quotation.strip() or ' '.join(data.quotation.split()) not in ' '.join(note_snapshot(note)['text'].split()):
        raise HTTPException(422,'Copy a supporting quotation from the selected source note.')
    payload={'sourceId':note.id,'sourceVersion':note.version,'medicationName':data.medicationName,'changeStatus':data.changeStatus,'quotation':data.quotation,
        'eventDate':note.event_date.isoformat() if note.event_date else None,'dateStatus':content.get('dateStatus','known' if note.event_date else 'unknown'),
        'confirmedBy':user.display_name,'confirmedById':user.id,'href':f'/patients/{patient.id}/sessions/{note.id}'}
    row=ConfirmedMedication(id=rid,patient_id=patient.id,created_by=user.id,state='confirmed',version=1,payload=encrypt(payload,f'medication:{patient.id}:{rid}'))
    db.add(row);record_audit(db,request,user,'medication.confirm',rid);db.flush();result=medication_output(db,row);db.commit();return result


@router.post('/{medication_id}/withdraw')
def withdraw(patient_id:UUID,medication_id:UUID,data:Withdrawal,user:CurrentUser,db:Db,request:Request):
    require(user,'indicators:write');patient=scoped_patient(db,user,patient_id,clinical=True,lock=True)
    if patient.status!='active':raise HTTPException(409,'Archived patients are read-only.')
    row=db.scalar(select(ConfirmedMedication).where(ConfirmedMedication.id==str(medication_id),ConfirmedMedication.patient_id==patient.id))
    if row is None:raise HTTPException(404,'Concern unavailable.')
    if row.version!=data.expectedVersion or row.state!='confirmed':raise HTTPException(409,'This medication changed. Refresh before withdrawing it.')
    row.state='withdrawn';row.version+=1;row.withdrawal=encrypt({'reason':data.reason,'actorId':user.id,'at':now().isoformat()},f'medication-withdrawal:{patient.id}:{row.id}')
    record_audit(db,request,user,'medication.withdraw',row.id);db.flush();result=medication_output(db,row);db.commit();return result
