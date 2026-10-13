import os
import shutil
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from career_agent.applications.answers import Question, answer_question


class FormHold(Exception):
    pass


def execute_form(profile, spec, resume, evidence_dir, *, mode, before_submit):
    target, post = urlsplit(spec.url), urlsplit(spec.post_url)
    if post.netloc != target.netloc or post.scheme != target.scheme:
        raise FormHold("post_destination_not_authorized")
    evidence_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    submitted = False
    with sync_playwright() as p:
        proxy_uri = os.environ.get("CAREER_BROWSER_PROXY") or os.environ.get("HTTPS_PROXY")
        proxy = None
        if (
            mode != "fixture"
            and urlsplit(spec.url).hostname not in {"localhost", "127.0.0.1"}
            and proxy_uri
        ):
            parsed_proxy = urlsplit(proxy_uri)
            proxy = {
                "server": (
                    f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port or 80}"
                )
            }
            if parsed_proxy.username:
                proxy["username"] = parsed_proxy.username
                proxy["password"] = parsed_proxy.password or ""
        browser = p.chromium.launch(
            executable_path=os.environ.get("CAREER_CHROMIUM_PATH")
            or shutil.which("chromium")
            or shutil.which("google-chrome"),
            headless=True,
            proxy=proxy,
        )
        try:
            context = browser.new_context()
            state = {"posts_allowed": False, "frozen": False}

            def guard(route):
                request, parsed = route.request, urlsplit(route.request.url)
                if state["frozen"]:
                    route.abort()
                elif mode == "fixture" and parsed.hostname != target.hostname:
                    route.abort()
                elif (
                    request.method in {"GET", "HEAD"}
                    and parsed.scheme == target.scheme
                    and (
                        parsed.hostname == target.hostname
                        or parsed.hostname in spec.resource_domains
                    )
                ):
                    route.continue_()
                elif (
                    state["posts_allowed"]
                    and request.method == "POST"
                    and (parsed.scheme, parsed.netloc, parsed.path)
                    == (post.scheme, post.netloc, post.path)
                ):
                    route.continue_()
                else:
                    route.abort()

            context.route("**/*", guard)
            page = context.new_page()
            page.goto(spec.url, wait_until="domcontentloaded", timeout=30000)
            if page.locator(
                'iframe[src*="captcha"], [data-sitekey], input[autocomplete="one-time-code"], '
                'input[type="password"]'
            ).count():
                raise FormHold("captcha_mfa_or_login_requires_manual_action")
            configured = {f.selector for f in spec.fields} | {spec.resume_selector}
            for node in page.locator("input, select, textarea").all():
                kind = node.get_attribute("type") or "text"
                if kind in {"hidden", "submit", "button"}:
                    continue
                if "#" + (node.get_attribute("id") or "") not in configured:
                    raise FormHold("unknown_form_question")
            answers = []
            for field in spec.fields:
                node = page.locator(field.selector)
                if node.count() != 1:
                    raise FormHold("form_schema_changed")
                labels = page.locator(f'label[for="{field.selector[1:]}"]').all_inner_texts()
                label = " ".join(labels).strip() or node.get_attribute("aria-label")
                question = Question.model_validate(field.question)
                required_now = (
                    node.get_attribute("required") is not None
                    or node.get_attribute("aria-required") == "true"
                )
                if required_now and not question.required:
                    raise FormHold("required_question_changed")
                if not label or label.casefold() != question.label.strip().casefold():
                    raise FormHold("question_label_changed")
                answer = answer_question(question, profile)
                if answer.status not in {"VERIFIED", "OMIT"}:
                    raise FormHold("answer_not_verified")
                answers.append((node, answer))
            state["frozen"] = mode == "dry_run"
            for node, answer in answers:
                if answer.status == "OMIT":
                    continue
                if node.evaluate("e => e.tagName") == "SELECT":
                    node.select_option(label=answer.value)
                else:
                    node.fill(answer.value)
            page.locator(spec.resume_selector).set_input_files(str(resume))
            if not page.locator("form").evaluate_all(
                "forms => forms.every(f => f.checkValidity())"
            ):
                raise FormHold("required_answers_or_document_invalid")
            screenshot = evidence_dir / "prefilled.png"
            page.screenshot(path=str(screenshot))
            if mode == "dry_run":
                return {"status": "DRY_RUN", "evidence": str(screenshot)}
            private_answers = [
                {
                    "question": field.question["label"],
                    "answer": answer.value,
                    "verification": answer.status,
                    "claim_ids": answer.claim_ids,
                }
                for field, (_, answer) in zip(spec.fields, answers, strict=True)
                if answer.status == "VERIFIED"
            ]
            if not page.locator(spec.submit_selector).is_enabled():
                raise FormHold("form_not_ready")
            before_submit(private_answers, screenshot)  # Commit reservation BEFORE the click.
            state["posts_allowed"] = True
            submitted = True
            page.locator(spec.submit_selector).click(timeout=15000)
            confirmation = page.locator(spec.confirmation_selector)
            confirmation.wait_for(state="visible", timeout=15000)
            if spec.confirmation_text not in confirmation.inner_text():
                return {"status": "UNKNOWN_SUBMISSION", "evidence": str(screenshot)}
            screenshot = evidence_dir / "confirmation.png"
            page.screenshot(path=str(screenshot))
            return {
                "status": "SUBMITTED",
                "evidence": str(screenshot),
                "confirmation_url": page.url,
            }
        except FormHold:
            raise
        except Exception as exc:
            if submitted:
                return {
                    "status": "UNKNOWN_SUBMISSION",
                    "evidence": str(evidence_dir / "prefilled.png"),
                }
            raise FormHold("browser_preparation_failed") from exc
        finally:
            browser.close()
