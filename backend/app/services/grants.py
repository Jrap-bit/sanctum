from fastapi import HTTPException
from sqlalchemy import select

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..db.models import ClinicalGrant
from ..db.models import Patient
from ..db.models import User
from ..db.models import now
from .audit import record_audit
from .authorization import require


def result(db,user,row):
 payload=decrypt(row.payload,f'grant:{row.id}')
 person=db.get(User,row.subject_id);approver=db.get(User,row.approver_id) if row.approver_id else None
 independent='grants:approve' in user.capabilities and user.id!=row.subject_id and user.id!=row.requester_id
 actions=[]
 if independent and row.state=='pending':actions=['approve','deny']
 if independent and row.state=='approved':actions=['revoke']
 if row.subject_id==user.id and row.state=='pending':actions=['cancel']
 return {'id':row.id,'version':row.version,'patientId':row.patient_id,'subjectId':row.subject_id,'subjectName':person.display_name,
  'requesterId':row.requester_id,'capability':row.capability,'state':row.state,'createdAt':row.created_at,
  'approverName':approver.display_name if approver else None,'reviewedAt':row.reviewed_at,**payload,'allowedActions':actions}


def locked(db,user,gid,expected):
 row=db.get(ClinicalGrant,str(gid))
 if row is None or ('grants:approve' not in user.capabilities and row.subject_id!=user.id):raise HTTPException(404,'Request unavailable.')
 # Match clinical write lock order; approval/revocation serialize with patient writes.
 db.scalar(select(Patient).where(Patient.id==row.patient_id).with_for_update())
 row=db.scalar(select(ClinicalGrant).where(ClinicalGrant.id==str(gid)).with_for_update().execution_options(populate_existing=True))
 if row.version!=expected:raise HTTPException(409,'This request changed. Refresh before deciding.')
 return row


def save(db,request,user,row,action,comment):
 payload=decrypt(row.payload,f'grant:{row.id}')
 payload['history'].append({'action':action,'comment':comment,'actor':user.display_name,'actorId':user.id,'at':now().isoformat()})
 row.payload=encrypt(payload,f'grant:{row.id}');row.version+=1
 record_audit(db,request,user,'grant.'+action,row.id);db.flush();output=result(db,user,row);db.commit();return output


def independent(user,row):
 require(user,'grants:approve')
 if user.id in {row.requester_id,row.subject_id}:raise HTTPException(403,'You cannot approve or manage your own access request.')
