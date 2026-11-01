"""Bind a native-built private ISO's controlled inputs to a bounded host model."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--private-job', type=pathlib.Path, required=True)
    ap.add_argument('--jar', type=pathlib.Path, required=True)
    ap.add_argument('--output', type=pathlib.Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    job, media = a.private_job, a.private_job / 'media'
    plan = json.loads((job / 'plan.json').read_text())
    password_hash = tomllib.loads((media / 'answer.toml').read_text())['global']['root_password_hashed']
    result = subprocess.run(['openssl', 'passwd', '-6', '-salt', password_hash.split('$')[2], '-stdin'],
                            input=(plan['host_password']+'\n').encode(), capture_output=True, check=True)
    password_ok = result.stdout.decode().strip() == password_hash
    spec = importlib.util.spec_from_file_location('first_boot_package', ROOT / 'first_boot_package.py')
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    with tempfile.TemporaryDirectory() as tmp:
        expected = pathlib.Path(tmp) / package.NAME
        package.build(expected)
        unit_ok = sha(expected) == sha(media / package.NAME) == sha(media / 'embedded-first-boot.deb')
    inventory = json.loads((media / 'payload-manifest.json').read_text())
    runtime = ['opendeploy.py','first_boot_package.py','host_health.py','relay-supervisor.cjs',
               'templates/opendeploy-stage2.service','workflow.json']
    assert all(sha(ROOT / name) == inventory[name] for name in runtime)
    expected_hook = (ROOT / 'templates/first-boot.sh').read_text().replace('__MANIFEST_SHA__', sha(media / 'payload-manifest.json'))
    assert (media / 'first-boot.sh').read_bytes() == expected_hook.encode()
    iso_sha = sha(media / 'OpenDeploy-PXVIRT.iso')
    assert iso_sha == json.loads((job / 'media.json').read_text())['outputs'][0]['sha256']
    assert unit_ok and password_ok, 'Controlled native media prerequisite failed'
    probe_ok = 'mount -t iso9660 -o ro' in expected_hook and 'lsblk --list --paths' in expected_hook
    assert probe_ok, 'Whole-device ISO probe missing'
    cases = [('nominal',unit_ok,password_ok,probe_ok,0,True),
             ('three_certificate_failures',unit_ok,password_ok,probe_ok,3,True),
             ('negative_missing_unit',False,password_ok,probe_ok,0,False),
             ('negative_password_cr',unit_ok,False,probe_ok,0,False),
             ('negative_cached_media_probe',unit_ok,password_ok,False,0,False)]
    rows = []
    for name, unit, password, probe, budget, expected_pass in cases:
        cfg = ('SPECIFICATION Spec\nCHECK_DEADLOCK FALSE\nCONSTANTS\n'
               f'UnitIncluded = {str(unit).upper()}\nPasswordMatches = {str(password).upper()}\n'
               f'MediaProbeCorrect = {str(probe).upper()}\n'
               f'InitialCertFailures = {budget}\n'
               'INVARIANTS TypeOK NoFalseReady NoEarlyPendingRemoval\nPROPERTY Completion\n')
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            (directory / 'Host.tla').write_text((HERE / 'Host.tla').read_text())
            (directory / 'Run.cfg').write_text(cfg)
            r = subprocess.run(['java','-Xmx512m','-cp',str(a.jar.resolve()),'tlc2.TLC',
                                '-workers','1','-config','Run.cfg','Host.tla'],
                               cwd=directory, capture_output=True, text=True, timeout=120)
        log = r.stdout + r.stderr
        matched = ('No error has been found' in log and r.returncode == 0) if expected_pass else 'Temporal properties were violated' in log
        (a.output / (name+'.log')).write_text(log)
        (a.output / (name+'.cfg')).write_text(cfg)
        row = {'case':name,'expected':'pass' if expected_pass else 'counterexample','matched':matched}
        rows.append(row)
        print(json.dumps(row), flush=True)
        assert matched, name
    report = {'scope':'Source-reviewed bounded host orchestration; successful firmware/ISO/hardware contracts, fair scheduling; certificate failures bounded to 0/3. Not whole-program or arbitrary failure proof.',
              'iso_sha256':iso_sha,'embedded_package_sha256':sha(media / 'embedded-first-boot.deb'),
              'saved_password_matches_native_answer':password_ok,
              'whole_device_iso_probe_present':probe_ok,
              'runtime_manifest_matches_source':True,'rendered_first_boot_matches_source':True,
              'source_sha256':{name:sha(ROOT/name) for name in runtime+['templates/first-boot.sh']},
              'model_sha256':sha(HERE/'Host.tla'),'tlc_sha256':sha(a.jar),'cases':rows}
    (a.output / 'results.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
