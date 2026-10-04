import heapq
from typing import Literal, TypedDict

from endoxa.solver.theories.base import TheorySolver

from .types import (
    L_FALSE,
    L_TRUE,
    L_UNDEF,
    NULL_LITERAL,
    UNSAT_LITERAL,
    AssignHook,
    Callbacks,
    Clause,
    LBool,
    Lit,
    VarId,
)


class SATStats(TypedDict):
    conflicts: int
    decisions: int
    propagations: int
    restarts: int


class Trail:
    def __init__(self, on_assign: AssignHook | None = None) -> None:
        self.assignment: list[LBool] = []
        self.level: list[int] = []
        self.reason: list[Clause | None] = []
        self.phase: list[LBool] = []

        self.lit_eval: list[LBool] = []

        self.stack: list[Lit] = []
        self.limits: list[int] = []
        self.on_assign = on_assign

    def add_variable(self) -> VarId:
        var = len(self.assignment)

        self.assignment.append(L_UNDEF)
        self.level.append(0)
        self.reason.append(None)
        self.phase.append(L_UNDEF)

        self.lit_eval.extend([L_UNDEF, L_UNDEF])

        return var

    def assign(self, lit: Lit, reason: Clause | None = None) -> None:
        var = lit >> 1

        self.assignment[var] = L_FALSE if bool(lit & 1) else L_TRUE
        level = self.get_decision_level()
        self.level[var] = level
        self.reason[var] = reason
        self.phase[var] = self.assignment[var]

        self.lit_eval[lit] = L_TRUE
        self.lit_eval[lit ^ 1] = L_FALSE

        self.stack.append(lit)

        if self.on_assign:
            val = not bool(lit & 1)
            self.on_assign(var, val, level, reason)

    def eval_literal(self, lit: Lit) -> LBool:
        return self.lit_eval[lit]

    def backtrack(self, target_level: int) -> None:
        if target_level >= self.get_decision_level():
            return

        limit = self.limits[target_level]
        while len(self.stack) > limit:
            lit = self.stack.pop()
            var = lit >> 1

            self.phase[var] = self.assignment[var]

            self.assignment[var] = L_UNDEF
            self.level[var] = 0
            self.reason[var] = None

            self.lit_eval[var << 1] = L_UNDEF
            self.lit_eval[(var << 1) | 1] = L_UNDEF

        del self.limits[target_level:]

    def push(self) -> None:
        self.limits.append(len(self.stack))

    def get_decision_level(self) -> int:
        return len(self.limits)

    def is_all_assigned(self) -> bool:
        return len(self.stack) == len(self.assignment)


class SATSolver:
    def __init__(self, theory: TheorySolver | None = None, callbacks: Callbacks | None = None) -> None:
        self.theory = theory
        self.callbacks = callbacks

        on_assign = callbacks.get("on_assign") if callbacks else None
        self.trail = Trail(on_assign=on_assign)
        self.clauses: list[Clause] = []
        self.learned: list[Clause] = []
        self.watches: list[list[tuple[Lit, Clause]]] = []
        self.bin_watches: list[list[tuple[Lit, Clause]]] = []
        self.qhead: int = 0
        self.seen: list[bool] = []

        # --- VSIDS ---
        self.activity: list[float] = []
        self.bump_inc = 1.0
        self.decay_factor = 0.95
        self.order_heap: list[tuple[float, VarId]] = []
        self.in_heap: list[bool] = []

        # --- Reduce DB ---
        self.c_bump_inc = 1.0
        self.c_decay_factor = 0.999
        self.reduce_threshold = 2000

        # --- Glucose Restarts (LBD Moving Average) ---
        self.conflicts = 0
        self.conflicts_since_restart = 0

        self.lbd_queue_size = 50
        self.lbd_queue = [0] * self.lbd_queue_size
        self.lbd_queue_pos = 0
        self.lbd_queue_sum = 0

        self.global_lbd_sum = 0
        self.restart_margin = 1.25
        self.restart_cooldown = 50

        self.seen_level: list[bool] = []

        # --- Statistics ---
        self.stats: SATStats = {
            "conflicts": 0,
            "decisions": 0,
            "propagations": 0,
            "restarts": 0,
        }
        self.unsat_core: list[Lit] = []

    def add_variable(self) -> VarId:
        var = self.trail.add_variable()

        self.watches.append([])
        self.watches.append([])
        self.bin_watches.append([])
        self.bin_watches.append([])

        self.seen.append(False)
        self.activity.append(0.0)
        self.in_heap.append(True)
        heapq.heappush(self.order_heap, (0.0, var))
        self.seen_level.append(False)

        return var

    def add_clause(self, literals: list[Lit]) -> bool:  # noqa: C901, PLR0912, PLR0915
        # Empty clause (UNSAT)
        if len(literals) == 0:
            return False

        # Unit clause
        if len(literals) == 1:
            lit = literals[0]
            v = self.trail.eval_literal(lit)
            if v == L_FALSE:
                return False  # Conflict
            if v == L_UNDEF:
                self.trail.assign(lit, reason=None)
            return True

        # Binary Clause
        c = Clause(literals)
        self.clauses.append(c)
        lits = c.literals

        if len(lits) == 2:  # noqa: PLR2004
            lit0, lit1 = lits[0], lits[1]
            self.bin_watches[lit0].append((lit1, c))
            self.bin_watches[lit1].append((lit0, c))

            v0 = self.trail.eval_literal(lit0)
            v1 = self.trail.eval_literal(lit1)

            if v0 == L_FALSE and v1 == L_FALSE:
                return False

            if v0 == L_UNDEF and v1 == L_FALSE:
                self.trail.assign(lit0, reason=c)
            elif v0 == L_FALSE and v1 == L_UNDEF:
                self.trail.assign(lit1, reason=c)

            return True

        # n (>= 3) Clauses: Watcher-priority swap
        best1_idx, best2_idx = 0, 1

        v0 = self.trail.eval_literal(lits[0])
        v1 = self.trail.eval_literal(lits[1])

        if v1 > v0:
            best1_idx, best2_idx = 1, 0
            best1_val, best2_val = v1, v0
        else:
            best1_idx, best2_idx = 0, 1
            best1_val, best2_val = v0, v1

        for i in range(2, len(lits)):
            if best1_val == L_TRUE and best2_val == L_TRUE:
                break

            lit = lits[i]
            v = self.trail.eval_literal(lit)

            if v > best1_val:
                best2_idx = best1_idx
                best2_val = best1_val
                best1_idx = i
                best1_val = v
            elif v > best2_val:
                best2_idx = i
                best2_val = v

        lits[0], lits[best1_idx] = lits[best1_idx], lits[0]
        if best2_idx == 0:
            best2_idx = best1_idx
        lits[1], lits[best2_idx] = lits[best2_idx], lits[1]

        self.watches[lits[0]].append((lits[1], c))
        self.watches[lits[1]].append((lits[0], c))

        if best1_val == L_FALSE:
            return False
        if best1_val == L_UNDEF and best2_val == L_FALSE:
            self.trail.assign(lits[0], reason=c)

        return True

    def check(self, assumptions: list[Lit] | None = None) -> Literal["SAT", "UNSAT"]:  # noqa: C901, PLR0912, PLR0915
        if assumptions is None:
            assumptions = []

        self.unsat_core = []

        while True:
            conflict_clause = self._propagate()

            if conflict_clause is None and self.theory is not None:
                lemmas = self.theory.check()
                for lemma in lemmas:
                    conflict = self._add_theory_lemma(lemma)
                    if conflict is not None and conflict_clause is None:
                        conflict_clause = conflict

            if conflict_clause is not None:
                if self.callbacks and "on_conflict" in self.callbacks:
                    self.callbacks["on_conflict"](conflict_clause)
                # 1. Conflict analysis and generation of learning clauses
                self.conflicts += 1
                self.stats["conflicts"] += 1

                if self.trail.get_decision_level() == 0:
                    self.unsat_core = []
                    return "UNSAT"

                max_level = 0
                for lit in conflict_clause.literals:
                    var = lit >> 1
                    lvl = self.trail.level[var]
                    max_level = max(max_level, lvl)

                if max_level == 0:
                    self.unsat_core = []
                    return "UNSAT"

                curr_level = self.trail.get_decision_level()
                if max_level < curr_level:
                    self.backtrack(max_level)

                learned_literals, backtrack_level = self._analyze_conflict(conflict_clause)
                self.backtrack(backtrack_level)

                if len(learned_literals) == 0:
                    self.unsat_core = []
                    return "UNSAT"

                lbd = 1
                if len(learned_literals) == 1:
                    self.trail.assign(learned_literals[0], reason=None)
                else:
                    lbd = self._compute_lbd(learned_literals)
                    learned_clause = Clause(learned_literals, is_learned=True)
                    learned_clause.lbd = lbd

                    self.learned.append(learned_clause)
                    self._attach_watcher(learned_clause)
                    if self.callbacks and "on_learn" in self.callbacks:
                        self.callbacks["on_learn"](learned_clause)
                    self.trail.assign(learned_literals[0], reason=learned_clause)

                # 2. Glucose restart update and determination
                self.conflicts += 1
                self.conflicts_since_restart += 1
                self.global_lbd_sum += lbd

                old_lbd = self.lbd_queue[self.lbd_queue_pos]
                self.lbd_queue[self.lbd_queue_pos] = lbd
                self.lbd_queue_sum += lbd - old_lbd
                self.lbd_queue_pos = (self.lbd_queue_pos + 1) % self.lbd_queue_size

                if self.conflicts >= self.reduce_threshold:
                    self._reduce_db()
                    self.reduce_threshold += 500

                if self.conflicts >= self.lbd_queue_size and self.conflicts_since_restart >= self.restart_cooldown:
                    short_avg = self.lbd_queue_sum / self.lbd_queue_size
                    global_avg = self.global_lbd_sum / self.conflicts

                    if short_avg > global_avg * self.restart_margin:
                        self.backtrack(0)
                        self.conflicts_since_restart = 0
                        self.stats["restarts"] += 1
            else:
                if self.trail.is_all_assigned():
                    for lit in assumptions:
                        if self.trail.eval_literal(lit) == L_FALSE:
                            self.unsat_core = self.analyze_final(lit, set(assumptions))
                            return "UNSAT"
                    return "SAT"

                next_lit = self._decide(assumptions)
                if next_lit == UNSAT_LITERAL:
                    for lit in assumptions:
                        if self.trail.eval_literal(lit) == L_FALSE:
                            self.unsat_core = self.analyze_final(lit, set(assumptions))
                            break
                    return "UNSAT"

                self.stats["decisions"] += 1
                self.trail.push()
                if self.theory is not None:
                    self.theory.push()

                self.trail.assign(next_lit, reason=None)

    def analyze_final(self, conflict_lit: Lit, assumptions: set[Lit]) -> list[Lit]:
        seen = [False] * len(self.trail.assignment)
        seen[conflict_lit >> 1] = True

        core = []
        if conflict_lit in assumptions:
            core.append(conflict_lit)
        elif (conflict_lit ^ 1) in assumptions:
            core.append(conflict_lit ^ 1)

        for lit in reversed(self.trail.stack):
            var = lit >> 1
            if seen[var]:
                reason = self.trail.reason[var]
                if reason is None:
                    # Follow the literal actually assigned on the trail. Both
                    # polarities may be assumptions, so choosing by variable
                    # would replace a negative premise with its positive rival.
                    if lit in assumptions:
                        core.append(lit)
                else:
                    for r_lit in reason.literals:
                        r_var = r_lit >> 1
                        if r_var != var:
                            seen[r_var] = True

        return list(set(core))

    def _propagate(self) -> Clause | None:  # noqa: C901, PLR0912, PLR0915
        conflict_clause: Clause | None = None

        lit_eval = self.trail.lit_eval
        watches = self.watches
        bin_watches = self.bin_watches
        stack = self.trail.stack

        while self.qhead < len(stack):
            self.stats["propagations"] += 1

            p = stack[self.qhead]
            self.qhead += 1

            if self.theory is not None:
                is_consistent, theory_props = self.theory.assert_literal(p)
                if not is_consistent:
                    lemmas = self.theory.check()
                    if lemmas:
                        return lemmas[0]

                for p_lit in theory_props:
                    val = lit_eval[p_lit]
                    if val == L_UNDEF:
                        reason = self.theory.explain_propagation(p_lit)
                        self.learned.append(reason)
                        self._attach_watcher(reason)
                        self.trail.assign(p_lit, reason=reason)
                    elif val == L_FALSE:
                        return self.theory.explain_propagation(p_lit)

            false_lit = p ^ 1

            for implied_lit, clause in bin_watches[false_lit]:
                if clause.is_deleted:
                    continue

                val = lit_eval[implied_lit]
                if val == L_FALSE:
                    return clause

                if val == L_UNDEF:
                    self.trail.assign(implied_lit, reason=clause)

            watchers = watches[false_lit]
            i, j = 0, 0
            while i < len(watchers):
                blocker, clause = watchers[i]
                i += 1

                if clause.is_deleted:
                    continue

                # 1. Eagerly check using the blocker literal
                if lit_eval[blocker] == L_TRUE:
                    watchers[j] = (blocker, clause)
                    j += 1
                    continue

                lits = clause.literals

                # 2. Normalize the watchers
                if lits[0] == false_lit:
                    lits[0], lits[1] = lits[1], lits[0]

                # Check if the first watch is satisfied
                first_watch = lits[0]
                if lit_eval[first_watch] == L_TRUE:
                    watchers[j] = (first_watch, clause)
                    j += 1
                    continue

                # 3. Find a new watch
                found_new_watch = False
                for k in range(2, len(lits)):
                    lit_k = lits[k]
                    if lit_eval[lit_k] != L_FALSE:
                        lits[1], lits[k] = lits[k], lits[1]

                        watches[lits[1]].append((first_watch, clause))
                        found_new_watch = True
                        break

                if found_new_watch:
                    continue

                # 4. Unit propagate or conflict
                watchers[j] = (first_watch, clause)
                j += 1

                if lit_eval[first_watch] == L_FALSE:
                    # Conflict: no new watch and the first watch is false
                    while i < len(watchers):
                        watchers[j] = watchers[i]
                        i += 1
                        j += 1
                    conflict_clause = clause
                    break

                # Unit propagate: no new watch but the first watch is unassigned
                self.trail.assign(first_watch, reason=clause)

            del watchers[j:]

            if conflict_clause is not None:
                return conflict_clause
        return None

    def _analyze_conflict(self, conflict: Clause) -> tuple[list[Lit], int]:  # noqa: C901, PLR0912
        stack = self.trail.stack

        learned: list[Lit] = [NULL_LITERAL]
        path_c = 0

        trail_idx = len(stack) - 1
        curr_level = self.trail.get_decision_level()
        # Reassigned from ``trail.reason`` below, where a decision variable has no
        # reason at all. The guards inside the loop are the consequence, not caution.
        clause: Clause | None = conflict
        p = NULL_LITERAL

        while True:
            if clause is not None:
                self._bump_clause_activity(clause)

            for lit in clause.literals if clause else []:
                var = lit >> 1
                if var == (p >> 1):
                    continue

                if not self.seen[var] and self.trail.level[var] > 0:
                    self.seen[var] = True

                    self._bump_activity(var)

                    if self.trail.level[var] >= curr_level:
                        path_c += 1
                    else:
                        learned.append(lit)

            while not self.seen[stack[trail_idx] >> 1]:
                trail_idx -= 1

            p = stack[trail_idx]
            trail_idx -= 1
            var_p = p >> 1

            path_c -= 1

            if path_c == 0:
                break

            self.seen[var_p] = False
            clause = self.trail.reason[var_p]

        learned[0] = p ^ 1

        for lit in learned:
            self.seen[lit >> 1] = False

        if len(learned) == 1:
            backtrack_level = 0
        else:
            max_i = 1
            max_level = self.trail.level[learned[1] >> 1]

            for i in range(2, len(learned)):
                lvl = self.trail.level[learned[i] >> 1]
                if lvl > max_level:
                    max_level = lvl
                    max_i = i

            learned[1], learned[max_i] = learned[max_i], learned[1]
            backtrack_level = max_level

        self._decay_clause_activity()
        self._decay_activity()

        return learned, backtrack_level

    def backtrack(self, target_level: int) -> None:
        curr_level = self.trail.get_decision_level()
        if curr_level <= target_level:
            return

        if self.callbacks and "on_backtrack" in self.callbacks:
            self.callbacks["on_backtrack"](target_level)

        if self.theory is not None:
            self.theory.pop(curr_level - target_level)

        limit = self.trail.limits[target_level]
        for i in range(len(self.trail.stack) - 1, limit - 1, -1):
            var = self.trail.stack[i] >> 1

            if not self.in_heap[var]:
                self.in_heap[var] = True
                heapq.heappush(self.order_heap, (-self.activity[var], var))

        self.trail.backtrack(target_level)
        self.qhead = len(self.trail.stack)

    def _decide(self, assumptions: list[Lit]) -> Lit:
        for lit in assumptions:
            val = self.trail.eval_literal(lit)
            if val == L_UNDEF:
                return lit
            if val == L_FALSE:
                return UNSAT_LITERAL

        while self.order_heap:
            neg_act, var = self.order_heap[0]

            if -neg_act < self.activity[var]:
                heapq.heappop(self.order_heap)
                continue

            heapq.heappop(self.order_heap)
            self.in_heap[var] = False

            if self.trail.assignment[var] != L_UNDEF:
                continue

            sign = False
            if self.trail.phase[var] == L_FALSE:
                sign = True

            return (var << 1) | int(sign)

        return NULL_LITERAL

    def _attach_watcher(self, clause: Clause) -> None:
        lit0, lit1 = clause.literals[0], clause.literals[1]
        if len(clause.literals) == 2:  # noqa: PLR2004
            self.bin_watches[lit0].append((lit1, clause))
            self.bin_watches[lit1].append((lit0, clause))
        else:
            self.watches[lit0].append((lit1, clause))
            self.watches[lit1].append((lit0, clause))

    def _bump_activity(self, var: VarId) -> None:
        self.activity[var] += self.bump_inc

        self.in_heap[var] = True
        heapq.heappush(self.order_heap, (-self.activity[var], var))

        if self.bump_inc > 1e100:  # noqa: PLR2004
            for i in range(len(self.activity)):
                self.activity[i] *= 1e-100
            self.bump_inc *= 1e-100

            self.order_heap = [(-self.activity[v], v) for v in range(len(self.activity)) if self.in_heap[v]]
            heapq.heapify(self.order_heap)

    def _decay_activity(self) -> None:
        self.bump_inc /= self.decay_factor

    def _compute_lbd(self, lits: list[Lit]) -> int:
        lbd = 0

        # 1. Eliminate duplication
        for lit in lits:
            var = lit >> 1
            lvl = self.trail.level[var]

            if lvl > 0 and not self.seen_level[lvl]:
                self.seen_level[lvl] = True
                lbd += 1

        # 2. Reset flags
        for lit in lits:
            var = lit >> 1
            lvl = self.trail.level[var]
            if lvl > 0:
                self.seen_level[lvl] = False

        return lbd

    def _bump_clause_activity(self, clause: Clause) -> None:
        if not clause.is_learned:
            return

        clause.activity += self.c_bump_inc
        if clause.activity > 1e20:  # noqa: PLR2004
            for c in self.learned:
                c.activity *= 1e-20
            self.c_bump_inc *= 1e-20

    def _decay_clause_activity(self) -> None:
        self.c_bump_inc /= self.c_decay_factor

    def _reduce_db(self) -> None:
        self.learned.sort(key=lambda c: (c.lbd, -c.activity))

        half = len(self.learned) // 2
        for i in range(half, len(self.learned)):
            c = self.learned[i]
            if c.lbd <= 2:  # noqa: PLR2004
                continue

            if self.trail.reason[c.literals[0] >> 1] is c:
                continue

            c.is_deleted = True

        self.learned = [c for c in self.learned if not c.is_deleted]

    def _add_theory_lemma(self, clause: Clause) -> Clause | None:  # noqa: C901, PLR0912
        clause.is_learned = True
        self.learned.append(clause)
        lits = clause.literals

        if len(lits) == 0:
            return clause

        if len(lits) == 1:
            val = self.trail.eval_literal(lits[0])
            if val == L_FALSE:
                return clause
            if val == L_UNDEF:
                self.trail.assign(lits[0], reason=clause)
            return None

        best1_idx, best2_idx = 0, 1
        v0 = self.trail.eval_literal(lits[0])
        v1 = self.trail.eval_literal(lits[1])

        if v1 > v0:
            best1_idx, best2_idx = 1, 0
            best1_val, best2_val = v1, v0
        else:
            best1_idx, best2_idx = 0, 1
            best1_val, best2_val = v0, v1

        for i in range(2, len(lits)):
            if best1_val == L_TRUE and best2_val == L_TRUE:
                break
            v = self.trail.eval_literal(lits[i])
            if v > best1_val:
                best2_idx = best1_idx
                best2_val = best1_val
                best1_idx = i
                best1_val = v
            elif v > best2_val:
                best2_idx = i
                best2_val = v

        lits[0], lits[best1_idx] = lits[best1_idx], lits[0]
        if best2_idx == 0:
            best2_idx = best1_idx
        lits[1], lits[best2_idx] = lits[best2_idx], lits[1]

        self._attach_watcher(clause)

        if best1_val == L_FALSE:
            return clause
        if best1_val == L_UNDEF and best2_val == L_FALSE:
            self.trail.assign(lits[0], reason=clause)

        return None

    @property
    def model(self) -> dict[VarId, LBool]:
        if not self.trail.is_all_assigned():
            return {}
        return {v: self.trail.assignment[v] for v in range(len(self.trail.assignment))}


CDCLSolver = SATSolver
