"""The topic's agents by name, as the hackathon's submission rules ask for them in ``agents.py``.

``agent.py`` stays the starter's entry point, which ``langgraph.json`` registers; this module
gathers every agent the topic defines so a reader finds them in one place.
"""

from agent import agent, build_agent
from sub_agent import SectionSummary, section_summariser_subagent

document_summary_agent = agent
"""The main deep agent: it loads the document and firm, fans out the sections, writes the brief."""

AGENTS = {
    "document_summary_agent": document_summary_agent,
    "section-summariser": section_summariser_subagent,
}
"""Every agent by the name it is registered or called under."""

__all__ = [
    "AGENTS",
    "SectionSummary",
    "build_agent",
    "document_summary_agent",
    "section_summariser_subagent",
]
