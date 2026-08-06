"""
Tie-Break Learner

Real, on-device, genuinely-trained machine learning -- deliberately kept
separate from (and never used to influence) the deterministic duplicate
detection and version-decision engines, which stay fully rule-based and
explainable on purpose. This model only ever gets consulted for the one
narrow case where the deterministic engine has already exhausted every
tier and genuinely cannot decide -- the "needs_confirmation" state a
human is required to resolve anyway.

What it does: learns this specific user's own past choices on those
ties, then *suggests* a pick the next time a similar tie occurs. It
never picks automatically -- the suggestion is pre-filled in the
confirmation UI, but the user still has to confirm it (or override it),
exactly like today, just with a head start instead of a blind guess.

Algorithm: multinomial Naive Bayes over a small set of hand-picked,
meaningful categorical features (see extract_features below), with
Laplace smoothing. This is a genuine, textbook probabilistic classifier
-- trained from real accumulated data, producing real confidence scores
-- not just more if/else logic with a new name on it. It's implemented
from scratch in pure Python specifically so this feature adds zero new
dependencies to the PyInstaller build (a real, previously-hard-won-
stable build pipeline not worth risking for this).

Privacy: every training example is the user's own already-local
decision history, stored in the local SQLite database. Nothing here
ever leaves the device, same as everything else in the app.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

# Below this many recorded past decisions, the model doesn't have enough
# signal to be trustworthy -- it stays silent (predict() returns None)
# rather than offering a low-confidence guess dressed up as a suggestion.
MIN_TRAINING_EXAMPLES = 5

# A suggestion is only surfaced if the model's confidence clears this
# bar. Below it, the UI falls back to today's plain "you decide" prompt
# rather than nudging toward a guess the model isn't actually sure about.
MIN_CONFIDENCE_TO_SUGGEST = 0.55


@dataclass
class Candidate:
    """One tied file/folder, described only by the small set of
    attributes the learner reasons about -- never the actual file
    content, never anything beyond what's needed to recognize a
    pattern like 'this user tends to keep the _backup one'."""
    folder_basename: str
    version_label: str  # e.g. "backup_suffix", "old_suffix", "none" -- see version_naming.py
    extension: str
    is_shortest_name: bool  # shortest filename among this specific tied group


@dataclass
class Prediction:
    chosen_index: int
    confidence: float
    reason: str


def extract_features(candidate: Candidate) -> list[tuple[str, str]]:
    """Turns a Candidate into the (feature_name, feature_value) pairs
    the model actually reasons over."""
    return [
        ("folder", candidate.folder_basename.lower()),
        ("version_label", candidate.version_label),
        ("extension", candidate.extension.lower()),
        ("is_shortest_name", str(candidate.is_shortest_name)),
    ]


class TieBreakLearner:
    """Wraps the tie_break_choices table. Counts are recomputed from
    the table on each call rather than cached in memory -- training
    data volume here is inherently small (one row per manually-resolved
    tie a single user encounters, realistically dozens to low hundreds
    over the lifetime of an install), so this stays fast without needing
    any incremental-update complexity."""

    def __init__(self, conn):
        self._conn = conn

    def record_choice(self, candidates: list[Candidate], chosen_index: int) -> None:
        if not (0 <= chosen_index < len(candidates)):
            raise ValueError("chosen_index out of range")
        payload = json.dumps([extract_features(c) for c in candidates])
        self._conn.execute(
            "INSERT INTO tie_break_choices (candidates_json, chosen_index) VALUES (?, ?)",
            (payload, chosen_index),
        )
        self._conn.commit()

    def training_example_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM tie_break_choices").fetchone()
        return row["c"]

    def predict(self, candidates: list[Candidate]) -> Optional[Prediction]:
        total_examples = self.training_example_count()
        if total_examples < MIN_TRAINING_EXAMPLES:
            return None

        chosen_counts, total_counts = self._load_counts()

        scores: list[float] = []
        for candidate in candidates:
            features = extract_features(candidate)
            # Laplace-smoothed log-probability sum -- log space avoids
            # floating-point underflow from multiplying many small
            # probabilities together, standard practice for Naive Bayes.
            log_score = 0.0
            for name, value in features:
                key = (name, value)
                chosen = chosen_counts.get(key, 0)
                seen = total_counts.get(key, 0)
                # +1 / +2 Laplace smoothing: an attribute never seen
                # before gets a modest, non-zero probability rather than
                # either 0% (impossible) or 100% (overconfident).
                prob = (chosen + 1) / (seen + 2)
                log_score += math.log(prob)
            scores.append(log_score)

        # Convert log-scores back to normalized probabilities (softmax
        # over the log-scores) so "confidence" is a real, interpretable
        # 0-1 number, not a raw log-likelihood.
        max_log = max(scores)
        exp_scores = [math.exp(s - max_log) for s in scores]
        total = sum(exp_scores)
        probabilities = [s / total for s in exp_scores]

        best_index = probabilities.index(max(probabilities))
        confidence = probabilities[best_index]

        if confidence < MIN_CONFIDENCE_TO_SUGGEST:
            return None

        winner = candidates[best_index]
        reason = self._explain(winner, chosen_counts, total_counts)
        return Prediction(chosen_index=best_index, confidence=round(confidence, 3), reason=reason)

    def _load_counts(self) -> tuple[dict, dict]:
        chosen_counts: dict[tuple[str, str], int] = defaultdict(int)
        total_counts: dict[tuple[str, str], int] = defaultdict(int)

        rows = self._conn.execute("SELECT candidates_json, chosen_index FROM tie_break_choices").fetchall()
        for row in rows:
            candidates_features = json.loads(row["candidates_json"])
            chosen_index = row["chosen_index"]
            for i, features in enumerate(candidates_features):
                for name, value in features:
                    key = (name, value)
                    total_counts[key] += 1
                    if i == chosen_index:
                        chosen_counts[key] += 1

        return dict(chosen_counts), dict(total_counts)

    def _explain(self, winner: Candidate, chosen_counts: dict, total_counts: dict) -> str:
        """Picks the single most-informative feature behind this
        suggestion, in plain English -- explainability matters here for
        the same reason it matters everywhere else in this app: a
        suggestion nobody can understand the reasoning for isn't
        trustworthy enough to act on, even as a mere pre-fill."""
        best_feature = None
        best_ratio = 0.0
        for name, value in extract_features(winner):
            key = (name, value)
            seen = total_counts.get(key, 0)
            chosen = chosen_counts.get(key, 0)
            if seen >= 2:
                ratio = chosen / seen
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_feature = (name, value, chosen, seen)

        if not best_feature:
            return "Based on your past choices in similar situations."

        name, value, chosen, seen = best_feature
        pct = round(best_ratio * 100)
        labels = {
            "folder": f'you\'ve kept files from "{value}" {pct}% of the time before',
            "version_label": f'you\'ve kept the "{value}" version {pct}% of the time before'
                if value != "none" else f"you've kept plainly-named files {pct}% of the time before",
            "extension": f'you\'ve kept "{value}" files {pct}% of the time before',
            "is_shortest_name": "you tend to keep the file with the shorter name"
                if value == "True" else "you tend to keep the file with the longer, more descriptive name",
        }
        return labels.get(name, "Based on your past choices in similar situations.").capitalize()


def build_candidate(full_path: str, version_label: str, all_names_in_group: list[str]) -> Candidate:
    """Builds a Candidate from data VersionCleanupAgent already has on
    hand -- no extra file reads, no new data collection beyond what the
    app already computed during its normal scan."""
    folder_basename = os.path.basename(os.path.dirname(full_path)) or "root"
    extension = os.path.splitext(full_path)[1]
    this_name = os.path.basename(full_path)
    is_shortest = len(this_name) == min(len(n) for n in all_names_in_group)
    return Candidate(
        folder_basename=folder_basename,
        version_label=version_label or "none",
        extension=extension,
        is_shortest_name=is_shortest,
    )
