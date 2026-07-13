import shutil
import subprocess
from pathlib import Path


def test_index_frontend_submits_form_and_renders_results():
    node = shutil.which("node")
    assert node is not None, (
        "Node.js is required for the frontend smoke test. Install Node.js and "
        "ensure the 'node' executable is available on PATH."
    )

    runner = Path(__file__).with_name("frontend_smoke_runner.js")
    result = subprocess.run(
        [node, str(runner)],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, (
        "Frontend smoke runner failed.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
