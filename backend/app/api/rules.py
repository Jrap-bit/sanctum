"""Bounded, versioned settings; no arbitrary rule code."""
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import Field
from pydantic import StrictBool
from pydantic import StrictInt
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.models import RuleHead
from ..db.models import RuleRevision
from ..domain.rules.defaults import DEFAULTS
from ..services.audit import record_audit
from ..services.authorization import require
from ..services.rules import current_rules
from ..services.rules import output
from .deps import CurrentUser
from .deps import Db
from .schemas import VersionInput


router=APIRouter(tags=['Rule settings'])


@router.get('/api/v1/oversight/rules')
def list_rules(user:CurrentUser,db:Db,request:Request):
 require(user,'rules:publish');result=output(db);record_audit(db,request,user,'rule.list',None);db.commit();return result


@router.get('/api/v1/rules')
def inspect_rules(user:CurrentUser,db:Db,request:Request):
 require(user,'clinical:read');result={'items':list(current_rules(db).values())};record_audit(db,request,user,'rule.inspect',None);db.commit();return result


class Publish(VersionInput):
 parameters: dict[str,StrictInt]
 enabled: StrictBool
 reason: str=Field(min_length=1,max_length=1000)
 @field_validator('reason')
 @classmethod
 def clean(cls,v):
  if not v.strip():raise ValueError('Explain the change.')
  return v.strip()


@router.post('/api/v1/oversight/rules/{rule_id}/publish')
def publish(rule_id:str,data:Publish,user:CurrentUser,db:Db,request:Request):
 require(user,'rules:publish')
 if rule_id not in DEFAULTS:raise HTTPException(404,'Rule unavailable.')
 bounds=DEFAULTS[rule_id]['bounds']
 if set(data.parameters)!=set(bounds) or any(not bounds[k]['min']<=v<=bounds[k]['max'] for k,v in data.parameters.items()):raise HTTPException(422,'Use exactly the supported parameters within their displayed bounds.')
 if rule_id=='repeated-concern' and data.parameters['K']>data.parameters['W']:raise HTTPException(422,'Required sessions cannot exceed sessions checked.')
 head=db.scalar(select(RuleHead).where(RuleHead.id==rule_id).with_for_update())
 if head is None:
  head=RuleHead(id=rule_id,current_version=1);db.add(head)
  try:db.flush()
  except IntegrityError:db.rollback();raise HTTPException(409,'The rule changed. Refresh and try again.') from None
  db.add(RuleRevision(rule_id=rule_id,version=1,parameters=DEFAULTS[rule_id]['parameters'],enabled=True,reason='Built-in defaults'))
 if head.current_version!=data.expectedVersion:raise HTTPException(409,'A newer rule version exists. Refresh before publishing.')
 old=db.get(RuleRevision,(rule_id,head.current_version))
 if old and old.parameters==data.parameters and old.enabled==data.enabled:raise HTTPException(409,'These settings are already published.')
 version=head.current_version+1
 db.add(RuleRevision(rule_id=rule_id,version=version,parameters=data.parameters,enabled=data.enabled,reason=data.reason,actor_id=user.id))
 head.current_version=version;record_audit(db,request,user,'rule.publish',rule_id);db.flush();result=output(db);db.commit();return result
