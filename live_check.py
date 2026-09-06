"""Opt-in real mailbox check. Sends only to the configured account itself."""

import argparse
import base64
import json
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from netease_email.mail import AttachmentRef, Compose, Draft, Flags, Mailbox, MailError, MessageRef, Move, Search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send-to-self", action="store_true", required=True,
                        help="Authorize one test email and draft, flag changes, and moving only these test messages to Trash")
    parser.parse_args()
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    state_path = root / ".live-test-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"marker": "connector-check-" + uuid.uuid4().hex}

    def save():
        temporary = state_path.with_suffix(".json.tmp")
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
            json.dump(state, stream)
        temporary.replace(state_path)

    if state.get("completed"):
        print("This test run already passed; no additional email was sent.")
        return
    save()
    box = Mailbox()
    box.writable()
    folders = box.list_folders()["folders"]
    drafts = next(f["name"] for f in folders if r"\Drafts" in f["flags"])
    trash = next(f["name"] for f in folders if r"\Trash" in f["flags"])
    print("PASS: TLS login and list_folders", flush=True)

    def find(folder, suffix, wait=False):
        for attempt in range(12 if wait else 1):
            try:
                results = box.search_emails(Search(folder=folder, query=state["marker"] + suffix, limit=2))["messages"]
            except MailError as exc:
                # NetEase's index can expose a just-moved UID before FETCH can read it.
                if not wait or "IMAP FETCH failed" not in str(exc) or attempt == 11:
                    raise
                results = []
            if results:
                if len(results) != 1:
                    raise RuntimeError("Multiple test messages found; inspect before continuing")
                return results[0]["ref"]
            if wait and attempt < 11:
                time.sleep(2)
        return None

    payload = {"to": [box.address], "subject": "连接器测试 " + state["marker"] + "-mail",
               "text": "这是连接器的自发自收测试邮件，不包含真实业务数据。",
               "html": "<p>这是连接器的自发自收测试邮件。</p>",
               "attachments": [{"filename": "测试.txt", "content_type": "text/plain",
                                "content_base64": base64.b64encode("附件测试通过".encode()).decode()}]}
    if not state.get("send_attempted"):
        state["send_attempted"] = True
        save()  # Record before SMTP: an interrupted/uncertain send must never be retried automatically.
        result = box.send_email(Compose(**payload))
        state["smtp_status"] = result["status"]
        save()
        if result["status"] != "accepted":
            raise RuntimeError("SMTP did not accept all test recipients; inspect mailbox before continuing")
    ref = find("INBOX", "-mail") or find(trash, "-mail") or find("INBOX", "-mail", wait=True)
    if not ref:
        raise RuntimeError("Test email not found. Send was already attempted; it will not be retried. Check delivery manually.")
    print("PASS: send_email and search_emails (self-delivery)", flush=True)
    read = box.read_email(MessageRef(**ref))
    assert payload["text"] in read["body"], "Body mismatch"
    assert read["attachments"][0]["filename"] == "测试.txt", "Attachment filename mismatch"
    part = box.download_attachment(AttachmentRef(**ref, attachment_id=read["attachments"][0]["attachment_id"]))
    assert base64.b64decode(part["content_base64"]).decode() == "附件测试通过", "Attachment content mismatch"
    print("PASS: read_email and download_attachment", flush=True)
    box.set_flags(Flags(**ref, seen=True, flagged=True))
    assert {r"\Seen", r"\Flagged"}.issubset(box.read_email(MessageRef(**ref))["flags"]), "Flags were not set"
    box.set_flags(Flags(**ref, seen=False, flagged=False))
    assert not {r"\Seen", r"\Flagged"}.intersection(box.read_email(MessageRef(**ref))["flags"]), "Flags were not cleared"
    print("PASS: set_flags set and clear", flush=True)
    if ref["folder"] != trash:
        box.move_email(Move(**ref, destination=trash))
        assert not find("INBOX", "-mail"), "Source message still present"
    assert find(trash, "-mail", wait=True), "Destination message missing"
    print("PASS: move_email; test email retained in Trash", flush=True)

    if not state.get("draft_attempted"):
        state["draft_attempted"] = True
        save()
        box.save_draft(Draft(**{**payload, "subject": "连接器草稿测试 " + state["marker"] + "-draft"}, folder=drafts))
    draft_ref = find(drafts, "-draft") or find(trash, "-draft") or find(drafts, "-draft", wait=True)
    if not draft_ref:
        raise RuntimeError("Draft was attempted but not found; inspect manually, no automatic duplicate append")
    assert payload["text"] in box.read_email(MessageRef(**draft_ref))["body"]
    if draft_ref["folder"] != trash:
        box.move_email(Move(**draft_ref, destination=trash))
    assert find(trash, "-draft", wait=True), "Moved draft missing"
    state["completed"] = True
    save()
    print("PASS: save_draft; test draft retained in Trash", flush=True)
    print("PASS: all 8 live mail operations; only self-addressed test data was changed", flush=True)


if __name__ == "__main__":
    main()
