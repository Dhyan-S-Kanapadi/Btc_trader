"""Throwaway invocation shape; fill runtime ARN only outside source control."""

import json
import uuid


def invoke(client: object, runtime_arn: str, snapshot: dict[str, object]) -> bytes:
    """Call AgentCore synchronously; production #21 owns timeout/retry handling."""
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(snapshot).encode(),
        qualifier="DEFAULT",
    )
    return b"".join(response["response"])
