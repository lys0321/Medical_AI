"""Source-independent reasoning scaffolds; never disclose scoring keys as hints."""
from knowledge import HINTS


def hint_text(question, index, level):
    point = question['points'][index]
    if level == 1:
        return HINTS['level1'].format(label=point['label'])
    if question['kind'] == 'transfer':
        return HINTS['transfer']
    return HINTS['diagnostic']
