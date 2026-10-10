import logging
import multiprocessing
import os
import sys
import time

MAX_PARALLEL_WORKERS = int(os.getenv("MAX_PARALLEL_WORKERS", "2"))
RESPAWN_CHECK_SECONDS = int(os.getenv("RQ_RESPAWN_CHECK_SECONDS", "15"))


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
        worker = Worker(["integrations", "workers"], connection=redis_conn)
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

    def _spawn(worker_index: int) -> multiprocessing.Process:
        p = multiprocessing.Process(
            target=_run_single_worker,
            args=(worker_index,),
            name=f"rq-worker-{worker_index}",
        )
        p.start()
        log.info(f"Spawned rq-worker-{worker_index} pid={p.pid}")
        return p

    processes: dict[int, multiprocessing.Process] = {
        i: _spawn(i) for i in range(MAX_PARALLEL_WORKERS)
    }

    # RQ quits a worker on a Redis connection timeout ("Redis connection
    # timeout, quitting..."). Redis is remote, so that happens on any network
    # blip; on 2026-10-10 three of four children died overnight and the whole
    # fleet ran on one worker for hours because they were never replaced.
    # Watch the children and respawn any that exit.
    try:
        while True:
            time.sleep(RESPAWN_CHECK_SECONDS)
            for i, p in list(processes.items()):
                if p.is_alive():
                    continue
                p.join()
                log.warning(
                    f"WORKER_DIED worker_index={i} pid={p.pid} exitcode={p.exitcode} — respawning"
                )
                processes[i] = _spawn(i)
    except KeyboardInterrupt:
        log.info("Interrupt received — terminating worker processes...")
        for p in processes.values():
            p.terminate()
        for p in processes.values():
            p.join()
        log.info(f"WORKER_FINISHED all {MAX_PARALLEL_WORKERS} worker processes stopped")
