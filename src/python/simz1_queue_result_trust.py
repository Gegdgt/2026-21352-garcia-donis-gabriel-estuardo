"""Incremental result authentication with a live, independent Merkle root.

The graph producer owns the SQLite transaction. Only ``publish`` grants trust
to a newly evaluated result. Reopening self-declared database rows cannot restore
this capability; the producer must evaluate a new generation from its inputs.
"""
import hashlib


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Result trust digest must be a lowercase SHA256')
    return value


def _leaf(generation,node,digest=None):
    identity=str(generation).encode()+b'\0'+node.encode('utf8')
    return _hash((b'empty-result\0' if digest is None else b'evaluated-result\0')+identity+
                 (b'' if digest is None else b'\0'+digest.encode('ascii')))


def _parent(left,right):
    return _hash(b'result-node\0'+bytes.fromhex(_digest(left))+bytes.fromhex(_digest(right)))


class IncrementalResultTrust:
    """Disk-backed authentication paths; only one scalar root lives in Python."""
    def __init__(self,db,generation,nodenames_sorted,*,storage=None):
        if type(generation) is not int or generation<0:
            raise ValueError('Result trust generation must be a nonnegative integer')
        self.db,self.generation=db,generation
        self.storage=storage
        self._check('result_trust_init.before')
        if not db.in_transaction:db.execute('BEGIN')
        db.execute('CREATE TABLE IF NOT EXISTS result_trust_generation(generation INTEGER PRIMARY KEY,leaves INTEGER NOT NULL,levels INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS result_trust_leaf(generation INTEGER NOT NULL,node TEXT NOT NULL,position INTEGER NOT NULL,published INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(generation,node),UNIQUE(generation,position))')
        db.execute('CREATE TABLE IF NOT EXISTS result_trust_auth(generation INTEGER NOT NULL,level INTEGER NOT NULL,position INTEGER NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(generation,level,position))')
        db.execute('SAVEPOINT result_trust_init');released=False
        try:
            if db.execute('SELECT 1 FROM result_trust_generation WHERE generation=?',(generation,)).fetchone():
                raise ValueError('Result trust generation already exists; a stored root cannot authorize reuse')
            db.execute('INSERT INTO result_trust_generation VALUES (?,0,0)',(generation,))
            count=0;previous=None
            for item in nodenames_sorted:
                node=item[0] if isinstance(item,(tuple,list)) and len(item)==1 else item
                if not isinstance(node,str) or not node or previous is not None and node<=previous:
                    raise ValueError('Result trust node names must be unique and sorted')
                db.execute('INSERT INTO result_trust_leaf VALUES (?,?,?,0)',(generation,node,count))
                db.execute('INSERT INTO result_trust_auth VALUES (?,0,?,?)',(generation,count,_leaf(generation,node)))
                count+=1;previous=node
                if count%256==0:self._check('result_trust_init.leaves')
            if not count:raise ValueError('Result trust cannot authenticate an empty graph')
            level,width=0,count
            while width>1:
                for position in range(0,width,2):
                    left=self._auth(level,position)
                    right=self._auth(level,min(position+1,width-1))
                    db.execute('INSERT INTO result_trust_auth VALUES (?,?,?,?)',
                               (generation,level+1,position//2,_parent(left,right)))
                width=(width+1)//2;level+=1
                self._check('result_trust_init.level')
            self.leaf_count,self.levels=count,level
            self._root=self._auth(level,0)
            db.execute('UPDATE result_trust_generation SET leaves=?,levels=? WHERE generation=?',(count,level,generation))
            self._check('result_trust_init.release.before')
            db.execute('RELEASE SAVEPOINT result_trust_init')
            released=True
            self._check('result_trust_init.release.after')
        except BaseException:
            if not released:
                db.execute('ROLLBACK TO SAVEPOINT result_trust_init');db.execute('RELEASE SAVEPOINT result_trust_init')
            raise

    @property
    def root_digest(self):
        return self._root

    def _check(self,stage):
        if self.storage is not None:self.storage.check(stage)

    def seal_complete(self,rows):
        """Stream all published (node,digest) pairs against the private root.

        A logarithmic frontier reproduces the odd-leaf Merkle construction.
        No persisted auth root or self-rehashed JSON grants completion.
        """
        self._check('result_trust_seal.before')
        frontier={};count=0;previous=None;stream=hashlib.sha256(b'complete-result-stream-v1\0')
        for node,digest in rows:
            _digest(digest)
            if not isinstance(node,str) or not node or previous is not None and node<=previous:
                raise ValueError('Complete result identities differ from sorted verified graph')
            position,published=self._entry(node)
            if position!=count or not published:raise ValueError('Result generation is not completely published')
            leaf=_leaf(self.generation,node,digest);level=0
            while level in frontier:leaf=_parent(frontier.pop(level),leaf);level+=1
            frontier[level]=leaf;stream.update(node.encode());stream.update(b'\0');stream.update(digest.encode());stream.update(b'\n')
            count+=1;previous=node
            if count%256==0:self._check('result_trust_seal.rows')
        if count!=self.leaf_count:raise ValueError('Complete result generation coverage differs')
        levels=sorted(frontier);level=levels[0];root=frontier[level]
        for next_level in levels[1:]:
            while level<next_level:root=_parent(root,root);level+=1
            root=_parent(frontier[next_level],root);level+=1
        if root!=self._root:raise ValueError('Complete result stream differs from independent live root')
        self._check('result_trust_seal.after')
        return dict(generation=self.generation,leaves=count,root_sha256=root,stream_sha256=stream.hexdigest())

    def _auth(self,level,position):
        row=self.db.execute('SELECT digest FROM result_trust_auth WHERE generation=? AND level=? AND position=?',
                            (self.generation,level,position)).fetchone()
        if row is None:raise ValueError('Result trust authentication path is missing')
        return _digest(row[0])

    def _entry(self,node):
        if not isinstance(node,str) or not node:raise ValueError('Result trust node identity missing')
        row=self.db.execute('SELECT position,published FROM result_trust_leaf WHERE generation=? AND node=?',
                            (self.generation,node)).fetchone()
        if row is None:raise ValueError('Result trust node was not in the verified graph')
        position,published=row
        if type(position) is not int or not 0<=position<self.leaf_count or published not in (0,1):
            raise ValueError('Result trust leaf metadata changed')
        return position,published

    def _proof(self,position,leaf):
        if self._auth(0,position)!=leaf:raise ValueError('Result trust leaf differs from evaluated result')
        width,level,witness=self.leaf_count,0,leaf
        siblings=[]
        while width>1:
            sibling=position-1 if position%2 else min(position+1,width-1)
            digest=self._auth(level,sibling)
            siblings.append((position%2,digest,sibling==position))
            witness=_parent(digest,witness) if position%2 else _parent(witness,digest)
            width=(width+1)//2;position//=2;level+=1
        if witness!=self._root:raise ValueError('Result trust differs from the independent live root')
        return siblings

    def publish(self,node,digest):
        """Authenticate the empty slot, then publish one freshly evaluated result."""
        _digest(digest)
        self.db.execute('SAVEPOINT result_trust_publish')
        try:
            position,published=self._entry(node)
            if published:raise ValueError('Result trust node has already been published')
            siblings=self._proof(position,_leaf(self.generation,node))
            witness=_leaf(self.generation,node,digest)
            self.db.execute('UPDATE result_trust_auth SET digest=? WHERE generation=? AND level=0 AND position=?',
                            (witness,self.generation,position))
            for level,(is_right,sibling,is_duplicate) in enumerate(siblings,1):
                # The odd last node is paired with itself, including its NEW
                # digest. Retaining the old placeholder would corrupt the tree.
                if is_duplicate:sibling=witness
                witness=_parent(sibling,witness) if is_right else _parent(witness,sibling)
                position//=2
                self.db.execute('UPDATE result_trust_auth SET digest=? WHERE generation=? AND level=? AND position=?',
                                (witness,self.generation,level,position))
            self.db.execute('UPDATE result_trust_leaf SET published=1 WHERE generation=? AND node=?',(self.generation,node))
            self.db.execute('RELEASE SAVEPOINT result_trust_publish')
            self._root=witness
        except BaseException:
            self.db.execute('ROLLBACK TO SAVEPOINT result_trust_publish');self.db.execute('RELEASE SAVEPOINT result_trust_publish')
            raise

    def verify(self,node,digest):
        """Verify result bytes against the live producer's independent root."""
        _digest(digest)
        position,published=self._entry(node)
        if not published:raise ValueError('Result trust node has not been evaluated and published')
        self._proof(position,_leaf(self.generation,node,digest))
        return True
