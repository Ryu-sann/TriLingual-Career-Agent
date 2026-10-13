"""Read-only local Streamlit dashboard. No application execution controls."""

import os
import shlex
from pathlib import Path

import streamlit as st
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from career_agent.core.config import Settings
from career_agent.dashboard.operations_pages import render
from career_agent.database.connection import database_url, engine_for, migrate
from career_agent.database.models import WorkflowRun
from career_agent.discovery.search import SearchKeywords
from career_agent.discovery.site_search import search_links
from career_agent.models.candidate import CandidateProfile
from career_agent.models.job import Watchlist
from career_agent.workflows.job_pipeline import ranked_jobs


def main():
    os.umask(0o077)
    st.set_page_config(page_title="TriLingual Career Agent", layout="wide")
    st.title("TriLingual Career Agent — 求人一覧")
    st.info(
        "自動応募は無効です。点数はルールによる参考評価です。"
        "OPT / STEM OPT の適合や入社可能時期を確定するものではありません。"
    )
    root = Path(os.environ.get("CAREER_PROJECT_ROOT", Path.cwd())).resolve()
    try:
        settings = Settings.load(root / "config/settings.yaml")
        private = root / "data/profile/candidate_profile.yaml"
        choice = st.sidebar.selectbox("プロフィール", ["サンプル", "ローカルの本人プロフィール"])
        if choice == "ローカルの本人プロフィール" and not private.is_file():
            st.warning("本人プロフィールがありません。サンプルを選択してください。")
            return
        profile = CandidateProfile.load(
            private if choice.startswith("ローカル") else root / "examples/candidate_profile.yaml"
        )
        url = make_url(database_url())
        if url.get_backend_name() == "sqlite" and url.database not in {None, ":memory:"}:
            url = url.set(database=str(root / url.database))
        engine = engine_for(url)
        try:
            migrate(engine, root)
            section = st.sidebar.selectbox(
                "画面", ["求人一覧", "書類", "応募履歴", "メール・面接", "分析", "設定・確認事項"]
            )
            if section != "求人一覧":
                render(section, root, engine, profile, settings)
                return
            with st.expander("企業の採用サイトから直接探す"):
                title = st.text_input("探したい職種", value="Applications Engineer")
                try:
                    for employer in Watchlist.load(
                        root / "config/company_watchlist.yaml"
                    ).companies:
                        search = search_links(employer, title)
                        st.code(search["query"], language=None)
                        st.link_button(
                            f"{employer.name} の企業サイト限定検索", search["google_url"]
                        )
                        st.link_button(f"{employer.name} の採用ページ", search["careers_url"])
                except ValueError:
                    st.warning("職種名には検索演算子や引用符を含めないでください。")
            query = st.text_input(
                "求人のキーワード検索", placeholder="physics / Japanese / photonics"
            )
            keywords = SearchKeywords.load(root / "config/job_keywords.yaml")
            preset = st.sidebar.selectbox(
                "保存済み検索",
                ["自由入力", *keywords.priority_searches, *keywords.secondary_searches],
            )
            if preset != "自由入力":
                query = preset + " " + query
            st.caption("スペースで複数条件を指定できます。引用符で囲むとフレーズ検索になります。")
            try:
                shlex.split(query)
            except ValueError:
                st.warning("引用符を閉じてから検索してください。")
                return
            rows = ranked_jobs(engine, profile, settings, query=query)
            options = ["remote", "hybrid", "onsite", "unknown"]
            modes = st.sidebar.multiselect("働き方", options, default=options)
            minimum = st.sidebar.slider("最低スコア", 0, 100, 0)
            show_rejected = st.sidebar.checkbox("募集終了・対象外も表示", value=False)
            rows = [
                r
                for r in rows
                if r["score"] >= minimum
                and r["work_mode"] in modes
                and (show_rejected or r["decision"] != "REJECTED")
            ]
            st.metric("表示中の求人", len(rows))
            if not rows:
                st.warning("該当求人がありません。CLI の discover で公開求人を取得してください。")
            else:
                columns = [
                    "company",
                    "title",
                    "location",
                    "work_mode",
                    "score",
                    "decision",
                    "opt_status",
                    "stem_opt_status",
                    "provider",
                    "last_seen",
                    "source_url",
                ]
                st.dataframe(
                    [{k: row[k] for k in columns} for row in rows],
                    hide_index=True,
                    column_config={"source_url": st.column_config.LinkColumn("出典 URL")},
                )
                ids = [r["id"] for r in rows]
                names = {r["id"]: f"{r['company']} — {r['title']}" for r in rows}
                selected = st.selectbox(
                    "根拠・未確認事項を見る求人", ids, format_func=lambda value: names[value]
                )
                row = next(r for r in rows if r["id"] == selected)
                st.link_button("求人の出典を開く", row["source_url"])
                st.subheader("スコアの内訳と根拠")
                for name, component in row["components"].items():
                    with st.expander(f"{name}: {component['points']:g}/{component['maximum']}"):
                        st.text(component["reason"])
                        for ev in component["evidence"]:
                            st.text(ev["excerpt"])
                            st.caption(ev["interpretation"])
                st.subheader("求人内での言語の役割")
                st.dataframe(
                    [
                        {"language": language, "role": role}
                        for language, role in row["language_roles"].items()
                    ],
                    hide_index=True,
                )
                st.subheader("OPT / STEM OPT の確認項目")
                st.dataframe(
                    [
                        {"item": name, "status": check["status"], "reason": check["reason"]}
                        for name, check in row["checks"].items()
                    ],
                    hide_index=True,
                )
                for warning in row["warnings"]:
                    st.warning(warning)
                with st.expander("掲載元の給与情報"):
                    if row["compensation"]:
                        st.json(row["compensation"])
                        st.caption(
                            "給与の単位や対象勤務地を確認してください。自動で年換算しません。"
                        )
                    else:
                        st.text(
                            "取得した API フィールドには給与情報がありません。"
                            "求人票を確認してください。"
                        )
                with st.expander("求人票（テキスト）"):
                    st.text(row["description"])
            with st.expander("実行ログ・通信エラー"):
                with Session(engine) as session:
                    runs = list(
                        session.scalars(
                            select(WorkflowRun)
                            .where(WorkflowRun.kind == "public_job_discovery")
                            .order_by(WorkflowRun.created_at.desc())
                            .limit(10)
                        )
                    )
                    for run in runs:
                        st.json(
                            {
                                "status": run.status,
                                "created_at": run.created_at.isoformat(),
                                "summary": run.summary,
                            }
                        )
            with st.expander("検索設定"):
                st.json(
                    {
                        "weights": settings.matching.weights.model_dump(),
                        "freshness_hours": settings.discovery.freshness_hours,
                        "keywords": keywords.model_dump(),
                        "live_submission_enabled": False,
                    }
                )
            st.caption(
                "保存された観測日時から鮮度を再計算しています。通信失敗は実行ログに残ります。"
            )
        finally:
            engine.dispose()
    except Exception:
        # Validation/DB errors can contain private inputs, URLs or secrets.
        st.error(
            "設定・プロフィール・データベースを読み込めませんでした。CLI で設定を確認してください。"
        )


if __name__ == "__main__":
    main()
