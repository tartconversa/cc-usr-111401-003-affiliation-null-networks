"""二部状态向团队投影的派生结构。

投影只用于计算统计量与列出结构明细；推断始终在二部参照上进行，
同一活动投影出的多条团队对不构成独立观测。
"""
from itertools import combinations

class Projection:
    __slots__ = ('team_events', 'event_members', 'pair_events', 'neighbors')

    def __init__(self, team_events, event_members, pair_events, neighbors):
        self.team_events = team_events      # 团队 -> {活动}
        self.event_members = event_members  # 活动 -> {团队}
        self.pair_events = pair_events      # (小键, 大键) -> {共同活动}
        self.neighbors = neighbors          # 团队 -> {投影邻居}

def project(teams, events, edges):
    team_events = {t: set() for t in teams}
    event_members = {e: set() for e in events}
    for t, e in edges:
        team_events[t].add(e)
        event_members[e].add(t)
    pair_events = {}
    for e in events:
        for a, b in combinations(sorted(event_members[e]), 2):
            pair_events.setdefault((a, b), set()).add(e)
    neighbors = {t: set() for t in teams}
    for a, b in pair_events:
        neighbors[a].add(b)
        neighbors[b].add(a)
    return Projection(team_events, event_members, pair_events, neighbors)
