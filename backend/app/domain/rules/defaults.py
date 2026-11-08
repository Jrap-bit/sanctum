DEFAULTS={
 'repeated-concern':{'name':'Repeated concerns','parameters':{'W':3,'K':3},'bounds':{'W':{'min':2,'max':10},'K':{'min':2,'max':10}},'description':'Count confirmed concerns across the latest dated sessions.'},
 'difficulty-scale':{'name':'Rating increase','parameters':{'D':2},'bounds':{'D':{'min':1,'max':10}},'description':'Compare the latest compatible ratings within 30 days.'},
 'overdue-followup':{'name':'Overdue follow-ups','parameters':{},'bounds':{},'description':'Open tasks are overdue after their due date.'},
 'medication-change':{'name':'Medication changes','parameters':{'L':30},'bounds':{'L':{'min':1,'max':90}},'description':'Check documented changes within the selected number of days.'},
 'missing-documentation':{'name':'Required documentation','parameters':{},'bounds':{},'description':'Require a date status and one Concern, Observation or Intervention entry. Template version 1.'}}
