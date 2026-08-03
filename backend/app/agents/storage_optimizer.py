"""
Storage Optimizer Agent

Analyzes the files table to surface actionable recommendations: where
space is going, what's safe to review for cleanup, and which categories
(installers, ISOs, temp files, empty folders) are worth a human's
attention. This agent only READS -- it never moves or deletes anything;
that stays the exclusive responsibility of Safe Cleanup Agent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository

_ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}
_ISO_EXTS = {".iso", ".img"}
_INSTALLER_EXTS = {".exe", ".msi", ".msix"}
_TEMP_EXTS = {".tmp", ".temp", ".log", ".bak", ".old"}


@dataclass
class Recommendation:
    category: str
    title: str
    detail: str
    reclaimable_bytes: int
    file_count: int
    severity: str = "info"  # info | suggestion | warning


@dataclass
class OptimizationReport:
    duplicate_bytes: int = 0
    largest_files: list[dict] = field(default_factory=list)
    largest_folders: list[dict] = field(default_factory=list)
    archive_bytes: int = 0
    iso_bytes: int = 0
    installer_bytes: int = 0
    temp_bytes: int = 0
    empty_folder_count: int = 0
    recommendations: list[Recommendation] = field(default_factory=list)


class StorageOptimizerAgent:
    def __init__(self, file_repo: FileRepository, dup_repo: DuplicateRepository):
        self._file_repo = file_repo
        self._dup_repo = dup_repo

    def analyze(self, top_n: int = 10, scan_roots: list[str] | None = None) -> OptimizationReport:
        report = OptimizationReport()

        report.duplicate_bytes = self._dup_repo.total_reclaimable()
        if report.duplicate_bytes > 0:
            report.recommendations.append(Recommendation(
                category="duplicates",
                title="Duplicate files detected",
                detail="Identical files (verified by SHA-256) are consuming space "
                       "that could be reclaimed by keeping only the newest valid copy.",
                reclaimable_bytes=report.duplicate_bytes,
                file_count=self._duplicate_redundant_count(),
                severity="suggestion",
            ))

        largest = self._file_repo.largest_files(limit=top_n)
        report.largest_files = [
            {"path": r["full_path"], "size_bytes": r["size_bytes"]} for r in largest
        ]

        report.largest_folders = self._largest_folders(top_n)

        report.archive_bytes = self._sum_extensions(_ARCHIVE_EXTS)
        report.iso_bytes = self._sum_extensions(_ISO_EXTS)
        report.installer_bytes = self._sum_extensions(_INSTALLER_EXTS)
        report.temp_bytes = self._sum_extensions(_TEMP_EXTS)

        if report.temp_bytes > 0:
            report.recommendations.append(Recommendation(
                category="temp_files",
                title="Temporary and log files found",
                detail="These files are typically safe to review for removal once "
                       "the applications that created them are closed.",
                reclaimable_bytes=report.temp_bytes,
                file_count=len(self._file_repo.by_extension_group(_TEMP_EXTS)),
                severity="suggestion",
            ))

        if report.iso_bytes > 0:
            report.recommendations.append(Recommendation(
                category="isos",
                title="Disk images (ISO/IMG) found",
                detail="ISO/IMG files are often one-time-use installers that are "
                       "rarely needed after initial setup.",
                reclaimable_bytes=report.iso_bytes,
                file_count=len(self._file_repo.by_extension_group(_ISO_EXTS)),
                severity="info",
            ))

        if scan_roots:
            report.empty_folder_count = self._count_empty_folders(scan_roots)
            if report.empty_folder_count:
                report.recommendations.append(Recommendation(
                    category="empty_folders",
                    title="Empty folders found",
                    detail="These folders contain no files and can typically be "
                           "removed to declutter your drive.",
                    reclaimable_bytes=0,
                    file_count=report.empty_folder_count,
                    severity="info",
                ))

        return report

    def _duplicate_redundant_count(self) -> int:
        groups = self._dup_repo.list_groups()
        return sum(max(g["file_count"] - 1, 0) for g in groups)

    def _sum_extensions(self, extensions: set[str]) -> int:
        rows = self._file_repo.by_extension_group(extensions)
        return sum(r["size_bytes"] for r in rows)

    def _largest_folders(self, top_n: int) -> list[dict]:
        # Aggregate over the already-scanned files table rather than
        # walking disk again -- keeps this agent purely a DB reader.
        totals: dict[str, int] = {}
        for row in self._file_repo.largest_files(limit=100000):
            totals[row["folder"]] = totals.get(row["folder"], 0) + row["size_bytes"]
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        return [{"folder": folder, "size_bytes": size} for folder, size in ranked]

    @staticmethod
    def _count_empty_folders(roots: list[str]) -> int:
        count = 0
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                if not dirnames and not filenames:
                    count += 1
        return count
