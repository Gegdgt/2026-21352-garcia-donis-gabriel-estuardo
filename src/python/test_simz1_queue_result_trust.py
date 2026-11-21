"""Synthetic SQLite authentication tests; no simulation or native replay IO."""
from contextlib import closing
import hashlib
import sqlite3
import unittest

from simz1_queue_result_trust import IncrementalResultTrust, _leaf, _parent


def digest(value):return hashlib.sha256(str(value).encode()).hexdigest()


class ResultTrustTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)

    def test_streamed_odd_tree_allows_each_publish_order_and_prior_verification(self):
        names=['node-'+str(i).zfill(3) for i in range(17)]
        trust=IncrementalResultTrust(self.db,0,((name,) for name in names))
        published=[]
        for name in reversed(names):
            with self.assertRaises(ValueError):trust.verify(name,digest(name))
            trust.publish(name,digest(name));published.append(name)
            for old in published:self.assertTrue(trust.verify(old,digest(old)))
        self.assertEqual(trust.leaf_count,17)

    def test_duplicate_publish_and_database_reopen_do_not_grant_authority(self):
        trust=IncrementalResultTrust(self.db,1,iter(['only']))
        trust.publish('only',digest('first'))
        with self.assertRaises(ValueError):trust.publish('only',digest('second'))
        with self.assertRaises(ValueError):IncrementalResultTrust(self.db,1,iter(['only']))
        self.assertTrue(trust.verify('only',digest('first')))

    def test_complete_self_rehashed_database_cannot_replace_private_root(self):
        trust=IncrementalResultTrust(self.db,0,iter(['a','b']))
        trust.publish('a',digest('a'));trust.publish('b',digest('b'))
        forged=digest('forged');leaf=_leaf(0,'a',forged)
        other=self.db.execute('SELECT digest FROM result_trust_auth WHERE generation=0 AND level=0 AND position=1').fetchone()[0]
        self.db.execute('UPDATE result_trust_auth SET digest=? WHERE generation=0 AND level=0 AND position=0',(leaf,))
        self.db.execute('UPDATE result_trust_auth SET digest=? WHERE generation=0 AND level=1 AND position=0',(_parent(leaf,other),))
        with self.assertRaisesRegex(ValueError,'independent'):trust.verify('a',forged)

    def test_missing_proof_and_changed_leaf_identity_fail_closed(self):
        trust=IncrementalResultTrust(self.db,0,iter(['a','b']))
        trust.publish('a',digest('a'))
        self.db.execute('DELETE FROM result_trust_auth WHERE generation=0 AND level=0 AND position=1')
        with self.assertRaises(ValueError):trust.verify('a',digest('a'))
        with self.assertRaises(ValueError):trust.publish('b',digest('b'))
        with self.assertRaises(ValueError):trust.verify('absent',digest('a'))

    def test_generations_and_payload_hashes_are_not_interchangeable(self):
        first=IncrementalResultTrust(self.db,0,iter(['same']))
        second=IncrementalResultTrust(self.db,1,iter(['same']))
        first.publish('same',digest('bytes'));second.publish('same',digest('bytes'))
        self.assertNotEqual(first.root_digest,second.root_digest)
        with self.assertRaises(ValueError):first.verify('same,different',digest('bytes'))
        with self.assertRaises(ValueError):first.verify('same',digest('other'))

    def test_invalid_input_rolls_back_partial_generation(self):
        for names in ([],['b','a'],['a','a'],['a',None]):
            with self.subTest(names=names),self.assertRaises(ValueError):
                IncrementalResultTrust(self.db,0,iter(names))
            self.assertEqual(self.db.execute('SELECT count(*) FROM result_trust_generation').fetchone(),(0,))
        for generation in (-1,True,1.5):
            with self.subTest(generation=generation),self.assertRaises(ValueError):
                IncrementalResultTrust(self.db,generation,iter(['a']))
        trust=IncrementalResultTrust(self.db,0,iter(['a']))
        with self.assertRaises(ValueError):trust.publish('a','self-declared-not-sha256')

    def test_complete_stream_matches_private_tree_for_even_odd_and_commit_boundaries(self):
        for size in (1,2,3,5,17,129,258):
            with self.subTest(size=size):
                names=['n'+str(i).zfill(4) for i in range(size)]
                trust=IncrementalResultTrust(self.db,size,iter(names))
                for name in reversed(names):trust.publish(name,digest(name))
                seal=trust.seal_complete((name,digest(name)) for name in names)
                self.assertEqual(seal['root_sha256'],trust.root_digest)
                self.assertEqual(seal['leaves'],size)
                with self.assertRaises(ValueError):trust.seal_complete((name,digest(name)) for name in names[:-1])
                with self.assertRaises(ValueError):trust.seal_complete((name,digest('forged')) for name in names)

    def test_complete_stream_cannot_accept_unpublished_or_rehashed_database(self):
        trust=IncrementalResultTrust(self.db,0,iter(['a','b','c']))
        trust.publish('a',digest('a'));trust.publish('b',digest('b'))
        with self.assertRaises(ValueError):trust.seal_complete((name,digest(name)) for name in ('a','b','c'))
        trust.publish('c',digest('c'))
        self.db.execute('UPDATE result_trust_auth SET digest=?',('f'*64,))
        # Public tree manipulation cannot authorize another result stream.
        with self.assertRaises(ValueError):trust.seal_complete((name,digest('forged')) for name in ('a','b','c'))


if __name__=='__main__':unittest.main()
