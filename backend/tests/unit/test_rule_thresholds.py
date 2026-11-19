"""Unit tests for published rule thresholds applied to the rule functions."""
import pytest
from app.domain.rules.dt02_rating_increase import rating_results
from app.domain.rules.dt01_repeated_concern import concern_results
from app.domain.rules.dt04_medication_change import medication_results
from test_rating_rule import row
from test_concern_rule import fixtures
from test_medication_rule import record
from datetime import date


@pytest.mark.unit
def test_actual_thresholds():
 today=date(2026,11,6)
 assert rating_results([row('2026-11-01',4),row('2026-11-06',6)],today,3)[0]['outcome']=='not_matched'
 sessions,facts=fixtures();facts[0]['assertion']='denied'
 assert concern_results(facts,sessions,today,3,2)[0]['outcome']=='matched'
 assert medication_results([record(eventDate='2026-10-01')],today,40)[0]['outcome']=='matched'
 assert medication_results([record(eventDate='2026-10-01')],today,30)[0]['outcome']=='not_matched'
