"""Pure accounting for how well an agent's ``known``/not-``known`` calls hold up.

A target once classified ``known`` that later leaves ``known`` is an
overconfidence signal; a target once classified non-``known`` that later becomes
``known`` is a confirmation signal. Making the classification is the host's;
counting how the classifications fared is this.
"""

from dataclasses import dataclass
from typing import Literal

EpistemicStatus = Literal["known", "uncertain", "unknown"]


@dataclass(slots=True, frozen=True)
class KnowledgeCalibrationStats:
    """Running counts of epistemic-status transitions across all targets.

    Attributes:
        known_ever: Number of distinct targets ever classified ``known``.
        known_to_nonknown: Of those, how many later left ``known``.
        nonknown_ever: Number of distinct targets ever classified non-``known``
            (``uncertain`` or ``unknown``).
        nonknown_to_known: Of those, how many later became ``known``.
    """

    known_ever: int = 0
    known_to_nonknown: int = 0
    nonknown_ever: int = 0
    nonknown_to_known: int = 0

    def observe_transition(
        self,
        *,
        previous: EpistemicStatus | None,
        status: EpistemicStatus,
        first_time_known: bool,
        first_time_nonknown: bool,
    ) -> KnowledgeCalibrationStats:
        """Return new stats with one more status transition folded in.

        Args:
            previous: The target's epistemic status before this transition, or
                ``None`` if this is the first observation of the target.
            status: The target's epistemic status after this transition.
            first_time_known: Whether this is the first time this target has
                ever been classified ``known`` (caller tracks per-target
                membership; this dataclass only holds aggregate counts).
            first_time_nonknown: Whether this is the first time this target has
                ever been classified non-``known``.

        Returns:
            A new :class:`KnowledgeCalibrationStats` (this type is immutable).
        """
        known_ever = self.known_ever + (1 if first_time_known else 0)
        nonknown_ever = self.nonknown_ever + (1 if first_time_nonknown else 0)
        known_to_nonknown = self.known_to_nonknown
        nonknown_to_known = self.nonknown_to_known
        if previous == "known" and status != "known":
            known_to_nonknown += 1
        if previous is not None and previous != "known" and status == "known":
            nonknown_to_known += 1
        return KnowledgeCalibrationStats(
            known_ever=known_ever,
            known_to_nonknown=known_to_nonknown,
            nonknown_ever=nonknown_ever,
            nonknown_to_known=nonknown_to_known,
        )

    def overconfidence_rate(self) -> float | None:
        """Return the fraction of ever-``known`` targets that later left ``known``."""
        if self.known_ever == 0:
            return None
        return self.known_to_nonknown / self.known_ever

    def unknown_confirmation_rate(self) -> float | None:
        """Return the fraction of ever-non-``known`` targets that later became ``known``."""
        if self.nonknown_ever == 0:
            return None
        return self.nonknown_to_known / self.nonknown_ever
