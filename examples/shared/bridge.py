"""Optional thin ingress: Connect bearer authentication → AgentCore SigV4 WebSocket.

No model, business tool, transcript persistence, or voice synthesis runs in this process.
"""

import asyncio
import hmac
import json
import logging
import os
import uuid
from http import HTTPStatus

import boto3
from bedrock_agentcore.runtime import AgentCoreRuntimeClient
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

EXT = "https://docs.aws.amazon.com/connect/a2a/ext/v1"
logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("websockets").setLevel(logging.WARNING)


async def pipe(source, target):
    async for frame in source:
        async with asyncio.timeout(8):
            await target.send(frame)


async def main():
    region = os.getenv("AWS_REGION", "us-east-1")
    token = os.getenv("ADAPTER_BEARER_TOKEN")
    if not token:
        token = boto3.client("secretsmanager", region_name=region).get_secret_value(
            SecretId=os.environ["ADAPTER_SECRET_ARN"]
        )["SecretString"]
    runtime = AgentCoreRuntimeClient(region=region)
    active = set()
    max_sessions = int(os.getenv("MAX_SESSIONS", "4"))
    if max_sessions < 1:
        raise ValueError("MAX_SESSIONS must be positive")

    def request_handler(connection, request):
        if request.path == "/health":
            return connection.respond(HTTPStatus.OK, "Strands Connect bridge healthy\n")
        if request.path not in ("/a2a", "/agentcore"):
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        if len(active) >= max_sessions:
            return connection.respond(HTTPStatus.TOO_MANY_REQUESTS, "Bridge at capacity\n")

    def response_handler(connection, request, response):
        if response.status_code == 101:
            response.headers["A2A-Extensions"] = EXT
        return response

    async def handler(caller):
        if len(active) >= max_sessions:
            await caller.close(code=1013, reason="Bridge at capacity")
            return
        active.add(caller)
        session_id = str(uuid.uuid4())
        tasks = []
        try:
            url, headers = await asyncio.to_thread(
                runtime.generate_ws_connection,
                runtime_arn=os.environ["AGENTCORE_RUNTIME_ARN"],
                session_id=session_id,
            )
            # The WebSocket library owns handshake headers; retain only AWS authentication/session headers.
            headers = {
                k: v
                for k, v in headers.items()
                if k.lower().startswith("x-amz") or k.lower() == "authorization"
            }
            async with connect(
                url,
                additional_headers=headers,
                max_size=2**20,
                max_queue=32,
                open_timeout=40,
                ping_interval=20,
                proxy=None,
            ) as agent:
                await agent.send(
                    json.dumps(
                        {
                            "type": "bridge_context",
                            "runtime_session_id": session_id,
                            "headers": {
                                k: caller.request.headers[k]
                                for k in ("traceparent", "tracestate")
                                if k in caller.request.headers
                            },
                        }
                    )
                )
                logging.info(json.dumps({"event": "agentcore_connected", "runtime_session": session_id}))
                tasks = [asyncio.create_task(pipe(caller, agent)), asyncio.create_task(pipe(agent, caller))]
                done, _ = await asyncio.wait(tasks, timeout=310, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except Exception as error:
            logging.error(
                json.dumps(
                    {
                        "event": "bridge_error",
                        "runtime_session": session_id,
                        "error_type": type(error).__name__,
                    }
                )
            )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await caller.close()
            active.discard(caller)

    async with serve(
        handler,
        "0.0.0.0",
        int(os.getenv("PORT", "8080")),
        process_request=request_handler,
        process_response=response_handler,
        max_size=2**20,
        max_queue=32,
    ):
        logging.info(json.dumps({"event": "bridge_ready"}))
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
