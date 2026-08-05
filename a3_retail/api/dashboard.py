"""A3 Retail — dashboard API endpoints.

Populated by the build steps that own this domain. Every method must call one of
the helpers in `a3_retail.api` before touching data.
"""

import frappe
from frappe import _

from a3_retail.api import parse_payload, require_branch_access, require_permission, require_role
