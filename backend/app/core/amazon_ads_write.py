"""The ONLY module permitted to make mutating Amazon Ads API calls.

Every other module in this codebase is read-only. Keeping writes in one small
file means the blast radius is auditable by reading a single module — you can
see everything the app is capable of changing in your ad account in one place.

Permitted operations, and nothing else:
  - change one keyword's bid          PUT  /sp/keywords
  - change one product target's bid   PUT  /sp/targets
  - add one negative keyword          POST /sp/negativeKeywords

Deliberately NOT here: creating or deleting campaigns, ad groups or product
ads; changing budgets; pausing anything. The test campaign is created by a
human in Amazon's console precisely so this surface stays small.

Safety model
------------
1. settings.amazon_write_enabled is a master kill-switch, default False.
   Every public function calls assert_write_enabled() FIRST, before building
   a request, so with the switch off no mutating request can even be
   constructed. A test enforces that ordering by inspecting source.
2. Callers must record the attempt in suggestion_actions before and after the
   call — see ExecutionService. This module never touches the database.
3. One call per suggestion. No batching in V1, per the spec: it trades API
   efficiency for per-suggestion error isolation.
4. v3 mutation endpoints return 200/207 with per-item success and error
   arrays, so HTTP status alone does not mean the change happened.
   _parse_mutation_result inspects the body and returns a definite ok flag.
"""
import logging
from typing import Any

import requests

from app.config import settings
from app.core.amazon_ads import _request_with_retry

logger = logging.getLogger(__name__)


class AmazonWriteDisabled(Exception):
    """Raised when a write is attempted while AMAZON_WRITE_ENABLED is false."""


def assert_write_enabled() -> None:
    """Gate every mutating call. Raises unless writes are explicitly enabled."""
    if not settings.amazon_write_enabled:
        raise AmazonWriteDisabled(
            "Amazon writes are disabled (AMAZON_WRITE_ENABLED=false). "
            "This is the default: the app cannot modify a live ad account "
            "until writes are explicitly authorised."
        )
