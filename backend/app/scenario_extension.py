"""Optional business adapters. The runtime imports only generic extension protocols."""

from .models import AgentRunContext
from .recommendation_renderer import RecommendationRenderer
from .runtime_extensions import OutputRegistry, PolicyRegistry, PolicyResolution
from .scenario_policy import UNPUBLISHED_HOMEWORK_CONTRACT, ScenarioPolicyRegistry


class HomeworkRoutingPolicy:
    def resolve(self, state, candidates):
        resolution = ScenarioPolicyRegistry().resolve(
            state.request.message, state.intent, candidates
        )
        return PolicyResolution(
            matched=resolution.matched,
            route=resolution.route,
            policy_id="list-unpublished-homeworks",
            question=(f"请先配置：{'、'.join(resolution.missing)}" if resolution.missing else ""),
        )


class HomeworkRenderer:
    async def render(self, state: AgentRunContext):
        plan = RecommendationRenderer().render(state.route.output_contract, state.results)
        yield (
            "output.validated",
            {
                "output_contract": state.route.output_contract,
                "card_type": plan.card_type,
                "item_count": sum(len(section.items) for section in plan.sections),
                "section_count": len(plan.sections),
            },
        )
        yield "recommendation", {"content": plan.model_dump(mode="json")}
        yield "message.completed", {"content": plan.text, "status": "recommendation"}


def register_homework_extension(policies: PolicyRegistry, outputs: OutputRegistry):
    policies.register(HomeworkRoutingPolicy())
    outputs.register(UNPUBLISHED_HOMEWORK_CONTRACT, HomeworkRenderer())
