"""Create A3 Retail roles before doctypes sync so permission rows resolve."""

from a3_retail.install import create_roles


def execute():
	create_roles()
