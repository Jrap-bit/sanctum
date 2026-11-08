"""DT-03: deterministic follow-up results with retained source snapshots."""
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import Field
from sqlalchemy import select
from typing import Literal
from uuid import UUID
from uuid import uuid4

from ..adapters.crypto import decrypt
from ..adapters.crypto import encrypt
from ..db.models import IndicatorRun
from ..db.models import now
from ..domain.rules.engine import compute
from ..services.audit import record_audit
from ..services.authorization import require
from ..services.authorization import scoped_patient
from ..services.indicators import digest
from ..services.indicators import latest
from ..services.indicators import output
from ..services.indicators import snapshot
from .deps import CurrentUser
from .deps import Db
from .schemas import VersionInput


router=APIRouter(prefix='/api/v1/patients/{patient_id}/indicators',tags=['Indicators'])


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
