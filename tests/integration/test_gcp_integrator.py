import logging
from pathlib import Path
import pytest
import shlex

log = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
async def test_build_and_deploy(ops_test, k8s_core_bundle, series):
    charm = next(Path.cwd().glob("gcp-integrator*.charm"), None)
    if not charm:
        log.info("Build Charm...")
        charm = await ops_test.build_charm(".")

    context = dict(charm=charm, series=series)
    overlays = [
        k8s_core_bundle,
        Path("tests/data/charm.yaml"),
    ]
    bundle, *overlays = await ops_test.async_render_bundles(*overlays, **context)
    log.info("Deploy Charm...")
    model = ops_test.model_full_name
    cmd = (
        f"juju deploy -m {model} {bundle} "
        "--trust " +
        " ".join(f"--overlay={f}" for f in overlays)
    )
    rc, stdout, stderr = await ops_test.run(*shlex.split(cmd))
    assert rc == 0, f"Bundle deploy failed: {(stderr or stdout).strip()}"
    log.info(stdout)
    await ops_test.model.block_until(
        lambda: "gcp-integrator" in ops_test.model.applications, timeout=60
    )
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)
