"""Unit tests for DT-05 required-documentation completeness logic."""
import pytest
from app.domain.rules.dt05_required_documentation import TEMPLATE, documentation_results


@pytest.mark.parametrize('status,day,content,outcome',[
 ('known','2026-11-06',True,'not_matched'),('unknown',None,True,'not_matched'),
 ('approximate','2026-11-01',True,'not_matched'),('known','2026-11-06',False,'matched'),
 (None,None,True,'matched'),('known',None,True,'matched'),('unknown','2026-11-01',True,'matched')])
@pytest.mark.unit
def test_completeness_cases(status,day,content,outcome):
 note={'id':'note-id','version':3,'dateStatus':status,'eventDate':day,'hasStructuredContent':content,'href':'/note','sourceType':'Session note'}
 result=documentation_results({'template':TEMPLATE,'sessions':[note]})[0]
 assert result['outcome']==outcome
 assert bool(result['missingFields'])==(outcome=='matched')
