from datetime import date



def follow_up_result(task,today):
    if task['state'] in {'completed','cancelled'}:
        return 'not_matched','This task is closed, so it is not overdue.'
    if task['state']!='open':return 'not_evaluable','The task state is unknown.'
    if not task.get('dueDate'):return 'not_evaluable','This open task has no due date. Its overdue status cannot be determined.'
    try:due=date.fromisoformat(task['dueDate'])
    except (ValueError,TypeError):return 'not_evaluable','The recorded due date is invalid.'
    if due<today:return 'matched',f'This task is still open and was due {(today-due).days} day(s) before the evaluation date.'
    return 'not_matched','This open task is due today or later; it is not overdue on the evaluation date.'
