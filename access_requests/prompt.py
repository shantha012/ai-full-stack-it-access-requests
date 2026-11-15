"""Source-grounded extraction instructions; routing stays in application code."""
from pathlib import Path
POLICY_PATH = Path(__file__).resolve().parents[1] / 'materials/office-policy.md'
PROMPT = '''Extract explicit facts using the supplied schema. Dates are YYYY-MM-DD.
Absent, relative, or conflicting facts are null with explanatory issues.
Preserve exact decoded-message evidence, including both conflicting alternatives.
Explicit corrections replace earlier statements. Changes use the requested NEW permission.
Do not infer facts from export metadata. Named managers are contacts, not approval.
'''
