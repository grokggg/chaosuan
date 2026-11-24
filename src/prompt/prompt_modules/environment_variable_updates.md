# Environment Variable Updates

After updating any environment variable with the environment variable tool, stop the current task flow immediately. Tell the user that the environment variable has been updated and ask them to submit the request again.

Do not continue planning or executing steps that depend on the updated environment variable in the same turn. Do not say that you will use the updated value immediately, and do not call tools that depend on it again in the same turn. The current turn still uses the old tool bindings, so updated environment variables only take effect in the next user request.
