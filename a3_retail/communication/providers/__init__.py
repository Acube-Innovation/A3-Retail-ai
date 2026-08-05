# Copyright (c) 2026, Acube Innovations Pvt Ltd and contributors
"""Provider abstraction (scope 9.2, ADR-06).

The client needs separate numbers per stream and may switch vendor, so the send
path talks to this interface and never to a vendor SDK.
"""

import frappe


def get_provider():
	"""Return the provider implementation named in WhatsApp Settings."""
	from a3_retail.communication.providers.base import NullProvider
	from a3_retail.communication.providers.meta_cloud import MetaCloudProvider

	name = frappe.db.get_single_value("WhatsApp Settings", "provider") or "Meta Cloud API"
	registry = {
		"Meta Cloud API": MetaCloudProvider,
	}
	return registry.get(name, NullProvider)()
