"""Multi-Tenant Genie — SP management demo (Streamlit UI).

Run locally:
    cd ~/Documents/github/multi-tenant-genie
    streamlit run src/ui/app.py

The app has two tabs:
    * **Admin** — create / rotate / deactivate tenant service principals.
      Every click hits the real Databricks API on the FEVM serverless
      workspace and updates the UC mapping table.
    * **Client** — pick a tenant, ask Genie a question *as that tenant*.
      Token is minted with the tenant's SP client_credentials and the
      UC row filter enforces isolation.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.lib.config import CONFIG  # noqa: E402
from src.lib.genie_client import GenieClient  # noqa: E402
from src.lib.sp_manager import SPManager, Tenant  # noqa: E402
from src.lib.token_minter import TokenMinter  # noqa: E402


# ------------------------------------------------------------------ helpers
SECRETS_FILE = _REPO / ".demo-secrets.env"


def _load_local_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    if not SECRETS_FILE.exists():
        return out
    for line in SECRETS_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _save_local_secrets(secrets: dict[str, str]) -> None:
    SECRETS_FILE.write_text(
        "\n".join(f"{k}={v}" for k, v in secrets.items()) + "\n"
    )


def _secret_key(tenant_id: str) -> str:
    return f"MT_GENIE_SECRET_{tenant_id.upper()}"


@st.cache_resource
def get_manager() -> SPManager:
    return SPManager()


@st.cache_resource
def get_genie_client() -> GenieClient:
    return GenieClient(TokenMinter())


def fetch_tenants() -> list[Tenant]:
    return get_manager().list_tenants()


def tenant_table(tenants: list[Tenant]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "tenant_id": t.tenant_id,
                "name": t.tenant_name,
                "status": t.status,
                "sp_app_id": t.sp_app_id,
                "sp_display_name": t.sp_display_name,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tenants
        ]
    )


# ------------------------------------------------------------------ page layout
st.set_page_config(
    page_title="Multi-Tenant Genie",
    page_icon="🎭",
    layout="wide",
)

st.title("🎭 Multi-Tenant Genie — SP Management Demo")
st.caption(
    f"Workspace `{CONFIG.host.replace('https://', '')}` · "
    f"Catalog `{CONFIG.catalog}.{CONFIG.schema}` · "
    f"Genie Space `{CONFIG.genie_space_id or '(unset)'}`"
)

tab_admin, tab_client, tab_arch = st.tabs(
    ["🔧 Admin", "💬 Client View", "🏗️ Architecture"]
)


# ================================================================ ADMIN TAB
with tab_admin:
    st.subheader("Tenant Service Principals")
    colL, colR = st.columns([2, 1])

    with colL:
        tenants = fetch_tenants()
        if tenants:
            df = tenant_table(tenants)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No tenants yet — onboard your first one on the right.")

    with colR:
        st.markdown("#### ➕ Onboard new tenant")
        with st.form("onboard_form", clear_on_submit=True):
            new_id = st.text_input("tenant_id (slug)", placeholder="hersheys")
            new_name = st.text_input("Display name", placeholder="Hershey's")
            submitted = st.form_submit_button("Onboard", type="primary")
            if submitted:
                if not new_id or not new_name:
                    st.error("Both fields required")
                else:
                    with st.spinner(
                        f"Creating SP, minting secret, updating mapping…"
                    ):
                        try:
                            result = get_manager().onboard_tenant(
                                tenant_id=new_id.strip().lower(),
                                tenant_name=new_name.strip(),
                            )
                            get_manager().grant_data_access([new_id.strip().lower()])
                            get_manager().grant_genie_access([new_id.strip().lower()])
                            sec = _load_local_secrets()
                            sec[_secret_key(new_id.strip().lower())] = result.client_secret
                            _save_local_secrets(sec)
                        except Exception as e:
                            st.error(f"Onboarding failed: {e}")
                        else:
                            st.success(
                                f"Onboarded **{result.tenant.tenant_name}** — "
                                f"SP `{result.tenant.sp_app_id}`"
                            )
                            st.code(
                                f"client_id={result.client_id}\n"
                                f"client_secret={result.client_secret}",
                                language="ini",
                            )
                            time.sleep(0.5)
                            st.rerun()

    st.divider()
    st.subheader("Maintenance")

    if tenants:
        target = st.selectbox(
            "Tenant",
            options=[t.tenant_id for t in tenants],
            format_func=lambda tid: next(
                f"{t.tenant_name} ({t.status})" for t in tenants if t.tenant_id == tid
            ),
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔁 Rotate secret", use_container_width=True):
                with st.spinner("Rotating OAuth secret…"):
                    try:
                        new_secret = get_manager().rotate_secret(target)
                        sec = _load_local_secrets()
                        sec[_secret_key(target)] = new_secret
                        _save_local_secrets(sec)
                        st.success("New secret stored. Old one revoked.")
                        st.code(f"new_client_secret={new_secret}", language="ini")
                    except Exception as e:
                        st.error(f"Rotation failed: {e}")
        with c2:
            if st.button("🗑️ Deactivate tenant", type="secondary", use_container_width=True):
                with st.spinner("Disabling SP, flipping mapping, revoking secrets…"):
                    try:
                        get_manager().deactivate_tenant(target)
                        st.success(
                            f"Deactivated **{target}**. "
                            "Any stale tokens will fail now."
                        )
                        time.sleep(0.4)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Deactivate failed: {e}")


# ================================================================ CLIENT TAB
with tab_client:
    st.subheader("Ask Genie as a tenant")
    st.caption(
        "Each tenant query is authenticated via OAuth client_credentials as "
        "their Service Principal. Unity Catalog row filters enforce isolation."
    )

    active_tenants = [t for t in fetch_tenants() if t.status == "active"]
    if not active_tenants:
        st.warning("No active tenants. Onboard one in the Admin tab first.")
    else:
        secrets = _load_local_secrets()
        pick = st.selectbox(
            "I am…",
            options=[t.tenant_id for t in active_tenants],
            format_func=lambda tid: next(
                t.tenant_name for t in active_tenants if t.tenant_id == tid
            ),
        )
        tenant = next(t for t in active_tenants if t.tenant_id == pick)
        secret = secrets.get(_secret_key(tenant.tenant_id))

        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("tenant_id", tenant.tenant_id)
            c2.metric("SP display", tenant.sp_display_name)
            c3.metric("SP app_id", tenant.sp_app_id[:8] + "…")

            if not secret:
                st.error(
                    f"No secret stored for `{tenant.tenant_id}`. "
                    "Rotate the secret in the Admin tab to generate one."
                )
            else:
                st.success(
                    "OAuth client_credentials ready. Token will be minted "
                    "on first call and cached in memory."
                )

        if secret:
            default_q = "How many bookings do I have and what is my total spend?"
            q = st.text_area("Question", value=default_q, height=80)
            ask = st.button("Ask Genie", type="primary")

            if ask and q.strip():
                started = time.time()
                with st.spinner("Minting token, calling Genie, polling for result…"):
                    try:
                        r = get_genie_client().ask(
                            space_id=CONFIG.genie_space_id,
                            question=q.strip(),
                            client_id=tenant.sp_app_id,
                            client_secret=secret,
                            timeout_s=120,
                        )
                    except Exception as e:
                        st.error(f"Genie call failed: {e}")
                        r = None

                if r is not None:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Status", r.status)
                    m2.metric("Latency", f"{r.latency_ms} ms")
                    m3.metric("Rows", len(r.rows))
                    if r.answer_text:
                        st.markdown(f"**Answer:** {r.answer_text}")
                    if r.sql:
                        with st.expander("Generated SQL", expanded=False):
                            st.code(r.sql, language="sql")
                    if r.rows:
                        df = pd.DataFrame(r.rows, columns=r.columns or None)
                        st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### 🧪 Isolation proof")
        st.caption(
            "Run the same question as *every* active tenant side by side. "
            "Rows differ, SQL is identical — UC row filters are invisible to Genie."
        )
        if st.button("Run isolation sweep"):
            col_proof = st.columns(len(active_tenants))
            for idx, t in enumerate(active_tenants):
                sec = _load_local_secrets().get(_secret_key(t.tenant_id))
                if not sec:
                    col_proof[idx].error(f"{t.tenant_name}: no secret")
                    continue
                with col_proof[idx]:
                    st.markdown(f"**{t.tenant_name}**")
                    try:
                        r = get_genie_client().ask(
                            space_id=CONFIG.genie_space_id,
                            question=q.strip() if 'q' in locals() else default_q,
                            client_id=t.sp_app_id,
                            client_secret=sec,
                            timeout_s=120,
                        )
                        st.write(r.answer_text or "(no text)")
                        st.caption(f"latency {r.latency_ms} ms · {len(r.rows)} rows")
                    except Exception as e:
                        st.error(str(e))


# ================================================================ ARCH TAB
with tab_arch:
    st.subheader("What's actually happening")
    st.markdown(
        """
1. **Onboarding** creates a workspace Service Principal + its first OAuth
   secret, stores the secret in a Databricks-backed secret scope, and inserts
   a row into `sp_tenant_mapping` so UC knows which SP is allowed to see
   which `tenant_id`.
2. **Client calls** mint an OAuth token via `client_credentials` against
   `/oidc/v1/token` using the tenant's SP. `session_user()` inside UC then
   resolves to the SP's `application_id`.
3. **Row filter** `tenant_row_filter(tenant_id)` is bound to `bookings` and
   `customers`. For every row Genie touches, UC checks:
   ```sql
   EXISTS (
     SELECT 1 FROM sp_tenant_mapping m
     WHERE m.sp_app_id = session_user()
       AND m.active = true
       AND m.tenant_id = tenant_row_filter.tenant_id
   )
   ```
4. **Rotation** creates a second secret before deleting the first, so
   in-flight tokens keep working until they naturally expire.
5. **Deactivate** flips `active=false` in the mapping, marks the SP
   inactive, and deletes all its OAuth secrets — any cached token stops
   working the next time a Databricks API re-validates it.

Everything above is deterministic Unity Catalog behavior. Nothing depends
on prompt shape, Genie model output, or the app doing the right thing.
        """
    )

    st.markdown("#### Mapping table — live")
    try:
        mgr = get_manager()
        rows = mgr._execute_sql(
            f"SELECT sp_app_id, tenant_id, active FROM {CONFIG.fq_mapping} "
            "ORDER BY tenant_id"
        )
        st.dataframe(
            pd.DataFrame(rows, columns=["sp_app_id", "tenant_id", "active"]),
            hide_index=True,
            use_container_width=True,
        )
    except Exception as e:
        st.error(str(e))

    st.markdown("#### Row filter SQL — live")
    st.code(
        f"""CREATE OR REPLACE FUNCTION {CONFIG.fq_row_filter}(tenant_param STRING)
RETURN
  is_account_group_member('{CONFIG.admin_group}')
  OR EXISTS (
    SELECT 1 FROM {CONFIG.fq_mapping} m
    WHERE m.sp_app_id = session_user()
      AND m.active = true
      AND m.tenant_id = tenant_param
  );

ALTER TABLE {CONFIG.fq_bookings}
  SET ROW FILTER {CONFIG.fq_row_filter} ON (tenant_id);""",
        language="sql",
    )
