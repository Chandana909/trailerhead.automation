"""
agent/perception/hud.py

Heads-Up Display (HUD) Overlay Manager for Playwright Browser Session.
Injects and updates a persistent floating status box on screen in real time,
and displays a completion modal popup when trial execution finishes.
"""
from __future__ import annotations

import logging
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger(__name__)

HUD_CSS = """
#sf-agent-hud {
    position: fixed !important;
    bottom: 24px !important;
    right: 24px !important;
    z-index: 2147483647 !important;
    min-width: 320px !important;
    max-width: 440px !important;
    background: rgba(15, 23, 42, 0.92) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
    box-shadow: 0 20px 35px -10px rgba(0, 0, 0, 0.6), 0 0 15px rgba(56, 189, 248, 0.25) !important;
    border-radius: 14px !important;
    padding: 16px 20px !important;
    color: #f8fafc !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    font-size: 13px !important;
    line-height: 1.5 !important;
    pointer-events: none !important;
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
    user-select: none !important;
}

#sf-agent-hud .hud-header {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    margin-bottom: 8px !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
    padding-bottom: 8px !important;
}

#sf-agent-hud .hud-title-container {
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
}

#sf-agent-hud .hud-pulse {
    width: 10px !important;
    height: 10px !important;
    border-radius: 50% !important;
    display: inline-block !important;
    box-shadow: 0 0 8px currentColor !important;
}

#sf-agent-hud .hud-pulse.pulse-active {
    background-color: #38bdf8 !important;
    color: #38bdf8 !important;
    animation: hudPulseAnim 1.6s infinite !important;
}

#sf-agent-hud .hud-pulse.pulse-warn {
    background-color: #fbbf24 !important;
    color: #fbbf24 !important;
    animation: hudPulseAnim 1.2s infinite !important;
}

#sf-agent-hud .hud-pulse.pulse-success {
    background-color: #4ade80 !important;
    color: #4ade80 !important;
}

#sf-agent-hud .hud-pulse.pulse-error {
    background-color: #f87171 !important;
    color: #f87171 !important;
}

@keyframes hudPulseAnim {
    0% { transform: scale(0.95); opacity: 0.8; }
    50% { transform: scale(1.25); opacity: 1; }
    100% { transform: scale(0.95); opacity: 0.8; }
}

#sf-agent-hud .hud-badge {
    font-weight: 700 !important;
    font-size: 11px !important;
    letter-spacing: 0.5px !important;
    text-transform: uppercase !important;
    padding: 3px 8px !important;
    border-radius: 6px !important;
    background: rgba(56, 189, 248, 0.15) !important;
    color: #38bdf8 !important;
    border: 1px solid rgba(56, 189, 248, 0.3) !important;
}

#sf-agent-hud .hud-badge.badge-warn {
    background: rgba(251, 191, 36, 0.15) !important;
    color: #fbbf24 !important;
    border-color: rgba(251, 191, 36, 0.3) !important;
}

#sf-agent-hud .hud-badge.badge-success {
    background: rgba(74, 222, 128, 0.15) !important;
    color: #4ade80 !important;
    border-color: rgba(74, 222, 128, 0.3) !important;
}

#sf-agent-hud .hud-badge.badge-error {
    background: rgba(248, 113, 113, 0.15) !important;
    color: #f87171 !important;
    border-color: rgba(248, 113, 113, 0.3) !important;
}

#sf-agent-hud .hud-brand {
    font-weight: 600 !important;
    color: #94a3b8 !important;
    font-size: 11px !important;
}

#sf-agent-hud .hud-status {
    font-weight: 600 !important;
    font-size: 13px !important;
    color: #f1f5f9 !important;
    word-break: break-word !important;
}

#sf-agent-hud .hud-detail {
    margin-top: 4px !important;
    font-size: 11px !important;
    color: #94a3b8 !important;
    font-family: monospace !important;
    word-break: break-all !important;
}

/* Completion Modal */
#sf-agent-modal-backdrop {
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    background: rgba(15, 23, 42, 0.75) !important;
    backdrop-filter: blur(8px) !important;
    -webkit-backdrop-filter: blur(8px) !important;
    z-index: 2147483646 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    animation: fadeInModal 0.4s ease-out !important;
}

@keyframes fadeInModal {
    from { opacity: 0; transform: scale(0.96); }
    to { opacity: 1; transform: scale(1); }
}

#sf-agent-modal {
    background: #0f172a !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8), 0 0 30px rgba(56, 189, 248, 0.3) !important;
    border-radius: 18px !important;
    padding: 32px !important;
    max-width: 520px !important;
    width: 90% !important;
    color: #f8fafc !important;
    text-align: center !important;
}

#sf-agent-modal .modal-icon {
    font-size: 48px !important;
    margin-bottom: 12px !important;
    display: block !important;
}

#sf-agent-modal .modal-title {
    font-size: 22px !important;
    font-weight: 800 !important;
    margin-bottom: 8px !important;
    letter-spacing: -0.5px !important;
}

#sf-agent-modal .modal-status-pill {
    display: inline-block !important;
    padding: 4px 14px !important;
    border-radius: 9999px !important;
    font-weight: 700 !important;
    font-size: 12px !important;
    text-transform: uppercase !important;
    margin-bottom: 16px !important;
    letter-spacing: 0.5px !important;
}

#sf-agent-modal .modal-status-pill.complete {
    background: rgba(74, 222, 128, 0.2) !important;
    color: #4ade80 !important;
    border: 1px solid rgba(74, 222, 128, 0.4) !important;
}

#sf-agent-modal .modal-status-pill.failed {
    background: rgba(248, 113, 113, 0.2) !important;
    color: #f87171 !important;
    border: 1px solid rgba(248, 113, 113, 0.4) !important;
}

#sf-agent-modal .modal-message {
    font-size: 14px !important;
    color: #cbd5e1 !important;
    line-height: 1.6 !important;
    margin-bottom: 20px !important;
}

#sf-agent-modal .modal-details {
    background: rgba(255, 255, 255, 0.05) !important;
    border-radius: 10px !important;
    padding: 14px !important;
    font-size: 12px !important;
    color: #94a3b8 !important;
    text-align: left !important;
    margin-bottom: 24px !important;
}

#sf-agent-modal .modal-btn {
    background: linear-gradient(135deg, #0284c7, #2563eb) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 12px 28px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    cursor: pointer !important;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4) !important;
    transition: transform 0.15s ease !important;
}

#sf-agent-modal .modal-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(37, 99, 235, 0.6) !important;
}
"""


class HUDOverlay:
    """Manages the persistent HUD text box and completion modal inside Playwright DOM."""

    @staticmethod
    async def update(
        page: Page,
        status: str,
        phase: str = "RUNNING",
        detail: str = "",
        style_type: str = "active",
    ) -> None:
        """Inject or update the floating HUD status text box."""
        try:
            if page.is_closed():
                return

            await page.evaluate(
                """({ css, status, phase, detail, styleType }) => {
                if (!document.getElementById('sf-agent-hud-style')) {
                    const style = document.createElement('style');
                    style.id = 'sf-agent-hud-style';
                    style.textContent = css;
                    document.head.appendChild(style);
                }

                let hud = document.getElementById('sf-agent-hud');
                if (!hud) {
                    hud = document.createElement('div');
                    hud.id = 'sf-agent-hud';
                    document.body.appendChild(hud);
                }

                let pulseClass = 'pulse-active';
                let badgeClass = '';
                if (styleType === 'warn') {
                    pulseClass = 'pulse-warn';
                    badgeClass = 'badge-warn';
                } else if (styleType === 'success') {
                    pulseClass = 'pulse-success';
                    badgeClass = 'badge-success';
                } else if (styleType === 'error') {
                    pulseClass = 'pulse-error';
                    badgeClass = 'badge-error';
                }

                hud.innerHTML = `
                    <div class="hud-header">
                        <div class="hud-title-container">
                            <span class="hud-pulse ${pulseClass}"></span>
                            <span class="hud-badge ${badgeClass}">${phase}</span>
                        </div>
                        <span class="hud-brand">🤖 Trailhead Agent</span>
                    </div>
                    <div class="hud-status">${status}</div>
                    ${detail ? `<div class="hud-detail">${detail}</div>` : ''}
                `;
            }""",
                {
                    "css": HUD_CSS,
                    "status": status,
                    "phase": phase,
                    "detail": detail,
                    "styleType": style_type,
                },
            )
        except Exception as exc:
            logger.debug(f"HUD update skipped: {exc}")

    @staticmethod
    async def show_completion_modal(
        page: Page,
        title: str,
        status: str,
        message: str,
        details: list[str] | None = None,
    ) -> None:
        """Display a prominent modal dialog on completion."""
        try:
            if page.is_closed():
                return

            details_html = ""
            if details:
                items = "".join(f"<li>{item}</li>" for item in details)
                details_html = f"<ul style='margin: 0; padding-left: 18px;'>{items}</ul>"

            await page.evaluate(
                """({ css, title, status, message, detailsHtml }) => {
                if (!document.getElementById('sf-agent-hud-style')) {
                    const style = document.createElement('style');
                    style.id = 'sf-agent-hud-style';
                    style.textContent = css;
                    document.head.appendChild(style);
                }

                const old = document.getElementById('sf-agent-modal-backdrop');
                if (old) old.remove();

                const isComplete = status.toUpperCase() === 'COMPLETE' || status.toUpperCase() === 'SUCCESS';
                const pillClass = isComplete ? 'complete' : 'failed';
                const icon = isComplete ? '🎉' : '⚠️';

                const backdrop = document.createElement('div');
                backdrop.id = 'sf-agent-modal-backdrop';
                backdrop.innerHTML = `
                    <div id="sf-agent-modal">
                        <span class="modal-icon">${icon}</span>
                        <div class="modal-title">${title}</div>
                        <div class="modal-status-pill ${pillClass}">Status: ${status}</div>
                        <div class="modal-message">${message}</div>
                        ${detailsHtml ? `<div class="modal-details">${detailsHtml}</div>` : ''}
                        <button class="modal-btn" onclick="document.getElementById('sf-agent-modal-backdrop').remove()">Close & Continue</button>
                    </div>
                `;
                document.body.appendChild(backdrop);
            }""",
                {
                    "css": HUD_CSS,
                    "title": title,
                    "status": status,
                    "message": message,
                    "detailsHtml": details_html,
                },
            )
        except Exception as exc:
            logger.warning(f"Could not display completion modal: {exc}")
