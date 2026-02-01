"""
Single source of truth for all plan details.
Used by /plans, plan activation, plan activated message, and any plan-related text.
"""

# Plan details: price, badge, credits, antispam (seconds), mlimit, duration (days), features list
PLAN_DETAILS = {
    "Plus": {
        "price": "$1",
        "badge": "💠",
        "credits": 200,
        "antispam": 13,
        "mlimit": 5,
        "duration_days": 1,
        "duration": "1 Day",
        "features": [
            "200 Credits",
            "13s Anti-Spam",
            "5 Mass Limit",
            "All Gates Access",
            "Priority Support"
        ]
    },
    "Pro": {
        "price": "$6",
        "badge": "🔰",
        "credits": 500,
        "antispam": 10,
        "mlimit": 10,
        "duration_days": 7,
        "duration": "7 Days",
        "features": [
            "500 Credits",
            "10s Anti-Spam",
            "10 Mass Limit",
            "All Gates Access",
            "Premium Support",
            "Private Mode"
        ]
    },
    "Elite": {
        "price": "$9",
        "badge": "🔷",
        "credits": 800,
        "antispam": 8,
        "mlimit": 15,
        "duration_days": 15,
        "duration": "15 Days",
        "features": [
            "800 Credits",
            "8s Anti-Spam",
            "15 Mass Limit",
            "All Gates Access",
            "VIP Support",
            "Private Mode",
            "Custom Requests"
        ]
    },
    "VIP": {
        "price": "$15",
        "badge": "👑",
        "credits": 1500,
        "antispam": 5,
        "mlimit": None,  # Unlimited
        "duration_days": 30,
        "duration": "30 Days",
        "features": [
            "1500 Credits",
            "5s Anti-Spam",
            "Unlimited Mass Limit",
            "All Gates Access",
            "24/7 VIP Support",
            "Private Mode",
            "Custom Gates",
            "Priority Processing"
        ]
    },
    "Ultimate": {
        "price": "$25",
        "badge": "👑",
        "credits": "∞",
        "antispam": 3,
        "mlimit": 50,
        "duration_days": 60,
        "duration": "60 Days",
        "features": [
            "Unlimited Credits",
            "3s Anti-Spam",
            "50 Mass Limit",
            "All Gates Access",
            "Dedicated Support",
            "Private Mode",
            "Custom Everything",
            "API Access"
        ]
    }
}
