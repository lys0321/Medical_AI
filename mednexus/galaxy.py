"""医学知识星图布局：把真实掌握度数据转成确定性的星座式可视化结构。

设计纪律（与 evidence.py 一脉相承）：
  · 完全是真实数据的确定性函数——同输入必得同布局，可单测、可复现；
  · 节点携带真实 id/status/score，可回溯到知识点与作答记录，不制造假数据；
  · tone 只编码学习状态（已掌握/需巩固/初步达标/未测评），不表示医学质量高低；
  · 未测评不算"薄弱"，避免制造焦虑；每个节点可点击回到真实学习入口。
"""
import math

VIEW_BOX = (0, 0, 680, 460)
CENTER = (340, 230)
MIN_R = 9.0
MAX_R = 20.0
RING_BASE = 74.0
RING_STEP = 62.0
PHASE = 0.4  # 确定性相位偏移，避免不同环节点正对着重叠

_TONE = {
    '已掌握': 'mastered',
    '初步达标': 'progressing',
    '需巩固': 'weak',
    '未测评': 'untested',
}


def score_radius(score, attempts=0):
    """掌握度→半径：单调、有界。未测评给最小半径，作答越多略微增大。"""
    base = MIN_R if score is None else MIN_R + (MAX_R - MIN_R) * (max(0.0, min(100.0, score)) / 100.0)
    bonus = min(2.0, max(0, attempts) * 0.4)
    return round(min(MAX_R, base + bonus), 2)


def build_galaxy(concepts, stats=None, weak=None):
    """把 overview 的真实数据转成星图布局。不改入参，确定性输出。"""
    concepts = concepts if isinstance(concepts, list) else []
    stats = stats if isinstance(stats, dict) else {}
    weak = weak if isinstance(weak, list) else []

    groups = {}
    for c in concepts:
        if not isinstance(c, dict):
            continue
        unit = str(c.get('unit') or '未分组')
        groups.setdefault(unit, []).append(c)

    clusters = []
    nodes = []
    for idx, (unit, items) in enumerate(groups.items()):
        ring = RING_BASE + idx * RING_STEP
        cluster = {'unit': unit, 'count': len(items), 'ring': round(ring, 2),
                   'center': [CENTER[0], CENTER[1]]}
        clusters.append(cluster)
        n = len(items)
        for j, c in enumerate(items):
            angle = 2 * math.pi * j / n - math.pi / 2 + PHASE * (idx % 2)
            x = round(CENTER[0] + ring * math.cos(angle), 2)
            y = round(CENTER[1] + ring * math.sin(angle), 2)
            status = str(c.get('status') or '未测评')
            score = c.get('score')
            score = score if isinstance(score, (int, float)) else None
            nodes.append({
                'id': c.get('id'), 'name': c.get('name') or c.get('id'),
                'unit': unit, 'cluster': idx,
                'status': status, 'score': score, 'attempts': c.get('attempts', 0),
                'tone': _TONE.get(status, 'untested'),
                'is_weak': status == '需巩固',
                'x': x, 'y': y, 'r': score_radius(score, c.get('attempts', 0)),
                'syllabus_refs': c.get('syllabus_refs', []),
            })

    summary = {
        'total': stats.get('total', len(concepts)),
        'mastered': stats.get('mastered', sum(1 for n in nodes if n['tone'] == 'mastered')),
        'weak': stats.get('weak', sum(1 for n in nodes if n['is_weak'])),
        'assessed': stats.get('assessed', sum(1 for n in nodes if n['attempts'] > 0)),
        'pages_reviewed': len(weak),
        'has_weak': any(n['is_weak'] for n in nodes),
        'source': '本地真实作答数据',
    }
    return {'viewBox': list(VIEW_BOX), 'center': list(CENTER),
            'clusters': clusters, 'nodes': nodes, 'summary': summary}
