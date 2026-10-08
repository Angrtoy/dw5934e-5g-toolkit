"""Offline audit of the build validator's fail-closed/no-runtime contract."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
validator = (root / "analysis" / "build_validate_dw5934e_voice_control.py").read_text(encoding="utf-8")

for needle in (
    'add_mutually_exclusive_group(required=True)', 'mode.add_argument("--offline"',
    'mode.add_argument("--remote"', 'sha256sum', 'sftp.put',
    'REMOTE_SOURCE_SHA256=', 'REMOTE_BINARY_SHA256=',
    'gcc -Wall -Wextra -Werror -O2', 'pkg-config --cflags --libs qmi-glib',
    'REMOTE_COMPILE_OK=exact current source compiled/linked; binary was not run',
    'RejectPolicy()', 'known_hosts is required',
):
    assert needle in validator, needle

# The validator must not turn an unavailable remote build into a claimed build,
# nor include a modem/control runtime command.
assert 'except Exception:' not in validator
assert 'qmicli' not in validator
assert 'mbimcli' not in validator
assert 'mmcli' not in validator
assert 'subprocess.run([remote_bin' not in validator
print("VALIDATOR_CONTRACT_AUDIT_OK")
