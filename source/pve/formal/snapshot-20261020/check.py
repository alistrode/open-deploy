"""Read-only snapshot binding and TLC orchestration; never launches deployment."""
import argparse
import ast
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
INVENTORY_SHA = '170d1be760883a6f84cd2c729d4699ebca42e34b4a7c3dc18047970adf64b791'
ARCHIVE_SHA = 'e671df74282ea38d5cab8740c85bc0292b8e2c9ac72ca1e2953c893430c4e8eb'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=pathlib.Path, required=True)
    parser.add_argument('--jar', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    root = args.snapshot.resolve(strict=True)
    inventory_path = root / 'snapshot-manifest.json'
    if digest(inventory_path) != INVENTORY_SHA:
        raise ValueError('Not the requested frozen snapshot')
    inventory = json.loads(inventory_path.read_text())
    expected = {item['path']: item for item in inventory['files']}
    actual_files, actual_dirs = set(), set()
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError('Snapshot link changed')
        if path.is_dir():
            actual_dirs.add(name)
        elif name != 'snapshot-manifest.json':
            actual_files.add(name)
            item = expected.get(name)
            if not item or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
                raise ValueError('Snapshot changed: ' + name)
    if actual_files != set(expected) or actual_dirs != set(inventory['directories']):
        raise ValueError('Snapshot inventory differs')
    out = args.output.resolve()
    if out.is_relative_to(root):
        raise ValueError('Evidence must not alter the frozen snapshot')
    out.mkdir(parents=True, exist_ok=True)
    paths = ['Start-Windows.ps1', 'Configure-Windows.ps1',
             'source/pve/opendeploy.py', 'source/pve/workflow.json',
             'source/pve/templates/opendeploy-stage2.service',
             'source/pve/templates/first-boot.sh',
             'source/pve/templates/Guest-Finalize.ps1']
    text = {name: (root / name).read_text(encoding='utf-8') for name in paths}
    service = text['source/pve/templates/opendeploy-stage2.service']
    commands = re.findall(r'^ExecStart=.*?opendeploy\.py (\w+) ', service, re.M)
    if commands != ['bootstrap', 'install']:
        raise ValueError('Unknown service schedule; update abstraction instead of assuming')
    tree = ast.parse(text['source/pve/opendeploy.py'])
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    direct_calls = {}
    for name in ['register', 'bootstrap', 'install', 'finalize', 'main']:
        direct_calls[name] = sorted({n.func.id for n in ast.walk(functions[name])
                                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})
    if any('finalize' in direct_calls[name] for name in ['register', 'bootstrap', 'install']):
        raise ValueError('Automatic schedule changed')
    if 'finalize' not in direct_calls['main']:
        raise ValueError('Explicit finalize dispatcher absent')
    rules = json.loads(text['source/pve/workflow.json'])
    edges = {item['action']: (item['from'], item['to']) for item in rules['transitions']}
    required = {'media.done': ('configured', 'media_ready'), 'host.done': ('media_ready', 'host_ready'),
                'vm.intent': ('host_ready', 'vm_creating'), 'vm.done': ('vm_creating', 'installing'),
                'guest.done': ('installing', 'guest_ready'),
                'snapshot.intent': ('guest_ready', 'snapshotting'),
                'snapshot.done': ('snapshotting', 'complete')}
    if any(edges.get(k) != v for k, v in required.items()):
        raise ValueError('Journal graph changed')
    binding = {'inventory_sha256': INVENTORY_SHA, 'archive_sha256': ARCHIVE_SHA,
               'files_verified': len(actual_files), 'directories_verified': len(actual_dirs),
               'source_commit': (root / 'SOURCE-COMMIT.txt').read_text().strip(),
               'source_sha256': {name: digest(root / name) for name in paths},
               'service_exec_commands': commands, 'direct_python_calls': direct_calls,
               'automatic_finalize': False, 'explicit_finalize_cli': True,
               'mapping_method': 'Hash-bound source review plus AST/entry-point assertions; not full program translation'}
    (out / 'snapshot-binding.json').write_text(json.dumps(binding, indent=2) + '\n')
    print('Fixed snapshot verified; actual scheduled commands:', commands, flush=True)
    cases = [
        ('automatic_safety', False, False, False, True, False, None, 'pass'),
        ('automatic_completion', False, False, False, True, True, None, 'temporal_counterexample'),
        ('explicit_finalize_nominal', True, False, False, True, True, None, 'pass'),
        ('explicit_finalize_one_failure', True, True, False, True, True, None, 'temporal_counterexample'),
        ('explicit_finalize_rerun', True, True, True, True, True, None, 'pass'),
        ('unconfigured_one_click', False, False, False, False, True, None, 'temporal_counterexample'),
        ('negative_missing_rdp_guard', True, False, False, True, False, 'rdp', 'invariant_counterexample')]
    results = []
    source = (HERE / 'Snapshot.tla').read_text()
    shutil.copy2(HERE / 'Snapshot.tla', out / 'Snapshot.tla')
    for name, manual, fault, rerun, configured, temporal, mutation, expected_result in cases:
        cfg = ('SPECIFICATION Spec\nCHECK_DEADLOCK FALSE\nCONSTANTS\n'
               'AutoFinalize = FALSE\nManualFinalize = %s\nFaultOnce = %s\nAllowRerun = %s\nConfigured = %s\n'
               'INVARIANTS TypeOK NoFalseComplete NoUnscheduledFinalize\n') % tuple(
                   str(value).upper() for value in [manual, fault, rerun, configured])
        if temporal:
            cfg += 'PROPERTY Completion\n'
        model = source
        if mutation:
            model = source.replace('/\\ snapshotVerified /\\ guestHealthy /\\ rdpReady\n            /\\ phase\'',
                                   '/\\ snapshotVerified /\\ guestHealthy\n            /\\ phase\'')
            if model == source:
                raise ValueError('Mutation did not apply')
        (out / (name + '.cfg')).write_text(cfg)
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            (work / 'Snapshot.tla').write_text(model)
            (work / 'Run.cfg').write_text(cfg)
            process = subprocess.run(['java', '-Xmx512m', '-cp', str(args.jar.resolve()),
                                      'tlc2.TLC', '-workers', '1', '-config', 'Run.cfg', 'Snapshot.tla'],
                                     cwd=work, capture_output=True, text=True, timeout=120)
            log = process.stdout + process.stderr
        (out / (name + '.log')).write_text(log)
        if expected_result == 'pass':
            matched = process.returncode == 0 and 'No error has been found' in log
        elif expected_result == 'temporal_counterexample':
            matched = 'Temporal properties were violated' in log and 'Stuttering' in log
        else:
            matched = 'Invariant NoFalseComplete is violated' in log
        row = {'case': name, 'expected': expected_result, 'matched': matched,
               'exit_code': process.returncode, 'manual_finalize_required': manual,
               'single_finite_command_failure': fault, 'explicit_rerun_allowed': rerun,
               'completion_claim_passed': expected_result == 'pass' and temporal}
        states = re.findall(r'([\d,]+) distinct states found', log)
        if states:
            row['distinct_states'] = int(states[-1].replace(',', ''))
        results.append(row)
        print(json.dumps(row), flush=True)
        if not matched:
            raise SystemExit(log[-8000:])
    report = {'target_archive_sha256': ARCHIVE_SHA, 'tlc_sha256': digest(args.jar),
              'model_sha256': digest(HERE / 'Snapshot.tla'),
              'automatic_three_stage_completion_proved': False,
              'per_stage_nominal_model_completion': True,
              'single_launch_per_stage_with_finite_failure_proved': False,
              'snapshot_modified': False, 'deployment_executed': False,
              'iso_contract': 'Assume valid compatible ISO and eventual successful installation; no ISO contents or compatibility theorem',
              'other_assumptions': ['Pre-bound valid configuration unless testing unconfigured entry',
                                    'Normal privileged host APIs, resources, ownership, networking and fair scheduling',
                                    'Truthful command results and guest health observations',
                                    'External media boot performed; physical firmware boot automation is not proved'],
              'scope': 'Finite source-reviewed orchestration abstraction; not a proof of all Python, PowerShell or third-party binary semantics',
              'cases': results}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
