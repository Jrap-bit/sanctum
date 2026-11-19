"""Unit tests for DT-03 outstanding follow-up boundaries."""
from datetime import date
import pytest
from app.domain.rules.dt03_followup_outstanding import follow_up_result


@pytest.mark.parametrize('state,due,expected',[
 ('open','2026-11-05','matched'),('open','2026-11-06','not_matched'),('open','2026-11-07','not_matched'),
 ('open',None,'not_evaluable'),('open','bad','not_evaluable'),('completed','2026-11-01','not_matched'),
 ('cancelled',None,'not_matched'),('unknown','2026-11-01','not_evaluable')])
@pytest.mark.unit
def test_boundaries(state,due,expected):
 assert follow_up_result({'state':state,'dueDate':due},date(2026,11,6))[0]==expected
