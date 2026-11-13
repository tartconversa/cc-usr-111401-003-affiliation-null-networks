"""现有业务摘要，不推断未观察到的业务关系。"""
from itertools import combinations

def analyze(snapshot):
    counts = {}
    teams = {r['id']: r for r in snapshot.rows('teams')}
    for event in snapshot.rows('events'):
        members = sorted(set(event['members']))
        if any(m not in teams or event['layer'] not in teams[m]['layers'] for m in members):
            raise ValueError('活动成员或有效层不存在')
        for a, b in combinations(members, 2):
            key = (event['layer'], a, b)
            counts[key] = counts.get(key, 0) + 1
    return [{'layer': k[0], 'left': k[1], 'right': k[2], 'activities': v}
            for k, v in sorted(counts.items())]
