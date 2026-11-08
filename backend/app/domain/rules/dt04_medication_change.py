from uuid import uuid4



def medication_results(records,today,lookback=30):
    from datetime import date,timedelta
    active=[r for r in records if r['state']=='confirmed' and r['freshness']=='current']
    results=[]
    for r in active:
        outcome='not_evaluable'
        if r['dateStatus']!='known' or not r['eventDate']:
            explanation=f'The source date is unknown or approximate, so the {lookback}-day window cannot be checked.'
        elif date.fromisoformat(r['eventDate'])>today:
            explanation='The recorded source date is after the evaluation date.'
        elif r['changeStatus']=='uncertain':
            explanation='Whether a medication change was documented is uncertain.'
        elif today-timedelta(days=lookback)<=date.fromisoformat(r['eventDate'])<=today and r['changeStatus']=='changed':
            outcome='matched';explanation=f'A medication change is confirmed in a source dated within the last {lookback} days, including the boundary date.'
        else:
            outcome='not_matched';explanation='This confirmed entry records no change.' if r['changeStatus']=='no_change' else f'This documented change falls outside the last {lookback} days.'
        results.append({'id':str(uuid4()),'name':'Medication change: '+r['medicationName'],'ruleId':'medication-change','outcome':outcome,'explanation':explanation,
            'conditions':[{'label':'Confirmed status','value':r['changeStatus'].replace('_',' ')},{'label':'Source date','value':r['eventDate'] or 'Unknown'},
                {'label':'Window starts (inclusive)','value':(today-timedelta(days=lookback)).isoformat()},{'label':'Evaluation date','value':today.isoformat()},
                {'label':'Withdrawn or superseded entries excluded','value':str(len(records)-len(active))}],
            'evidence':[{'title':r['medicationName']+' · source note','href':r['href'],'passage':r['quotation']}]})
    if not results:
        results.append({'id':str(uuid4()),'name':'Documented medication changes','ruleId':'medication-change','outcome':'not_evaluable',
            'explanation':'No current confirmed medication entries are available. Missing documentation does not mean there were no changes.',
            'conditions':[{'label':'Eligible entries','value':'0'},{'label':'Withdrawn or superseded entries excluded','value':str(len(records))}],'evidence':[]})
    return results
