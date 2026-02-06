import os
import yaml
from crewai import Agent, Task, Crew, Process, LLM

from tools.budget_tools import check_budget, record_expense, record_revenue
from tools.memory_tools import save_memory, read_memory, list_memories
from tools.stripe_tools import create_stripe_product, get_stripe_balance, list_recent_payments
from tools.email_tools import send_email, send_notification
from tools.domain_tools import check_domain_available, register_domain, setup_dns
from tools.search_tools import web_search, ai_research
from tools.builder_tools import build_code, deploy_to_cloudflare, ai_generate_content

ROUTER_URL = "http://ai-mesh-router:8000/v1"


def make_llm(model: str) -> LLM:
    """Create an LLM that routes through ai-mesh router."""
    return LLM(
        model=f"openai/{model}",
        base_url=ROUTER_URL,
        api_key="not-needed",
    )


def load_config(filename: str) -> dict:
    config_dir = os.path.join(os.path.dirname(__file__), "config")
    with open(os.path.join(config_dir, filename)) as f:
        return yaml.safe_load(f)


def create_agents() -> dict:
    agent_configs = load_config("agents.yaml")

    shared_tools = [check_budget, save_memory, read_memory, list_memories, send_notification]

    agents = {
        "strategist": Agent(
            role=agent_configs["strategist"]["role"],
            goal=agent_configs["strategist"]["goal"],
            backstory=agent_configs["strategist"]["backstory"],
            llm=make_llm(agent_configs["strategist"]["llm_model"]),
            tools=shared_tools + [web_search, ai_research],
            verbose=True,
            allow_delegation=True,
        ),
        "researcher": Agent(
            role=agent_configs["researcher"]["role"],
            goal=agent_configs["researcher"]["goal"],
            backstory=agent_configs["researcher"]["backstory"],
            llm=make_llm(agent_configs["researcher"]["llm_model"]),
            tools=shared_tools + [web_search, ai_research],
            verbose=True,
        ),
        "builder": Agent(
            role=agent_configs["builder"]["role"],
            goal=agent_configs["builder"]["goal"],
            backstory=agent_configs["builder"]["backstory"],
            llm=make_llm(agent_configs["builder"]["llm_model"]),
            tools=shared_tools + [build_code, deploy_to_cloudflare, record_expense],
            verbose=True,
        ),
        "marketer": Agent(
            role=agent_configs["marketer"]["role"],
            goal=agent_configs["marketer"]["goal"],
            backstory=agent_configs["marketer"]["backstory"],
            llm=make_llm(agent_configs["marketer"]["llm_model"]),
            tools=shared_tools + [ai_generate_content, send_email, record_expense],
            verbose=True,
        ),
        "finance": Agent(
            role=agent_configs["finance"]["role"],
            goal=agent_configs["finance"]["goal"],
            backstory=agent_configs["finance"]["backstory"],
            llm=make_llm(agent_configs["finance"]["llm_model"]),
            tools=shared_tools + [
                create_stripe_product, get_stripe_balance, list_recent_payments,
                record_expense, record_revenue,
            ],
            verbose=True,
        ),
    }
    return agents


def run_strategy_session() -> str:
    """Run a full strategy session — the main entry point."""
    agents = create_agents()
    task_configs = load_config("tasks.yaml")

    strategy_task = Task(
        description=task_configs["strategy_session"]["description"],
        expected_output=task_configs["strategy_session"]["expected_output"],
        agent=agents["strategist"],
    )

    crew = Crew(
        agents=list(agents.values()),
        tasks=[strategy_task],
        process=Process.hierarchical,
        manager_agent=agents["strategist"],
        verbose=True,
    )

    result = crew.kickoff()
    return str(result)


def run_business_build(business_description: str, target_audience: str = "general") -> str:
    """Run a full business build cycle."""
    agents = create_agents()
    task_configs = load_config("tasks.yaml")

    research_task = Task(
        description=task_configs["market_research"]["description"].format(topic=business_description),
        expected_output=task_configs["market_research"]["expected_output"],
        agent=agents["researcher"],
    )

    build_task = Task(
        description=task_configs["build_mvp"]["description"].format(business_description=business_description),
        expected_output=task_configs["build_mvp"]["expected_output"],
        agent=agents["builder"],
        context=[research_task],
    )

    marketing_task = Task(
        description=task_configs["create_marketing"]["description"].format(
            business_description=business_description,
            target_audience=target_audience,
            tone="professional and persuasive",
        ),
        expected_output=task_configs["create_marketing"]["expected_output"],
        agent=agents["marketer"],
        context=[research_task],
    )

    finance_task = Task(
        description=task_configs["financial_setup"]["description"].format(business_description=business_description),
        expected_output=task_configs["financial_setup"]["expected_output"],
        agent=agents["finance"],
        context=[research_task, build_task],
    )

    crew = Crew(
        agents=list(agents.values()),
        tasks=[research_task, build_task, marketing_task, finance_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    return str(result)
