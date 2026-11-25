"""The topic's agents by name, as the hackathon's submission rules ask for them in ``agents.py``.

``agent.py`` stays the starter's entry point, which ``langgraph.json`` registers; this module
gathers every agent the topic defines so a reader finds them in one place.
"""

from agent import agent, build_agent
from workflow.graph import graph as transaction_monitoring

transaction_monitoring_agent = agent
"""The starter's agent: three tools, a short-term and a long-term memory, and its own pause for a
person when its confidence is low."""

AGENTS = {
    "transaction_monitoring_agent": transaction_monitoring_agent,
    "transaction_monitoring": transaction_monitoring,
}
"""Every agent by the name it is registered or called under."""

__all__ = [
    "AGENTS",
    "build_agent",
    "transaction_monitoring",
    "transaction_monitoring_agent",
]
