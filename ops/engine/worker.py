"""The engine thread inside the host runner (GEN-33, docs/AI-STACK-PLAN.md WP2).

The runner (ops/missions.py) is threads around plain functions; Temporal's SDK is asyncio. One thread owns one event
loop with the client and a worker per task queue; activities are the runner's plain functions, run in a thread pool,
so they keep working as they do today. Other threads reach the engine through call(), which runs a coroutine on the
engine's loop and waits for its answer.

    E = Engine(workflows=[...], activities=[...], queues={"aistack": 4})
    E.start()                      # returns once the workers poll, or raises why they could not
    E.call(lambda c: c.start_workflow(...))
    E.stop()
"""
import asyncio
import concurrent.futures
import contextlib
import threading

from temporalio.worker import Worker

from engine import client as CL

# limit: paces, a queue without its own size runs this many activities at once (pools, GEN-28, give theirs)
DEFAULT_ACTIVITIES = 4
# limit: stops, a call into the engine that has no answer after this is given up, with the reason
CALL_TIMEOUT_S = 60


class Engine:
    def __init__(self, workflows=(), activities=(), queues=None, connect=None, **connect_kw):
        self.workflows, self.activities = list(workflows), list(activities)
        self.queues = dict(queues or {"aistack": DEFAULT_ACTIVITIES})
        self._connect = connect or (lambda: CL.connect(**connect_kw))
        self.client = None
        self.loop = None
        self._ready = threading.Event()
        self._stop = None
        self._error = None
        self._thread = None
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=sum(self.queues.values()), thread_name_prefix="activity")

    async def _main(self):
        try:
            self.client = await self._connect()
            await CL.ensure_namespace(self.client)
            self._stop = asyncio.Event()
            workers = [Worker(self.client, task_queue=q, workflows=self.workflows, activities=self.activities,
                              activity_executor=self._pool, max_concurrent_activities=n) for q, n in self.queues.items()]
            async with contextlib.AsyncExitStack() as stack:
                for w in workers:
                    await stack.enter_async_context(w)
                self._ready.set()
                await self._stop.wait()
        except BaseException as e:                   # the starter hears why, instead of a thread that died quietly
            self._error = e
            self._ready.set()

    def start(self, timeout=CALL_TIMEOUT_S):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_until_complete, args=(self._main(),), daemon=True, name="engine")
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError(f"the engine did not start within {timeout} s")
        if self._error:
            raise RuntimeError(f"the engine could not start: {self._error}") from self._error
        return self

    def call(self, fn, timeout=CALL_TIMEOUT_S):
        """fn(client) -> a coroutine; runs it on the engine's loop and returns its result."""
        return asyncio.run_coroutine_threadsafe(fn(self.client), self.loop).result(timeout)

    def stop(self, timeout=CALL_TIMEOUT_S):
        if self.loop and self._stop:
            self.loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout)
        self._pool.shutdown(wait=False, cancel_futures=True)
