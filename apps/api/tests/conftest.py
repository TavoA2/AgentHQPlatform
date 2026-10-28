import asyncio
import sys

# Psycopg's async mode cannot run on Windows' default ProactorEventLoop; the server uses
# the same workaround in agent_hq.cli.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
