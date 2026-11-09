"""The engine library (GEN-33, GEN-36, docs/AI-STACK-PLAN.md WP2): payloads encrypted with the deployment's key, content
refused from a customer-class history inside a real run, one namespace per deployment, and the engine thread that the
runner's other threads call into. Runs on Temporal's time-skipping test server."""
import asyncio
import base64
import dataclasses
import os
from datetime import timedelta

import pytest
from temporalio import activity, workflow
from temporalio.api.common.v1 import Payload
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from engine import client as CL
    from engine import converter as CV
    from engine import worker as EW

KEY = bytes(range(32))
SECRET = "the customer's extract, line one"


def env(customer):
    return WorkflowEnvironment.start_time_skipping(data_converter=CV.data_converter(customer, KEY),
                                                   download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR"))


@activity.defn
def hand_back(what: str) -> str:
    return SECRET * 20 if what == "content" else "artifact:" + "ab" * 32


@workflow.defn
class OneStep:
    @workflow.run
    async def run(self, what: str) -> str:
        return await workflow.execute_activity(hand_back, what, start_to_close_timeout=timedelta(seconds=10),
                                               retry_policy=RetryPolicy(maximum_attempts=1))


async def run_one(customer, what, wid):
    async with await env(customer) as e:
        async with Worker(e.client, task_queue="t", workflows=[OneStep], activities=[hand_back],
                          activity_executor=__import__("concurrent.futures").futures.ThreadPoolExecutor(2)):
            h = await e.client.start_workflow(OneStep.run, what, id=wid, task_queue="t")
            try:
                out = await h.result()
            except WorkflowFailureError as err:
                out = err
            history = await h.fetch_history()
            return out, history


def test_every_payload_is_encrypted_with_the_deployments_key_and_only_that_key_reads_it():
    codec = CV.Encrypting(KEY)
    plain = Payload(metadata={"encoding": b"json/plain"}, data=b'"' + SECRET.encode() + b'"')
    [enc] = asyncio.run(codec.encode([plain]))
    assert enc.metadata["encoding"] == CV.ENCODING and SECRET.encode() not in enc.SerializeToString()
    assert asyncio.run(codec.decode([enc])) == [plain]
    with pytest.raises(ValueError, match="cannot be read with key"):
        asyncio.run(CV.Encrypting(bytes(32)).decode([enc]))


def test_the_codec_key_comes_from_the_secret_and_a_wrong_one_is_refused_without_showing_it():
    good = base64.b64encode(KEY).decode()
    assert CV.key_from_env({"TEMPORAL_CODEC_KEY": good}) == KEY
    with pytest.raises(SystemExit, match="needs TEMPORAL_CODEC_KEY"):
        CV.key_from_env({})
    with pytest.raises(SystemExit, match="holds 16 bytes") as e:
        CV.key_from_env({"TEMPORAL_CODEC_KEY": base64.b64encode(b"x" * 16).decode()})
    assert "eHh4" not in str(e.value)                                       # the value itself is never in the message
    assert len(base64.b64decode(CV.new_key())) == 32


def test_a_customer_class_converter_refuses_content_and_passes_references():
    pc = CV.ReferencesOnly()
    ok = {"artifact": "sha256:" + "ab" * 32, "item": "T-1", "pass": False, "problems": 3}
    assert pc.to_payloads([ok])
    for content in (SECRET * 20, b"raw", {"lines": ["x" * 120] * 60}):
        with pytest.raises(CV.ContentRefused, match="refused by the data guard"):
            pc.to_payloads([content])

    @CV.structure
    @dataclasses.dataclass
    class Shape:
        nodes: list
    assert pc.to_payloads([Shape(nodes=[f"node {i}" for i in range(800)])])         # a known shape may be larger
    with pytest.raises(CV.ContentRefused):
        pc.to_payloads([{"nodes": [f"node {i}" for i in range(800)]}])              # the same as a plain dict may not


def test_inside_a_real_run_a_customer_class_deployment_fails_the_step_that_returns_content():
    out, history = asyncio.run(run_one(True, "content", "c-1"))
    assert isinstance(out, WorkflowFailureError) and "refused by the data guard" in str(out.__cause__.__cause__ or out.__cause__)
    assert SECRET.encode() not in history.to_json().encode()
    out, history = asyncio.run(run_one(True, "ref", "c-2"))
    assert out == "artifact:" + "ab" * 32


def test_home_is_not_strict_but_its_history_is_ciphertext_too():
    out, history = asyncio.run(run_one(False, "content", "h-1"))
    assert out == SECRET * 20                                               # personal data: content may pass
    raw = history.to_json()
    assert SECRET not in raw and base64.b64encode(CV.ENCODING).decode() in raw   # stored encrypted, tagged ours


def test_a_namespace_is_the_deployment_folder_name_and_is_made_once():
    assert CL.namespace("/x/deployments/home") == "home" and CL.namespace("/srv/sites/work-site") == "work-site"
    with pytest.raises(SystemExit, match="cannot be a namespace"):
        CL.namespace("/x/My Site!")

    async def go():
        async with await env(False) as e:
            assert await CL.ensure_namespace(e.client, "default") is False      # exists: left as it is
    asyncio.run(go())


def test_the_runners_threads_reach_the_engine_through_its_own_loop():
    async def serve():
        e = await env(False)
        target = e.client.service_client.config.target_host
        engine = EW.Engine(workflows=[OneStep], activities=[hand_back], queues={"t": 2},
                           connect=lambda: CL.connect(target, "default", data_converter=CV.data_converter(False, KEY)))
        await asyncio.to_thread(engine.start)
        try:
            h = await asyncio.to_thread(engine.call, lambda c: c.start_workflow(OneStep.run, "ref", id="w-1", task_queue="t"))
            assert await asyncio.to_thread(engine.call, lambda c: c.get_workflow_handle("w-1").result()) == "artifact:" + "ab" * 32
            assert h.id == "w-1"
        finally:
            await asyncio.to_thread(engine.stop)
            await e.shutdown()
    asyncio.run(serve())
