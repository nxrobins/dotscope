"""Data models for the enforcement system.

Backward-compatibility facade. All definitions now live in dotscope.models.intent.
"""

from ..models.intent import (  # noqa: F401
    Severity,
    CheckCategory,
    IntentDirective,
    Constraint,
    ConventionRule,
    ProposedFix,
    CheckResult,
    CheckReport,
)
