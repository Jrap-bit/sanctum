"""Patient-scoped grants with independent approval and revocation."""
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
from ..db.models import ClinicalGrant
from ..db.models import Patient
from ..db.models import User
from ..db.models import now
from ..services.audit import record_audit
from ..services.authorization import has_access
from ..services.authorization import require
from ..services.grants import independent
from ..services.grants import locked
from ..services.grants import result
from ..services.grants import save
from .deps import CurrentUser
from .deps import Db
from .schemas import Input
from .schemas import VersionInput


router=APIRouter(prefix='/api/v1/access/grants',tags=['Access requests'])


class NewRequest(Input):
 patientId: UUID
 capability: Literal['clinical:read','clinical:write']
 reason: str=Field(min_length=1,max_length=2000)
 @field_validator('reason')
 @classmethod
 def clean(cls,v):
  if not v.strip():raise ValueError('Explain why access is needed.')
  return v.strip()


class Decision(VersionInput):
 decision: Literal['approve','deny']
 comment: str=Field(min_length=1,max_length=2000)
 @field_validator('comment')
 @classmethod
 def clean(cls,v):
  if not v.strip():raise ValueError('Explain this decision.')
  return v.strip()


class Revoke(VersionInput):
 reason: str=Field(min_length=1,max_length=2000)
 @field_validator('reason')
 @classmethod
 def clean(cls,v):
  if not v.strip():raise ValueError('Explain why access is being revoked.')
  return v.strip()


@router.get('')
def listing(user:CurrentUser,db:Db,request:Request):
 if not {'grants:request','grants:approve'}&set(user.capabilities):raise HTTPException(403,'Access requests are unavailable for this account.')
 query=select(ClinicalGrant).order_by(ClinicalGrant.created_at.desc())
 if 'grants:approve' not in user.capabilities:query=query.where(ClinicalGrant.subject_id==user.id)
 output={'items':[result(db,user,row) for row in db.scalars(query)],'canRequest':'grants:request' in user.capabilities and 'clinical:read' in user.capabilities,'canRequestWrite':'clinical:write' in user.capabilities}
 record_audit(db,request,user,'grant.list',None);db.commit();return output


@router.post('',status_code=201)
def create(data:NewRequest,user:CurrentUser,db:Db,request:Request):
 require(user,'grants:request');require(user,data.capability)
 patient=db.scalar(select(Patient).where(Patient.id==str(data.patientId),Patient.status=='active').with_for_update())
 if patient is None:raise HTTPException(404,'Patient unavailable. Check the ID with the responsible clinician.')
 if has_access(db,user,patient.id,write=data.capability=='clinical:write'):raise HTTPException(409,'You already have this level of access.')
 existing=db.scalar(select(ClinicalGrant).where(ClinicalGrant.patient_id==patient.id,ClinicalGrant.subject_id==user.id,ClinicalGrant.capability==data.capability,ClinicalGrant.state=='pending'))
 if existing:raise HTTPException(409,'You already have a pending request for this access.')
 gid=str(uuid4());row=ClinicalGrant(id=gid,patient_id=patient.id,subject_id=user.id,requester_id=user.id,capability=data.capability,state='pending',version=1,payload=encrypt({'reason':data.reason,'history':[]},f'grant:{gid}'))
 db.add(row);record_audit(db,request,user,'grant.request',gid);db.flush();output=result(db,user,row);db.commit();return output


@router.post('/{grant_id}/review')
def review(grant_id:UUID,data:Decision,user:CurrentUser,db:Db,request:Request):
 require(user,'grants:approve');row=locked(db,user,grant_id,data.expectedVersion);independent(user,row)
 if row.state!='pending':raise HTTPException(409,'This request has already been decided.')
 if data.decision=='approve':
  subject=db.get(User,row.subject_id);patient=db.get(Patient,row.patient_id)
  if not subject.active or not subject.credentials_ready or subject.password_reset_required or row.capability not in subject.capabilities or patient.status!='active':raise HTTPException(409,'The account or patient is not eligible for this access.')
 row.state='approved' if data.decision=='approve' else 'denied';row.approver_id=user.id;row.reviewed_at=now()
 return save(db,request,user,row,data.decision,data.comment)


@router.post('/{grant_id}/revoke')
def revoke(grant_id:UUID,data:Revoke,user:CurrentUser,db:Db,request:Request):
 require(user,'grants:approve');row=locked(db,user,grant_id,data.expectedVersion);independent(user,row)
 if row.state!='approved':raise HTTPException(409,'Only approved grants can be revoked.')
 row.state='revoked';return save(db,request,user,row,'revoke',data.reason)


@router.post('/{grant_id}/cancel')
def cancel(grant_id:UUID,data:VersionInput,user:CurrentUser,db:Db,request:Request):
 row=locked(db,user,grant_id,data.expectedVersion)
 if row.subject_id!=user.id:raise HTTPException(404,'Request unavailable.')
 if row.state!='pending':raise HTTPException(409,'Only pending requests can be cancelled.')
 row.state='cancelled';return save(db,request,user,row,'cancel','Cancelled by requester')
