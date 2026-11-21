"""Private checkpoint transport tests over synthetic, contract-only graphs.

The fixture producer is deliberately a stub: these tests certify authentication
and binding, not the renderer geometry or any historical simulation result.
"""
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import test_simz1_causal_support_graph as graph_fixture
from simz1_queue_checkpoint import kernel_contract
from simz1_queue_checkpoints import checkpoint_digest, decode_result_payload, encode_result_payload
from simz1_queue_checkpoint_library import CheckpointLibrary, seal_verified_library, _MerkleFrontier, _leaf, _parent


class CheckpointLibraryTests(unittest.TestCase):
    def test_private_frontier_matches_odd_and_even_public_tree_shapes(self):
        for count in (1,2,3,4,5,7,8,9,127,128,129,257):
            with self.subTest(leaves=count):
                witness=_MerkleFrontier()
                level=[_leaf('synthetic-'+str(i),'a'*64) for i in range(count)]
                for leaf in level:witness.add(leaf)
                while len(level)>1:
                    level=[_parent(level[i],level[min(i+1,len(level)-1)]) for i in range(0,len(level),2)]
                self.assertEqual(witness.finish(),level[0])
                self.assertLessEqual(len(witness.levels),count.bit_length())

    def setUp(self):
        fixture=graph_fixture.CausalSupportGraphTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.record=fixture.record('root','a',0,30,1,hold=10)
        fixture.write_source({1:self.record})
        self.manager=fixture.graph('library')
        self.graph=self.manager.__enter__()
        self.addCleanup(self.manager.__exit__,None,None,None)
        self.graph.root('root',1);self.graph.expand();self.graph.components()
        contract=kernel_contract(self.graph.index.receipt['contract'],self.graph.index.receipt['sha256'],fixture.geometry,{})
        class FixtureKernel:
            calls=0;max_request_bytes=0
            def solve(self,packet):
                self.calls+=1
                return dict(states=[dict(request,result=dict(available=True,anchor_m=1,
                    within_storage=True,pose=None,pose_available=False,turn_bounds=[]),
                    input='{}',prepared='{}',release=None,release_recipe=None)
                    for request in packet['requests']])
        # Defer only automatic transport publication so each test can exercise
        # the real seal function at its own trust boundary below.
        with patch('simz1_queue_checkpoint_library.seal_verified_library',
                   side_effect=lambda graph:dict(contract=json.loads(graph.db.execute(
                       "SELECT value FROM metadata WHERE key='checkpoint_contract'").fetchone()[0]))):
            self.outcome=self.graph.evaluate(FixtureKernel(),contract)
        self.assertTrue(self.outcome['converged'])

    def seal(self):
        # Tests emulate the private trusted producer after the synthetic solve.
        # Production must establish this capability by real semantic checks.
        self.graph.verification_complete=True
        self.preparation=seal_verified_library(self.graph)
        return self.preparation

    def reopen(self,preparation=None,expected=None):
        preparation=self.preparation if preparation is None else preparation
        return CheckpointLibrary(preparation,expected=preparation['contract'] if expected is None else expected)

    def preserve_metadata_stamp(self):
        self.graph.db.commit()
        current=self.graph.path.stat()
        self.assertEqual(current.st_size,self.preparation['bytes'],'fixture tamper must not rely on size guard')
        os.utime(self.graph.path,ns=(current.st_atime_ns,self.preparation['mtime_ns']))

    def test_only_private_verified_parent_can_seal_and_open(self):
        self.graph.verification_complete=False
        with self.assertRaises(ValueError):seal_verified_library(self.graph)
        self.graph.verification_complete=True
        self.seal()
        with self.assertRaises(ValueError):self.reopen(dict(self.preparation))
        with self.reopen() as library:
            capsule=library.state(1,10,'final',self.record)
            self.assertEqual(capsule['final']['anchor_m'],1)

    def test_committed_public_tree_cannot_reauthorize_a_rewritten_evaluated_result(self):
        original_commit=self.graph.commit
        attacked=[]
        def commit_and_rewrite(stage):
            original_commit(stage)
            if stage!='library_sealing_merkle' or attacked:return
            node,payload=self.graph.db.execute('SELECT node,payload FROM result ORDER BY node LIMIT 1').fetchone()
            wrapper=decode_result_payload(payload)
            role=wrapper['contract']['role']
            wrapper['capsule'][role]['anchor_m']=999
            digest=checkpoint_digest(wrapper)
            self.graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE node=?',
                                  (encode_result_payload(wrapper),digest,node))
            position=self.graph.db.execute('SELECT position FROM result_leaf WHERE node=?',(node,)).fetchone()[0]
            self.graph.db.execute('UPDATE result_auth SET digest=? WHERE level=0 AND position=?',(_leaf(node,digest),position))
            width=self.graph.db.execute('SELECT count(*) FROM result_leaf').fetchone()[0]
            level=0
            while width>1:
                for pos in range(0,width,2):
                    rows=self.graph.db.execute('SELECT digest FROM result_auth WHERE level=? AND position BETWEEN ? AND ? ORDER BY position',
                                               (level,pos,min(pos+1,width-1))).fetchall()
                    self.graph.db.execute('UPDATE result_auth SET digest=? WHERE level=? AND position=?',
                                          (_parent(rows[0][0],rows[-1][0]),level+1,pos//2))
                width=(width+1)//2;level+=1
            self.graph.db.commit()
            attacked.append(node)
        with patch.object(self.graph,'commit',side_effect=commit_and_rewrite):
            with self.assertRaisesRegex(ValueError,'independently verified results'):
                self.seal()
        self.assertEqual(len(attacked),1)

    def test_mismatched_native_identity_and_kernel_are_rejected(self):
        self.seal()
        for field,value in (('identity',dict(run_id='foreign',iteration=0,run_manifest_sha256='a'*64)),
                            ('kernel_sha256','e'*64),('generation',1)):
            expected={**self.preparation['contract'],field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):self.reopen(expected=expected)

    def test_missing_record_or_epoch_has_no_fabricated_state(self):
        self.seal()
        with self.reopen() as library:
            self.assertIsNone(library.state(999,10,'final',self.record))
            self.assertIsNone(library.state(1,11,'final',self.record))
            changed=deepcopy(self.record);changed['Native_Occupancy']['ordinal']=2
            with self.assertRaises(ValueError):library.state(1,10,'final',changed)

    def test_result_mutation_and_self_rehash_cannot_replace_merkle_root(self):
        self.seal()
        node,raw=self.graph.db.execute("SELECT n.key,r.payload FROM node n JOIN result r ON r.node=n.key WHERE n.role='base' AND r.generation=0").fetchone()
        wrapper=decode_result_payload(raw);wrapper['capsule']['base']['anchor_m']=2
        self.graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE generation=0 AND node=?',
            (encode_result_payload(wrapper),checkpoint_digest(wrapper),node))
        self.preserve_metadata_stamp()
        with self.reopen() as library:
            with self.assertRaisesRegex(ValueError,'root'):library.state(1,10,'base',self.record)

    def test_self_rehash_before_final_seal_cannot_launder_an_unverified_result(self):
        node,raw=self.graph.db.execute("SELECT n.key,r.payload FROM node n JOIN result r ON r.node=n.key WHERE n.role='base' AND r.generation=0").fetchone()
        wrapper=decode_result_payload(raw);wrapper['capsule']['base']['anchor_m']=2
        self.graph.db.execute('UPDATE result SET payload=?,sha256=? WHERE generation=0 AND node=?',
            (encode_result_payload(wrapper),checkpoint_digest(wrapper),node))
        self.graph.verification_complete=True
        with self.assertRaises(ValueError):seal_verified_library(self.graph)

    def test_missing_authentication_path_cannot_be_treated_as_complete(self):
        self.seal()
        self.assertEqual(self.preparation['leaf_count'],2)
        self.graph.db.execute('DELETE FROM result_auth WHERE level=0 AND position=1')
        self.preserve_metadata_stamp()
        with self.reopen() as library:
            with self.assertRaisesRegex(ValueError,'authentication'):library.state(1,10,'base',self.record)

    def test_missing_evaluated_state_cannot_be_sealed(self):
        self.graph.verification_complete=True
        self.graph.db.execute("DELETE FROM result WHERE node=(SELECT key FROM node WHERE role='base')")
        with self.assertRaisesRegex(ValueError,'omits'):seal_verified_library(self.graph)

    def test_changed_library_metadata_is_not_its_own_authority(self):
        self.seal()
        contract=deepcopy(self.preparation['contract']);contract['root_digest']='f'*64
        self.graph.db.execute("UPDATE metadata SET value=? WHERE key='checkpoint_contract'",(json.dumps(contract,separators=(',',':')),))
        self.preserve_metadata_stamp()
        with self.assertRaisesRegex(ValueError,'metadata'):self.reopen()


if __name__=='__main__':unittest.main()
