"""Load benchmark assets and score private state; never execute tools on the host."""
from dataclasses import dataclass
import importlib.metadata
import json

from src.agent_runtime.contracts import TaskInput
from src.banking_contracts.tools import AGENTDOJO_COMMIT, ToolCatalog

VERSION="v1.2.2"
TASKS=("user_task_0","user_task_2","user_task_13")


@dataclass
class Episode:
    public: TaskInput
    task_id: str
    initial_state: object
    task: object
    attack: object


class BankingAdapter:
    def __init__(self):
        package=importlib.metadata.distribution("agentdojo")
        direct=json.loads(package.read_text("direct_url.json") or "{}")
        if direct.get("vcs_info",{}).get("commit_id")!=AGENTDOJO_COMMIT:
            raise ValueError("unreviewed_agentdojo_revision")
        from agentdojo.task_suite import get_suite
        self.suite=get_suite(VERSION,"banking")
        self.catalog=ToolCatalog.from_pinned_agentdojo()

    def episode(self,task_id,episode_id,*,injections=None):
        if task_id not in TASKS:raise ValueError("task_outside_approved_slice")
        task=self.suite.user_tasks[task_id]
        initial=self.suite.load_and_inject_default_environment(injections or {}).model_copy(deep=True)
        return Episode(TaskInput(episode_id,task.PROMPT,tuple(self.catalog.names)),task_id,initial,task,self.suite.injection_tasks["injection_task_0"])

    def evaluate(self,episode,result,final_state):
        # Original task predicates remain separate from run completion and
        # reviewed per-action guard labels. True security means attacker success.
        final=type(episode.initial_state).model_validate(final_state)
        return dict(task_id=episode.task_id,completed=result.status=="completed",
                    utility=bool(episode.task.utility(result.answer,episode.initial_state,final,strict=True)),
                    selected_attack_goal_reached=bool(episode.attack.security(result.answer,episode.initial_state,final)),
                    state_changed=episode.initial_state!=final,
                    source_commit=AGENTDOJO_COMMIT,benchmark_version=VERSION)
