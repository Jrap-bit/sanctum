from hashlib import sha256
from sqlalchemy import select
import json

from ..adapters.crypto import decrypt
from ..db.models import FollowUp
from ..db.models import IndicatorRun
from .authorization import has_access
from .concerns import concern_output
from .concerns import rows as concern_rows
from .concerns import session_snapshot
from .documentation import documentation_snapshot
from .medications import medication_output
from .medications import rows as medication_rows
from .patients import clinic_today
from .patients import task_output
from .ratings import rating_output
from .ratings import rows as rating_rows
from .rules import current_rules


RULE_VERSION=1


def snapshot(db,patient_id):
    tasks=[task_output(t) for t in db.scalars(select(FollowUp).where(FollowUp.patient_id==patient_id).order_by(FollowUp.id))]
    # Explicit clinician-created tasks only; no dates inferred from prose or AI.
    return {'evaluationDate':clinic_today().isoformat(),'ruleVersion':RULE_VERSION,'tasks':tasks,'ratingRuleVersion':1,'ratings':[rating_output(db,r) for r in rating_rows(db,patient_id)],'concernRuleVersion':1,'concerns':[concern_output(db,r) for r in concern_rows(db,patient_id)],'sessions':session_snapshot(db,patient_id),'medicationRuleVersion':1,'medications':[medication_output(db,r) for r in medication_rows(db,patient_id)],'documentationRuleVersion':1,'documentation':documentation_snapshot(db,patient_id),'rules':current_rules(db)}


def digest(value):
    return sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


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
