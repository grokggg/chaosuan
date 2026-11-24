# MCP Authentication Failures

This rule only applies to MCP tools. If the `execute` tool reports an authentication error, do not treat it as an `MCP_API_KEY` failure: `execute` is a built-in tool and is unrelated to MCP authentication.

If an MCP tool result indicates an authentication failure, such as an invalid access_key, invalid api_key, expired key, deleted key, or authorization failure, treat it as a sign that the current environment's `MCP_API_KEY` is invalid or has been deleted.

When responding to the user, do not mention internal MCP key names such as access_key or api_key. When this happens, tell the user that MCP authentication has failed because the current `MCP_API_KEY` is invalid, expired, deleted, or does not have permission. First suggest contacting customer support for help. Then, if the user has a valid `MCP_API_KEY`, ask them to provide it and offer to update the environment variable for them.
