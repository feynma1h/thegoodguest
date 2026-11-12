"""tools/enqueue_still.py: the task it builds, with no queue and no credentials.

The one fact worth pinning is the audience: it is the service's /still even
when the POST goes to the candidate--- tag, or the candidate refuses the token.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import enqueue_still as tool  # noqa: E402

SID = "e64fab6a-f48e-427a-bcc9-f72208c6357d"


def test_a_candidate_task_posts_to_the_tag_with_the_services_audience():
    task = tool.still_task("p/l/q", SID, candidate=True, now=7)
    http = task["http_request"]
    assert http["url"] == tool.CANDIDATE_URL + "/still"
    assert http["oidc_token"] == {"service_account_email": tool.INVOKER_SA, "audience": tool.RECEIVER_URL + "/still"}
    assert json.loads(http["body"]) == {"scene_id": SID}
    assert task["name"] == f"p/l/q/tasks/still-{SID}-7"
    assert task["dispatch_deadline"].seconds == 930


def test_a_service_task_posts_to_the_service():
    http = tool.still_task("p/l/q", SID, candidate=False, now=7)["http_request"]
    assert http["url"] == http["oidc_token"]["audience"] == tool.RECEIVER_URL + "/still"
