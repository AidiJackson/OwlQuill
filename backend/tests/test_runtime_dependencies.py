"""Deployment dependency contract for the reference-isolation import chain.

The bug this exists to prevent is invisible to an ordinary import test. In the
workspace, cv2 and numpy are always importable from the dev-local .pythonlibs,
so ``import cv2`` passes whether or not the package is declared. The deployment
build installs ONLY from backend/requirements.txt into .deploy-python, so an
undeclared runtime import is discovered for the first time in production — and
because reference_isolation is imported at module scope by two modules on the
route chain main.py loads at startup, the failure is not a degraded feature but
a service that will not boot.

So these tests assert the DECLARATION, not the import. Same class of failure the
boto3 note in requirements.txt records.
"""
import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REQUIREMENTS = _BACKEND / "requirements.txt"

#: Modules whose module-scope third-party imports must be installable in the
#: deployment image. These sit on the chain app.main imports at startup: main →
#: api.routes.image_generator → services.image_generation_pipeline →
#: services.reference_isolation.
_STARTUP_CHAIN = (
    _BACKEND / "app" / "services" / "reference_isolation.py",
    _BACKEND / "app" / "services" / "image_generation_pipeline.py",
    _BACKEND / "app" / "api" / "routes" / "image_generator.py",
)


def _declared_requirements() -> set[str]:
    """Distribution names pinned in requirements.txt, normalised per PEP 503."""
    names = set()
    for line in _REQUIREMENTS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip extras, version specifiers and environment markers.
        name = re.split(r"[\[<>=!;~ ]", line, maxsplit=1)[0]
        if name:
            names.add(re.sub(r"[-_.]+", "-", name).lower())
    return names


def _module_scope_imports(path: Path) -> set[str]:
    """Top-level import names bound at MODULE scope (not inside a function).

    Function-local imports are excluded deliberately: they are only needed on
    the code path that runs, not to import the module, so they cannot break
    startup. ``editor_self_hosted_pod.py`` relies on exactly that distinction.
    """
    tree = ast.parse(path.read_text())
    found = set()
    for node in tree.body:  # module scope only — not ast.walk
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def _third_party(names: set[str]) -> set[str]:
    """Drop stdlib and first-party imports, leaving installable packages."""
    return {
        n for n in names
        if n not in sys.stdlib_module_names and n not in {"app", "tests"}
    }


@pytest.mark.parametrize("module_path", _STARTUP_CHAIN, ids=lambda p: p.name)
def test_startup_chain_imports_are_declared(module_path):
    """Every third-party package imported at module scope is in requirements."""
    declared = _declared_requirements()
    import_to_dist = packages_distributions()

    undeclared = []
    for import_name in sorted(_third_party(_module_scope_imports(module_path))):
        dists = import_to_dist.get(import_name)
        if not dists:
            # Not installed here; nothing to map. Skip rather than guess a name.
            continue
        normalised = {re.sub(r"[-_.]+", "-", d).lower() for d in dists}
        if not (normalised & declared):
            undeclared.append(f"{import_name} (provided by {sorted(dists)})")

    assert not undeclared, (
        f"{module_path.name} imports these at module scope, but no providing "
        f"distribution is pinned in backend/requirements.txt: {undeclared}. "
        "The deployment installs only from that file, so this would fail at "
        "startup in production while passing locally."
    )


def test_opencv_is_the_headless_wheel():
    """Full opencv-python needs libGL, absent from the Cloud Run image."""
    declared = _declared_requirements()
    assert "opencv-python-headless" in declared
    assert "opencv-python" not in declared, (
        "Full opencv-python links libGL/libgthread, which the deployment "
        "runtime image does not provide. Use opencv-python-headless."
    )


def test_reference_isolation_uses_no_gui_opencv_api():
    """Headless is only a valid substitute while no GUI API is used."""
    source = (_BACKEND / "app" / "services" / "reference_isolation.py").read_text()
    gui = [
        api for api in
        ("imshow", "waitKey", "namedWindow", "destroyAllWindows",
         "createTrackbar", "selectROI", "VideoCapture")
        if f"cv2.{api}" in source
    ]
    assert not gui, f"GUI-only cv2 APIs used, incompatible with headless: {gui}"


def test_haar_cascade_data_ships_with_the_wheel():
    """reference_isolation loads its classifiers from cv2.data at import time."""
    cv2 = pytest.importorskip("cv2")
    cascades = Path(cv2.data.haarcascades)
    for xml in (
        "haarcascade_frontalface_default.xml",
        "haarcascade_frontalface_alt2.xml",
        "haarcascade_eye.xml",
    ):
        assert (cascades / xml).is_file(), f"{xml} missing from the cv2 wheel"
