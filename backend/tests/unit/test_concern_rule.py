"""Unit tests for DT-01 repeated-concern rule logic."""
from datetime import date
import pytest
from app.domain.rules.dt01_repeated_concern import concern_results


def fixtures():
 sessions=[{'id':str(i),'version':3,'eventDate':f'2026-11-0{i}','dateStatus':'known','href':'/source'} for i in (1,2,3)]
 facts=[{'sourceId':s['id'],'sourceVersion':3,'concernCode':'sleep_difficulty','state':'confirmed','freshness':'current','assertion':'present','temporality':'current','subject':'patient','quotation':'Sleep difficulty reported.'} for s in sessions]
 return sessions,facts


@pytest.mark.parametrize('change,outcome',[
 ({},'matched'),({'assertion':'denied'},'not_matched'),({'assertion':'possible'},'not_evaluable'),
 ({'subject':'other'},'not_matched'),({'temporality':'historical'},'not_matched'),
 ({'assertion':'unknown'},'not_evaluable'),({'state':'withdrawn'},'not_evaluable'),({'freshness':'stale'},'not_evaluable')])
@pytest.mark.unit
def test_semantics(change,outcome):
 sessions,facts=fixtures();facts[0].update(change)
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']==outcome


@pytest.mark.unit
def test_window_uses_all_sessions_and_distinct_sources():
 sessions,facts=fixtures()
 assert concern_results(facts,sessions[:2],date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions.append({'id':'4','version':1,'eventDate':'2026-11-04','dateStatus':'known','href':'/4'})
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions[-1]['eventDate']='2026-11-01'
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions.pop();facts.append(facts[0].copy())
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'


@pytest.mark.unit
def test_dates_and_same_day_distinct_sessions():
 sessions,facts=fixtures();sessions[0]['dateStatus']='approximate'
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='not_evaluable'
 sessions[0]['dateStatus']='known'
 for s in sessions:s['eventDate']='2026-11-01'
 assert concern_results(facts,sessions,date(2026,11,6))[0]['outcome']=='matched'
