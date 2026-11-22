"""Run (or, with dry_run, only print) switch and host commands."""

import os
import subprocess
import tempfile
from typing import List


class Executor:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def local(self, cmd: str) -> str:
        """Run a shell command on the traffic server; return stdout. Crashes on non-zero exit."""
        print(f"[local] {cmd}", flush=True)
        if self.dry_run:
            return ""
        return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout

    def eos_exec(self, switch: str, cmd: str) -> str:
        """Run one EOS exec-mode command over ssh (the switch login shell is the EOS CLI)."""
        return self.local(f'ssh {switch} "{cmd}"')

    def eos_config(self, switch: str, tag: str, lines: List[str]) -> None:
        """Merge config `lines` into `switch`'s running-config via flash (same as the original rules.sh)."""
        print(f"[{switch} config {tag}]\n  " + "\n  ".join(lines), flush=True)
        if self.dry_run:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".cfg", delete=False) as f:
            f.write("\n".join(lines) + "\n")
        self.local(f"scp {f.name} {switch}:/mnt/flash/fives_{tag}.cfg")
        os.unlink(f.name)
        self.eos_exec(switch, f"copy flash:fives_{tag}.cfg running-config")
