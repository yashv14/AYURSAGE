"""Run real MySQL checks in an isolated Docker project with ephemeral credentials."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4


def main():
    root = Path(__file__).resolve().parents[1]
    project = "ayursage-test-" + uuid4().hex[:12]
    environment = os.environ.copy()
    password = secrets.token_hex(24)
    environment.update(MYSQL_TEST_PASSWORD=password, MYSQL_TEST_PORT="0")
    compose = ["docker", "compose", "-p", project, "-f", str(root / "compose.test.yaml")]
    try:
        subprocess.run(compose + ["up", "-d", "--wait", "--wait-timeout", "180"],
                       cwd=root, env=environment, check=True)
        port = subprocess.check_output(compose + ["port", "mysql", "3306"], cwd=root,
                                       env=environment, text=True).strip().rsplit(":", 1)[1]
        environment["MYSQL_TEST_SERVER_URL"] = f"mysql+pymysql://root:{password}@127.0.0.1:{port}/?charset=utf8mb4"
        environment["REQUIRE_MYSQL_TESTS"] = "1"
        return subprocess.run([sys.executable, "-m", "pytest", "tests/integration", "-p", "no:cacheprovider"],
                              cwd=root, env=environment).returncode
    finally:
        # UUID project name and tmpfs isolate cleanup from development/user databases.
        subprocess.run(compose + ["down"], cwd=root, env=environment, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
