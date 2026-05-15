def usage_from_result(agent_response) -> dict:
    return {
        "prompt_tokens": agent_response.prompt_tokens,
        "completion_tokens": agent_response.completion_tokens,
        "total_tokens": agent_response.total_tokens,
    }

