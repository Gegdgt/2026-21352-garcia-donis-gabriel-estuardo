"""Disk-backed topological schedule for one verified graph generation.

An edge points from a consumer to its dependency. Only same-generation edges
between distinct strongly connected components constrain this schedule. The
caller evaluates each ready component atomically before calling ``resolved``.
"""


class ComponentSchedule:
    def __init__(self, db, generation, *, storage=None):
        if type(generation) is not int or generation < 0:
            raise ValueError('Component schedule generation must be a nonnegative integer')
        self.db, self.generation = db, generation
        self.storage=storage
        if storage is not None:storage.check('component_schedule_init.before')
        if not db.in_transaction:db.execute('BEGIN')
        db.execute('CREATE TABLE IF NOT EXISTS component_schedule_generation(generation INTEGER PRIMARY KEY,pending INTEGER NOT NULL,claimed INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS component_schedule_node(generation INTEGER NOT NULL,component INTEGER NOT NULL,remaining INTEGER NOT NULL,resolved INTEGER NOT NULL DEFAULT 0,claimed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(generation,component))')
        db.execute('CREATE TABLE IF NOT EXISTS component_schedule_dependency(generation INTEGER NOT NULL,parent INTEGER NOT NULL,child INTEGER NOT NULL,PRIMARY KEY(generation,parent,child))')
        db.execute('CREATE INDEX IF NOT EXISTS component_schedule_parent ON component_schedule_dependency(generation,child,parent)')
        db.execute('CREATE INDEX IF NOT EXISTS component_schedule_ready ON component_schedule_node(generation,component DESC) WHERE remaining=0 AND resolved=0 AND claimed=0')
        db.execute('SAVEPOINT component_schedule_init');released=False
        try:
            if db.execute('SELECT 1 FROM component_schedule_generation WHERE generation=?',(generation,)).fetchone():
                raise ValueError('Component schedule generation already exists')
            if db.execute('SELECT 1 FROM node n LEFT JOIN component c ON c.id=n.component WHERE c.id IS NULL LIMIT 1').fetchone():
                raise ValueError('Component schedule requires a complete component partition')
            if db.execute("SELECT 1 FROM edge e LEFT JOIN node a ON a.key=e.source LEFT JOIN node b ON b.key=e.target WHERE a.key IS NULL OR b.key IS NULL OR e.kind NOT IN ('same_pass','release') LIMIT 1").fetchone():
                raise ValueError('Component schedule edge has no verified endpoint or kind')
            # Deduplicate once at component granularity. SQLite stores the
            # working set; no Python object graph or repeated edge scan exists.
            db.execute("INSERT INTO component_schedule_dependency SELECT ?,a.component,b.component FROM edge e JOIN node a ON a.key=e.source JOIN node b ON b.key=e.target WHERE e.kind='same_pass' AND a.component<>b.component GROUP BY a.component,b.component",(generation,))
            db.execute('INSERT INTO component_schedule_node(generation,component,remaining) SELECT ?,c.id,count(d.child) FROM component c LEFT JOIN component_schedule_dependency d ON d.generation=? AND d.parent=c.id GROUP BY c.id',(generation,generation))
            count=db.execute('SELECT count(*) FROM component').fetchone()[0]
            self.component_count=count
            db.execute('INSERT INTO component_schedule_generation VALUES (?,?,0)',(generation,count))
            if storage is not None:storage.check('component_schedule_init.release.before')
            db.execute('RELEASE SAVEPOINT component_schedule_init')
            released=True
            if storage is not None:storage.check('component_schedule_init.release.after')
        except BaseException:
            if not released:
                db.execute('ROLLBACK TO SAVEPOINT component_schedule_init')
                db.execute('RELEASE SAVEPOINT component_schedule_init')
            raise

    def verify_complete(self):
        """Verify the barrier against all components, not its counter alone."""
        if self.storage is not None:self.storage.check('component_schedule_complete.before')
        row=self.db.execute('SELECT pending,claimed FROM component_schedule_generation WHERE generation=?',(self.generation,)).fetchone()
        count=self.db.execute('SELECT count(*) FROM component_schedule_node WHERE generation=?',(self.generation,)).fetchone()[0]
        invalid=self.db.execute('SELECT 1 FROM component_schedule_node WHERE generation=? AND (remaining<>0 OR resolved<>1 OR claimed<>0) LIMIT 1',(self.generation,)).fetchone()
        missing=self.db.execute('SELECT 1 FROM component c LEFT JOIN component_schedule_node n ON n.generation=? AND n.component=c.id WHERE n.component IS NULL LIMIT 1',(self.generation,)).fetchone()
        if row!=(0,0) or count!=self.component_count or invalid or missing:
            raise ValueError('Component generation barrier is incomplete')
        if self.storage is not None:self.storage.check('component_schedule_complete.after')
        return dict(generation=self.generation,components=count,pending=0,claimed=0)

    def ready(self, limit, *, claim=False):
        if type(limit) is not int or not 1 <= limit <= 512 or type(claim) is not bool:
            raise ValueError('Component schedule batch must contain 1..512 components')
        rows=[row[0] for row in self.db.execute('SELECT component FROM component_schedule_node WHERE generation=? AND remaining=0 AND resolved=0 AND claimed=0 ORDER BY component DESC LIMIT ?',(self.generation,limit))]
        if not rows:
            pending,claimed=self.db.execute('SELECT pending,claimed FROM component_schedule_generation WHERE generation=?',(self.generation,)).fetchone()
            if pending and not claimed:
                raise ValueError('Component schedule has a cycle or unresolved dependency')
            return []
        if claim:
            self.db.execute('SAVEPOINT component_schedule_claim')
            try:
                self.db.executemany('UPDATE component_schedule_node SET claimed=1 WHERE generation=? AND component=?',((self.generation,value) for value in rows))
                self.db.execute('UPDATE component_schedule_generation SET claimed=claimed+? WHERE generation=?',(len(rows),self.generation))
                self.db.execute('RELEASE SAVEPOINT component_schedule_claim')
            except BaseException:
                self.db.execute('ROLLBACK TO SAVEPOINT component_schedule_claim')
                self.db.execute('RELEASE SAVEPOINT component_schedule_claim')
                raise
        return rows

    def resolved(self, component):
        if type(component) is not int:
            raise ValueError('Component schedule identity must be an integer')
        self.db.execute('SAVEPOINT component_schedule_resolve')
        try:
            row=self.db.execute('SELECT remaining,resolved,claimed FROM component_schedule_node WHERE generation=? AND component=?',(self.generation,component)).fetchone()
            if row is None or row[0] != 0 or row[1] != 0:
                raise ValueError('Component must be ready and unresolved before publication')
            if self.db.execute('SELECT 1 FROM component_schedule_dependency d JOIN component_schedule_node n ON n.generation=d.generation AND n.component=d.parent WHERE d.generation=? AND d.child=? AND (n.remaining<=0 OR n.resolved<>0) LIMIT 1',(self.generation,component)).fetchone():
                raise ValueError('Component schedule dependent count is inconsistent')
            self.db.execute('UPDATE component_schedule_node SET resolved=1,claimed=0 WHERE generation=? AND component=?',(self.generation,component))
            self.db.execute('UPDATE component_schedule_node SET remaining=remaining-1 WHERE generation=? AND component IN (SELECT parent FROM component_schedule_dependency WHERE generation=? AND child=?)',(self.generation,self.generation,component))
            self.db.execute('UPDATE component_schedule_generation SET pending=pending-1,claimed=claimed-? WHERE generation=?',(row[2],self.generation))
            self.db.execute('RELEASE SAVEPOINT component_schedule_resolve')
        except BaseException:
            self.db.execute('ROLLBACK TO SAVEPOINT component_schedule_resolve')
            self.db.execute('RELEASE SAVEPOINT component_schedule_resolve')
            raise
