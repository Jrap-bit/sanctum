from uuid import uuid4



CATEGORIES={'sleep_difficulty':'Sleep difficulty','anxiety':'Anxiety','low_mood':'Low mood','concentration_difficulty':'Concentration difficulty','fatigue':'Fatigue','irritability':'Irritability','social_avoidance':'Social avoidance','work_stress':'Work-related stress'}


def concern_results(concerns,sessions,today,window=3,threshold=3):
    eligible=sorted([s for s in sessions if s['dateStatus']=='known' and s['eventDate'] and s['eventDate']<=today.isoformat()],key=lambda s:(s['eventDate'],s['id']),reverse=True)
    selected=eligible[:window]
    # Same-day notes are distinct sessions; a tie crossing the window boundary is ambiguous.
    ambiguous=len(eligible)>window and eligible[window-1]['eventDate']==eligible[window]['eventDate']
    active=[c for c in concerns if c['state']=='confirmed' and c['freshness']=='current']
    codes=sorted({c['concernCode'] for c in active})
    results=[]
    for code in codes or [None]:
        count=0;missing=0;evidence=[]
        for session in selected:
            candidates=[c for c in active if c['sourceId']==session['id'] and c['sourceVersion']==session['version'] and c['concernCode']==code]
            if len(candidates)!=1:missing+=1;continue
            c=candidates[0]
            evidence.append({'title':f"{CATEGORIES.get(code,'Concern')} · {session['eventDate']} · {c['assertion']}",'href':session['href'],'passage':c['quotation']})
            if c['assertion']=='unknown' or c['assertion']=='possible' or c['temporality']=='unknown' or c['subject']=='unknown':missing+=1
            elif c['assertion']=='present' and c['temporality']=='current' and c['subject']=='patient':count+=1
        outcome='not_evaluable'
        if code is None:explanation='No confirmed concern categories are recorded.'
        elif len(selected)<window:explanation=f'{window} finalized sessions with known dates are required.'
        elif ambiguous:explanation='Several sessions share the date at the selected-session boundary. The latest window cannot be chosen unambiguously.'
        elif missing:explanation=f'{missing} of the latest {window} sessions lack a definite confirmed classification for this concern. Missing information is not treated as absence.'
        else:
            outcome='matched' if count>=threshold else 'not_matched'
            explanation=f'The patient has this concern confirmed as present at {count} of the latest {window} sessions. The rule requires {threshold} of {window}. Denied, historical and other-person statements do not count.'
        results.append({'id':str(uuid4()),'name':'Repeated concern: '+CATEGORIES[code] if code else 'Repeated concerns','ruleId':'repeated-concern','outcome':outcome,'explanation':explanation,
            'conditions':[{'label':'Required pattern','value':f'{threshold} of the latest {window} sessions'},
              {'label':'Eligible dated sessions','value':str(len(eligible))},{'label':'Confirmed present in selected sessions','value':str(count)},
              {'label':'Selected sessions without definite classification','value':str(missing)},
              {'label':'Undated, approximate or future sessions excluded','value':str(len(sessions)-len(eligible))},
              {'label':'Withdrawn or superseded concern records excluded','value':str(len(concerns)-len(active))}],
            'evidence':evidence+[{'title':'Selected session · '+s['eventDate'],'href':s['href']} for s in selected]})
    return results
