import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.applications.policy import digest
from career_agent.database.models import (
    Application,
    AuditLog,
    EmailEvent,
    ResumeVersion,
    WorkflowRun,
)
from career_agent.documents.tailoring import DocumentError
from career_agent.models.candidate import CandidateProfile
from career_agent.operations.analytics import overview
from career_agent.operations.profile_review import confirm_profile
from career_agent.operations.worker import Operations
from career_agent.workflows.document_pipeline import prepare_documents
from career_agent.workflows.job_pipeline import ranked_jobs


def render(section, root, engine, profile, settings):
    if section == "書類":
        st.subheader("検証済みの応募書類")
        if not profile.identity_verified or not profile.verified_claims:
            st.warning("本人情報と経歴の確認が必要です。未確認の実績は書類へ追加しません。")
        rows = ranked_jobs(engine, profile, settings)
        if rows:
            ids = [r["id"] for r in rows]
            names = {r["id"]: r["company"] + " — " + r["title"] for r in rows}
            job_id = st.selectbox("対象の求人", ids, format_func=lambda v: names[v])
            if st.button(
                "検証済み経歴から DOCX / PDF を作成",
                disabled=not profile.identity_verified or not profile.verified_claims,
            ):
                try:
                    st.success(prepare_documents(engine, profile, job_id, root)["document_path"])
                except DocumentError:
                    st.error(
                        "生成・検証を完了できませんでした。確認済み経歴と文字の対応を確認してください。"
                    )
        with Session(engine) as s:
            versions = list(
                s.scalars(
                    select(ResumeVersion)
                    .where(ResumeVersion.candidate_id == profile.candidate_id)
                    .order_by(ResumeVersion.created_at.desc())
                )
            )
            for v in versions:
                with st.expander(f"書類 v{v.version} / {v.id[:8]}"):
                    folder = (root / v.document_path).resolve()
                    if folder.is_relative_to(root.resolve()):
                        for name in [
                            "resume.docx",
                            "resume.pdf",
                            "cover_letter.docx",
                            "cover_letter.pdf",
                        ]:
                            file = folder / name
                            if file.is_file():
                                st.download_button(
                                    name, file.read_bytes(), file_name=name, key=v.id + name
                                )
    elif section == "応募履歴":
        st.subheader("応募・保留・証拠")
        st.info("自動応募は初期状態で無効です。テスト送信と実応募を区別します。")
        with Session(engine) as s:
            modes = {
                a.application_id: a.details.get("mode", "unknown")
                for a in s.scalars(select(AuditLog).where(AuditLog.action == "SUBMISSION_RESERVED"))
            }
            apps = list(
                s.scalars(
                    select(Application).where(Application.candidate_id == profile.candidate_id)
                )
            )
            st.dataframe(
                [
                    {
                        "job_id": a.job_id,
                        "status": a.status,
                        "mode": modes.get(a.id, "unknown"),
                        "submitted_at": str(a.submitted_at or ""),
                    }
                    for a in apps
                ],
                hide_index=True,
            )
            for run in s.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.status.in_(["HOLD", "FAILED", "UNKNOWN_SUBMISSION", "PARTIAL"]))
                .order_by(WorkflowRun.created_at.desc())
                .limit(20)
            ):
                st.json({"kind": run.kind, "status": run.status, "summary": run.summary})
    elif section == "メール・面接":
        st.subheader("メール候補と面接日時")
        st.caption("メールは候補分類です。内容だけで応募成功や面接日時を確定しません。")
        with Session(engine) as s:
            events = [
                e
                for e in s.scalars(select(EmailEvent).order_by(EmailEvent.created_at.desc()))
                if e.payload.get("candidate_id") == profile.candidate_id
            ]
            st.dataframe(
                [
                    {
                        "id": e.provider_message_id,
                        "category": e.category,
                        "subject": e.payload.get("subject", ""),
                        "needs_review": e.payload.get("needs_review", True),
                    }
                    for e in events
                ],
                hide_index=True,
            )
            if events:
                selected = st.selectbox(
                    "日時を確認したメール", [e.provider_message_id for e in events]
                )
                date = st.date_input(
                    "面接日", value=datetime.now(ZoneInfo(settings.project.timezone)).date()
                )
                start_time = st.time_input("開始時刻")
                minutes = st.number_input("長さ（分）", 15, 180, 60)
                verified = st.checkbox("元の案内と日時・タイムゾーンを確認しました")
                if st.button("確認済みの予定を保存", disabled=not verified):
                    start = datetime.combine(
                        date, start_time, tzinfo=ZoneInfo(settings.project.timezone)
                    )
                    proposal = {
                        "source_message_id": selected,
                        "summary": "Interview",
                        "start": start.isoformat(),
                        "end": (start + timedelta(minutes=minutes)).isoformat(),
                        "timezone": settings.project.timezone,
                        "time_verified": True,
                        "evidence": "Candidate confirmed invitation in dashboard",
                    }
                    event = next(e for e in events if e.provider_message_id == selected)
                    event.payload = {**event.payload, "calendar_proposal": proposal}
                    s.commit()
                    st.success(
                        "確認済み予定を保存しました。"
                        "Calendar 書き込みが有効なワーカーで反映します。"
                    )
    elif section == "分析":
        st.subheader("活動の集計")
        st.json(overview(engine, profile.candidate_id))
        with Session(engine) as session:
            for notice in session.scalars(
                select(AuditLog)
                .where(AuditLog.action.in_(["DAILY_SUMMARY", "EMAIL_ALERT"]))
                .order_by(AuditLog.created_at.desc())
                .limit(20)
            ):
                if notice.details.get("candidate_id") == profile.candidate_id:
                    st.json({"type": notice.action, "details": notice.details})
    elif section == "設定・確認事項":
        st.subheader("不足している設定と確認")
        if st.button("自動応募を緊急停止"):
            flag = root / "data/emergency_stop.flag"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("paused\n")
            flag.chmod(0o600)
            st.success("送信を停止しました。再開には設定と停止フラグの確認が必要です。")
        st.json(
            {
                "identity_verified": profile.identity_verified,
                "verified_claims": len(profile.verified_claims),
                "cip_status": profile.education.cip_verification.value,
                "visa_answers_verified": profile.work_authorization.answers_verified,
                "exact_start_date_known": profile.preferences.available_start_date is not None,
                "automation": settings.automation.model_dump(),
                "operations": Operations.load(root).model_dump(),
            }
        )
        st.json(
            {
                name: bool(os.environ.get(name))
                for name in [
                    "CAREER_OPENAI_API_KEY",
                    "CAREER_OPENAI_MODEL",
                    "CAREER_BRAVE_API_KEY",
                    "CAREER_GOOGLE_CLIENT_ID",
                    "CAREER_GOOGLE_CLIENT_SECRET",
                    "CAREER_GOOGLE_REFRESH_TOKEN",
                ]
            }
        )
        st.caption(
            "キーの値は表示しません。環境設定で入力してください。"
            "OpenAI は CAREER_OPENAI_API_KEY を使用します。"
        )
        private = root / "data/profile/candidate_profile.yaml"
        if (
            private.is_file()
            and CandidateProfile.load(private).candidate_id == profile.candidate_id
        ):
            with st.expander("本人情報・経歴を一度確認する"):
                st.text(profile.name)
                st.text(profile.application_email or profile.email or "")
                identity = st.checkbox(
                    "表示された本人情報が正確であることを確認しました",
                    value=profile.identity_verified,
                )
                selected = []
                for claim in profile.claims:
                    st.text(claim.text)
                    st.caption("根拠: " + str(claim.source or "未登録"))
                    if st.checkbox(
                        "この実績を確認済みとして使用する",
                        key="claim-" + claim.claim_id,
                        value=claim.verification.value == "VERIFIED",
                    ):
                        selected.append(claim.claim_id)
                languages = st.multiselect(
                    "習熟度を確認した言語",
                    [language.language for language in profile.languages],
                    default=[
                        language.language
                        for language in profile.languages
                        if language.verification.value == "VERIFIED"
                    ],
                )
                st.caption("就労資格・DSO回答・CIPの適合性は、この操作では確認済みにしません。")
                if st.button("確認結果を非公開プロフィールへ保存"):
                    try:
                        result = confirm_profile(
                            private,
                            digest(profile.model_dump(mode="json")),
                            identity_confirmed=identity,
                            claim_ids=selected,
                            languages=languages,
                            timezone=settings.project.timezone,
                        )
                        st.success(f"確認済み経歴: {result['verified_claims']}件")
                    except ValueError:
                        st.error(
                            "保存できませんでした。プロフィールを再読み込みして確認してください。"
                        )
        path = root / "data/search_leads.json"
        if path.is_file():
            st.subheader("企業サイト限定検索の候補（未検証）")
            for result in json.loads(path.read_text()):
                st.code(result["query"], language=None)
                st.dataframe(
                    result["results"],
                    hide_index=True,
                    column_config={"url": st.column_config.LinkColumn("企業の出典 URL")},
                )
