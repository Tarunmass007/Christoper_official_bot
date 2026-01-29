"""
Stripe Auto Auth Gate (WooCommerce Stripe)
==========================================
Professional async WooCommerce Stripe auth: register → add-payment-method → Stripe tokenize → create_setup_intent.
Uses user's saved Stripe Auth sites (/sturl, /murl). Commands: /starr (single), /mstarr (mass).
Does NOT mingle with existing /au, /mau (StripeAuth API).
"""

from BOT.Auth.StripeAuto.api import auto_stripe_auth

# Load handlers so Pyrogram registers them
from BOT.Auth.StripeAuto import single, mass, addurl  # noqa: F401

__all__ = ["auto_stripe_auth"]
