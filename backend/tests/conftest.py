import os
import sys
import tempfile
from pathlib import Path

# Isolate every test session from the real database and media folder.
_tmp = Path(tempfile.mkdtemp(prefix="cerca-case-tests-"))
os.environ.setdefault("CC_DATA_DIR", str(_tmp))
os.environ.setdefault("CC_DATABASE_URL", f"sqlite:///{(_tmp / 'test.db').as_posix()}")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
