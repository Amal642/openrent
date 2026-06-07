import logging
import multiprocessing
import os
import sys

MAX_PARALLEL_WORKERS = int(os.getenv("MAX_PARALLEL_WORKERS", "2"))


def _run_single_worker(worker_index: int) -> None:
    """
    Entry point for one RQ worker subprocess.
    All imports are deferred so each process gets its own fresh Redis connection
    rather than inheriting a forked socket from the parent.
    """
    from rq import Worker

    from app.queue.redis_conn import redis_conn
    from app.utils.logger import logger

    logger.info(
        f"WORKER_STARTED worker_index={worker_index} pid={os.getpid()} "
        f"ACTIVE_WORKERS={MAX_PARALLEL_WORKERS}"
    )
    try:
        worker = Worker(["workers"], connection=redis_conn)
        worker.work()
    finally:
        logger.info(
            f"WORKER_FINISHED worker_index={worker_index} pid={os.getpid()}"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    log = logging.getLogger(__name__)

    # spawn gives each child a clean interpreter — no forked Redis sockets
    multiprocessing.set_start_method("spawn")

    log.info(
        f"Starting {MAX_PARALLEL_WORKERS} RQ worker process(es) "
        f"(MAX_PARALLEL_WORKERS={MAX_PARALLEL_WORKERS})"
    )

    processes: list[multiprocessing.Process] = []
    for i in range(MAX_PARALLEL_WORKERS):
        p = multiprocessing.Process(
            target=_run_single_worker,
            args=(i,),
            name=f"rq-worker-{i}",
        )
        p.start()
        log.info(f"Spawned rq-worker-{i} pid={p.pid}")
        processes.append(p)

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        log.info("Interrupt received — terminating worker processes...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join()
        log.info(f"WORKER_FINISHED all {MAX_PARALLEL_WORKERS} worker processes stopped")
