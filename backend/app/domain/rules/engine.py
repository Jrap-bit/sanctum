from datetime import date
from uuid import uuid4

from .dt01_repeated_concern import concern_results
from .dt02_rating_increase import rating_results
from .dt03_followup_outstanding import follow_up_result
from .dt04_medication_change import medication_results
from .dt05_required_documentation import documentation_results


def compute(inputs,patient_id):
    today=date.fromisoformat(inputs['evaluationDate']);items=[];rules=inputs['rules']
    for task in inputs['tasks'] if rules['overdue-followup']['enabled'] else []:
        outcome,explanation=follow_up_result(task,today)
        items.append({'id':str(uuid4()),'taskId':task['id'],'name':'Follow-up: '+task['title'],
            'ruleId':'overdue-followup','outcome':outcome,'explanation':explanation,
            'conditions':[{'label':'Recorded task state','value':task['state']},{'label':'Due date','value':task.get('dueDate') or 'Not recorded'},{'label':'Evaluation date (clinic timezone)','value':inputs['evaluationDate']}],
            'evidence':[{'title':'Follow-up: '+task['title'],'href':f'/patients/{patient_id}#follow-ups'}]})
    if not items:
        items.append({'id':str(uuid4()),'name':'Follow-up outstanding','ruleId':'overdue-followup','outcome':'not_evaluable',
            'explanation':'No follow-up tasks are recorded. There is no task to evaluate; this does not mean that follow-up care is unnecessary.',
            'conditions':[{'label':'Recorded tasks','value':'0'},{'label':'Evaluation date (clinic timezone)','value':inputs['evaluationDate']}],'evidence':[]})
    if not rules['overdue-followup']['enabled']:items=[]
    if rules['difficulty-scale']['enabled']:items+=rating_results(inputs.get('ratings',[]),today,rules['difficulty-scale']['parameters']['D'])
    if rules['repeated-concern']['enabled']:items+=concern_results(inputs.get('concerns',[]),inputs.get('sessions',[]),today,rules['repeated-concern']['parameters']['W'],rules['repeated-concern']['parameters']['K'])
    if rules['medication-change']['enabled']:items+=medication_results(inputs.get('medications',[]),today,rules['medication-change']['parameters']['L'])
    if rules['missing-documentation']['enabled']:items+=documentation_results(inputs['documentation'])
    for key,rule in rules.items():
        if not rule['enabled']:items.append({'id':str(uuid4()),'name':rule['name'],'ruleId':key,'outcome':'not_evaluable','explanation':'This rule was disabled at evaluation. No result was calculated.','conditions':[],'evidence':[]})
    for item in items:
        rule=rules[item['ruleId']];item.update(enabled=rule['enabled'],ruleVersion=rule['version'],ruleParameters=rule['parameters'])
    return items
