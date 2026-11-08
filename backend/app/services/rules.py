from copy import deepcopy
from sqlalchemy import select

from ..db.models import RuleHead
from ..db.models import RuleRevision
from ..db.models import User
from ..domain.rules.defaults import DEFAULTS


def current_rules(db):
 result={key:{'id':key,**deepcopy(value),'version':1,'enabled':True} for key,value in DEFAULTS.items()}
 revisions=db.scalars(select(RuleRevision).join(RuleHead,(RuleHead.id==RuleRevision.rule_id)&(RuleHead.current_version==RuleRevision.version))).all()
 for row in revisions:
  if row.rule_id in result:result[row.rule_id].update(version=row.version,enabled=row.enabled,parameters=row.parameters)
 return result


def output(db):
 items=list(current_rules(db).values())
 for item in items:
  history=db.scalars(select(RuleRevision).where(RuleRevision.rule_id==item['id']).order_by(RuleRevision.version.desc())).all()
  item['history']=[{'version':r.version,'author':db.get(User,r.actor_id).display_name if r.actor_id else 'Built-in defaults','at':r.created_at,'reason':r.reason,'parameters':r.parameters,'enabled':r.enabled} for r in history]
 return {'items':items}
