from __future__ import annotations

import json

from backend import access, admin, admin_catalog, catalog_expansion, defaults, guides, store


def main():
    store.init_db()
    defaults.initialize()
    guides.initialize()
    admin.bootstrap_admin()
    admin_catalog.install()
    access.initialize_grants()
    access.initialize_spaces()
    catalog_expansion.install()
    defaults.sync_all()
    with store.connect() as db:
        counts = {row["kind"]: row["n"] for row in db.execute("SELECT kind,count(*) n FROM default_templates GROUP BY kind")}
        copies = db.execute("SELECT count(*) FROM entities WHERE json_extract(data,'$.default_template_id') IS NOT NULL").fetchone()[0]
    print(json.dumps({"default_templates": counts, "managed_copies": copies, "private_resources": "preserved"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
