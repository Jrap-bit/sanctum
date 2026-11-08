from datetime import date
from datetime import timedelta
from uuid import uuid4



def rating_results(ratings,today,threshold=2):
    # Each named scale is evaluated separately; unknown/approximate dates cannot establish order.
    active=[r for r in ratings if r['state']=='confirmed' and r['freshness']=='current']
    groups={}
    for r in active:groups.setdefault(r['scaleName'].casefold(),[]).append(r)
    results=[]
    if not groups:groups[''] = []
    for group in groups.values():
        name=group[0]['scaleName'] if group else 'Reported rating increase'
        conditions=[{'label':'Increase threshold','value':f'{threshold} points'},{'label':'Comparison window','value':'Latest two dated ratings; both within the last 30 days (inclusive)'}]
        evidence=[];outcome='not_evaluable'
        explanation='Two confirmed, current ratings on the same named 0–10 scale are required.'
        excluded=sum(r['state']=='confirmed' and r['freshness']=='stale' for r in ratings)
        conditions.append({'label':'Superseded-source ratings excluded (all scales)','value':str(excluded)})
        if group:
            evidence=[{'title':f"{r['scaleName']}: {r['value']:g}/10 · {r['eventDate'] or 'Undated'}",'href':r['href']} for r in group]
            if any(r['dateStatus']!='known' or not r['eventDate'] for r in group):
                explanation='An active rating has an unknown or approximate date. The latest comparable pair cannot be established.'
            else:
                dated=sorted(group,key=lambda r:(r['eventDate'],r['id']),reverse=True)
                recent=[r for r in dated if today-timedelta(days=30)<=date.fromisoformat(r['eventDate'])<=today]
                conditions.append({'label':'Ratings within the date window','value':str(len(recent))})
                if len(recent)>=2:
                    newer,older=recent[:2]
                    # Ties at either selected date make choosing a pair arbitrary.
                    if sum(r['eventDate']==newer['eventDate'] for r in recent)>1 or sum(r['eventDate']==older['eventDate'] for r in recent)>1:
                        explanation='Multiple ratings share a selected date. Their order is ambiguous; no pair was chosen.'
                    elif any(r['higherMeans']!='more_difficulty' for r in (older,newer)):
                        explanation='Both selected ratings must explicitly use a scale where higher means more difficulty.'
                    else:
                        delta=round(newer['value']-older['value'],6)
                        outcome='matched' if delta>=threshold else 'not_matched'
                        explanation=f"The recorded rating changed from {older['value']:g}/10 to {newer['value']:g}/10 ({delta:+g}). "+(f'The increase meets the {threshold}-point rule.' if delta>=threshold else f'The increase does not meet the {threshold}-point rule.')
                        conditions += [{'label':'Previous rating','value':f"{older['value']:g}/10 on {older['eventDate']}"},{'label':'Latest rating','value':f"{newer['value']:g}/10 on {newer['eventDate']}"},{'label':'Change','value':f'{delta:+g}'}]
                        evidence=[{'title':f"{r['scaleName']}: {r['value']:g}/10 · {r['eventDate']}",'href':r['href']} for r in (older,newer)]
        results.append({'id':str(uuid4()),'name':'Rating increase: '+name if group else name,'ruleId':'difficulty-scale','outcome':outcome,'explanation':explanation,
            'conditions':conditions,'evidence':evidence})
    return results
