"""Check the actual repaired service composition, including finite snapshot failures."""
import argparse,hashlib,json,pathlib,re,subprocess,tempfile
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--jar',type=pathlib.Path,required=True);ap.add_argument('--output',type=pathlib.Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 unit=(ROOT/'templates/opendeploy-stage2.service').read_text()
 commands=re.findall(r'^ExecStart=.*?opendeploy\.py (\w+) ',unit,re.M)
 assert commands==['bootstrap','install','finalize'],commands
 assert 'Restart=on-failure' in unit and 'TimeoutStartSec=infinity' in unit and 'StartLimitIntervalSec=0' in unit
 cases=[('nominal',True,True,0,True),('one_failure',True,True,1,True),('three_failures',True,True,3,True),('negative_no_finalize',False,True,0,False),('negative_no_retry',True,False,1,False)]
 results=[]
 for name,auto,retry,budget,success in cases:
  cfg=f'SPECIFICATION Spec\nCHECK_DEADLOCK FALSE\nCONSTANTS AutoFinalize = {str(auto).upper()}\nManualFinalize = FALSE\nInitialFailures = {budget}\nAutomaticRetry = {str(retry).upper()}\nConfigured = TRUE\nINVARIANTS TypeOK NoFalseComplete NoUnscheduledFinalize\nPROPERTY Completion\n'
  (a.output/(name+'.cfg')).write_text(cfg)
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);(p/'Fixed.tla').write_text((HERE/'Fixed.tla').read_text());(p/'Run.cfg').write_text(cfg)
   r=subprocess.run(['java','-Xmx512m','-cp',str(a.jar.resolve()),'tlc2.TLC','-workers','1','-config','Run.cfg','Fixed.tla'],cwd=p,capture_output=True,text=True,timeout=120)
  log=r.stdout+r.stderr;(a.output/(name+'.log')).write_text(log)
  matched=('No error has been found' in log and r.returncode==0) if success else ('Temporal properties were violated' in log and 'Stuttering' in log)
  row={'case':name,'snapshot_failures':budget,'manual_finalize':False,'expected':'pass' if success else 'counterexample','matched':matched,'exit_code':r.returncode}
  found=re.findall(r'([\d,]+) distinct states found',log)
  if found:row['distinct_states']=int(found[-1].replace(',',''))
  print(json.dumps(row),flush=True);results.append(row)
  if not matched:raise SystemExit(log)
 files=['opendeploy.py','first_boot_package.py','host_health.py','windows/Start-Windows.ps1','windows/build_windows.py','templates/opendeploy-stage2.service','templates/first-boot.sh','workflow.json']
 (a.output/'results.json').write_text(json.dumps({'service_exec_commands':commands,'scope':'Finite source-reviewed orchestration model with valid preconfiguration, successful ISO/guest setup and truthful host APIs; finite failures injected in snapshot operation only; not full interpreter semantics','manual_third_stage_required':False,'source_sha256':{n:sha(ROOT/n) for n in files},'model_sha256':sha(HERE/'Fixed.tla'),'tlc_sha256':sha(a.jar),'cases':results},indent=2)+'\n')
if __name__=='__main__':main()
