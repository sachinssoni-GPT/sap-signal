"""Every crew's prompt placeholders are filled by its inputs (a missing key would only fail at run time,
on GitHub, after the news had been read). No model is called: the crew is replaced by a checker."""
from types import SimpleNamespace

import pytest

from sapsignal.agents import crews
from sapsignal.schemas import (Candidate, Claim, DeadlineProposals, LinkedInPack, ProofReport, StoryBrief, Take, TakePlan,
                               TakeSection, TriageResult, VerificationReport)


@pytest.fixture
def checked(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls = []

    class FakeCrew:
        def __init__(self, agents, tasks):
            self.agents, self.tasks = agents, tasks

        def kickoff(self, inputs):
            for a in self.agents:
                a.interpolate_inputs(inputs)
            for t in self.tasks:
                t.interpolate_inputs_and_add_conversation_history(inputs)
                assert "{" not in t.description, t.description[:200]
            calls.append(inputs)
            model = self.tasks[-1].output_pydantic
            return SimpleNamespace(pydantic=FAKES[model], raw="", tasks_output=[])
    monkeypatch.setattr(crews, "_crew", lambda agents, tasks: FakeCrew(agents, tasks))
    return calls


take = Take(format="decision_guide", title="t", dek="d", sections=[TakeSection(heading="h", body="b [C1]")])
FAKES = {TriageResult: TriageResult(picks=[]),
         StoryBrief: StoryBrief(claims=[], headline="h", summary="s", why_it_matters="w"),
         TakePlan: TakePlan(story_id="E1", format="decision_guide", angle="a"),
         Take: take, DeadlineProposals: DeadlineProposals(), ProofReport: ProofReport(),
         LinkedInPack: LinkedInPack(share_post="s", story_post="p", carousel_caption="c")}
rep = VerificationReport(candidate_id="E1", claims=[Claim(id="C1", text="a {braced} fact")], evidence=[])


def test_all_prompts_fill_their_placeholders(checked):
    c = Candidate(id="E1", title="SAP {x}", url="https://news.sap.com/a", section="ecc_exit")
    crews.run_triage_events("E1 | 1 outlets | SAP {odd} braces", 5)
    crews.run_story_brief(c, "article with {braces}", c.url, ["theregister.com"])
    crews.run_plan_take([{"candidate_id": "E1"}], [], [], notes="my {note}", prefer_topics=["Integration {x}"])
    crews.run_plan_take([{"candidate_id": "E1"}], ["contrarian"], ["Old title"])
    crews.run_take(TakePlan(story_id="E1", format="long_view", angle="a"), "T", rep, "a fact", notes="mine")
    crews.run_take(TakePlan(story_id="E1", format="contrarian", angle="a"), "T", rep, "a fact", feedback="fix")
    crews.run_deadlines({"E1": [("C1", "ends", "ends on 31 December 2027")]})
    pack = crews.run_linkedin(take, ["h1", "h2"], "intro", ["31 Dec 2027: ECC"], "")
    crews.run_proofread({"issue.title": "A {braced} title"})
    assert len(checked) == 9 and pack.story_needs_input is False
    assert crews.run_deadlines({}).rows == []                      # nothing dated: no model call
