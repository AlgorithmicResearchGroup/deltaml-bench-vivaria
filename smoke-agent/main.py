import asyncio

from pyhooks import Hooks


hooks = Hooks()


async def main(*args):
    await hooks.getTask()
    hooks.log("Smoke agent started")
    await asyncio.sleep(180)
    await hooks.submit("smoke-test")


hooks.main(main)
