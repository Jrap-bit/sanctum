"""Unit tests for DT-04 medication-change rule logic."""
from datetime import date
import pytest
from app.domain.rules.dt04_medication_change import medication_results


def record(**kw):return {'state':'confirmed','freshness':'current','medicationName':'Synthetic medication','changeStatus':'changed','dateStatus':'known','eventDate':'2026-11-06','href':'/source','quotation':'A change was documented.',**kw}


@pytest.mark.parametrize('changes,expected',[
 ({},'matched'),({'eventDate':'2026-10-07'},'matched'),({'eventDate':'2026-10-06'},'not_matched'),
 ({'changeStatus':'no_change'},'not_matched'),({'changeStatus':'uncertain'},'not_evaluable'),
 ({'dateStatus':'unknown','eventDate':None},'not_evaluable'),({'dateStatus':'approximate'},'not_evaluable'),
 ({'eventDate':'2026-11-07'},'not_evaluable'),({'state':'withdrawn'},'not_evaluable'),({'freshness':'stale'},'not_evaluable')])
@pytest.mark.unit
def test_boundaries(changes,expected):assert medication_results([record(**changes)],date(2026,11,6))[0]['outcome']==expected


@pytest.mark.unit
def test_partial_coverage_is_not_hidden():
 results=medication_results([record(),record(changeStatus='uncertain')],date(2026,11,6))
 assert [r['outcome'] for r in results]==['matched','not_evaluable']
 assert medication_results([],date(2026,11,6))[0]['outcome']=='not_evaluable'
