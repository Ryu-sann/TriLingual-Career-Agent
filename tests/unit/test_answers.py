from career_agent.applications.answers import Question, answer_question


def test_unknown_immigration_legal_and_demographics_hold(profile):
    for question in [
        Question(label="Are you authorized to work?", kind="work_authorization"),
        Question(label="Please sign this certification", kind="identity", field="name"),
        Question(label="Unknown question"),
        Question(label="Gender", kind="demographic"),
    ]:
        assert answer_question(question, profile).status == "HOLD"
    assert (
        answer_question(
            Question(label="Gender", kind="demographic", required=False), profile
        ).status
        == "OMIT"
    )


def test_identity_not_inferred_and_technical_draft_not_submittable(profile):
    q = Question(label="Full name", kind="identity", field="name")
    assert answer_question(q, profile).status == "HOLD"
    profile.identity_verified = True
    assert answer_question(q, profile).value == profile.name
    assert (
        answer_question(Question(label="Python skills", kind="technical"), profile).status == "HOLD"
    )


def test_signatures_always_hold_even_with_confirmed_visa(profile):
    profile.work_authorization.dso_verified = True
    profile.work_authorization.work_authorization_answer = "Yes"
    profile.work_authorization.sponsorship_answer = "Yes"
    profile.work_authorization.answers_verified = True
    assert (
        answer_question(
            Question(label="Sign this work authorization attestation", kind="work_authorization"),
            profile,
        ).status
        == "HOLD"
    )
