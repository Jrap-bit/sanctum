"""Unit tests for DT-02 rating-increase rule logic."""
from datetime import date
from uuid import uuid4
import pytest
from app.domain.rules.dt02_rating_increase import rating_results


def row(day,value,**changes):
 return {'id':str(uuid4()),'state':'confirmed','freshness':'current','dateStatus':'known','eventDate':day,'scaleName':'Anxiety','value':value,'higherMeans':'more_difficulty','href':'/source',**changes}


@pytest.mark.parametrize('previous,latest,expected',[(4,6,'matched'),(4,5,'not_matched'),(6,4,'not_matched'),(0,10,'matched'),(4.5,6.5,'matched')])
@pytest.mark.unit
def test_delta_boundary(previous,latest,expected):
 result=rating_results([row('2026-11-01',previous),row('2026-11-06',latest)],date(2026,11,6))
 assert result[0]['outcome']==expected


@pytest.mark.parametrize('values',[
 [],[row('2026-11-01',4)],
 [row('2026-11-01',4),row('2026-11-06',6,scaleName='Sleep')],
 [row('2026-11-01',4),row('2026-11-06',6,higherMeans='less_difficulty')],
 [row('2026-11-01',4),row(None,6,dateStatus='unknown')],
 [row('2026-11-01',4),row('2026-11-06',6,dateStatus='approximate')],
 [row('2026-10-06',4),row('2026-11-06',6)],
 [row('2026-11-06',4),row('2026-11-06',6)],
 [row('2026-11-01',4),row('2026-11-06',6,freshness='stale')],
 [row('2026-11-01',4),row('2026-11-06',6,state='withdrawn')],
])
@pytest.mark.unit
def test_incompatible_or_missing(values):
 assert all(r['outcome']=='not_evaluable' for r in rating_results(values,date(2026,11,6)))


@pytest.mark.unit
def test_inclusive_window_and_latest_pair_only():
 assert rating_results([row('2026-10-07',4),row('2026-11-06',6)],date(2026,11,6))[0]['outcome']=='matched'
 assert rating_results([row('2026-11-01',2),row('2026-11-04',6),row('2026-11-06',5)],date(2026,11,6))[0]['outcome']=='not_matched'


@pytest.mark.unit
def test_scale_names_pair_case_insensitively():
 """DT-02: names are compared case-insensitively, so 'Anxiety' and 'anxiety' form one pair."""
 result=rating_results([row('2026-11-01',4,scaleName='Anxiety'),row('2026-11-06',6,scaleName='anxiety')],date(2026,11,6))
 assert len(result)==1 and result[0]['outcome']=='matched'
