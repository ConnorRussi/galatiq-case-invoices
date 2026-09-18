"""Load the single normalization contract shared by ingestion stages."""

from pathlib import Path


_POLICY_PATH = Path(__file__).with_name("normalization_policy.md")


def load_normalization_policy() -> str:
    """Return the current shared policy text.

    The file is intentionally read when a prompt is built, so a policy edit is
    reflected by the normalizer, critic, and revision stages without a code
    change or process restart.
    """

    return _POLICY_PATH.read_text(encoding="utf-8").strip()
