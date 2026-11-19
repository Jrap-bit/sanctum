"""Unit tests for summary passage resolution, evidence grounding and category checks."""
import pytest
from app.adapters import llm as ai


TEXT='The patient denied alcohol use.'


@pytest.mark.parametrize('source,quote',[('S2',TEXT),('S1','Alcohol use confirmed.'),('S1','   ')])
@pytest.mark.unit
def test_invalid_evidence_rejected(source,quote):
    result=ai.Generated.model_validate({'summary':[{'text':'Example','evidence':[{'sourceId':source,'quote':quote}]}],'facts':[]})
    with pytest.raises(ValueError,match='unsupported_evidence'):ai.grounded(result,[{'text':TEXT}])


@pytest.mark.unit
def test_source_limit_never_truncates():
    with pytest.raises(ValueError,match='source_limit'):ai.check_size([{'wordCount':1,'text':'a'*8001}],'single_session')


@pytest.mark.unit
def test_passage_references_use_exact_original_text():
    text='Alex said “I feel worried.”\nThe patient denied alcohol use.'
    source={'id':'note','text':text,'title':'Session','href':'/source','version':3}
    result=ai.SelectedGeneration.model_validate({'summary':[{'text':'Alcohol use was denied.','evidence':[{'sourceId':'S1','passageId':'P2'}]}],'facts':[]})
    output=ai.resolve_passages(result,[source])
    assert output['paragraphs'][0]['evidence'][0]['passage']=='The patient denied alcohol use.'
    assert output['paragraphs'][0]['evidence'][0]['sourceVersion']==3


@pytest.mark.parametrize('sid,pid',[('S2','P1'),('S1','P99')])
@pytest.mark.unit
def test_invented_passage_references_are_rejected(sid,pid):
    result=ai.SelectedGeneration.model_validate({'summary':[{'text':'Example','evidence':[{'sourceId':sid,'passageId':pid}]}],'facts':[]})
    with pytest.raises(ValueError,match='unsupported_evidence'):
        ai.resolve_passages(result,[{'text':'A documented observation.'}])


@pytest.mark.unit
def test_long_passages_preserve_content_and_fit_quote_limit():
    text=' '.join(['documented']*150)+'。'+'文'*600
    parts=ai.passages(text)
    assert all(len(p)<=450 and p in text for p in parts.values())
    assert ''.join(parts.values())==text


@pytest.mark.parametrize('text,label,expected',[
 ('Alex rated anxiety as 7/10.','intervention','observation'),
 ('Alex attended a team meeting.','intervention','other'),
 ('The therapist guided Alex through a CBT exercise.','intervention','intervention'),
])
@pytest.mark.unit
def test_conservative_category_checks(text,label,expected):
    evidence=[{'sourceId':'S1','quote':text}]
    result=ai.Generated.model_validate({'summary':[{'text':text,'evidence':evidence}],'facts':[{'text':text,'evidence':evidence,'label':label,'assertion':'present','temporality':'current','subject':'patient'}]})
    source={'id':'test','version':1,'title':'Test','href':'/test','text':text}
    fact=ai.grounded(result,[source])['facts'][0]
    assert fact['label']==expected
    if label!=expected:assert fact['modelProposedLabel']==label and fact['reviewNote']
