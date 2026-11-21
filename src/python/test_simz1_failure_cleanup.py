from simz1_history_fixtures import dataset
"""Task 2 component checks only: javac/main + event manager + inert launcher.

No Controller/QSim, Validate, massive preflight or approval receipts.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
ARTIFACTS=None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NativeCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global ARTIFACTS
        cls.folder=Path(tempfile.mkdtemp(prefix='failure-cleanup-',dir=ROOT/'runtime'))
        ARTIFACTS=cls.folder
        print('FAILURE_CLEANUP_ARTIFACTS='+str(cls.folder),flush=True)
        history=dataset('cursor')
        paths=[history/name for name in ('matsim-run.log','historical-manifest.json','roster.json')]
        paths += list((ROOT/'runtime/workflow').glob('*'))
        # Task 1 production/test sources must not be changed by these checks.
        paths += [ROOT/name for name in ('python/generate_montecarlo_z1.py','python/simz1_population.py',
            'python/simz1_balanced_od_audit.py','python/simz1_freight.py','python/simz1_route_xml.py',
            'python/test_simz1_route_xml.py','src/test/java/gt/edu/uvg/sim/zona1/PopulationRouteXmlCheck.java',
            '.gitignore')]
        cls.preserved={p:sha(p) for p in paths if p.is_file()}
        (cls.folder/'historical-full.log').write_bytes((history/'matsim-run.log').read_bytes())
        cls.java=Path(os.environ.get('SIMZ1_JDK17',r'C:\Program Files\Java\jdk-17'))/'bin'
        cls.cp=str(ROOT/'target/classes')+os.pathsep+(ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()
        names=['src/main/java/gt/edu/uvg/sim/zona1/'+n+'.java' for n in ('SimZ1Freight','SimZ1FreightCompletion','SimZ1FailureReport')]
        names += ['src/test/java/gt/edu/uvg/sim/zona1/'+n+'.java' for n in ('SimZ1FreightCheck','SimZ1FreightClosureCheck','SimZ1FailureReportCheck')]
        empty=cls.folder/'empty-sourcepath';empty.mkdir()
        cls.command('java-version',[str(cls.java/'java.exe'),'-version'])
        assert 'version "17.' in (cls.folder/'java-version.log').read_text(encoding='utf-8')
        cls.command('compile',[str(cls.java/'javac.exe'),'--release','17','-encoding','UTF-8','-proc:none',
            '-cp',cls.cp,'-sourcepath',str(empty),'-d',str(cls.folder),*[str(ROOT/n) for n in names]])

    @classmethod
    def tearDownClass(cls):
        after={p:sha(p) for p in cls.preserved}
        evidence=dict(before={p.relative_to(ROOT).as_posix():v for p,v in cls.preserved.items()},
                      after={p.relative_to(ROOT).as_posix():v for p,v in after.items()})
        (cls.folder/'preservation.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
        assert cls.preserved==after,'Historical evidence, Task 1 or receipts changed'

    @classmethod
    def command(cls,label,args):
        result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=60)
        (cls.folder/(label+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        (cls.folder/(label+'.command.json')).write_text(json.dumps(dict(command=args,returncode=result.returncode),indent=2),encoding='utf-8')
        if result.returncode:raise AssertionError(f'{label}: exit={result.returncode}\n{result.stdout}\n{result.stderr}')
        return result

    def main(self,name):
        return self.command(name,[str(self.java/'java.exe'),'-Xmx256m','-cp',str(self.folder)+os.pathsep+self.cp,
            'gt.edu.uvg.sim.zona1.'+name])

    def test_closure_component_parallel_manager_no_simulation(self):
        self.assertIn('SIMZ1_FREIGHT_CLOSURE_OK',self.main('SimZ1FreightClosureCheck').stdout)

    def test_failure_report_roundtrip_extractor(self):
        from ejecutar_simz1 import diagnostico_causal_log
        self.main('SimZ1FailureReportCheck')
        result=diagnostico_causal_log(self.folder/'SimZ1FailureReportCheck.log')
        self.assertEqual(result['diagnostic_status'],'explicit_propagated_chain')
        self.assertIn('real binding failure',result['root_cause']['message'])
        self.assertTrue(any(b['context']=='suppressed' for b in result['secondary_errors']))
        (self.folder/'failure-report-extracted.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

    def test_validate_fingerprints_new_components_without_receipts(self):
        from simz1_workflow_state import fingerprint
        workflow=(ROOT/'scripts/simz1_workflow.ps1').read_text(encoding='utf-8')
        self.assertLess(workflow.index('python\\test_simz1_route_xml.py'),workflow.index('python\\test_simz1_failure_cleanup.py'))
        self.assertLess(workflow.index('python\\test_simz1_failure_cleanup.py'),workflow.index("'validated-source.txt'"))
        folder=self.folder/'fingerprint';folder.mkdir()
        from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
        fixed=list(REQUIRED_FIXTURE_FILES)
        changed=['python/test_simz1_failure_cleanup.py','python/test_simz1_signals_config.py','python/ejecutar_simz1.py',
            'src/main/java/gt/edu/uvg/sim/zona1/SimZ1Freight.java','src/main/java/gt/edu/uvg/sim/zona1/SimZ1FailureReport.java',
            'src/test/java/gt/edu/uvg/sim/zona1/SimZ1FreightClosureCheck.java',
            'src/test/java/gt/edu/uvg/sim/zona1/SimZ1FailureReportCheck.java','scripts/simz1_workflow.ps1']
        for name in fixed+changed:
            path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
        for name in changed:
            before=fingerprint(folder);(folder/name).write_text('changed')
            self.assertNotEqual(before,fingerprint(folder),name)


def suite():
    from test_simz1_signals_config import CausalDiagnosticTests, SignalsConfigurationTests
    from test_simz1_freight_closure import FreightClosureTests, FreightEvidenceReaderTests
    loader=unittest.defaultTestLoader
    checks=unittest.TestSuite(loader.loadTestsFromTestCase(c) for c in
        (NativeCleanupTests,CausalDiagnosticTests,FreightClosureTests,FreightEvidenceReaderTests))
    checks.addTest(SignalsConfigurationTests('test_first_causal_error_and_exception_chain_are_not_warnings'))
    return checks


if __name__=='__main__':
    import io,sys
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite())
    print(output.getvalue())
    if ARTIFACTS is not None:
        (ARTIFACTS/'focused-tests.log').write_text(output.getvalue(),encoding='utf-8')
        (ARTIFACTS/'focused-results.json').write_text(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),
            errors=len(result.errors),skipped=len(result.skipped),returncode=0 if result.wasSuccessful() else 1,
            scope='components only',controller_started=False,qsim_started=False,validate_executed=False),indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
