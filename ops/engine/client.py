"""The connection to the engine (GEN-33): this deployment's namespace, its data converter, the namespace made when
missing. One Temporal namespace per deployment, so two deployments on one machine never see each other's runs.

    await connect()                 a client for this deployment (address, namespace, converter from its settings)
    await ensure_namespace(client)  registers the namespace when it is missing; safe to repeat
    namespace()                     this deployment's namespace: its folder's name
"""
import os
import re
import sys
from pathlib import Path

from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, RegisterNamespaceRequest
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dataguard as DG  # noqa: E402
import deployment as DEPLOY  # noqa: E402
from engine import converter as CV  # noqa: E402

ADDRESS_ENV = "AISTACK_TEMPORAL"
ADDRESS = "127.0.0.1:7233"            # compose/core.yaml publishes the front door here only
# limit: drops, Temporal keeps a closed run's history this long; the record export (GEN-31) keeps a journey for good
RETENTION_DAYS = 30


def namespace(folder=None):
    """This deployment's namespace: the name of its folder (deployments/<name>, or a folder elsewhere)."""
    name = Path(folder or DEPLOY.FOLDER).name.lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", name):
        raise SystemExit(f"the deployment folder's name {name!r} cannot be a namespace: letters, digits and dashes")
    return name


def address(env=os.environ):
    return env.get(ADDRESS_ENV) or ADDRESS


async def ensure_namespace(client, ns=None, retention_days=RETENTION_DAYS):
    """Registers the namespace when it is missing. True when it was made now."""
    ns = ns or client.namespace
    try:
        await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=ns))
        return False
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise
    try:
        await client.workflow_service.register_namespace(RegisterNamespaceRequest(
            namespace=ns, description="the AI Stack deployment's runs",
            workflow_execution_retention_period=Duration(seconds=retention_days * 86400)))
    except RPCError as e:
        if e.status != RPCStatusCode.ALREADY_EXISTS:
            raise
        return False
    return True


async def connect(addr=None, ns=None, customer=None, key=None, data_converter=None):
    """A client of this deployment's namespace, with its converter (references only for customer data, encrypted)."""
    if data_converter is None:
        customer = DG.customer() if customer is None else customer
        data_converter = CV.data_converter(customer, key if key is not None else CV.key_from_env())
    return await Client.connect(addr or address(), namespace=ns or namespace(), data_converter=data_converter)
