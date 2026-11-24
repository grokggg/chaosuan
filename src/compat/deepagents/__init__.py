"""Version-pinned DeepAgents compatibility files; no eager dependency imports.

Graph, memory and filesystem files are loaded under their upstream module names
by ``override``. Import those implementations through ``deepagents``, not this
package, to preserve type identity.
"""
