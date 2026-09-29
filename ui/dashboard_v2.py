"""
Streamlit dashboard for DayTradingPaperBot.
Real-time monitoring, HITL approvals, and system status.
"""
import streamlit as st
import pandas as pd
from datetime import datetime
import time
import sys
import requests
import webbrowser
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.storage import storage
from app.core.zerodha_auth import zerodha_auth
from app.core.config import settings
from app.core.utils import format_price, format_pnl
from app.core.schemas import OrderStatus
import importlib
import app.core.strategy_engine
importlib.reload(app.core.strategy_engine)
from app.core.strategy_engine import StrategyEngine

# Page config
st.set_page_config(
    page_title="DayTradingPaperBot",
    page_icon="https://raw.githubusercontent.com/mohanmac/proactive_agentic_dt/main/favicon_512.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .big-metric {
        font-size: 2rem;
        font-weight: bold;
    }
    .safe-mode-alert {
        background-color: #ff4444;
        color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        font-weight: bold;
        text-align: center;
        margin-bottom: 1rem;
    }
    .success-box {
        background-color: #00cc66;
        color: white;
        padding: 0.5rem;
        border-radius: 0.3rem;
        margin: 0.5rem 0;
    }
    .warning-box {
        background-color: #ff9900;
        color: white;
        padding: 0.5rem;
        border-radius: 0.3rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main dashboard function (V2)."""
    
    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.title("📈 DayTradingPaperBot V2")
    
    with col2:
        st.metric("Mode", "PAPER" if not settings.ENABLE_LIVE_TRADING else "LIVE ⚠️")
    
    with col3:
        current_time = datetime.now().strftime("%H:%M:%S")
        st.metric("Time", current_time)
    
    # Auth status
    auth_status = zerodha_auth.get_auth_status()
    
    # Initialize session state for login flow
    if 'login_step' not in st.session_state:
        st.session_state.login_step = 1
        
    # Initialize or update StrategyEngine
    if 'strategy_engine' not in st.session_state:
        st.session_state.strategy_engine = StrategyEngine()
    else:
        # Check if we have the updated class with 'get_strategies'
        if not hasattr(st.session_state.strategy_engine, 'get_strategies'):
            st.session_state.strategy_engine = StrategyEngine()
        
    # --- Sidebar - Authentication ---
    with st.sidebar:
        st.header("🔐 Authentication")
        
        if not auth_status.get("authenticated"):
            st.warning("❌ Not Authenticated")
            
            # Step 1: Login Credentials
            st.markdown("### Step 1: Login")
            st.info("Enter details to open Zerodha login.")
            
            user_id = st.text_input("User ID", value="RVQ434")
            password = st.text_input("Password", type="password")
                
            if st.button("🚀 Login & Get Token"):
                if user_id and password:
                    st.session_state.temp_user_id = user_id
                    
                    # Fetch login URL
                    try:
                        response = requests.get("http://127.0.0.1:8000/auth/login_url", timeout=2)
                        if response.status_code == 200:
                            login_url = response.json().get("login_url")
                            st.session_state.auth_url = login_url
                            st.session_state.login_step = 2
                            
                            # Auto-open in new tab
                            webbrowser.open_new_tab(login_url)
                            st.success("Opening Zerodha login page...")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("Could not fetch URL")
                    except Exception:
                        st.error("Auth server unreachable")
                else:
                    st.warning("Enter User ID & Password")
            
            # Step 2: Login Link & Token Entry
            if st.session_state.get('login_step', 1) >= 2:
                # Login Link
                if st.session_state.get('auth_url'):
                    st.markdown("---")
                    st.markdown(
                        f'''
                        <a href="{st.session_state.auth_url}" target="_blank" style="
                            display: inline-block;
                            width: 100%;
                            background-color: #ff5722;
                            color: white;
                            text-align: center;
                            text-decoration: none;
                            padding: 10px;
                            border-radius: 5px;
                            font-weight: bold;
                            margin-bottom: 10px;">
                            🔑 Open Zerodha Login (New Tab)
                        </a>
                        ''', 
                        unsafe_allow_html=True
                    )
                    st.info("1. Click above to log in.\n2. Copy the 'request_token' from the URL.\n3. Paste it below.")
                
                st.markdown("---")
                st.markdown("### Step 2: Enter Token")
                
                manual_token = st.text_input("Access Token / Request Token", type="password", help="Paste from Zerodha redirect")
                
                if st.button("✅ Sync & Verify"):
                    if manual_token:
                        uid = st.session_state.get('temp_user_id', 'Unknown')
                        
                        try:
                            # Attempt 1: Try exchanging as Request Token
                            with st.spinner("Exchanging token..."):
                                zerodha_auth.exchange_request_token(manual_token)
                                st.success("✅ Authenticated!")
                                time.sleep(1)
                                st.rerun()
                                
                        except Exception as e:
                            # Attempt 2: Treat as direct Access Token
                            st.warning(f"Exchange failed. Trying as Access Token... ({str(e)})")
                            time.sleep(0.5)
                            
                            try:
                                # Set it
                                zerodha_auth.set_manual_token(manual_token, user_id=uid, user_name=uid)
                                
                                # VALIDATE IMMEDIATELY
                                is_valid, profile = zerodha_auth.validate_token()
                                
                                if is_valid:
                                    st.success(f"✅ Verified! Welcome {profile.get('user_name')}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("❌ Authentication Failed!")
                                    st.error("Invalid Checksum or Token.")
                                    # Debug info
                                    masked_secret = f"{settings.KITE_API_SECRET[:4]}...{settings.KITE_API_SECRET[-4:]}"
                                    st.code(f"Using Secret: {masked_secret}")
                                    st.warning("If you changed .env, you MUST restart the app (Ctrl+C).")
                                    
                            except Exception as inner_e:
                                st.error(f"Critical Auth Error: {str(inner_e)}")
                    else:
                        st.error("Paste token first")
            
            # Debug info in sidebar
            with st.expander("🛠️ Debug Config"):
                st.write(f"**API Key:** `{settings.KITE_API_KEY[:4]}...{settings.KITE_API_KEY[-4:]}`")
                st.write(f"**Secret:** `{settings.KITE_API_SECRET[:4]}...{settings.KITE_API_SECRET[-4:]}`")
                st.info("Restart app if these are wrong.")
                    
        else:
            # Authenticated State in Sidebar
            st.success("✅ Connected")
            st.info("Ready for Trading")
            st.write(f"**User:** {auth_status.get('user_name', 'Unknown')}")
            
            if st.button("Logout"):
                zerodha_auth.logout()
                st.rerun()
                
            st.markdown("---")
            # Note: "Emerging" button removed from Sidebar as requested

    # --- Main Content ---
    if not auth_status.get("authenticated"):
        st.info("👈 Please authenticate in the Left Sidebar to access the dashboard.")
        return

    # Reset login step if authenticated
    if auth_status.get("authenticated"):
        st.session_state.login_step = 1
    
    # Get daily state
    daily_state = storage.get_or_create_daily_state()
    
    # SAFE_MODE alert
    if daily_state.safe_mode:
        st.markdown(
            '<div class="safe-mode-alert">🚨 SAFE MODE ACTIVE - MAX DAILY LOSS REACHED 🚨</div>',
            unsafe_allow_html=True
        )
    
    # --- V2 Layout Tabs ---
    tab_market, tab_portfolio, tab_tools, tab_strategies, tab_reports, tab_settings = st.tabs([
        "📈 Market Trends",
        "💼 Portfolio",
        "🛠️ Orders & Tools",
        "🧠 Strategies",
        "📊 Reports",
        "⚙️ Settings"
    ])
    
    with tab_market:
        show_market_trends()
        
    with tab_portfolio:
        show_portfolio()
        
    with tab_tools:
        show_tools()

    with tab_strategies:
        show_strategies()
        
    with tab_reports:
        show_reports(daily_state)
        
    with tab_settings:
        show_settings()


    # Auto-refresh
    time.sleep(10)
    st.rerun()


# --- V2 View Functions ---

def show_market_trends():
    """Show market trends, exchange selector, and emerging stocks."""
    st.header("Market Trends")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        exchange = st.radio("Exchange", ["NSE", "BSE"], horizontal=True)
    
    st.markdown(f"### 🚀 Emerging Low-Cost Gems ({exchange})")
    
    # User Formula
    st.info("**Formula:** Emerging low-cost stock = Small-cap + Earnings Growth + Improving Margins + Price > 200-DMA + Beating NIFTY")
    
    symbols = settings.get_trading_symbols()
    
    # Check for emerging candidates
    from app.core.market_data import market_data
    
    with st.spinner("Scanning market for candidates..."):
        try:
            # This scans using the specified criteria (some simulated)
            candidates = market_data.scan_emerging_stocks(symbols)
        except Exception as e:
            candidates = []
            st.warning(f"Scanner error: {e}")
    
    if not candidates:
        st.warning("No stocks found matching the 'Emerging' criteria right now.")
    else:
        # Detailed Grid
        for i, stock in enumerate(candidates):
            with st.expander(f"🔹 {stock['symbol']} - ₹{stock['price']:.2f} ({stock['earnings_growth']:.1f}% Grw)", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Price", f"₹{stock['price']:.2f}")
                    st.caption(f"Reason: {stock.get('reason', 'N/A')}")
                with col2:
                    st.metric("200 DMA", f"₹{stock['dma_200']:.0f}")
                    st.caption("✅ Margins Improving")

                # Strategy Analysis Section
                if st.button(f"Analyze {stock['symbol']}", key=f"analyze_{stock['symbol']}"):
                    st.write("running strategy analysis...")
                    
                    # Construct valid stock_data for the strategy engine
                    # Using data from candidate + mocks for missing fields
                    stock_data = {
                        "symbol": stock['symbol'],
                        "ltp": stock['price'],
                        "vwap": stock['price'] * 0.99, # Mock VWAP
                        "volume": 120000, # Mock Volume
                        "average_volume": 100000,
                        "rsi": 60, # Mock RSI
                        "high": stock['price'] * 1.02,
                        "prev_high": stock['price'] * 0.98
                    }
                    
                    if 'strategy_engine' in st.session_state:
                         signals = st.session_state.strategy_engine.run_strategies(stock_data)
                         
                         if signals:
                            for sig in signals:
                                st.markdown(f"**Strategy: {sig.strategy_name}**")
                                if sig.analysis_breakdown:
                                    st.table(sig.analysis_breakdown)
                                
                                if sig.signal_type == "BUY":
                                    st.success(f"Signal: {sig.signal_type}")
                                elif sig.signal_type == "SELL":
                                    st.error(f"Signal: {sig.signal_type}")
                                else:
                                    st.warning(f"Result: {sig.signal_type}")
                         else:
                            st.warning("No strategies returned any result.")
                    else:
                        st.error("Strategy Engine not initialized. Please refresh.")
    
    st.markdown("---")
    st.subheader("🔔 Alerts")
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.info("**Low Price Alerts**\n\nNo active alerts.")
    with col_a2:
        st.info("**Emerging Stock Alerts**\n\n" + (f"{len(candidates)} candidates found." if candidates else "No alerts."))


def show_portfolio():
    """Show Holdings and Positions."""
    st.header("Portfolio")
    
    tab_hold, tab_pos = st.tabs(["Holdings", "Day Positions"])
    
    with tab_hold:
        st.subheader("Long Term Holdings")
        # Placeholder for Holdings API
        st.info("Fetching holdings from Zerodha...")
        st.dataframe(pd.DataFrame([
            {"Symbol": "RELIANCE", "Qty": 10, "Avg": 2400.0, "LTP": 2450.0, "PnL": 500.0},
            {"Symbol": "TATASTEEL", "Qty": 100, "Avg": 140.0, "LTP": 142.0, "PnL": 200.0}
        ]), use_container_width=True)
        
    with tab_pos:
        show_positions()


def show_tools():
    """Show Orders, GTT, Baskets, SIPs."""
    st.header("Orders & Tools")
    
    tab_man, tab_bk, tab_sip, tab_gtt = st.tabs(["Manual Order", "Tradebook", "Baskets", "SIPs & GTT"])
    
    with tab_man:
        col1, col2 = st.columns(2)
        with col1:
             show_manual_order()
        with col2:
            show_hitl_approvals() # Re-integrating HITL here
        
    with tab_bk:
        show_trade_history()
        
    with tab_sip:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🧺 Low Value Baskets")
            st.info("Create baskets of low-value stocks for diversification.")
            st.button("Create New Basket")
            
        with col2:
            st.subheader("📅 SIPs")
            st.info("Active SIPs: 0")
            st.button("Start New SIP")
            
    with tab_gtt:
        st.subheader("GTT Orders (Good Till Triggered)")
        st.info("No active GTT orders.")


def show_reports(daily_state):
    """Show PnL and Tax Reports."""
    st.header("Reports")
    
    tab_ov, tab_tax = st.tabs(["Daily P&L", "Tax P&L"])
    
    with tab_ov:
        show_overview(daily_state)
        
    with tab_tax:
        st.subheader("Tax P&L Report")
        st.warning("Tax P&L requires historical trade data.")
        st.date_input("Select Financial Year", datetime.now())
        st.button("Generate Tax Report")


# --- Original Functions (Preserved and Adapted) ---

def show_overview(daily_state):
    """Show overview metrics."""
    st.subheader("Daily P&L Overview")
    
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        pnl_color = "normal" if daily_state.total_pnl >= 0 else "inverse"
        st.metric(
            "Total P&L",
            format_pnl(daily_state.total_pnl),
            delta=f"{daily_state.total_pnl:+.2f}",
            delta_color=pnl_color
        )
    
    with col2:
        st.metric(
            "Realized P&L",
            format_pnl(daily_state.realized_pnl)
        )
    
    with col3:
        st.metric(
            "Unrealized P&L",
            format_pnl(daily_state.unrealized_pnl)
        )
    
    with col4:
        st.metric(
            "Trades Today",
            f"{daily_state.trades_count} / {daily_state.max_trades}"
        )
    
    # Loss budget
    st.caption("Loss Budget Usage")
    budget_pct = (daily_state.loss_budget_remaining / daily_state.max_daily_loss) * 100
    st.progress(budget_pct / 100)
    st.write(f"Remaining: {format_price(daily_state.loss_budget_remaining)} / {format_price(daily_state.max_daily_loss)}")
    
    # Active strategy
    st.subheader("Active Strategy")
    
    if daily_state.active_strategy:
        st.info(f"📊 {daily_state.active_strategy.value.replace('_', ' ').title()}")
        
        if daily_state.strategy_switched_at:
            st.caption(f"Last switched: {daily_state.strategy_switched_at.strftime('%H:%M:%S')}")
    else:
        st.warning("No active strategy yet")

def show_strategies():
    """Show strategy library and backtesting."""
    st.header("Strategy Library & Backtesting")
    
    se = st.session_state.strategy_engine
    strategies = se.get_strategies()
    strategy_names = [s.name for s in strategies]
    
    # Selection
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Select Strategy")
        selected_strategy_name = st.selectbox("Available Strategies", strategy_names)
        
        # Find description
        selected_strategy = next((s for s in strategies if s.name == selected_strategy_name), None)
        if selected_strategy:
            st.info(f"**Description:** {selected_strategy.description}")
            
    with col2:
        st.subheader("Backtest Configuration")
        symbol = st.selectbox("Symbol for Backtest", settings.get_trading_symbols())
        days = st.slider("Historical Data Check (Days)", 30, 365, 30)
        
        if st.button("🚀 Run Backtest"):
            with st.spinner(f"Backtesting {selected_strategy_name} on {symbol}..."):
                results = se.run_backtest(selected_strategy_name, symbol, days)
                
                # Show results
                st.subheader("Backtest Results")
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Win Rate", f"{results.win_rate:.1f}%")
                m2.metric("Total P&L", format_pnl(results.total_pnl))
                m3.metric("Total Trades", results.total_trades)
                m4.metric("Max Drawdown", f"{results.max_drawdown:.2f}%")
                
                if results.trades:
                    st.dataframe(pd.DataFrame(results.trades))
                else:
                    st.info("No trades generated in this period.")


def show_manual_order():
    """Show manual order form."""
    st.subheader("Place Manual Order")
    
    with st.form("manual_order_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            symbol = st.selectbox("Symbol", settings.get_trading_symbols())
            side = st.selectbox("Side", ["BUY", "SELL"])
        
        with col2:
            order_type = st.selectbox("Type", ["MARKET", "LIMIT"])
            quantity = st.number_input("Quantity", min_value=1, value=1)
        
        price = st.number_input("Price (Limit)", min_value=0.0, value=0.0, step=0.05)
        
        submitted = st.form_submit_button("Place Order")
        
        if submitted:
            place_manual_order(symbol, side, order_type, quantity, price)


def place_manual_order(symbol, side, order_type, quantity, price):
    """Execute manual order."""
    from app.core.schemas import TradeIntent, TradeSide, OrderType, StrategyType, RiskApproval
    from app.agents.execution_paper import execution_paper
    from app.core.storage import storage
    import uuid
    
    try:
        side_enum = TradeSide.BUY if side == "BUY" else TradeSide.SELL
        type_enum = OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT
        
        # Create intent
        intent = TradeIntent(
            strategy_id=StrategyType.MOMENTUM_BREAKOUT,  # Default for manual
            symbol=symbol,
            side=side_enum,
            quantity=quantity,
            entry_type=type_enum,
            entry_price=price if type_enum == OrderType.LIMIT else 0.0,
            stop_loss_price=0.0,  # Manual orders might not have SL
            target_price=0.0,
            confidence_score=1.0,
            rationale="Manual Order from Dashboard",
            expected_risk_rupees=0.0,
            status="approved"
        )
        
        # Save intent to get ID
        intent_id = storage.save_trade_intent(intent)
        
        # Create approval
        approval = RiskApproval(
            intent_id=intent_id,
            approved=True,
            adjusted_quantity=quantity,
            remaining_loss_budget=1000.0, # Placeholder
            trades_today=0,
            current_strategy=StrategyType.MOMENTUM_BREAKOUT
        )
        
        # Save approval
        storage.save_approval(approval)
        
        # Execute
        order = execution_paper.execute(intent, approval)
        
        if order:
            st.success(f"✅ Order placed: {order.symbol} {order.side.value} {order.quantity} @ {order.fill_price}")
            time.sleep(1)
            st.rerun()
        else:
            st.error("❌ Order execution failed (check logs)")
            
    except Exception as e:
        st.error(f"Error placing order: {str(e)}")


def show_positions():
    """Show open positions."""
    st.subheader("Intraday Positions")
    
    positions = storage.get_all_positions()
    
    if not positions:
        st.info("No open intraday positions")
        return
    
    # Convert to DataFrame
    pos_data = []
    for pos in positions:
        pos_data.append({
            "Symbol": pos.symbol,
            "Quantity": pos.quantity,
            "Avg Price": f"₹{pos.avg_price:.2f}",
            "Current Price": f"₹{pos.current_price:.2f}" if pos.current_price else "N/A",
            "Unrealized P&L": format_pnl(pos.unrealized_pnl),
            "Strategy": pos.strategy.value if pos.strategy else "N/A"
        })
    
    df = pd.DataFrame(pos_data)
    st.dataframe(df, use_container_width=True)


def show_trade_history():
    """Show trade history."""
    st.subheader("Tradebook")
    
    # Get recent orders from database
    with storage.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                timestamp, symbol, side, quantity, order_type,
                fill_price, slippage, brokerage, status
            FROM paper_orders
            WHERE status = 'filled'
            ORDER BY timestamp DESC
            LIMIT 50
        """)
        
        orders = cursor.fetchall()
    
    if not orders:
        st.info("No trades executed yet")
        return
    
    # Convert to DataFrame
    trade_data = []
    for order in orders:
        trade_data.append({
            "Time": order['timestamp'],
            "Symbol": order['symbol'],
            "Side": order['side'].upper(),
            "Qty": order['quantity'],
            "Fill Price": f"₹{order['fill_price']:.2f}",
        })
    
    df = pd.DataFrame(trade_data)
    st.dataframe(df, use_container_width=True)


def show_hitl_approvals():
    """Show HITL approval panel."""
    st.subheader("Human-in-the-Loop Approvals")
    
    # Get pending approvals
    with storage.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                a.id as approval_id,
                a.intent_id,
                a.hitl_reason,
                a.hitl_status,
                t.timestamp,
                t.strategy_id,
                t.symbol,
                t.side,
                t.quantity,
                t.entry_price,
                t.stop_loss_price,
                t.target_price,
                t.confidence_score,
                t.rationale,
                t.expected_risk_rupees
            FROM approvals a
            JOIN trade_intents t ON a.intent_id = t.id
            WHERE a.hitl_required = 1 AND a.hitl_status = 'pending'
            ORDER BY a.timestamp DESC
        """)
        
        pending = cursor.fetchall()
    
    if not pending:
        st.success("✅ No pending approvals")
        return
    
    st.warning(f"⏳ {len(pending)} trade(s) awaiting approval")
    
    for approval in pending:
        with st.expander(f"📋 {approval['symbol']} - {approval['strategy_id']} ({approval['side'].upper()})"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Trade Details:**")
                st.write(f"- Symbol: {approval['symbol']}")
                st.write(f"- Strategy: {approval['strategy_id']}")
                st.write(f"- Side: {approval['side'].upper()}")
                st.write(f"- Quantity: {approval['quantity']}")
                st.write(f"- Entry: ₹{approval['entry_price']:.2f}" if approval['entry_price'] else "MARKET")
                st.write(f"- Stop Loss: ₹{approval['stop_loss_price']:.2f}")
                st.write(f"- Target: ₹{approval['target_price']:.2f}" if approval['target_price'] else "N/A")
            
            with col2:
                st.write("**Risk & Confidence:**")
                st.write(f"- Confidence: {approval['confidence_score']:.1%}")
                st.write(f"- Expected Risk: ₹{approval['expected_risk_rupees']:.2f}")
                st.write(f"- HITL Reason: {approval['hitl_reason']}")
            
            st.write("**Rationale:**")
            st.info(approval['rationale'])
            
            # Approval buttons
            col_approve, col_reject = st.columns(2)
            
            with col_approve:
                if st.button(f"✅ Approve", key=f"approve_{approval['approval_id']}"):
                    # Update approval status
                    with storage.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE approvals SET hitl_status = 'approved' WHERE id = ?",
                            (approval['approval_id'],)
                        )
                        cursor.execute(
                            "UPDATE trade_intents SET status = 'approved' WHERE id = ?",
                            (approval['intent_id'],)
                        )
                    
                    st.success("Trade approved!")
                    time.sleep(1)
                    st.rerun()
            
            with col_reject:
                if st.button(f"❌ Reject", key=f"reject_{approval['approval_id']}"):
                    # Update approval status
                    with storage.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE approvals SET hitl_status = 'rejected' WHERE id = ?",
                            (approval['approval_id'],)
                        )
                        cursor.execute(
                            "UPDATE trade_intents SET status = 'rejected' WHERE id = ?",
                            (approval['intent_id'],)
                        )
                    
                    st.success("Trade rejected")
                    time.sleep(1)
                    st.rerun()


def show_settings():
    """Show settings and configuration."""
    st.header("Settings")
    st.json({
        "Mode": "PAPER" if not settings.ENABLE_LIVE_TRADING else "LIVE",
        "Capital": settings.DAILY_CAPITAL,
        "Max Loss": settings.MAX_DAILY_LOSS,
        "LLM": settings.LLM_PROVIDER
    })
    
    st.subheader("Trading Parameters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**Daily Capital:** {format_price(settings.DAILY_CAPITAL)}")
        st.write(f"**Max Daily Loss:** {format_price(settings.MAX_DAILY_LOSS)}")
        st.write(f"**Max Trades/Day:** {settings.MAX_TRADES_PER_DAY}")
        st.write(f"**Per-Trade Max Loss %:** {settings.PER_TRADE_MAX_LOSS_PERCENT}%")
    
    with col2:
        st.write(f"**Trading Mode:** {'PAPER' if not settings.ENABLE_LIVE_TRADING else 'LIVE ⚠️'}")
        st.write(f"**HITL First N Trades:** {settings.REQUIRE_HITL_FIRST_N_TRADES}")
        st.write(f"**HITL Confidence Threshold:** {settings.HITL_CONFIDENCE_THRESHOLD}")
        st.write(f"**Strategy Switch Cooldown:** {settings.STRATEGY_SWITCH_COOLDOWN_MINUTES} min")
    
    st.subheader("LLM Configuration")
    st.write(f"**Provider:** {settings.LLM_PROVIDER.upper()}")
    
    if settings.LLM_PROVIDER == "google":
        st.write(f"**Model:** {settings.GOOGLE_MODEL}")
        masked_key = f"{settings.GOOGLE_API_KEY[:4]}...{settings.GOOGLE_API_KEY[-4:]}" if settings.GOOGLE_API_KEY else "Not Set"
        st.write(f"**API Key:** {masked_key}")
    else:
        st.write(f"**Base URL:** {settings.OLLAMA_BASE_URL}")
        st.write(f"**Model:** {settings.OLLAMA_MODEL}")
    
    st.subheader("Trading Symbols")
    # Show symbols from settings which we updated
    st.write(", ".join(settings.get_trading_symbols()))
    
    # Actions
    st.subheader("Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Reset Daily State"):
            from app.agents.risk_policy import risk_policy
            risk_policy.reset_daily_state()
            st.success("Daily state reset!")
            time.sleep(1)
            st.rerun()
    
    with col2:
        if st.button("🚨 Trigger SAFE_MODE"):
            from app.agents.risk_policy import risk_policy
            risk_policy.trigger_safe_mode("Manual trigger from dashboard")
            st.warning("SAFE_MODE activated!")
            time.sleep(1)
            st.rerun()
    
    with col3:
        if st.button("📊 Flatten All Positions"):
            from app.agents.execution_paper import execution_paper
            execution_paper.flatten_all_positions("Manual flatten from dashboard")
            st.info("All positions flattened")
            time.sleep(1)
            st.rerun()



if __name__ == "__main__":
    main()
