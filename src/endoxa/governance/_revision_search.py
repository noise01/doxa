"""Lazily enumerate omission sets in policy order, without checking or applying them."""

from collections.abc import Iterator
from heapq import heappop, heappush

from endoxa.governance.premises import Assertion, RevisionPolicy, Rule, Target, target_of

type _Rank = tuple[tuple[int, ...], tuple[tuple[float, ...], ...]]


def _successors(indices: tuple[int, ...], size: int, limit: int) -> tuple[tuple[int, ...], ...]:
    next_index = indices[-1] + 1
    if next_index >= size:
        return ()
    replacement = (*indices[:-1], next_index)
    return (replacement, (*indices, next_index)) if len(indices) < limit else (replacement,)


def ordered_omissions(
    records: tuple[Assertion | Rule, ...],
    policy: RevisionPolicy,
    candidate: Assertion | Rule | None,
    max_withdrawals: int,
) -> Iterator[tuple[_Rank, tuple[Target, ...]]]:
    """Enumerate existing withdrawals and standalone candidate rejection.

    Larger numeric priorities are more important. First minimize counts from the
    most important layer down, then descending confidences within each layer.
    Equal ranks remain equal: indices order enumeration, never select a winner.

    Each subset has one parent and at most two successors: append the next index
    or replace its last index with the next. Both successors have a rank at least
    as costly as their parent, so a heap visits ranks in order. Its frontier grows
    by at most one per visited subset, rather than materializing combinations.
    Candidate rejection is a separate singleton, never mixed with withdrawals.
    """
    eligible = tuple(
        sorted(
            (record for record in records if target_of(record) not in policy.protected),
            key=lambda record: (
                policy.priorities.get(target_of(record), 0),
                record.confidence,
                target_of(record).kind,
                record.id,
            ),
        )
    )
    all_records = (*records, candidate) if candidate is not None else records
    priorities = sorted({policy.priorities.get(target_of(record), 0) for record in all_records}, reverse=True)

    def rank(selected: tuple[Assertion | Rule, ...]) -> _Rank:
        layers: dict[int, list[float]] = {priority: [] for priority in priorities}
        for record in selected:
            layers[policy.priorities.get(target_of(record), 0)].append(record.confidence)
        return (
            tuple(len(layers[priority]) for priority in priorities),
            tuple(tuple(sorted(layers[priority], reverse=True)) for priority in priorities),
        )

    frontier: list[tuple[_Rank, tuple[int, ...]]] = []
    if eligible:
        heappush(frontier, (rank((eligible[0],)), (0,)))
    if candidate is not None and target_of(candidate) not in policy.protected:
        heappush(frontier, (rank((candidate,)), ()))
    while frontier:
        current_rank, indices = heappop(frontier)
        if not indices:
            if candidate is not None:
                yield current_rank, (target_of(candidate),)
            continue
        yield current_rank, tuple(target_of(eligible[index]) for index in indices)
        for successor in _successors(indices, len(eligible), max_withdrawals):
            heappush(frontier, (rank(tuple(eligible[index] for index in successor)), successor))
