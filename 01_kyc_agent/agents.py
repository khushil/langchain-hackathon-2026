"""The topic's agents by name, as the hackathon's submission rules ask for them in ``agents.py``.

``agent.py`` stays the starter's entry point, which ``langgraph.json`` registers; this module
gathers every agent the topic defines so a reader finds them in one place. Importing it chooses
no model and makes no call: each agent asks ``get_model`` when it runs.
"""

from agent import agent, build_agent
from workflow.graph import graph as kyc_onboarding

kyc_agent = agent
"""The starter's graph: extract, screen, assess the risk, route, review and write the memo."""

AGENTS = {
    "kyc_agent": kyc_agent,
    "kyc_onboarding": kyc_onboarding,
}
"""Every agent by the name it is registered or called under."""

__all__ = ["AGENTS", "build_agent", "kyc_agent", "kyc_onboarding"]
