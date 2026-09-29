"""
FastAPI server for Zerodha authentication and status endpoints.
"""
import os
from html import escape

# Trust the OS keychain so corporate MITM TLS proxies work (must run before any HTTPS).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Dict, Any, Optional

from app.core.zerodha_auth import zerodha_auth
from app.core.utils import logger, log_event
from app.core.config import settings
from app.agents.registry import AGENT_BY_NAME, AGENT_CLASSES, system_card


# Create FastAPI app
app = FastAPI(
    title="DayTradingPaperBot Auth Server",
    description="Authentication server for Zerodha Kite Connect",
    version="1.0.0"
)

# Add CORS middleware for Streamlit integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": "DayTradingPaperBot",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "login_url": "/auth/login_url",
            "callback": "/callback",
            "status": "/status",
            "logout": "/auth/logout",
            "agents_index": "/agents",
            "system_card": "/agents/system.json",
        }
    }


@app.get("/agents")
async def agents_index():
    """List the 12 agents with one-line capability + card URL."""
    return {
        "count": len(AGENT_CLASSES),
        "system_card": "/agents/system.json",
        "agents": [
            {
                "name": cls.name,
                "description": cls.description,
                "uses_llm": cls.uses_llm,
                "interval_seconds": cls.interval_seconds,
                "card_url": f"/agents/{cls.name}/card.json",
            }
            for cls in AGENT_CLASSES
        ],
    }


@app.get("/agents/system.json")
async def agents_system_card():
    """Top-level card describing the whole 12-agent trading system."""
    return system_card()


@app.get("/agents/{name}/card.json")
async def agent_card(name: str):
    """Full A2A-style card for a single agent."""
    cls = AGENT_BY_NAME.get(name)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"unknown agent: {name}")
    return cls.card()


@app.get("/auth/login_url")
async def get_login_url():
    """
    Generate Kite Connect login URL for manual user authentication.
    
    Returns:
        JSON with login URL
    """
    try:
        login_url = zerodha_auth.generate_login_url()
        
        return {
            "success": True,
            "login_url": login_url,
            "message": "Please visit this URL in your browser to log in to Zerodha",
            "instructions": [
                "1. Click the login URL",
                "2. Log in with your Zerodha credentials",
                "3. Authorize the application",
                "4. You will be redirected back to this server"
            ]
        }
    
    except Exception as e:
        logger.error(f"Error generating login URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/callback")
async def auth_callback(
    request: Request,
    request_token: Optional[str] = None,
    status: Optional[str] = None,
    format: Optional[str] = None,
):
    """
    OAuth callback from Zerodha (must match KITE_REDIRECT_URL).

    Default: show a copyable token page and DO NOT consume the ``request_token``.
    This is the safest local-dev flow because Kite request tokens are single-use
    and checksum errors are easier to diagnose from the Streamlit UI/manual paste.

    ``?format=json`` — legacy: exchange token here and return JSON (kept for tests).
    """
    wants_json = (format or "").lower() == "json"
    streamlit_port = os.environ.get("STREAMLIT_PORT", "8501")
    # Use 'localhost' (not 127.0.0.1) so Streamlit's XSRF/CORS check matches
    # the host the browser sees during normal browsing.
    streamlit_host = os.environ.get("STREAMLIT_HOST", "localhost")
    streamlit_base = f"http://{streamlit_host}:{streamlit_port}"

    if status != "success" or not request_token:
        log_event(
            "auth_callback_failed",
            {"status": status, "has_token": bool(request_token)},
            level="ERROR",
        )
        if wants_json:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Authentication failed or was cancelled",
                    "status": status,
                },
            )
        return HTMLResponse(
            """
            <html><body style="font-family: system-ui; margin: 40px;">
            <h2>Kite login failed or was cancelled</h2>
            <p>No <code>request_token</code> was returned by Kite.</p>
            </body></html>
            """,
            status_code=400,
        )

    if not wants_json:
        safe_token = escape(request_token)
        safe_streamlit = escape(streamlit_base)
        return HTMLResponse(
            f"""
            <html>
              <body style="font-family: system-ui; margin: 40px; line-height: 1.5;">
                <h2>Kite request token received</h2>
                <p>This page intentionally does <b>not</b> consume the one-time token.</p>
                <label style="display:block; margin-bottom: 8px;">Copy this request_token:</label>
                <input value="{safe_token}" readonly onclick="this.select()"
                       style="width: 100%; max-width: 760px; font-size: 16px; padding: 10px;" />
                <p>Now return to <a href="{safe_streamlit}">{safe_streamlit}</a>,
                open <b>Trouble logging in? Paste token manually</b>, paste the token, and click
                <b>Authenticate</b>. Tokens expire quickly, so do this immediately.</p>
              </body>
            </html>
            """,
            status_code=200,
        )

    # JSON/test mode only: exchange the request_token here (single-use).
    try:
        session_data = zerodha_auth.exchange_request_token(request_token)
        log_event(
            "auth_callback_token_exchanged",
            {"user_id": session_data.get("user_id"), "user_name": session_data.get("user_name")},
        )
    except Exception as e:
        logger.error(f"Token exchange in /callback failed: {e}", exc_info=True)
        if wants_json:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": f"Failed to complete authentication: {e}"},
            )
        from urllib.parse import quote
        return RedirectResponse(
            url=f"{streamlit_base}/?auth_error={quote(str(e))}", status_code=302
        )

    if wants_json:
        return {
            "success": True,
            "message": "Authentication successful!",
            "user": {
                "user_id": session_data.get("user_id"),
                "user_name": session_data.get("user_name"),
                "email": session_data.get("email"),
                "user_type": session_data.get("user_type"),
            },
        }

    return RedirectResponse(url=f"{streamlit_base}/?auth=ok", status_code=302)


@app.get("/status")
async def get_status():
    """
    Get current authentication and system status.
    
    Returns:
        JSON with status information (NO secrets)
    """
    try:
        auth_status = zerodha_auth.get_auth_status()
        
        return {
            "success": True,
            "auth": auth_status,
            "trading_mode": "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER",
            "config": {
                "daily_capital": settings.DAILY_CAPITAL,
                "max_daily_loss": settings.MAX_DAILY_LOSS,
                "max_trades_per_day": settings.MAX_TRADES_PER_DAY,
                "ollama_model": settings.OLLAMA_MODEL
            }
        }
    
    except Exception as e:
        logger.error(f"Error getting status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/auth/logout")
async def logout():
    """
    Logout and clear access token.
    
    Returns:
        JSON with logout confirmation
    """
    try:
        zerodha_auth.logout()
        
        return {
            "success": True,
            "message": "Logged out successfully. Access token has been cleared."
        }
    
    except Exception as e:
        logger.error(f"Error during logout: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/shutdown")
async def shutdown():
    """
    Graceful server shutdown endpoint.
    
    Returns:
        JSON with shutdown confirmation
    """
    log_event("server_shutdown_requested")
    
    return {
        "success": True,
        "message": "Server shutting down..."
    }


@app.on_event("startup")
async def startup_event():
    """Server startup event."""
    logger.info("FastAPI auth server starting up")
    log_event("server_startup", {
        "trading_mode": "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER"
    })
    
    # Validate LLM connection
    from app.core.llm import llm_client
    llm_healthy = llm_client.check_health()
    
    if not llm_healthy:
        logger.warning(f"LLM health check failed ({settings.LLM_PROVIDER}) - AI features may not work")


@app.on_event("shutdown")
async def shutdown_event():
    """Server shutdown event."""
    logger.info("FastAPI auth server shutting down")
    log_event("server_shutdown")


def run_auth_server(host: str = "127.0.0.1", port: int = 8000):
    """
    Run the FastAPI auth server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
    """
    logger.info(f"Starting auth server on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    run_auth_server()
