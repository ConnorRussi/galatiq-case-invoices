from pathlib import Path

_POLICY_PATH = Path(__file__).with_name("policy.md")


def load_approval_policy() -> str:
    return _POLICY_PATH.read_text(encoding="utf-8")
