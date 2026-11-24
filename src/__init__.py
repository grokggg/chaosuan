"""Project package root."""

# This must run before any src module imports deepagents (including its
# backends/profiles): deepagents.__init__ eagerly imports deepagents.graph.
from src.compat.deepagents.override import install_deepagents_override

install_deepagents_override()
