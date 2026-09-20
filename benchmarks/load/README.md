# Load verification (§13)

Two of §13's definition-of-done items cannot be checked by any unit test,
because they are claims about a broker, three worker pools and a scheduler
under contention:

- *A 500-file batch runs to completion without raising p95 latency on
  `queue_preview`.*
- *Worker RSS stays flat across a long soak.*

Everything else in this repository dispatches jobs inline, which is the one
configuration in which the first claim cannot fail. These run the real
thing: Redis, Postgres, a uvicorn process and two Celery pools on separate
queues and separate cores.

## Setting up the dependencies

```sh
# Redis
redis-server --port 6399 --daemonize yes --save ''

# Postgres (as a non-root user; postgres refuses to run as root)
D=/var/lib/postgresql/loadtest && mkdir -p $D && chown postgres $D
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D $D/data -U vect --auth=trust"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D $D/data -l $D/pg.log -o '-p 5433' start"
su postgres -c "/usr/lib/postgresql/16/bin/createdb -p 5433 -h 127.0.0.1 -U vect vectorize"

export VEC_DATABASE_URL="postgresql+psycopg://vect@127.0.0.1:5433/vectorize"
export VEC_REDIS_URL="redis://127.0.0.1:6399/0"
cd apps/api && alembic upgrade head && cd -
```

Then `make load-test` and `make soak`.

## Reading the results

The harness pins each pool to its own cores, because §4.2's three pools are
three separate Fly apps in production — separate machines, separate CPUs.
`--share-cpus` runs them on the same cores instead, which is what a
single-machine deployment would look like.

Two measurement traps, both of which this test fell into before it was
right, and both of which would have been reported as "the batch is
starving previews":

1. **Unequal sample sizes.** `worker_max_tasks_per_child` recycles a child
   every N tasks and the next task pays for the interpreter warm-up. If the
   idle phase takes 10 previews and the loaded phase takes 230, the recycle
   lands at a different percentile in each, and p95 moves for reasons that
   have nothing to do with the batch.
2. **Sampling a sawtooth.** Prefork RSS rises and drops as children recycle.
   Reading it once per chunk measures the phase of the saw, not its trend —
   it reported 1.32x growth on a worker that started and ended at 255 MB.

`/health` is measured alongside the previews as a control: if its tail moves
too, the contention is in the API, the database or the disk, and the queue
lanes are not the problem.
