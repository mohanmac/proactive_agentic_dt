"""
Zerodha Intraday Bot — real-money, phase-aware auto loop.

Once you click **Enable bot**, the background TradingEngine takes over:
  • Pre-market (<9:15) — idle
  • 9:15–9:30        — auto-arms, warm-up, no trades
  • 9:30–10:15       — observation only (noisy open)
  • 10:15–14:45      — scans every 5s; trades if Auto-execute is ON
  • 14:45–15:30      — no new entries; broker MIS auto-squares-off

Enabling the bot starts monitoring/scanning and turns **Auto-execute orders**
ON automatically; live broker orders still require `ENABLE_LIVE_TRADING=true`.

The dashboard auto-refreshes every 15s and auto-logs-off at 15:40 IST (after
broker MIS square-off) on trading days.
"""
from __future__ import annotations

import sys
import logging
import traceback
from html import escape
from datetime import datetime
from pathlib import Path

# Trust the OS keychain so corporate MITM TLS works. Must run before any HTTPS.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import streamlit as st

sys.path.append(str(Path(__file__).resolve().parent.parent))

st.set_page_config(
    page_title="Zerodha Intraday Bot",
    layout="wide",
    initial_sidebar_state="expanded",
)

GLOBAL_CSS = """
<style>
/* ── App-wide theme polish ─────────────────────────────────────────── */
.block-container { padding-top: 1.2rem; max-width: 1400px; }
[data-testid="stMetric"] {
  background: linear-gradient(160deg, rgba(34,197,94,0.06), rgba(59,130,246,0.05));
  border: 1px solid rgba(148,163,184,0.18);
  border-radius: 14px;
  padding: 10px 14px;
}
[data-testid="stMetricLabel"] { color: #94a3b8; font-size: 0.74rem; letter-spacing: 0.04em; text-transform: uppercase; }
div[data-testid="stSidebar"] { background: linear-gradient(180deg, #0d1526 0%, #0b1220 100%); }
.hero {
  border-radius: 20px;
  padding: 26px 30px 22px 30px;
  margin-bottom: 14px;
  background:
    radial-gradient(circle at 12% 0%, rgba(34,197,94,0.22), transparent 42%),
    radial-gradient(circle at 88% 100%, rgba(59,130,246,0.20), transparent 45%),
    linear-gradient(135deg, #0f1b31 0%, #101a2e 100%);
  border: 1px solid rgba(148,163,184,0.20);
  box-shadow: 0 8px 40px rgba(2,6,23,0.45);
}
.hero h1 { margin: 0; font-size: 1.75rem; color: #f1f5f9; letter-spacing: -0.01em; }
.hero .sub { color: #94a3b8; font-size: 0.92rem; margin-top: 6px; }
.hero-pills { margin-top: 14px; }
.pill {
  display: inline-block; border-radius: 999px; padding: 4px 13px;
  font-size: 0.74rem; font-weight: 700; margin-right: 8px; letter-spacing: 0.03em;
  border: 1px solid rgba(148,163,184,0.25); color: #cbd5e1; background: rgba(15,23,42,0.5);
}
.pill.green { color: #4ade80; border-color: rgba(34,197,94,0.45); background: rgba(34,197,94,0.10); }
.pill.amber { color: #fbbf24; border-color: rgba(245,158,11,0.45); background: rgba(245,158,11,0.10); }
.pill.red   { color: #f87171; border-color: rgba(239,68,68,0.45);  background: rgba(239,68,68,0.10); }
.pill.blue  { color: #93c5fd; border-color: rgba(59,130,246,0.45); background: rgba(59,130,246,0.10); }
.step-card {
  border-radius: 16px; padding: 18px 20px; height: 100%;
  background: linear-gradient(160deg, rgba(30,41,59,0.65), rgba(15,23,42,0.65));
  border: 1px solid rgba(148,163,184,0.22);
}
.step-num {
  display:inline-flex; align-items:center; justify-content:center;
  width: 30px; height: 30px; border-radius: 10px; font-weight: 800;
  background: rgba(34,197,94,0.16); color: #4ade80; margin-bottom: 10px;
}
.step-card h4 { margin: 0 0 6px 0; color: #e2e8f0; }
.step-card p { color: #94a3b8; font-size: 0.85rem; margin: 0; }
</style>
"""


def hero_header(authed: bool, live: bool, market_open: bool) -> None:
    mode_pill = (
        "<span class='pill red'>LIVE MONEY</span>" if (authed and live)
        else "<span class='pill amber'>DRY-RUN</span>"
    )
    auth_pill = (
        "<span class='pill green'>● KITE CONNECTED</span>" if authed
        else "<span class='pill'>○ NOT LOGGED IN</span>"
    )
    mkt_pill = (
        "<span class='pill blue'>MARKET OPEN</span>" if market_open
        else "<span class='pill'>MARKET CLOSED</span>"
    )
    st.markdown(
        "<div class='hero'>"
        "<h1>⚡ Zerodha Intraday Bot</h1>"
        "<div class='sub'>NIFTY-500 · ₹40–600 price band · ₹2,000/day capital · "
        "daily loss capped at ₹200 (10%) · auto square-off 15:15 IST</div>"
        f"<div class='hero-pills'>{auth_pill}{mode_pill}{mkt_pill}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


# Paint immediately so Streamlit Cloud never shows a blank page while imports/init run.
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
_boot_status = st.empty()
_boot_status.info("Loading dashboard…")

log = logging.getLogger("app")
log.info("dashboard_module_loaded")

try:
    from app.core.config import settings
    from app.core.zerodha_auth import zerodha_auth
    from app.core.env_bootstrap import is_streamlit_cloud, CLOUD_APP_URL
    from app.core.market_calendar import (
        can_place_nse_bse_equity_trade,
        is_nse_bse_trading_day,
        market_status_line,
        ist_now,
        IST,
    )
except Exception as e:
    _boot_status.error(f"Import failed: {e}")
    st.code(traceback.format_exc())
    st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
ss = st.session_state
ss.setdefault("authed", False)
ss.setdefault("profile", None)
ss.setdefault("strategy_enabled", {
    "Opening Range Breakout": True,
    "VWAP Pullback": True,
    "Momentum": True,
})


# ─────────────────────────────────────────────────────────────────────────────
# Auth bootstrap
# ─────────────────────────────────────────────────────────────────────────────
def bootstrap_auth() -> None:
    """Handle OAuth redirect query params only (fast — no blocking Kite API calls)."""
    if ss.authed:
        return
    qp = st.query_params
    if "auth_error" in qp:
        err = qp.get("auth_error")
        try:
            st.query_params.clear()
        except Exception:
            pass
        ss._oauth_error = f"Login failed: {err}"
        return
    if "request_token" not in qp:
        return
    token = str(qp.get("request_token") or "").strip()
    # Single-use token: only attempt each one once per session. Don't clear the
    # URL or rerun on a repeat — that's what created the silent login loop.
    if not token or ss.get("_oauth_token_done") == token:
        return
    ss._oauth_token_done = token
    try:
        zerodha_auth.exchange_request_token(token)
        log.info("kite_oauth_exchange_success")
        ok, profile = zerodha_auth.validate_token()
    except Exception as exc:
        log.exception("kite_oauth_exchange_failed")
        ss._oauth_error = f"Kite login failed: {exc}. Generate a fresh token and retry."
        return
    if ok and profile:
        ss.authed = True
        ss.profile = {
            "user_id": profile.get("user_id"),
            "user_name": profile.get("user_name"),
            "email": profile.get("email"),
        }
        ss._oauth_error = None
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.rerun()
    else:
        ss._oauth_error = "Token exchanged but Kite profile validation failed. Generate a fresh token and retry."


def try_restore_session() -> None:
    """Restore a saved Kite token. Retries (rate-limited) rather than once per
    session — on Streamlit Cloud the websocket can drop right after login, and a
    reconnect must be able to pick the freshly saved token back up."""
    if ss.authed:
        return
    import time as _time
    last = float(ss.get("_auth_restore_last") or 0.0)
    if _time.time() - last < 30.0:
        return
    ss._auth_restore_last = _time.time()
    try:
        zerodha_auth._load_token()
        if not zerodha_auth.kite.access_token:
            return
        ok, profile = zerodha_auth.validate_token()
        if ok and profile:
            ss.authed = True
            ss.profile = {
                "user_id": profile.get("user_id"),
                "user_name": profile.get("user_name"),
                "email": profile.get("email"),
            }
    except Exception as e:
        log.exception("try_restore_session failed")
        st.sidebar.warning(f"Auth check failed: {e}")


@st.cache_resource
def get_engine():
    """Singleton engine — created on first use, not at import."""
    from app.core.trading_engine import TradingEngine
    return TradingEngine()


@st.cache_resource
def get_orchestrator():
    """One Orchestrator across Streamlit reruns — threads aren't recreated each tick."""
    from app.agents.orchestrator import Orchestrator
    return Orchestrator()


@st.cache_resource
def _intraday_rules():
    from app.core.intraday_agent import (
        MIN_TARGET_PCT,
        MAX_STOP_LOSS_PCT,
        MAX_TRADES_PER_DAY,
        session_capital,
        scan_intraday_universe,
    )
    return MIN_TARGET_PCT, MAX_STOP_LOSS_PCT, MAX_TRADES_PER_DAY, session_capital, scan_intraday_universe


ss.setdefault("agents_running", False)


def get_orch():
    """Lazy init — avoids Cloud deploy rollback when orchestrator fails at import time."""
    try:
        return get_orchestrator()
    except Exception as e:
        st.error(f"Orchestrator() failed: {e}")
        st.code(traceback.format_exc())
        st.stop()


def orch_running() -> bool:
    """Is the agent loop actually running? (process-wide truth)

    Computed from agent thread liveness rather than orch.running, because the
    Orchestrator is an @st.cache_resource singleton: on a hot redeploy Streamlit
    may hand back an instance built from the PREVIOUS code revision (which lacks
    the `running` property), so `orch.running` would raise AttributeError. The
    `agents` list and each agent's `_thread` have existed all along, so reading
    them works against a stale cached instance too. Falls back to the property
    if present (covers any future agent-list refactor)."""
    orch = get_orch()
    prop = getattr(type(orch), "running", None)
    if isinstance(prop, property):
        try:
            return bool(orch.running)
        except Exception:
            pass
    return any(
        getattr(a, "_thread", None) is not None and a._thread.is_alive()
        for a in getattr(orch, "agents", [])
    )


def attached_to_existing_session() -> bool:
    """True when this browser is viewing a bot started by another session/device."""
    try:
        snap = get_engine().snapshot()
        return bool(ss.authed and (snap.enabled or orch_running()) and not ss.get("agents_running"))
    except Exception:
        return False


def shared_session_notice() -> None:
    """Explain cross-device monitoring vs starting a new trading session."""
    if attached_to_existing_session():
        st.info(
            "Attached to the existing trading session. This device is monitoring the same "
            "bot, orders, and 9-agent state; do not start a second session."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
PULSE_CSS = """
<style>
@keyframes pulseDot {
  0%   { opacity: 1; transform: scale(1); }
  50%  { opacity: 0.35; transform: scale(1.4); }
  100% { opacity: 1; transform: scale(1); }
}
.pulse-dot {
  display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; background: #16a34a; margin-right: 6px;
  vertical-align: middle; animation: pulseDot 1.1s ease-in-out infinite;
}
.dormant-dot {
  display: inline-block; width: 9px; height: 9px;
    border-radius: 50%; background: #f59e0b; margin-right: 6px;
    vertical-align: middle; opacity: 0.85;
}
.done-dot {
  display: inline-block; width: 9px; height: 9px;
    border-radius: 50%; background: #dc2626; margin-right: 6px;
  vertical-align: middle;
}
.agent-line { font-family: ui-monospace, Menlo, monospace; font-size: 0.78rem; line-height: 1.5; }
.flow-chip {
    display: inline-block;
    border-radius: 999px;
    padding: 0 7px;
    font-size: 0.66rem;
    line-height: 1.5;
    margin-left: 6px;
    vertical-align: middle;
}
.flow-parallel { background: rgba(59,130,246,0.22); color: #93c5fd; }
.flow-sequence { background: rgba(16,185,129,0.20); color: #6ee7b7; }
.agent-flow-stage {
  margin: 14px 0 22px 0;
  padding: 16px;
  border: 1px solid rgba(148,163,184,0.22);
  border-radius: 18px;
  background:
    radial-gradient(circle at top left, rgba(59,130,246,0.12), transparent 30%),
    rgba(15,23,42,0.025);
}
.agent-flow-title {
  display:flex; align-items:center; justify-content:space-between;
  gap: 12px; margin-bottom: 12px;
}
.agent-flow-title h3 { margin:0; font-size: 1.05rem; }
.agent-flow-legend { color:#64748b; font-size:0.78rem; }
.agent-flow-grid {
  display:grid;
  grid-template-columns: minmax(92px, 0.8fr) 1.2fr 1.45fr 1.2fr minmax(110px, 0.9fr);
  gap: 12px;
  align-items: stretch;
}
.flow-group {
  border:1px solid rgba(148,163,184,0.20);
  border-radius:16px;
  padding:10px;
  min-height:132px;
  background:rgba(255,255,255,0.55);
  position:relative;
}
.flow-group-label {
  font-size:0.70rem;
  letter-spacing:0.06em;
  text-transform:uppercase;
  color:#64748b;
  margin-bottom:8px;
  font-weight:700;
}
.flow-card {
  border-radius:14px;
  padding:9px 10px;
  margin:7px 0;
  border:1px solid rgba(148,163,184,0.25);
  background:#fff;
  box-shadow:0 1px 6px rgba(15,23,42,0.06);
}
.flow-card.active {
  border-color:rgba(22,163,74,0.55);
  box-shadow:0 0 0 2px rgba(34,197,94,0.10), 0 0 18px rgba(34,197,94,0.18);
  animation: activeCardGlow 1.25s ease-in-out infinite;
}
.flow-card.dormant { border-color:rgba(245,158,11,0.42); }
.flow-card.finished { border-color:rgba(220,38,38,0.42); }
.flow-card-name {
  font-weight:700;
  font-size:0.82rem;
  color:#0f172a;
}
.flow-card-task {
  margin-top:3px;
  font-size:0.70rem;
  color:#64748b;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.flow-status {
  float:right;
  font-size:0.62rem;
  font-weight:800;
  border-radius:999px;
  padding:1px 6px;
}
.flow-status.active { color:#15803d; background:rgba(34,197,94,0.13); }
.flow-status.dormant { color:#b45309; background:rgba(245,158,11,0.16); }
.flow-status.finished { color:#b91c1c; background:rgba(220,38,38,0.12); }
.flow-arrow {
  position:absolute;
  right:-18px;
  top:50%;
  width:24px;
  height:2px;
  background:linear-gradient(90deg, rgba(59,130,246,0.25), rgba(59,130,246,0.9));
  animation: arrowPulse 1.2s linear infinite;
  z-index:2;
}
.flow-arrow:after {
  content:"";
  position:absolute;
  right:-1px;
  top:-4px;
  border-left:8px solid rgba(59,130,246,0.9);
  border-top:5px solid transparent;
  border-bottom:5px solid transparent;
}
@keyframes activeCardGlow {
  0%,100% { transform:translateY(0); }
  50% { transform:translateY(-2px); }
}
@keyframes arrowPulse {
  0% { opacity:0.25; transform:translateX(-5px); }
  50% { opacity:1; }
  100% { opacity:0.25; transform:translateX(5px); }
}
@media (max-width: 900px) {
  .agent-flow-grid { grid-template-columns:1fr; }
  .flow-arrow { display:none; }
}
</style>
"""


def sidebar_llm_meter() -> None:
    """LLM tokens + tokens-per-trade — always visible at the top of the sidebar."""
    try:
        from app.core.llm import llm_client
        total_tokens = int(getattr(llm_client, "total_tokens_used", 0) or 0)
    except Exception:
        total_tokens = 0
    try:
        trades_today = int(get_engine().risk_engine.daily_stats.total_trades or 0)
    except Exception:
        trades_today = 0
    per_trade = (total_tokens / trades_today) if trades_today else None

    c1, c2 = st.sidebar.columns(2)
    c1.metric("LLM tokens", f"{total_tokens:,}")
    c2.metric("Per trade", f"{per_trade:,.0f}" if per_trade is not None else "—",
              help="Total LLM tokens consumed today ÷ trades placed today.")
    st.sidebar.caption("LLM used only by **agent09_sentiment** — every other agent is pure Python.")


def sidebar() -> None:
    st.sidebar.markdown(PULSE_CSS, unsafe_allow_html=True)
    st.sidebar.title("Zerodha Intraday Bot")
    if is_streamlit_cloud():
        st.sidebar.success("Streamlit Cloud")
        if "127.0.0.1" in settings.KITE_REDIRECT_URL or "localhost" in settings.KITE_REDIRECT_URL:
            st.sidebar.error("Fix Secrets: KITE_REDIRECT_URL must be your .streamlit.app URL")
        else:
            st.sidebar.caption(f"OAuth: {settings.KITE_REDIRECT_URL}")
    sidebar_llm_meter()
    st.sidebar.divider()
    min_tgt, _, max_trades, _, _ = _intraday_rules()
    st.sidebar.caption(
        f"Capital ₹{settings.DAILY_CAPITAL:,.0f}  ·  SL <10%  ·  Target ≥{min_tgt:g}%  "
        f"·  Max {max_trades}/day"
    )

    api_ok = (
        settings.KITE_API_KEY and settings.KITE_API_KEY.strip() != "your_api_key_here"
        and settings.KITE_API_SECRET and settings.KITE_API_SECRET.strip() != "your_api_secret_here"
    )
    if not api_ok:
        st.sidebar.error("KITE_API_KEY / KITE_API_SECRET missing in .env")
        return

    if ss.authed and ss.profile:
        st.sidebar.success(f"Logged in: {ss.profile.get('user_name') or ss.profile.get('user_id')}")
        if ss.profile.get("email"):
            st.sidebar.caption(ss.profile["email"])
        if st.sidebar.button("Logout", use_container_width=True, key="logout_btn"):
            try:
                zerodha_auth.logout()
            except Exception:
                pass
            get_engine().disable()
            ss.authed = False
            ss.profile = None
            st.rerun()
        st.sidebar.divider()
        sidebar_funds()
        st.sidebar.divider()
        sidebar_engine_controls()
        st.sidebar.divider()
        sidebar_strategies()
        return

    # Not logged in. No username/password fields here by design — Zerodha collects
    # credentials + 2FA on its OWN page. We just send the user there; on the
    # redirect back, bootstrap_auth() reads request_token from the URL and
    # exchanges it for an access_token automatically (no manual step needed).
    st.sidebar.subheader("Login")
    if ss.get("_oauth_error"):
        st.sidebar.error(ss._oauth_error)
    st.sidebar.caption(
        "Click **Login to Kite** — Zerodha verifies your credentials + 2FA on their "
        "own site, then redirects back here. The app auto-reads the token from the "
        "redirect URL and signs you in. Your password is never seen by this app."
    )
    login_url = zerodha_auth.generate_login_url()
    st.sidebar.link_button("Login to Kite", login_url, use_container_width=True, type="primary")
    # Auto token-capture only works if Kite redirects back to THIS app. Show the
    # exact Redirect URL that must be registered at developers.kite.trade, so a
    # mismatch (which forces manual token paste) is obvious.
    st.sidebar.caption(
        f"⚠️ For one-click login, the **Redirect URL** in your Kite developer "
        f"console must be exactly:\n\n`{settings.KITE_REDIRECT_URL.strip()}`\n\n"
        "If it points anywhere else, the token won't return here and you'll have "
        "to paste it manually below."
    )

    # Manual fallback: if Kite's redirect URL points somewhere this app can't
    # receive (e.g. a dead localhost callback), paste the request_token here.
    with st.sidebar.expander("Trouble logging in? Paste token manually"):
        st.caption(
            "After **Login to Kite**, copy the `request_token=…` value from the "
            "page Kite redirects you to (you can paste the whole URL too), then "
            "authenticate here. Tokens expire in ~2 minutes — be quick."
        )
        raw = st.text_input(
            "request_token (or full redirect URL)",
            key="manual_request_token",
            autocomplete="off",
            placeholder="e.g. 1cYvT5nkL88piDYZdO8xaF2NBcx3TngB",
        )
        if st.button("Authenticate", use_container_width=True, key="manual_auth_btn"):
            from urllib.parse import urlparse, parse_qs

            token = (raw or "").strip()
            if "request_token=" in token:  # user pasted the whole redirect URL
                qs = parse_qs(urlparse(token).query)
                token = (qs.get("request_token") or [""])[0]
            if not token:
                st.error("Paste a request_token (or the full redirect URL) first.")
            else:
                try:
                    zerodha_auth.exchange_request_token(token)
                    ok, profile = zerodha_auth.validate_token()
                    if ok and profile:
                        ss.authed = True
                        ss.profile = {
                            "user_id": profile.get("user_id"),
                            "user_name": profile.get("user_name"),
                            "email": profile.get("email"),
                        }
                        log.info("kite_manual_token_exchange_success")
                        st.rerun()
                    else:
                        st.error("Token accepted but profile validation failed. Try a fresh token.")
                except Exception as exc:
                    log.exception("kite_manual_token_exchange_failed")
                    st.error(f"Login failed: {exc}. Generate a fresh token and retry quickly.")


def _exchange_pasted_token(raw: str) -> tuple[bool, str]:
    """Exchange a pasted request_token (or full redirect URL) for a Kite session.
    Returns (ok, message). On success, session_state is updated."""
    from urllib.parse import urlparse, parse_qs

    token = (raw or "").strip()
    if "request_token=" in token:  # user pasted the whole redirect URL
        qs = parse_qs(urlparse(token).query)
        token = (qs.get("request_token") or [""])[0]
    if not token:
        return False, "Paste a request_token (or the full redirect URL) first."
    try:
        zerodha_auth.exchange_request_token(token)
        ok, profile = zerodha_auth.validate_token()
    except Exception as exc:
        log.exception("kite_manual_token_exchange_failed")
        return False, f"Login failed: {exc}. Generate a fresh token and retry quickly."
    if ok and profile:
        ss.authed = True
        ss.profile = {
            "user_id": profile.get("user_id"),
            "user_name": profile.get("user_name"),
            "email": profile.get("email"),
        }
        log.info("kite_manual_token_exchange_success")
        return True, "Logged in."
    return False, "Token accepted but profile validation failed. Try a fresh token."


def login_hero() -> None:
    """Main-page login flow: open Kite, paste the request_token, connect."""
    if ss.get("_oauth_error"):
        st.error(ss._oauth_error)
    login_url = zerodha_auth.generate_login_url()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            "<div class='step-card'><span class='step-num'>1</span>"
            "<h4>Login to Kite</h4>"
            "<p>Zerodha verifies your credentials and 2FA on its own page — "
            "this app never sees your password.</p></div>",
            unsafe_allow_html=True,
        )
        st.link_button("🔐 Open Kite login", login_url, use_container_width=True, type="primary")
    with c2:
        st.markdown(
            "<div class='step-card'><span class='step-num'>2</span>"
            "<h4>Copy the token</h4>"
            "<p>After login, Kite redirects to a URL containing "
            "<code>request_token=…</code>. Copy the token — or the whole URL. "
            "It expires in ~2 minutes, so be quick.</p></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            "<div class='step-card'><span class='step-num'>3</span>"
            "<h4>Paste &amp; connect</h4>"
            "<p>Paste below and hit Connect. You'll then choose "
            "<b>Monitor</b> or <b>Live trade</b>.</p></div>",
            unsafe_allow_html=True,
        )

    st.write("")
    pc1, pc2 = st.columns([3, 1])
    raw = pc1.text_input(
        "request_token or full redirect URL",
        key="hero_request_token",
        autocomplete="off",
        placeholder="e.g. 1cYvT5nkL88piDYZdO8xaF2NBcx3TngB — or paste the whole redirect URL",
        label_visibility="collapsed",
    )
    if pc2.button("⚡ Connect", use_container_width=True, type="primary", key="hero_auth_btn"):
        ok, msg = _exchange_pasted_token(raw)
        if ok:
            st.rerun()
        else:
            st.error(msg)

    min_tgt, _, max_trades, _, _ = _intraday_rules()
    st.caption(
        f"Hard rules once trading: SL <10% · Target ≥{min_tgt:g}% · max {max_trades} trades/day · "
        f"daily loss auto-halt at ₹{settings.MAX_DAILY_LOSS:,.0f} · NSE 9:15–15:30 IST only."
    )


def _active_kite_user_id() -> str:
    """Kite user_id of the process-wide session (from the saved token file)."""
    try:
        import json as _json
        with open(zerodha_auth.token_file) as f:
            return str((_json.load(f) or {}).get("user_id") or "").strip().upper()
    except Exception:
        return ""


def session_status_view() -> None:
    """Read-only status page for a second device (e.g. mobile over 5G) when a
    trading session is already running in this process. Gated by Kite User ID so
    a stranger hitting the public URL sees nothing."""
    active_uid = _active_kite_user_id()
    if active_uid and not ss.get("viewer_verified"):
        st.markdown(
            "<div class='step-card'><h4>📡 A trading session is running</h4>"
            "<p>Enter the <b>Kite User ID</b> of the logged-in account to view "
            "its live status (read-only, no password needed).</p></div>",
            unsafe_allow_html=True,
        )
        v1, v2 = st.columns([3, 1])
        uid = v1.text_input(
            "Kite User ID", key="viewer_uid", autocomplete="off",
            placeholder="e.g. AB1234", label_visibility="collapsed",
        )
        if v2.button("View status", use_container_width=True, type="primary", key="viewer_btn"):
            if (uid or "").strip().upper() == active_uid:
                ss.viewer_verified = True
                st.rerun()
            else:
                st.error("User ID does not match the active Kite session.")
        return
    st.success(
        "📡 A trading session is already running — live status below. "
        "You're viewing as a monitor; no login needed."
    )
    snap = get_engine().snapshot()
    _, _, _, session_capital, _ = _intraday_rules()
    try:
        cap = session_capital()
    except Exception:
        cap = float(settings.DAILY_CAPITAL)
    safe("top_strip", top_status_strip, cap, snap)
    safe("auto_mode", auto_mode_status_strip, cap, snap)
    st.divider()
    safe("agent_flow", main_agent_flow_panel)
    safe("brackets", brackets_panel)
    safe("activity", activity_feed, snap)
    st.divider()
    with st.expander("🔐 Login to take control of this session"):
        login_hero()


def mode_selector(snap) -> None:
    """Big, explicit choice after login: watch the market, or trade for real."""
    orch = get_orch()
    orch_auto = bool(orch.bus.get("auto_execute") or False)
    live = bool(getattr(settings, "ENABLE_LIVE_TRADING", False))

    with st.container(border=True):
        if not snap.enabled:
            st.markdown("#### What would you like to do?")
            m1, m2 = st.columns(2)
            with m1:
                st.markdown(
                    "<div class='step-card'><h4>👁 Monitor</h4>"
                    "<p>Starts the 9-agent loop: live scans, signals, market regime, "
                    "positions — but <b>never places an order</b>.</p></div>",
                    unsafe_allow_html=True,
                )
                if st.button("Start monitoring", use_container_width=True, key="mode_monitor_btn"):
                    get_engine().enable()
                    get_engine().set_auto_execute(False)
                    if not orch_running():
                        orch.start_all()
                    orch.set_auto_execute(False)
                    ss.agents_running = True
                    ss["auto_exec_checkbox"] = False
                    st.rerun()
            with m2:
                st.markdown(
                    "<div class='step-card'><h4>🚀 Live trade</h4>"
                    "<p>Everything Monitor does, plus auto-execution of approved "
                    "setups during 10:15–14:45 IST — <b>real MIS orders, real money</b>.</p></div>",
                    unsafe_allow_html=True,
                )
                if is_streamlit_cloud():
                    st.warning(
                        "Live trading is disabled on Streamlit Cloud: the container "
                        "sleeps/restarts and can't run the engine reliably, and a second "
                        "engine would duplicate orders against the same Kite account. "
                        "Trade from the local dashboard; use this copy to monitor."
                    )
                    st.button(
                        "Start live trading", use_container_width=True,
                        key="mode_live_btn", disabled=True,
                    )
                    return
                confirm = st.checkbox(
                    "I understand real orders will be placed with real money",
                    key="mode_live_confirm",
                )
                if st.button(
                    "Start live trading", type="primary", use_container_width=True,
                    key="mode_live_btn", disabled=not confirm,
                ):
                    get_engine().enable()
                    get_engine().set_auto_execute(False)
                    if not orch_running():
                        orch.start_all()
                    orch.set_auto_execute(True)
                    ss.agents_running = True
                    ss["auto_exec_checkbox"] = True
                    ss["auto_exec_confirm"] = True
                    st.rerun()
            if not live:
                st.warning(
                    "`ENABLE_LIVE_TRADING` is **false** — even 'Live trade' will only simulate "
                    "orders (DRY-RUN). Set it to `true` in `.env`/Secrets for real orders."
                )
        else:
            mode = "🚀 LIVE TRADING" if (orch_auto and live) else ("🧪 DRY-RUN AUTO" if orch_auto else "👁 MONITORING")
            b1, b2 = st.columns([3, 1])
            b1.markdown(f"**Session active:** {mode} — the 9-agent loop is scanning. Use the sidebar to fine-tune.")
            if b2.button("⏹ Stop session", use_container_width=True, key="mode_stop_btn"):
                get_engine().disable()
                get_engine().set_auto_execute(False)
                orch.set_auto_execute(False)
                if orch_running():
                    orch.shutdown()
                ss.agents_running = False
                ss["auto_exec_checkbox"] = False
                st.rerun()


def sidebar_funds() -> None:
    """Live funds & margins from Zerodha (equity segment)."""
    st.sidebar.subheader("Zerodha funds (equity)")
    try:
        kite = zerodha_auth.get_kite_instance()
        m = kite.margins(segment="equity") or {}
        avail = (m.get("available") or {})
        used = (m.get("utilised") or {})

        cash = float(avail.get("live_balance") or avail.get("cash") or 0.0)
        net = float(m.get("net") or 0.0)
        margin_used = float(used.get("debits") or 0.0)
        m2m = float(used.get("m2m_unrealised") or 0.0) + float(used.get("m2m_realised") or 0.0)

        c1, c2 = st.sidebar.columns(2)
        c1.metric("Available", f"₹{cash:,.0f}")
        c2.metric("Net", f"₹{net:,.0f}")
        c1.metric("Used", f"₹{margin_used:,.0f}")
        c2.metric("M2M", f"₹{m2m:+,.0f}")
        if st.sidebar.button("↻ Refresh funds", use_container_width=True, key="refresh_funds_btn"):
            st.rerun()
    except Exception as e:
        st.sidebar.warning(f"Funds unavailable: {e}")


def sidebar_engine_controls() -> None:
    st.sidebar.subheader("Bot controls")
    snap = get_engine().snapshot()
    orch = get_orch()

    # Reconcile process-global state vs this browser session. The engine + orchestrator
    # are @st.cache_resource singletons (process-wide), but the bot can be enabled in one
    # session while a fresh session/reload starts with ss.agents_running = False. That left
    # the UI wedged: button shows "Disable bot" (engine enabled) yet the panel shows "Idle"
    # with no way to start the loop. Heal it: if the bot is enabled but the agent loop isn't
    # actually running, start it (start_all/agent.start are idempotent, so this is safe).
    if snap.enabled and not orch_running():
        get_orch().start_all()

    try:
        if snap.enabled:
            if not ss.get("agents_running"):
                st.sidebar.info("Viewing existing bot session from this device.")
            if st.sidebar.button("⏸ Disable bot", use_container_width=True, key="disable_bot_btn"):
                log.info("UI: Disable bot clicked")
                get_engine().disable()
                get_engine().set_auto_execute(False)
                orch.set_auto_execute(False)
                ss["auto_exec_checkbox"] = False
                # Stop the loop based on the real process-wide state, not this
                # session's flag — a session that didn't start it must still be able
                # to stop it. Clear ss.agents_running so auto_logoff won't fire later.
                if orch_running():
                    get_orch().shutdown()
                ss.agents_running = False
                st.rerun()
        else:
            if st.sidebar.button(
                "▶️ Enable bot", type="primary", use_container_width=True, key="enable_bot_btn"
            ):
                log.info("UI: Enable bot clicked")
                get_engine().enable()
                # Keep engine as phase/risk monitor; real dispatch runs through
                # the 9-agent chain (agent08 execution).
                get_engine().set_auto_execute(False)
                if not orch_running():
                    orch.start_all()
                orch.set_auto_execute(True)
                # Mark THIS session as having armed the bot — auto_logoff keys off this
                # so an after-hours review session is never force-logged-off.
                ss.agents_running = True
                ss["auto_exec_checkbox"] = True
                ss["auto_exec_confirm"] = True
                st.rerun()
    except Exception as e:
        log.exception("Bot toggle failed")
        st.sidebar.error(f"Toggle failed: {e}")

    # Real-order gate for the 9-agent execution path.
    try:
        orch_auto = bool(orch.bus.get("auto_execute") or False)
        ss.setdefault("auto_exec_checkbox", orch_auto)
        ss.setdefault("auto_exec_confirm", False)
        live = bool(getattr(settings, "ENABLE_LIVE_TRADING", False))
        st.sidebar.checkbox(
            "I understand Auto-execute can place intraday orders",
            key="auto_exec_confirm",
            disabled=not snap.enabled,
            help="Required before Auto-execute can be turned on.",
        )
        new_auto = st.sidebar.checkbox(
            "Auto-execute orders",
            key="auto_exec_checkbox",
            disabled=not snap.enabled,
            help="When ON, the engine places approved candidates automatically during "
                 "10:15–14:45 IST. Enable bot turns this ON automatically.",
        )
        if new_auto and not ss.get("auto_exec_confirm"):
            st.sidebar.error("Confirm the Auto-execute risk acknowledgement first.")
            new_auto = False
        if new_auto != orch_auto:
            orch.set_auto_execute(new_auto)
        # Prevent duplicate order paths: keep engine execution disabled.
        get_engine().set_auto_execute(False)
        if new_auto and live:
            st.sidebar.warning("⚠️ Auto-execute ON · **LIVE** — agent08 can place REAL Zerodha MIS orders.")
        elif new_auto:
            st.sidebar.info(
                "Auto-execute ON · **DRY-RUN** — 9-agent pipeline is armed but orders are simulated. "
                "Set `ENABLE_LIVE_TRADING=true` in Secrets to trade for real."
            )
        else:
            st.sidebar.caption("Monitoring only — agent pipeline scans; no automatic broker orders.")
    except Exception as e:
        log.exception("Auto-execute toggle failed")
        st.sidebar.error(f"Auto-exec toggle failed: {e}")


AGENT_NAMES = [
    "agent01_data", "agent02_feature", "agent03_trend", "agent04_breakout",
    "agent05_pullback", "agent06_decision", "agent07_risk", "agent08_execution", "agent09_sentiment",
]

AGENT_INTERVALS = {
    "agent01_data": 5.0,
    "agent02_feature": 5.0,
    "agent03_trend": 10.0,
    "agent04_breakout": 10.0,
    "agent05_pullback": 10.0,
    "agent06_decision": 15.0,
    "agent07_risk": 15.0,
    "agent08_execution": 15.0,
    "agent09_sentiment": 300.0,
}

AGENT_FLOW = {
    "agent01_data": ("parallel", "P1 ingest"),
    "agent02_feature": ("parallel", "P1 features"),
    "agent03_trend": ("parallel", "P2 signal"),
    "agent04_breakout": ("parallel", "P2 signal"),
    "agent05_pullback": ("parallel", "P2 signal"),
    "agent06_decision": ("sequence", "S1 confluence"),
    "agent07_risk": ("sequence", "S2 risk"),
    "agent08_execution": ("sequence", "S3 execute"),
    "agent09_sentiment": ("parallel", "P0 context"),
}


def _agent_action_text(last) -> str:
    """One-line 'what this agent just did', derived from its last AgentResult."""
    if last is None:
        return "waiting for first tick…"
    if isinstance(last, dict):
        ok = bool(last.get("ok", True))
        p = last.get("payload")
        error = last.get("error")
    else:
        ok = bool(getattr(last, "ok", True))
        p = getattr(last, "payload", None)
        error = getattr(last, "error", None)
    if not ok:
        return f"⚠ {error or 'tick failed'}"
    if isinstance(p, dict) and p:
        return " · ".join(f"{k}={v}" for k, v in p.items())
    return "ok"


def _agent_state(name: str, last) -> tuple[str, str]:
    if last is None:
        return "dormant", "DORMANT"
    if isinstance(last, dict):
        ok = bool(last.get("ok", True))
        ts_raw = last.get("ts")
        payload = last.get("payload")
        try:
            ts = datetime.fromisoformat(str(ts_raw)) if ts_raw else datetime.now()
        except Exception:
            ts = datetime.now()
    else:
        ok = bool(getattr(last, "ok", True))
        ts = getattr(last, "ts", datetime.now())
        payload = getattr(last, "payload", None)
    if not ok:
        return "dormant", "DORMANT"
    age_s = (datetime.now() - ts).total_seconds()
    interval = AGENT_INTERVALS.get(name, 15.0)
    if age_s <= max(2.0, interval * 0.6):
        return "active", "ACTIVE"
    if isinstance(payload, dict):
        # Finished = completed useful work in last successful tick.
        for k in ("placed", "approved", "buys", "symbols", "scored"):
            v = payload.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return "finished", "FINISHED"
    return "dormant", "DORMANT"


def _agent_flow_badge(name: str) -> str:
    mode, label = AGENT_FLOW.get(name, ("parallel", "P?"))
    klass = "flow-sequence" if mode == "sequence" else "flow-parallel"
    mode_text = "SEQ" if mode == "sequence" else "PAR"
    return f"<span class='flow-chip {klass}'>{mode_text} · {label}</span>"


AGENT_LABELS = {
    "agent01_data": "Market Data",
    "agent02_feature": "Feature Builder",
    "agent03_trend": "Trend Agent",
    "agent04_breakout": "Breakout Agent",
    "agent05_pullback": "Pullback Agent",
    "agent06_decision": "Synthesizer",
    "agent07_risk": "Risk Check",
    "agent08_execution": "Execution",
    "agent09_sentiment": "Sentiment",
}

MAIN_AGENT_FLOW_GROUPS = [
    ("INPUT", ["agent01_data"]),
    ("PARALLEL ANALYSIS", ["agent02_feature", "agent03_trend", "agent04_breakout", "agent05_pullback", "agent09_sentiment"]),
    ("SYNTHESIZE", ["agent06_decision"]),
    ("VALIDATE + ACT", ["agent07_risk", "agent08_execution"]),
    ("OUTPUT", []),
]


def _agent_flow_card(name: str) -> str:
    last = get_orch().bus.get(f"last_result:{name}")
    state, state_text = _agent_state(name, last)
    label = escape(AGENT_LABELS.get(name, name))
    action = escape(_agent_action_text(last))
    return (
        f"<div class='flow-card {state}'>"
        f"<span class='flow-status {state}'>{state_text}</span>"
        f"<div class='flow-card-name'>{label}</div>"
        f"<div class='flow-card-task'>{action}</div>"
        f"</div>"
    )


def main_agent_flow_panel() -> None:
    """Main-screen animated router-pattern view for the 9-agent system."""
    st.markdown(PULSE_CSS, unsafe_allow_html=True)
    health = get_orch().bus.get("health") or {}
    ok = sum(1 for v in health.values() if v.get("status") == "OK")
    loop_state = "running" if orch_running() else "idle"
    auto_state = "auto-execute ON" if bool(get_orch().bus.get("auto_execute") or False) else "auto-execute OFF"

    groups_html = []
    for idx, (title, names) in enumerate(MAIN_AGENT_FLOW_GROUPS):
        arrow = "<div class='flow-arrow'></div>" if idx < len(MAIN_AGENT_FLOW_GROUPS) - 1 else ""
        if names:
            cards = "".join(_agent_flow_card(name) for name in names)
        else:
            placed = get_orch().bus.get("executed_today") or set()
            approved = get_orch().bus.get("approved_decision", max_age_s=60.0) or {}
            if placed:
                state, status, task = "finished", "FINISHED", f"orders sent: {len(placed)}"
            elif approved:
                state, status, task = "active", "ACTIVE", f"approved setups: {len(approved)}"
            elif orch_running():
                state, status, task = "dormant", "DORMANT", "waiting for approved trade"
            else:
                state, status, task = "dormant", "DORMANT", "enable bot to start"
            cards = (
                f"<div class='flow-card {state}'>"
                f"<span class='flow-status {state}'>{status}</span>"
                f"<div class='flow-card-name'>Trade Output</div>"
                f"<div class='flow-card-task'>{escape(task)}</div>"
                f"</div>"
            )
        groups_html.append(
            f"<div class='flow-group'>"
            f"<div class='flow-group-label'>{escape(title)}</div>"
            f"{cards}{arrow}</div>"
        )

    html = (
        "<div class='agent-flow-stage'>"
        "<div class='agent-flow-title'>"
        "<h3>9-Agent Router Pattern</h3>"
        f"<div class='agent-flow-legend'>{ok}/{len(AGENT_NAMES)} healthy · {loop_state} · {auto_state} · green=active amber=dormant red=finished</div>"
        "</div>"
        "<div class='agent-flow-grid'>"
        + "".join(groups_html)
        + "</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _agents_fragment() -> None:
    """Renders the 9-agent panel. Refreshes with the page every 15s (see
    auto_refresh()); a per-fragment run_every broke first-render on Streamlit Cloud."""
    st.subheader("Agent system (9)")
    # Read the real, process-wide loop state — not ss.agents_running, which is a
    # per-session flag (kept only as the auto-logoff guard) and is False on a fresh
    # session even while the loop is running from another session in the same process.
    if not orch_running():
        st.caption("Idle — Enable bot to start the 9-agent loop.")
        return
    health = get_orch().bus.get("health") or {}
    ok = sum(1 for v in health.values() if v.get("status") == "OK")
    st.caption(f"{ok}/{len(AGENT_NAMES)} healthy · auto-refreshes every 15s")
    st.caption("Flow: PAR lanes = 01/02 + 03/04/05 + 09, SEQ chain = 06 → 07 → 08")

    for name in AGENT_NAMES:
        last = get_orch().bus.get(f"last_result:{name}")
        info = health.get(name) or {}
        state, state_text = _agent_state(name, last)
        if state == "active":
            dot = '<span class="pulse-dot"></span>'
        elif state == "finished":
            dot = '<span class="done-dot"></span>'
        else:
            dot = '<span class="dormant-dot"></span>'
        stale = info.get("stale_s")
        suffix = f"<span style='color:#888'> · {stale:.1f}s</span>" if isinstance(stale, (int, float)) else ""
        if is_streamlit_cloud():
            card_link = "<span style='color:#888'>card (local API)</span>"
        else:
            card_link = f"<a href='http://127.0.0.1:8000/agents/{name}/card.json' target='_blank' style='color:#3b82f6; text-decoration:none;'>card</a>"
        flow_badge = _agent_flow_badge(name)
        action = _agent_action_text(last)
        st.markdown(
            f"<div class='agent-line'>{dot}{name} <span style='color:#ddd'>[{state_text}]</span>{flow_badge}{suffix} · {card_link}</div>"
            f"<div class='agent-line' style='margin-left:15px;color:#9aa0a6'>↳ task: {action}</div>",
            unsafe_allow_html=True,
        )

    # Risk alerts from agent07
    alerts = get_orch().bus.get("risk_alerts") or []
    if alerts:
        st.markdown("---")
        st.markdown("**⚠️ Risk alerts (agent07)**")
        for a in alerts[:6]:
            sev = a.get("severity", "?")
            colour = "#ef4444" if sev == "high" else "#f59e0b"
            st.markdown(
                f"<div class='agent-line' style='color:{colour}'>"
                f"• {a.get('symbol', '—')}: {a.get('reason', '')}</div>",
                unsafe_allow_html=True,
            )


def sidebar_agents() -> None:
    with st.sidebar:
        _agents_fragment()


def sidebar_strategies() -> None:
    st.sidebar.subheader("Strategies")
    for name in list(ss.strategy_enabled.keys()):
        ss.strategy_enabled[name] = st.sidebar.checkbox(
            name, value=ss.strategy_enabled[name], key=f"strat_{name}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Top status strip
# ─────────────────────────────────────────────────────────────────────────────
def minutes_to_square_off() -> int | None:
    now = ist_now()
    if not is_nse_bse_trading_day(now.date()):
        return None
    from datetime import datetime as _dt, time as _t
    eod = _dt.combine(now.date(), _t(15, 15), tzinfo=IST)
    delta = eod - now
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() // 60)


def _open_position_symbols() -> set[str]:
    syms: set[str] = set()
    try:
        from app.core.bracket_manager import ENTRY_PENDING, IN_POSITION, get_bracket_manager

        for b in get_bracket_manager().snapshot():
            if b.get("state") in (ENTRY_PENDING, IN_POSITION):
                syms.add(str(b.get("symbol") or ""))
    except Exception:
        pass
    try:
        portfolio = get_orch().bus.get("portfolio", max_age_s=120.0) or {}
        for p in portfolio.get("positions") or []:
            if int(p.get("qty") or 0) != 0:
                syms.add(str(p.get("symbol") or ""))
    except Exception:
        pass
    return {s for s in syms if s}


def auto_mode_state(capital: float, snap) -> dict:
    """Single source of truth for READY/BLOCKED and 'Why not trading?'."""
    from app.core.trading_engine import PHASE_ACTIVE

    re = get_engine().risk_engine
    open_syms = _open_position_symbols()
    loss_used = max(0.0, -re.daily_stats.total_pnl)
    approved = {}
    risk_alerts = []
    market_data_error = {}
    try:
        approved = get_orch().bus.get("approved_decision", max_age_s=45.0) or {}
        risk_alerts = get_orch().bus.get("risk_alerts", max_age_s=45.0) or []
        market_data_error = get_orch().bus.get("market_data_error", max_age_s=120.0) or {}
    except Exception:
        pass
    orch_auto = bool(get_orch().bus.get("auto_execute") or False)
    reasons: list[str] = []
    market_ok, market_msg = can_place_nse_bse_equity_trade()
    if not ss.authed:
        reasons.append("Not logged into Kite")
    if not settings.KITE_API_KEY or settings.KITE_API_KEY.strip() == "your_api_key_here":
        reasons.append("Streamlit Secrets missing KITE_API_KEY")
    if not settings.KITE_API_SECRET or settings.KITE_API_SECRET.strip() == "your_api_secret_here":
        reasons.append("Streamlit Secrets missing KITE_API_SECRET")
    if not bool(getattr(settings, "ENABLE_LIVE_TRADING", False)):
        reasons.append("ENABLE_LIVE_TRADING is false (DRY-RUN only)")
    if not market_ok:
        reasons.append(f"Market gate closed: {market_msg}")
    if not snap.enabled:
        reasons.append("Bot disabled")
    if not orch_running():
        reasons.append("9-agent loop not running")
    if not orch_auto:
        reasons.append("Auto-execute OFF")
    if market_data_error:
        err = str(market_data_error.get("error") or "unknown")
        reasons.append(f"Kite market-data blocked: {err}")
    if snap.phase != PHASE_ACTIVE:
        reasons.append(f"Outside active phase: {snap.phase_label or snap.phase}")
    if re.daily_stats.is_trading_halted:
        reasons.append("Risk cap reached: trading halted")
    if re.daily_stats.total_trades >= re.config.max_trades_per_day:
        reasons.append(f"Max trades/day reached ({re.config.max_trades_per_day})")
    if len(open_syms) >= re.config.max_open_positions:
        reasons.append(f"Max open positions reached ({len(open_syms)}/{re.config.max_open_positions})")
    if snap.enabled and snap.phase == PHASE_ACTIVE and not approved:
        reasons.append("No approved decision yet from agents")
    if risk_alerts and not approved:
        latest = risk_alerts[0]
        reasons.append(f"Risk rejected latest setup: {latest.get('reason', 'unknown')}")
    for ev in reversed(snap.activity[-5:]):
        msg = str(ev.get("msg", ""))
        if "order failed" in msg.lower() or "kite" in msg.lower() and "failed" in msg.lower():
            reasons.append(f"Kite order failed: {msg}")
            break
    return {
        "ready": not reasons,
        "reason": reasons[0] if reasons else "Ready to trade automatically",
        "reasons": reasons,
        "logged_in": bool(ss.authed),
        "bot_enabled": bool(snap.enabled),
        "auto_execute": bool(orch_auto),
        "phase": snap.phase_label or snap.phase,
        "open_count": len(open_syms),
        "max_open": re.config.max_open_positions,
        "loss_used": loss_used,
        "loss_cap": re.config.max_loss_per_day,
        "trades_used": re.daily_stats.total_trades,
        "trades_cap": re.config.max_trades_per_day,
        "live": bool(getattr(settings, "ENABLE_LIVE_TRADING", False)),
        "capital": capital,
    }


def auto_mode_status_strip(capital: float, snap) -> None:
    state = auto_mode_state(capital, snap)
    if state["ready"]:
        st.success("AUTO MODE: READY TO TRADE")
    else:
        st.warning(f"AUTO MODE: BLOCKED — {state['reason']}")
    c = st.columns(7)
    c[0].metric("Logged in", "Yes" if state["logged_in"] else "No")
    c[1].metric("Bot enabled", "Yes" if state["bot_enabled"] else "No")
    c[2].metric("Auto-execute", "Yes" if state["auto_execute"] else "No")
    c[3].metric("Phase", state["phase"])
    c[4].metric("Open positions", f"{state['open_count']}/{state['max_open']}")
    c[5].metric("Daily loss", f"₹{state['loss_used']:.0f}/₹{state['loss_cap']:.0f}")
    c[6].metric("Trades", f"{state['trades_used']}/{state['trades_cap']}")


def why_not_trading_panel(capital: float, snap) -> None:
    state = auto_mode_state(capital, snap)
    st.subheader("Why not trading?")
    if state["ready"]:
        st.success(
            "All gates are open. The next approved setup during the active phase can be placed automatically."
        )
        return
    st.caption("First blocking reason is shown in the Auto Mode strip. Full checklist:")
    for reason in state["reasons"]:
        st.markdown(f"- {reason}")


def top_status_strip(capital: float, snap) -> None:
    mkt_ok, mkt_msg = can_place_nse_bse_equity_trade()
    re = get_engine().risk_engine

    c = st.columns([1.4, 1.4, 1.0, 1.0, 1.0, 1.2, 1.0])

    # Bot + phase
    if snap.enabled:
        if snap.armed:
            c[0].markdown("🟢 **BOT ENABLED · ARMED**")
        else:
            c[0].markdown("🟡 **BOT ENABLED · IDLE**")
    else:
        c[0].markdown("⚪ **BOT DISABLED**")
    c[0].caption(snap.phase_label or "—")

    # Market + last tick
    if mkt_ok:
        c[1].markdown("🟢 **MARKET OPEN**")
    elif is_nse_bse_trading_day():
        c[1].markdown("🟠 **OFF-HOURS**")
    else:
        c[1].markdown("🔴 **HOLIDAY/WKND**")
    c[1].caption(f"Last tick: {snap.last_tick or '—'}")

    # Equity + PnL
    c[2].metric("Equity", f"₹{capital:,.0f}", delta=f"₹{re.daily_stats.total_pnl:+,.0f}")

    # Trade slots
    used = re.daily_stats.total_trades
    cap_trades = re.config.max_trades_per_day
    c[3].metric("Trades", f"{used}/{cap_trades}")
    c[3].progress(min(1.0, used / cap_trades if cap_trades else 0), text=" ")

    # Risk used
    loss_used = max(0.0, -re.daily_stats.total_pnl)
    loss_cap = re.config.max_loss_per_day
    pct = min(1.0, loss_used / loss_cap if loss_cap else 0)
    c[4].metric("Risk used", f"{pct * 100:.0f}%")
    c[4].progress(pct, text=" ")

    # Bot-side force exit countdown
    mins = minutes_to_square_off()
    if mins is None:
        c[5].metric("Force exit", "—")
    elif mins == 0:
        c[5].metric("Force exit", "NOW")
    else:
        c[5].metric("Force exit in", f"{mins} min")

    # KILL ALL
    if c[6].button(
        "🔥 KILL ALL",
        key="kill_all_btn",
        use_container_width=True,
        help="Emergency: disable bot + cancel all open Kite orders",
    ):
        with st.spinner("Cancelling all open orders…"):
            result = get_engine().kill_all()
        st.toast(
            f"KILL ALL — cancelled {result['cancelled']}, failures {len(result['failures'])}",
            icon="🔥",
        )
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Pre-trade validation
# ─────────────────────────────────────────────────────────────────────────────
def validate_trade(entry: float, sl: float, target: float, qty: int, capital: float, strategy: str):
    if not ss.strategy_enabled.get(strategy, False):
        return False, f"Strategy '{strategy}' disabled in sidebar."
    if qty <= 0:
        return False, "Quantity must be > 0."
    if min(entry, sl, target) <= 0:
        return False, "Entry / SL / target must be positive."
    sl_pct = (entry - sl) / entry * 100
    tgt_pct = (target - entry) / entry * 100
    if sl_pct <= 0:
        return False, f"SL must be below entry (SL ₹{sl:.2f}, entry ₹{entry:.2f})."
    if sl_pct >= 10.0:
        return False, f"SL distance {sl_pct:.2f}% violates hard cap (<10%)."
    min_tgt, _, _, _, _ = _intraday_rules()
    if tgt_pct < min_tgt - 1e-6:
        return False, f"Target {tgt_pct:.2f}% below {min_tgt:.1f}% floor."
    re = get_engine().risk_engine
    pos_cap_inr = capital * (re.config.max_position_size_percent / 100.0)
    notional = entry * qty
    if notional > pos_cap_inr:
        return False, (
            f"Position ₹{notional:,.0f} > cap ₹{pos_cap_inr:,.0f} "
            f"({re.config.max_position_size_percent:.0f}% of capital)."
        )
    ok_mkt, msg_mkt = can_place_nse_bse_equity_trade()
    if not ok_mkt:
        return False, msg_mkt
    ok_risk, msg_risk = re.can_place_trade(notional, assumed_sl_pct=sl_pct / 100.0)
    if not ok_risk:
        return False, msg_risk
    return True, "OK"


# ─────────────────────────────────────────────────────────────────────────────
# Strategy cards
# ─────────────────────────────────────────────────────────────────────────────
def strategy_cards(snap) -> None:
    st.subheader("Strategies")
    counts = {k: 0 for k in ss.strategy_enabled.keys()}
    for d in snap.candidates or []:
        if d.strategy in counts:
            counts[d.strategy] += 1
    descriptions = {
        "Opening Range Breakout": "Breakout above first-15m high with volume + NIFTY bias",
        "VWAP Pullback": "Holding/discounting VWAP with bullish candle + volume",
        "Momentum": "RSI > 60, price > 20MA, volume > 2× avg, RS vs NIFTY",
    }
    cols = st.columns(3)
    for i, name in enumerate(["Opening Range Breakout", "VWAP Pullback", "Momentum"]):
        with cols[i].container(border=True):
            enabled = ss.strategy_enabled.get(name, False)
            badge = "🟢 ON" if enabled else "⚪ OFF"
            st.markdown(f"**{name}** &nbsp;&nbsp;{badge}")
            st.caption(descriptions[name])
            st.metric("Signals (latest scan)", counts[name])


# ─────────────────────────────────────────────────────────────────────────────
# Panels
# ─────────────────────────────────────────────────────────────────────────────
def safe(name: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log.exception(f"section '{name}' failed")
        st.error(f"Section **{name}** failed: {e}")
        with st.expander("stack trace", expanded=False):
            st.code(traceback.format_exc())
        return None


def positions_panel() -> None:
    st.subheader("Open positions (live)")
    try:
        from app.core.live_broker import LiveBroker
        b = LiveBroker()
        portfolio = b.get_portfolio()
    except Exception as e:
        st.warning(f"Could not fetch positions: {e}")
        return
    if not portfolio:
        st.caption("No open positions.")
        return
    rows = [
        {
            "Symbol": getattr(p, "symbol", ""),
            "Qty": getattr(p, "quantity", 0),
            "Avg": round(getattr(p, "avg_price", 0.0), 2),
            "LTP": round(getattr(p, "ltp", 0.0), 2),
            "Unrealized PnL": round(
                (getattr(p, "ltp", 0.0) - getattr(p, "avg_price", 0.0))
                * getattr(p, "quantity", 0),
                2,
            ),
        }
        for p in portfolio
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def order_book_panel() -> None:
    st.subheader("Order book (live)")
    try:
        from app.core.live_broker import LiveBroker
        b = LiveBroker()
        orders = b.orders
    except Exception as e:
        st.warning(f"Could not fetch order book: {e}")
        return
    if not orders:
        st.caption("No orders today.")
        return
    rows = [
        {
            "Order ID": o.order_id,
            "Symbol": o.symbol,
            "Side": o.transaction_type,
            "Qty": o.quantity,
            "Price": o.price,
            "Status": o.status,
            "Time": str(o.timestamp),
        }
        for o in orders
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def signals_panel(capital: float, snap) -> None:
    from app.core.trading_engine import PHASE_ACTIVE
    min_tgt, _, _, _, _ = _intraday_rules()
    st.subheader("Signals (engine candidates)")
    re = get_engine().risk_engine
    slots = max(0, re.config.max_trades_per_day - re.daily_stats.total_trades)
    st.caption(
        f"Slots left: **{slots}/{re.config.max_trades_per_day}** · "
        f"SL cap <10% · Target floor ≥{min_tgt:g}% · "
        + (f"Last scan **{snap.last_scan_at}** IST" if snap.last_scan_at else "No scan yet")
    )
    try:
        from app.core.intraday_agent import LAST_SCAN_DIAGNOSTICS

        behavior = (LAST_SCAN_DIAGNOSTICS or {}).get("behavior") or {}
        if behavior:
            label = behavior.get("label", "UNKNOWN")
            if label == "RISK_OFF":
                st.error(f"Market behavior: **{label}** — {behavior.get('summary', '')}")
            elif label == "RISK_ON":
                st.success(f"Market behavior: **{label}** — {behavior.get('summary', '')}")
            elif label == "ILLIQUID_CHOP":
                st.warning(f"Market behavior: **{label}** — {behavior.get('summary', '')}")
            else:
                st.info(f"Market behavior: **{label}** — {behavior.get('summary', '')}")
            m = st.columns(5)
            m[0].metric("Advancers", f"{behavior.get('advancers_pct', 0)}%")
            m[1].metric("Above VWAP", f"{behavior.get('above_vwap_pct', 0)}%")
            m[2].metric("Avg day ret", f"{behavior.get('avg_day_ret_pct', 0)}%")
            m[3].metric("Liquid names", f"{behavior.get('liquid_pct', 0)}%")
            m[4].metric("Avg spread", f"{behavior.get('avg_spread_pct', 0)}%")
            with st.expander("Top movers in last scanned slice", expanded=False):
                c1, c2 = st.columns(2)
                c1.markdown("**Top gainers**")
                c1.dataframe(behavior.get("top_gainers") or [], hide_index=True, use_container_width=True)
                c2.markdown("**Top losers**")
                c2.dataframe(behavior.get("top_losers") or [], hide_index=True, use_container_width=True)
    except Exception:
        pass
    candidates = snap.candidates or []
    if not candidates:
        if not snap.enabled:
            st.info("Bot is disabled. Press **Enable bot** in the sidebar to start the auto loop.")
        elif snap.phase == PHASE_ACTIVE:
            st.info("Active phase — no candidates passed the last scan. Engine will retry on the next tick.")
            try:
                from app.core.intraday_agent import LAST_SCAN_DIAGNOSTICS

                diag = LAST_SCAN_DIAGNOSTICS or {}
                reasons = diag.get("reasons") or {}
                if reasons:
                    st.caption("Last scan rejection reasons")
                    rows = [
                        {"Reason": reason, "Count": count}
                        for reason, count in sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)
                    ]
                    st.dataframe(rows, hide_index=True, use_container_width=True)
            except Exception:
                pass
        else:
            st.info(f"Phase: {snap.phase_label}. Engine scans candidates only during the active phase (10:15–14:45 IST).")
        return

    visible = [d for d in candidates if ss.strategy_enabled.get(d.strategy, False)][:5]
    if not visible:
        st.caption("Engine has candidates, but all matching strategies are disabled in the sidebar.")
        return

    for d in visible:
        with st.container(border=True):
            top = st.columns([2, 1, 1, 1, 1, 1])
            top[0].markdown(f"**{d.stock}** · {d.strategy}")
            top[1].metric("Entry", f"₹{d.entry_price:.2f}")
            top[2].metric(
                "SL", f"₹{d.stop_loss:.2f}",
                delta=f"-{d.risk_pct:.2f}%",
                delta_color="inverse",
            )
            tgt_pct = (d.target / d.entry_price - 1) * 100
            top[3].metric("Target", f"₹{d.target:.2f}", delta=f"+{tgt_pct:.2f}%")
            top[4].metric("Qty", d.quantity)
            top[5].metric("Confidence", f"{d.confidence:.0f}")

            with st.expander("Plan & checks"):
                st.markdown(d.planning or "_no plan_")
                for pt in d.hitl_points:
                    st.markdown(f"- {pt}")

            ok_v, msg_v = validate_trade(
                d.entry_price, d.stop_loss, d.target, d.quantity, capital, d.strategy
            )
            ac = st.columns([2, 1, 1])
            ac[0].caption(("✅ " if ok_v else "⛔ ") + msg_v)
            confirmed = ac[1].checkbox("I checked it", key=f"chk_{d.stock}")
            disabled = (not snap.enabled) or (not ok_v) or (not confirmed)
            help_text = "Enable bot first" if not snap.enabled else None
            if ac[2].button(
                "Place bracket",
                key=f"buy_{d.stock}",
                type="primary",
                disabled=disabled,
                use_container_width=True,
                help=help_text,
            ):
                place_bracket_manually(d)


def place_bracket_manually(d) -> None:
    ok, msg = can_place_nse_bse_equity_trade()
    if not ok:
        st.error(f"Market gate: {msg}")
        return
    try:
        from app.core.live_broker import LiveBroker
        b = LiveBroker()
        order = b.place_bracket_buy(
            symbol=d.stock,
            quantity=int(d.quantity),
            limit_price=float(d.entry_price),
            stop_loss_price=float(d.stop_loss),
            target_price=float(d.target),
        )
        get_engine().risk_engine.daily_stats.total_trades += 1
        oid = getattr(order, "order_id", order)
        st.success(f"✅ Live order sent: {oid}")
    except Exception as e:
        st.error(f"Order failed: {e}")


def brackets_panel() -> None:
    """Live view of managed brackets (entry → target/stop → done) so the full
    buy→sell cycle is visible, in both DRY-RUN and LIVE mode."""
    st.subheader("Brackets (entry → target/stop)")
    try:
        from app.core.bracket_manager import get_bracket_manager
        mgr = get_bracket_manager()
        rows = mgr.snapshot()
        mode = "LIVE" if mgr.live else "DRY-RUN (simulated)"
    except Exception as e:
        st.caption(f"Bracket manager unavailable: {e}")
        return
    st.caption(f"Mode: **{mode}**")
    if not rows:
        st.caption("No brackets yet today.")
        return
    state_icon = {
        "ENTRY_PENDING": "⏳ entry pending",
        "IN_POSITION": "🟢 in position (target+stop live)",
        "DONE": "✅ closed",
        "FAILED": "🛑 entry failed",
    }
    st.dataframe(
        [
            {
                "Symbol": r["symbol"],
                "Qty": r["qty"],
                "Entry": r["entry"],
                "Target": r["target"],
                "Stop": r["stop"],
                "State": state_icon.get(r["state"], r["state"]),
                "Note": r["note"],
            }
            for r in rows
        ],
        use_container_width=True,
        hide_index=True,
    )


def activity_feed(snap) -> None:
    st.subheader("Activity (engine)")
    if not snap.activity:
        st.caption("No events yet.")
        return
    icons = {"info": "·", "warn": "⚠️", "error": "🛑"}
    for ev in reversed(snap.activity[-15:]):
        st.markdown(
            f"<span style='color:#888'>{ev['ts']}</span>  "
            f"{icons.get(ev['level'], '·')}  {ev['msg']}",
            unsafe_allow_html=True,
        )


def guardrails_panel() -> None:
    min_tgt, max_sl, _, _, _ = _intraday_rules()
    re = get_engine().risk_engine
    c = re.config
    st.markdown(
        f"""
**Daily flow (auto-managed by the engine)**
- `< 9:15` Pre-market — idle
- `9:15–9:30` Setup — auto-armed, no trades
- `9:30–10:15` Noisy open — observation only
- `10:15–14:45` Active — scans every 5s; auto-executes only if confirmed ON
- `14:45–15:15` Closing — no new entries; target/stop exits continue
- `15:15` Force square-off — bot cancels tracked exits and sends final MIS sell
- `15:30` Broker MIS square-off remains the last backstop

**Hard rules (every order)**
- SL distance **< 10%** (engine caps at {max_sl:g}%)
- Target **≥ {min_tgt:g}%**
- Position size **≤ {c.max_position_size_percent:.0f}%** of capital
- Max open positions: **{c.max_open_positions}**
- Max trades/day: **{c.max_trades_per_day}**
- Max daily loss: **₹{c.max_loss_per_day:.0f}** (auto-halt)
- Halt on consecutive losses: **{c.max_consecutive_losses}**
- Min capital threshold: **₹{c.min_capital_threshold:.0f}**

**Kill switches**
- **Disable bot** — armed/auto-execute off; open positions untouched
- **🔥 KILL ALL** — disarms + cancels every open Kite order in one click
        """
    )


def dashboard() -> None:
    snap = get_engine().snapshot()
    _, _, _, session_capital, _ = _intraday_rules()
    cap = session_capital()
    safe("shared_session", shared_session_notice)
    safe("mode_selector", mode_selector, snap)
    safe("top_strip", top_status_strip, cap, snap)
    safe("auto_mode", auto_mode_status_strip, cap, snap)
    st.divider()
    safe("agent_flow", main_agent_flow_panel)
    st.divider()
    safe("strategy_cards", strategy_cards, snap)
    st.divider()
    left, right = st.columns([3, 2])
    with left:
        tabs = st.tabs(["Signals", "Why not trading?", "Order book", "Guardrails"])
        with tabs[0]:
            safe("signals", signals_panel, cap, snap)
        with tabs[1]:
            safe("why_not_trading", why_not_trading_panel, cap, snap)
        with tabs[2]:
            safe("order_book", order_book_panel)
        with tabs[3]:
            safe("guardrails", guardrails_panel)
    with right:
        safe("positions", positions_panel)
        safe("brackets", brackets_panel)
        safe("activity", activity_feed, snap)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh + auto-logoff
# ─────────────────────────────────────────────────────────────────────────────
def auto_refresh(interval_ms: int = 15_000, key: str = "dash_autorefresh") -> None:
    """Re-run the script every interval_ms so the 9-agent status, candidates and
    countdowns stay live without a manual click.

    Uses streamlit-autorefresh — a websocket-driven rerun, NOT a full browser
    reload — so the Kite session/session_state survive and the KILL ALL button
    stays responsive. Degrades to a hint if the component isn't installed.
    """
    # Never auto-rerun mid-OAuth handshake — a rerun could clear the redirect's
    # request_token before bootstrap_auth() exchanges it.
    try:
        if "request_token" in st.query_params:
            return
    except Exception:
        pass
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=interval_ms, key=key)
    except Exception:
        st.caption("⏳ Auto-refresh unavailable (install streamlit-autorefresh) — click any control to refresh.")


def auto_logoff_after_close() -> None:
    """At/after 15:40 IST on a trading day, stop the bot + agents and log off Kite.

    15:40 is the post-square-off boundary (REGULAR_END 15:30 → CLOSING_START 15:40),
    so MIS positions are already flat.

    Fires for EVERY logged-in session once the market day is over — trading
    session, monitors, and fresh logins alike — so no device stays signed into
    Kite after close. A user who logs back in after 15:40 for review is not
    kicked again the same day (_auto_logged_off_date guard).
    """
    if not ss.authed:
        return
    from datetime import time as _t
    now = ist_now()
    if not is_nse_bse_trading_day(now.date()):
        return
    if now.time() < _t(15, 40):
        return
    if ss.get("_auto_logged_off_date") == now.date().isoformat():
        return
    ss._auto_logged_off_date = now.date().isoformat()
    try:
        get_engine().disable()
    except Exception:
        log.exception("auto_logoff: engine.disable failed")
    try:
        if orch_running():
            get_orch().shutdown()
        ss.agents_running = False
    except Exception:
        log.exception("auto_logoff: orchestrator shutdown failed")
    try:
        zerodha_auth.logout()
    except Exception:
        log.exception("auto_logoff: kite logout failed")
    ss.authed = False
    ss.profile = None
    log.info("auto_logoff_after_close at %s IST", now.strftime("%H:%M:%S"))
    st.toast("Exchange closed (15:40 IST) — bot stopped and logged out.", icon="🔒")
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Render
# ─────────────────────────────────────────────────────────────────────────────
try:
    auto_refresh()
    bootstrap_auth()
    try_restore_session()
    auto_logoff_after_close()
    # Advance managed brackets on each render too, so manual trades placed while
    # the engine loop isn't running still get their exits managed (idempotent).
    if ss.authed:
        try:
            from app.core.bracket_manager import get_bracket_manager
            get_bracket_manager().poll()
        except Exception:
            log.exception("render bracket poll failed")
    _boot_status.empty()
    try:
        _mkt_open, _ = can_place_nse_bse_equity_trade()
    except Exception:
        _mkt_open = False
    hero_header(
        bool(ss.authed),
        bool(getattr(settings, "ENABLE_LIVE_TRADING", False)),
        bool(_mkt_open),
    )
    sidebar()
    if ss.authed:
        dashboard()
    else:
        # Second device (e.g. mobile) while a session is live: show its status
        # instead of the login flow. The Kite token + engine are process-wide.
        _session_live = False
        try:
            _session_live = get_engine().snapshot().enabled or orch_running()
        except Exception:
            pass
        if _session_live:
            session_status_view()
        else:
            login_hero()
            redirect = settings.KITE_REDIRECT_URL.strip()
            st.caption(f"Kite redirect URL: `{redirect}`")
        if is_streamlit_cloud():
            st.markdown(
                f"**Cloud checklist:** Kite console redirect = `{CLOUD_APP_URL}` · "
                "Secrets must include `KITE_API_KEY`, `KITE_API_SECRET`, same redirect URL, "
                "`LLM_PROVIDER=openai`, and `OPENAI_API_KEY`. Then **Reboot app** after saving Secrets."
            )
            if redirect == CLOUD_APP_URL:
                st.success("Redirect URL is correct for Streamlit Cloud.")
            else:
                st.warning(
                    f"Redirect should be `{CLOUD_APP_URL}` (not localhost). "
                    "Update Streamlit Secrets and reboot."
                )
except Exception as e:
    _boot_status.empty()
    st.error(f"Render failed: {e}")
    st.code(traceback.format_exc())
