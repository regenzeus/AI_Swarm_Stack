"""Fetches Temporal's two test servers into TEMPORAL_DOWNLOAD_DIR while the image builds (the sandbox reaches only the
package registries later): the time-skipping server and the dev server, each started once and stopped."""
import asyncio
import os

from temporalio.testing import WorkflowEnvironment


async def main():
    d = os.environ["TEMPORAL_DOWNLOAD_DIR"]
    async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=d):
        pass
    async with await WorkflowEnvironment.start_local(download_dest_dir=d):
        pass


asyncio.run(main())
print("the test servers are in", os.environ["TEMPORAL_DOWNLOAD_DIR"])
