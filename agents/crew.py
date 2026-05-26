"""
CrewAI crew for LinkedIn post generation.

Configure the LLM via environment variables (see .env.example):
  HF_TOKEN or HUGGINGFACE_HUB_TOKEN — Hugging Face API token
  AGENTS_LLM_MODEL — LiteLLM model id (e.g. huggingface/<org>/<model>)
  AGENTS_LLM_TEMPERATURE — optional, default 0.5
  AGENTS_LLM_BASE_URL — optional OpenAI-compatible endpoint URL
"""
from __future__ import annotations

import os
from typing import List

from crewai import Agent, Crew, LLM, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task


def _resolve_hf_token() -> str:
    token = (os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN") or "").strip()
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        token = token[1:-1].strip()
    if not token:
        raise RuntimeError(
            "Hugging Face token is not configured. Set HF_TOKEN or HUGGINGFACE_HUB_TOKEN."
        )
    return token


def _strip_optional_env_quotes(value: str) -> str:
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    return v


def _resolve_llm_model() -> str:
    raw = _strip_optional_env_quotes((os.getenv("AGENTS_LLM_MODEL") or "").strip())
    if not raw:
        raise RuntimeError(
            "LLM model is not configured. Set AGENTS_LLM_MODEL (see .env.example)."
        )
    return raw


def _build_llm() -> LLM:
    model = _resolve_llm_model()
    temperature = float(os.getenv("AGENTS_LLM_TEMPERATURE", "0.5"))

    hf_token = _resolve_hf_token()
    os.environ["HF_TOKEN"] = hf_token
    os.environ["HUGGINGFACE_HUB_TOKEN"] = hf_token

    base_url = _strip_optional_env_quotes((os.getenv("AGENTS_LLM_BASE_URL") or "").strip()).rstrip(
        "/"
    )

    if base_url:
        return LLM(
            model=model,
            base_url=base_url,
            api_key=hf_token,
            temperature=temperature,
        )

    return LLM(model=model, api_key=hf_token, temperature=temperature)


@CrewBase
class ContentCrew:
    """Two-agent crew: writer drafts the post, editor polishes it."""

    agents: List[BaseAgent]
    tasks: List[Task]

    @agent
    def writer_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["writer_agent"],
            llm=_build_llm(),
            max_tokens=420,
            verbose=False,
        )

    @agent
    def editor_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["editor_agent"],
            llm=_build_llm(),
            max_tokens=380,
            verbose=False,
        )

    @task
    def write_post_task(self) -> Task:
        return Task(config=self.tasks_config["write_post_task"])

    @task
    def edit_post_task(self) -> Task:
        return Task(config=self.tasks_config["edit_post_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
        )
